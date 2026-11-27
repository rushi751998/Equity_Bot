"""Plug-and-play BrokerClient interface + Paper, Zerodha Kite v3 REST, Fyers, Kotak Neo."""
from __future__ import annotations

import hashlib
import json
import urllib.parse
import urllib.request
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


class ZerodhaBroker(BrokerClient):
    """Direct Zerodha Kite Connect v3 REST API implementation (https://kite.trade/docs/connect/v3/)."""
    name = "zerodha"
    BASE = "https://api.kite.trade"

    def __init__(self) -> None:
        self.cfg = load_settings()["brokers"]["zerodha"]

    def _headers(self) -> dict[str, str]:
        api_key = self.cfg.get("api_key", "")
        token = self.cfg.get("access_token", "")
        if not api_key or not token:
            raise RuntimeError("Zerodha api_key and access_token are required in Settings / .env")
        return {
            "X-Kite-Version": "3",
            "Authorization": f"token {api_key}:{token}",
        }

    def _req(self, method: str, path: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.BASE}{path}"
        body = urllib.parse.urlencode(data).encode("utf-8") if data else None
        req = urllib.request.Request(url, data=body, headers=self._headers(), method=method)
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode("utf-8"))

    @staticmethod
    def login_url(api_key: str) -> str:
        return f"https://kite.zerodha.com/connect/login?v=3&api_key={urllib.parse.quote(api_key)}"

    @classmethod
    def exchange_request_token(cls, api_key: str, api_secret: str, request_token: str) -> dict[str, Any]:
        checksum = hashlib.sha256(f"{api_key}{request_token}{api_secret}".encode("utf-8")).hexdigest()
        body = urllib.parse.urlencode({
            "api_key": api_key,
            "request_token": request_token,
            "checksum": checksum,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{cls.BASE}/session/token",
            data=body,
            headers={"X-Kite-Version": "3"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def get_ltp(self, symbol: str) -> float:
        inst = symbol if ":" in symbol else f"NSE:{symbol.upper()}"
        res = self._req("GET", f"/quote/ltp?i={urllib.parse.quote(inst)}")
        return float(res.get("data", {}).get(inst, {}).get("last_price", 0.0))

    def place_order(self, symbol: str, side: str, qty: int, order_type: str, product: str, price: float | None = None, trigger_price: float | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "tradingsymbol": symbol.upper(),
            "exchange": "NSE",
            "transaction_type": side.upper(),
            "order_type": order_type.upper(),
            "quantity": int(qty),
            "product": product.upper(),
            "validity": "DAY",
        }
        if price is not None and order_type.upper() in ("LIMIT", "SL"):
            payload["price"] = float(price)
        if trigger_price is not None and order_type.upper() in ("SL", "SL-M"):
            payload["trigger_price"] = float(trigger_price)
        res = self._req("POST", "/orders/regular", payload)
        oid = res.get("data", {}).get("order_id", "")
        return {"order_id": oid, "symbol": symbol.upper(), "side": side.upper(), "qty": qty, "order_type": order_type.upper(), "product": product.upper(), "price": price or 0.0, "trigger_price": trigger_price, "status": "OPEN", "ts": datetime.now().isoformat()}

    def modify_order(self, order_id: str, price: float | None = None, trigger_price: float | None = None, order_type: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if price is not None:
            payload["price"] = float(price)
        if trigger_price is not None:
            payload["trigger_price"] = float(trigger_price)
        if order_type is not None:
            payload["order_type"] = order_type.upper()
        res = self._req("PUT", f"/orders/regular/{order_id}", payload)
        return {"order_id": order_id, "status": "MODIFIED", "raw": res}

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        res = self._req("DELETE", f"/orders/regular/{order_id}")
        return {"order_id": order_id, "status": "CANCELLED", "raw": res}

    def get_orders(self) -> list[dict[str, Any]]:
        res = self._req("GET", "/orders")
        out = []
        for o in res.get("data", []):
            out.append({
                "order_id": o.get("order_id"),
                "symbol": o.get("tradingsymbol"),
                "side": o.get("transaction_type"),
                "qty": int(o.get("quantity", 0)),
                "order_type": o.get("order_type"),
                "product": o.get("product"),
                "price": float(o.get("average_price") or o.get("price") or 0.0),
                "trigger_price": o.get("trigger_price"),
                "status": o.get("status"),
                "ts": o.get("order_timestamp") or "",
            })
        return out

    def get_positions(self) -> list[dict[str, Any]]:
        res = self._req("GET", "/portfolio/positions")
        out = []
        for p in res.get("data", {}).get("net", []):
            nq = int(p.get("quantity", 0))
            if nq == 0:
                continue
            out.append({
                "symbol": p.get("tradingsymbol"),
                "product": p.get("product"),
                "net_qty": nq,
                "avg_price": float(p.get("average_price", 0.0)),
                "ltp": float(p.get("last_price", 0.0)),
                "mtm": float(p.get("pnl", 0.0)),
            })
        return out


class PaperBroker(BrokerClient):
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
            "orders": self.orders[-300:],
            "positions": self.positions,
            "closed_trades": self.closed_trades[-1000:],
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
            "order_id": oid, "symbol": sym, "side": side.upper(), "qty": int(qty),
            "order_type": order_type.upper(), "product": product.upper(),
            "price": float(price or self.get_ltp(sym)),
            "trigger_price": float(trigger_price) if trigger_price else None,
            "status": "OPEN", "ts": datetime.now().isoformat(),
        }
        self.orders.append(ord_rec)
        self._process_fills()
        self._persist()
        return ord_rec

    def modify_order(self, order_id: str, price: float | None = None, trigger_price: float | None = None, order_type: str | None = None) -> dict[str, Any]:
        for o in self.orders:
            if o["order_id"] == order_id and o["status"] in ("OPEN", "TRIGGER_PENDING"):
                if price is not None: o["price"] = float(price)
                if trigger_price is not None: o["trigger_price"] = float(trigger_price)
                if order_type is not None: o["order_type"] = order_type.upper()
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
                "symbol": symbol, "product": product, "net_qty": signed, "peak_qty": abs(signed),
                "avg_price": round(px, 2), "sl_price": None, "sl_order_id": None, "target_price": None,
                "initial_risk_inr": 0.0, "realized_pnl": 0.0, "exit_notional": 0.0, "exit_qty": 0,
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
            self.closed_trades.append({
                "trade_id": f"LIVE_{len(self.closed_trades) + 1}",
                "symbol": symbol, "product": product, "side": "LONG" if old_q > 0 else "SHORT",
                "qty": pos.get("peak_qty", tot_ex_q), "entry_price": pos["avg_price"], "exit_price": avg_exit,
                "initial_risk_inr": round(init_risk, 2), "net_pnl": round(tot_pnl, 2),
                "money_r": round(tot_pnl / init_risk, 2) if init_risk > 0 else 0.0,
                "fills": pos.get("fills", []), "opened_at": pos.get("opened_at"), "closed_at": now_iso,
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
    def __init__(self, broker_name: str) -> None:
        self.name = broker_name
    def get_ltp(self, symbol: str) -> float: return 0.0
    def place_order(self, *a, **kw) -> dict[str, Any]: raise NotImplementedError(f"{self.name} adapter")
    def modify_order(self, *a, **kw) -> dict[str, Any]: raise NotImplementedError(f"{self.name} adapter")
    def cancel_order(self, *a, **kw) -> dict[str, Any]: raise NotImplementedError(f"{self.name} adapter")
    def get_orders(self) -> list[dict[str, Any]]: return []
    def get_positions(self) -> list[dict[str, Any]]: return []


_PAPER_SINGLETON = PaperBroker()


def get_active_broker() -> BrokerClient:
    name = load_settings().get("active_broker", "paper")
    if name == "paper":
        return _PAPER_SINGLETON
    if name == "zerodha":
        return ZerodhaBroker()
    return LiveBrokerStub(name)
