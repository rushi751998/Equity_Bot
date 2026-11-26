"""Plug-and-play BrokerClient interface + Paper, Zerodha, Fyers, Kotak Neo adapters."""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from tfalgo.web.core.config_store import STORE, load_settings


class BrokerClient(ABC):
    name: str = "base"

    @abstractmethod
    def get_ltp(self, symbol: str) -> float: ...

    @abstractmethod
    def place_order(self, symbol: str, side: str, qty: int, order_type: str, product: str, price: float | None = None, trigger_price: float | None = None) -> dict[str, Any]: ...

    @abstractmethod
    def modify_order(self, order_id: str, price: float | None = None, trigger_price: float | None = None, order_type: str | None = None) -> dict[str, Any]: ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> dict[str, Any]: ...

    @abstractmethod
    def get_orders(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def get_positions(self) -> list[dict[str, Any]]: ...


class PaperBroker(BrokerClient):
    """In-memory + persisted Paper Trading broker with editable LTP feed."""
    name = "paper"

    def __init__(self) -> None:
        st = STORE.load_live_state()
        self.ltp_map: dict[str, float] = st.get("ltp_map", {"RELIANCE": 2950.0, "INFY": 1820.0, "TCS": 4120.0})
        self.orders: list[dict[str, Any]] = st.get("orders", [])
        self.positions: list[dict[str, Any]] = st.get("positions", [])
        self.closed_trades: list[dict[str, Any]] = st.get("closed_trades", [])

    def _persist(self) -> None:
        STORE.save_live_state({
            "ltp_map": self.ltp_map,
            "orders": self.orders[-200:],
            "positions": self.positions,
            "closed_trades": self.closed_trades[-500:],
        })

    def set_ltp(self, symbol: str, ltp: float) -> None:
        self.ltp_map[symbol.upper()] = float(ltp)
        self._process_fills()
        self._persist()

    def get_ltp(self, symbol: str) -> float:
        return float(self.ltp_map.get(symbol.upper(), 100.0))

    def place_order(self, symbol: str, side: str, qty: int, order_type: str, product: str, price: float | None = None, trigger_price: float | None = None) -> dict[str, Any]:
        sym = symbol.upper()
        if sym not in self.ltp_map and price:
            self.ltp_map[sym] = float(price)
        oid = f"PPR_{uuid.uuid4().hex[:8].upper()}"
        ord_rec = {
            "order_id": oid,
            "symbol": sym,
            "side": side.upper(),
            "qty": int(qty),
            "order_type": order_type.upper(),
            "product": product.upper(),
            "price": float(price or self.get_ltp(sym)),
            "trigger_price": float(trigger_price) if trigger_price else None,
            "status": "OPEN",
            "ts": datetime.now().isoformat(),
        }
        self.orders.append(ord_rec)
        self._process_fills()
        self._persist()
        return ord_rec

    def modify_order(self, order_id: str, price: float | None = None, trigger_price: float | None = None, order_type: str | None = None) -> dict[str, Any]:
        for o in self.orders:
            if o["order_id"] == order_id and o["status"] in ("OPEN", "TRIGGER_PENDING"):
                if price is not None:
                    o["price"] = float(price)
                if trigger_price is not None:
                    o["trigger_price"] = float(trigger_price)
                if order_type is not None:
                    o["order_type"] = order_type.upper()
                self._process_fills()
                self._persist()
                return o
        return {"order_id": order_id, "status": "NOT_FOUND"}

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        for o in self.orders:
            if o["order_id"] == order_id and o["status"] in ("OPEN", "TRIGGER_PENDING"):
                o["status"] = "CANCELLED"
                self._persist()
                return o
        return {"order_id": order_id, "status": "NOT_FOUND"}

    def _process_fills(self) -> None:
        for o in self.orders:
            if o["status"] not in ("OPEN", "TRIGGER_PENDING"):
                continue
            ltp = self.get_ltp(o["symbol"])
            otype = o["order_type"]
            fill_px = None
            if otype == "MARKET":
                fill_px = ltp
            elif otype == "LIMIT":
                if (o["side"] == "BUY" and ltp <= o["price"]) or (o["side"] == "SELL" and ltp >= o["price"]):
                    fill_px = ltp
            elif otype in ("SL", "SL-M"):
                trig = o["trigger_price"] or o["price"]
                if (o["side"] == "SELL" and ltp <= trig) or (o["side"] == "BUY" and ltp >= trig):
                    fill_px = ltp
            if fill_px is not None:
                o["status"] = "COMPLETE"
                o["fill_price"] = round(fill_px, 2)
                self._apply_position_fill(o["symbol"], o["side"], o["qty"], fill_px, o["product"])

    def _apply_position_fill(self, symbol: str, side: str, qty: int, px: float, product: str) -> None:
        signed = qty if side == "BUY" else -qty
        now_iso = datetime.now().isoformat()
        pos = next((p for p in self.positions if p["symbol"] == symbol and p["product"] == product), None)
        if pos is None:
            self.positions.append({
                "symbol": symbol,
                "product": product,
                "net_qty": signed,
                "peak_qty": abs(signed),
                "avg_price": round(px, 2),
                "sl_price": None,
                "sl_order_id": None,
                "target_price": None,
                "initial_sl": None,
                "initial_risk_inr": 0.0,
                "realized_pnl": 0.0,
                "exit_notional": 0.0,
                "exit_qty": 0,
                "fills": [{"ts": now_iso, "side": side, "qty": abs(signed), "price": round(px, 2), "pnl": 0.0, "note": "Entry"}],
                "opened_at": now_iso,
            })
            return

        old_q = pos["net_qty"]
        new_q = old_q + signed
        is_add = (old_q > 0 and signed > 0) or (old_q < 0 and signed < 0)

        if is_add:
            tot_val = abs(old_q) * pos["avg_price"] + abs(signed) * px
            pos["avg_price"] = round(tot_val / abs(new_q), 2)
            pos["net_qty"] = new_q
            pos["peak_qty"] = max(pos.get("peak_qty", abs(old_q)), abs(new_q))
            pos.setdefault("fills", []).append({"ts": now_iso, "side": side, "qty": abs(signed), "price": round(px, 2), "pnl": 0.0, "note": "Scale-In"})
            return

        # Partial or full exit
        closed_q = min(abs(old_q), abs(signed))
        part_pnl = (px - pos["avg_price"]) * closed_q if old_q > 0 else (pos["avg_price"] - px) * closed_q
        pos["realized_pnl"] = round(float(pos.get("realized_pnl", 0.0)) + part_pnl, 2)
        pos["exit_notional"] = float(pos.get("exit_notional", 0.0)) + closed_q * px
        pos["exit_qty"] = int(pos.get("exit_qty", 0)) + closed_q
        pos.setdefault("fills", []).append({"ts": now_iso, "side": side, "qty": closed_q, "price": round(px, 2), "pnl": round(part_pnl, 2), "note": "Exit" if new_q == 0 else "Partial Exit"})

        if new_q == 0:
            tot_pnl = pos["realized_pnl"]
            tot_ex_q = max(1, pos["exit_qty"])
            avg_exit = round(pos["exit_notional"] / tot_ex_q, 2)
            init_risk = float(pos.get("initial_risk_inr") or 0.0)
            if init_risk <= 0 and pos.get("sl_price"):
                init_risk = abs(pos["avg_price"] - float(pos["sl_price"])) * pos.get("peak_qty", tot_ex_q)
            money_r = round(tot_pnl / init_risk, 2) if init_risk > 0 else 0.0
            self.closed_trades.append({
                "trade_id": f"LIVE_{len(self.closed_trades) + 1}",
                "symbol": symbol,
                "product": product,
                "side": "LONG" if old_q > 0 else "SHORT",
                "qty": pos.get("peak_qty", tot_ex_q),
                "entry_price": pos["avg_price"],
                "exit_price": avg_exit,
                "initial_risk_inr": round(init_risk, 2),
                "net_pnl": round(tot_pnl, 2),
                "money_r": money_r,
                "fills": pos.get("fills", []),
                "opened_at": pos.get("opened_at"),
                "closed_at": now_iso,
            })
            self.positions = [p for p in self.positions if p is not pos]
        else:
            pos["net_qty"] = new_q

    def get_orders(self) -> list[dict[str, Any]]:
        self._process_fills()
        return list(self.orders)

    def get_positions(self) -> list[dict[str, Any]]:
        for p in self.positions:
            ltp = self.get_ltp(p["symbol"])
            p["ltp"] = ltp
            p["mtm"] = round((ltp - p["avg_price"]) * p["net_qty"], 2)
        return list(self.positions)


class LiveBrokerStub(BrokerClient):
    """Adapter scaffold for Zerodha Kite / Fyers / Kotak Neo using .env + PyOTP."""
    def __init__(self, broker_name: str) -> None:
        self.name = broker_name
        self.cfg = load_settings()["brokers"].get(broker_name, {})

    def _require_token(self) -> None:
        if not self.cfg.get("access_token"):
            raise RuntimeError(f"{self.name} access_token not configured in Settings / .env")

    def get_ltp(self, symbol: str) -> float:
        self._require_token()
        raise NotImplementedError(f"Connect {self.name} SDK quote call here")

    def place_order(self, symbol: str, side: str, qty: int, order_type: str, product: str, price: float | None = None, trigger_price: float | None = None) -> dict[str, Any]:
        self._require_token()
        raise NotImplementedError(f"Connect {self.name} SDK order placement here")

    def modify_order(self, order_id: str, price: float | None = None, trigger_price: float | None = None, order_type: str | None = None) -> dict[str, Any]:
        self._require_token()
        raise NotImplementedError(f"Connect {self.name} SDK order modify here")

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        self._require_token()
        raise NotImplementedError(f"Connect {self.name} SDK order cancel here")

    def get_orders(self) -> list[dict[str, Any]]:
        return []

    def get_positions(self) -> list[dict[str, Any]]:
        return []


_PAPER_SINGLETON = PaperBroker()


def get_active_broker() -> BrokerClient:
    name = load_settings().get("active_broker", "paper")
    if name == "paper":
        return _PAPER_SINGLETON
    return LiveBrokerStub(name)