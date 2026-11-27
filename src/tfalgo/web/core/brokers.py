"""Multi-Account BrokerClient interface + Paper & Zerodha Kite Connect v3 REST."""
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


def split_exchange_symbol(symbol: str, default_exch: str = "NSE") -> tuple[str, str]:
    """Split 'BSE:RELIANCE-EQ' -> ('BSE', 'RELIANCE'), or 'RELIANCE' -> ('NSE', 'RELIANCE')."""
    s = str(symbol or "").strip().upper()
    exch = default_exch.upper()
    if ":" in s:
        exch, s = s.split(":", 1)
    for suf in ("-EQ", "-BE", "-BZ", "-SM"):
        if s.endswith(suf):
            s = s[:-len(suf)]
    return (exch if exch in ("NSE", "BSE") else default_exch.upper()), s


def canonical_symbol(symbol: str) -> str:
    """Normalize NSE:RELIANCE-EQ -> RELIANCE; keeps BSE: prefix when BSE."""
    exch, sym = split_exchange_symbol(symbol)
    return f"BSE:{sym}" if exch == "BSE" else sym


def broker_symbol(symbol: str, broker_name: str, for_quote: bool = False) -> str:
    """Translate RELIANCE or BSE:RELIANCE to each broker's native NSE/BSE format."""
    exch, sym = split_exchange_symbol(symbol)
    b = str(broker_name or "paper").lower()
    if b == "zerodha":
        return f"{exch}:{sym}" if for_quote else sym
    if b == "fyers":
        return f"{exch}:{sym}-EQ"
    if b == "kotak_neo":
        return f"{sym}-EQ"
    return f"{exch}:{sym}" if exch == "BSE" else sym


class BrokerClient(ABC):
    name: str = "base"
    account_id: str = "DEFAULT"

    @abstractmethod
    def get_profile(self) -> dict[str, str]: ...

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
    name = "zerodha"
    BASE = "https://api.kite.trade"

    def __init__(self, acct_cfg: dict[str, Any] | None = None) -> None:
        self.cfg = acct_cfg or load_settings()["brokers"]["zerodha"]
        self.account_id = str(self.cfg.get("account_id") or "ZERODHA_1")

    def _headers(self) -> dict[str, str]:
        api_key = self.cfg.get("api_key", "")
        token = self.cfg.get("access_token", "")
        if not api_key or not token:
            raise RuntimeError(f"{self.account_id}: Zerodha api_key and access_token required")
        return {"X-Kite-Version": "3", "Authorization": f"token {api_key}:{token}"}

    def _req(self, method: str, path: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        import urllib.error
        body = urllib.parse.urlencode(data).encode("utf-8") if data else None
        req = urllib.request.Request(f"{self.BASE}{path}", data=body, headers=self._headers(), method=method)
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            err_txt = exc.read().decode("utf-8", errors="ignore")
            try:
                msg = json.loads(err_txt).get("message") or err_txt
            except Exception:
                msg = err_txt or str(exc)
            raise RuntimeError(f"Kite {exc.code}: {msg}") from exc

    def get_profile(self) -> dict[str, str]:
        try:
            d = self._req("GET", "/user/profile").get("data", {})
            return {"user_id": d.get("user_id", self.account_id), "user_name": d.get("user_name") or self.cfg.get("user_name") or self.account_id}
        except Exception:
            return {"user_id": self.account_id, "user_name": self.cfg.get("user_name") or self.account_id}

    @staticmethod
    def login_url(api_key: str) -> str:
        return f"https://kite.zerodha.com/connect/login?v=3&api_key={urllib.parse.quote(api_key)}"

    @classmethod
    def exchange_request_token(cls, api_key: str, api_secret: str, request_token: str) -> dict[str, Any]:
        checksum = hashlib.sha256(f"{api_key}{request_token}{api_secret}".encode("utf-8")).hexdigest()
        body = urllib.parse.urlencode({"api_key": api_key, "request_token": request_token, "checksum": checksum}).encode("utf-8")
        req = urllib.request.Request(f"{cls.BASE}/session/token", data=body, headers={"X-Kite-Version": "3"}, method="POST")
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def get_ltp(self, symbol: str) -> float:
        inst = broker_symbol(symbol, "zerodha", for_quote=True)
        res = self._req("GET", f"/quote/ltp?i={urllib.parse.quote(inst)}")
        return float(res.get("data", {}).get(inst, {}).get("last_price", 0.0))

    def place_order(self, symbol: str, side: str, qty: int, order_type: str, product: str, price: float | None = None, trigger_price: float | None = None) -> dict[str, Any]:
        exch, _ = split_exchange_symbol(symbol)
        payload: dict[str, Any] = {
            "tradingsymbol": broker_symbol(symbol, "zerodha"), "exchange": exch, "transaction_type": side.upper(),
            "order_type": order_type.upper(), "quantity": int(qty), "product": product.upper(), "validity": "DAY",
        }
        if price is not None and order_type.upper() in ("LIMIT", "SL"):
            payload["price"] = float(price)
        if trigger_price is not None and order_type.upper() in ("SL", "SL-M"):
            payload["trigger_price"] = float(trigger_price)
        res = self._req("POST", "/orders/regular", payload)
        oid = res.get("data", {}).get("order_id", "")
        return {"order_id": oid, "account_id": self.account_id, "exchange": exch, "symbol": canonical_symbol(symbol), "side": side.upper(), "qty": qty, "order_type": order_type.upper(), "product": product.upper(), "price": price or 0.0, "trigger_price": trigger_price, "status": "OPEN", "ts": datetime.now().isoformat()}

    def modify_order(self, order_id: str, price: float | None = None, trigger_price: float | None = None, order_type: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if price is not None: payload["price"] = float(price)
        if trigger_price is not None: payload["trigger_price"] = float(trigger_price)
        if order_type is not None: payload["order_type"] = order_type.upper()
        self._req("PUT", f"/orders/regular/{order_id}", payload)
        return {"order_id": order_id, "status": "MODIFIED"}

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        self._req("DELETE", f"/orders/regular/{order_id}")
        return {"order_id": order_id, "status": "CANCELLED"}

    def get_orders(self) -> list[dict[str, Any]]:
        res = self._req("GET", "/orders")
        return [{
            "order_id": o.get("order_id"), "account_id": self.account_id, "exchange": o.get("exchange") or "NSE", "symbol": canonical_symbol(o.get("tradingsymbol") or ""),
            "side": o.get("transaction_type"), "qty": int(o.get("quantity", 0)), "order_type": o.get("order_type"),
            "product": o.get("product"), "price": float(o.get("average_price") or o.get("price") or 0.0),
            "trigger_price": o.get("trigger_price"), "status": o.get("status"), "ts": o.get("order_timestamp") or "",
        } for o in res.get("data", [])]

    def get_positions(self) -> list[dict[str, Any]]:
        res = self._req("GET", "/portfolio/positions")
        return [{
            "symbol": canonical_symbol(p.get("tradingsymbol") or ""), "exchange": p.get("exchange") or "NSE", "account_id": self.account_id, "product": p.get("product"),
            "net_qty": int(p.get("quantity", 0)), "avg_price": float(p.get("average_price", 0.0)),
            "ltp": float(p.get("last_price", 0.0)), "mtm": float(p.get("pnl", 0.0)),
        } for p in res.get("data", {}).get("net", []) if int(p.get("quantity", 0)) != 0]


class PaperBroker(BrokerClient):
    name = "paper"

    def __init__(self, account_id: str = "PAPER_1", user_name: str = "Paper Pilot") -> None:
        self.account_id = account_id
        self.user_name = user_name
        st = STORE.load_live_state()
        self.ltp_map: dict[str, float] = st.get("ltp_map", {"RELIANCE": 2950.0, "INFY": 1820.0, "TCS": 4120.0})
        self.orders: list[dict[str, Any]] = st.get("orders", [])
        self.positions: list[dict[str, Any]] = st.get("positions", [])
        self.closed_trades: list[dict[str, Any]] = st.get("closed_trades", [])

    def get_profile(self) -> dict[str, str]:
        return {"user_id": self.account_id, "user_name": self.user_name}

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

    def place_order(self, symbol: str, side: str, qty: int, order_type: str, product: str, price: float | None = None, trigger_price: float | None = None, account_id: str | None = None) -> dict[str, Any]:
        sym = symbol.upper()
        acct = account_id or self.account_id
        if sym not in self.ltp_map and price:
            self.ltp_map[sym] = float(price)
        oid = f"PPR_{uuid.uuid4().hex[:8].upper()}"
        ord_rec = {
            "order_id": oid, "account_id": acct, "symbol": sym, "side": side.upper(), "qty": int(qty),
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
                self._apply_position_fill(o["symbol"], o["side"], o["qty"], fill_px, o["product"], o.get("account_id", self.account_id))

    def _apply_position_fill(self, symbol: str, side: str, qty: int, px: float, product: str, account_id: str) -> None:
        signed = qty if side == "BUY" else -qty
        now_iso = datetime.now().isoformat()
        pos = next((p for p in self.positions if p["symbol"] == symbol and p["product"] == product and p.get("account_id", self.account_id) == account_id), None)
        if pos is None:
            self.positions.append({
                "symbol": symbol, "account_id": account_id, "product": product, "net_qty": signed, "peak_qty": abs(signed),
                "avg_price": round(px, 2), "sl_price": None, "sl_order_id": None, "target_price": None,
                "initial_risk_inr": 0.0, "realized_pnl": 0.0, "exit_notional": 0.0, "exit_qty": 0,
                "fills": [{"ts": now_iso, "side": side, "qty": abs(signed), "price": round(px, 2), "pnl": 0.0, "note": "Entry"}],
                "opened_at": now_iso,
            })
            return
        old_q = pos["net_qty"]
        new_q = old_q + signed
        if (old_q > 0 and signed > 0) or (old_q < 0 and signed < 0):
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
                "trade_id": f"LIVE_{len(self.closed_trades) + 1}", "account_id": account_id,
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



class KotakNeoBroker(BrokerClient):
    """Kotak Neo Trade API client for live LTP (nse_cm/bse_cm) & historical OHLCV."""
    name = "kotak_neo"
    _CACHE_PATH = __import__("pathlib").Path("data/kotak_scrip_cache.json")

    def __init__(self, acct_cfg: dict[str, Any] | None = None) -> None:
        self.cfg = acct_cfg or load_settings()["brokers"]["kotak_neo"]
        self.account_id = str(self.cfg.get("account_id") or "KOTAK_1")
        self.user_name = str(self.cfg.get("user_name") or self.account_id)
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        ckey = str(self.cfg.get("consumer_key") or self.cfg.get("api_key") or "").strip()
        if not ckey:
            raise RuntimeError(f"{self.account_id}: Kotak Consumer Key / API Key required")
        try:
            from neo_api_client import NeoAPI
        except ImportError as exc:
            raise RuntimeError("Install Kotak SDK first: pip install kotakneoapi") from exc
        self._client = NeoAPI(consumer_key=ckey, environment="prod")
        return self._client

    def _resolve_token(self, symbol: str) -> tuple[str, str]:
        exch, sym = split_exchange_symbol(symbol)
        seg = "bse_cm" if exch == "BSE" else "nse_cm"
        cache_key = f"{seg}:{sym}"
        cache: dict[str, str] = {}
        if self._CACHE_PATH.exists():
            try:
                cache = json.loads(self._CACHE_PATH.read_text(encoding="utf-8"))
            except Exception:
                cache = {}
        if cache_key in cache:
            return seg, str(cache[cache_key])
        cli = self._get_client()
        res = cli.search_scrip(exchange_segment=seg, symbol=sym)
        rows = res if isinstance(res, list) else (res.get("data") or [])
        tok = ""
        target_trd = f"{sym}-EQ"
        for r in rows:
            trd = str(r.get("pTrdSymbol") or "").upper()
            sname = str(r.get("pSymbolName") or "").upper()
            if trd == target_trd or sname == sym or trd == sym:
                tok = str(r.get("pSymbol") or "")
                break
        if not tok and rows:
            tok = str(rows[0].get("pSymbol") or "")
        if not tok:
            raise RuntimeError(f"Kotak token not found for {seg}:{sym}")
        cache[cache_key] = tok
        self._CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._CACHE_PATH.write_text(json.dumps(cache), encoding="utf-8")
        return seg, tok

    def get_profile(self) -> dict[str, str]:
        return {"user_id": self.account_id, "user_name": self.user_name}

    def get_ltp(self, symbol: str) -> float:
        seg, tok = self._resolve_token(symbol)
        cli = self._get_client()
        res = cli.quotes(instrument_tokens=[{"instrument_token": tok, "exchange_segment": seg}], quote_type="ltp")
        rows = res if isinstance(res, list) else (res.get("data") or res.get("message") or [])
        if isinstance(rows, list) and rows:
            return float(rows[0].get("ltp") or rows[0].get("last_traded_price") or 0.0)
        if isinstance(res, dict) and res.get("ltp"):
            return float(res["ltp"])
        return 0.0

    def get_historical_data(self, symbol: str, interval: str = "D", from_date: str | None = None, to_date: str | None = None) -> list[list[Any]]:
        from datetime import timedelta
        seg, tok = self._resolve_token(symbol)
        iv_map = {"1m": "1min", "3m": "3min", "5m": "5min", "10m": "10min", "15m": "15min", "30m": "30min", "1h": "60min", "60m": "60min", "1d": "D", "1w": "W"}
        iv = iv_map.get(interval.lower(), interval)
        days_back = 25 if iv in ("1min", "3min", "5min") else (55 if iv in ("10min", "15min") else (85 if iv in ("30min", "60min") else 175))
        td = to_date or datetime.now().strftime("%Y-%m-%d")
        fd = from_date or (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        res = self._get_client().historical_data(neosymbol=f"{seg}|{tok}", interval=iv, from_date=fd, to_date=td)
        return res.get("data", {}).get("candles", []) if isinstance(res, dict) else []

    def get_historical_df(self, symbol: str, tf: str = "1d"):
        import pandas as pd
        candles = self.get_historical_data(symbol, interval=tf)
        if not candles:
            return pd.DataFrame()
        df = pd.DataFrame(candles, columns=["ts", "open", "high", "low", "close", "volume", "oi"])
        df["ts"] = pd.to_datetime(df["ts"])
        return df.set_index("ts")[["open", "high", "low", "close", "volume"]].astype(float).dropna()

    def place_order(self, *a, **kw) -> dict[str, Any]: raise NotImplementedError("Kotak Neo order placement requires TOTP+MPIN trading session")
    def modify_order(self, *a, **kw) -> dict[str, Any]: raise NotImplementedError("Kotak Neo modify requires trading session")
    def cancel_order(self, *a, **kw) -> dict[str, Any]: raise NotImplementedError("Kotak Neo cancel requires trading session")
    def get_orders(self) -> list[dict[str, Any]]: return []
    def get_positions(self) -> list[dict[str, Any]]: return []


class LiveBrokerStub(BrokerClient):
    def __init__(self, broker_name: str, account_id: str = "STUB_1", user_name: str = "") -> None:
        self.name = broker_name
        self.account_id = account_id
        self.user_name = user_name or account_id
    def get_profile(self) -> dict[str, str]: return {"user_id": self.account_id, "user_name": self.user_name}
    def format_symbol(self, symbol: str) -> str: return broker_symbol(symbol, self.name)
    def get_ltp(self, symbol: str) -> float: return 0.0
    def place_order(self, *a, **kw) -> dict[str, Any]: raise NotImplementedError(f"{self.name} adapter")
    def modify_order(self, *a, **kw) -> dict[str, Any]: raise NotImplementedError(f"{self.name} adapter")
    def cancel_order(self, *a, **kw) -> dict[str, Any]: raise NotImplementedError(f"{self.name} adapter")
    def get_orders(self) -> list[dict[str, Any]]: return []
    def get_positions(self) -> list[dict[str, Any]]: return []


_PAPER_SINGLETON = PaperBroker()


def get_broker_for_account(account_id: str | None = None) -> BrokerClient:
    cfg = load_settings()
    accts = cfg.get("accounts") or []
    target = next((a for a in accts if a.get("account_id") == account_id), None) if account_id else None
    if target is None and accts:
        target = next((a for a in accts if a.get("account_id") == cfg.get("active_account")), accts[0])
    if target:
        b = target.get("broker", "paper")
        if b == "zerodha" and target.get("access_token"):
            return ZerodhaBroker(target)
        if b == "kotak_neo" and (target.get("api_key") or target.get("consumer_key") or load_settings()["brokers"]["kotak_neo"].get("consumer_key")):
            merged = {**load_settings()["brokers"]["kotak_neo"], **target}
            return KotakNeoBroker(merged)
        if b == "paper":
            _PAPER_SINGLETON.account_id = target.get("account_id") or "PAPER_1"
            _PAPER_SINGLETON.user_name = target.get("user_name") or "Paper Pilot"
            return _PAPER_SINGLETON
        return LiveBrokerStub(b, target.get("account_id", "ACCT"), target.get("user_name", ""))
    if cfg.get("active_broker") == "zerodha":
        return ZerodhaBroker()
    return _PAPER_SINGLETON


def get_active_broker() -> BrokerClient:
    return get_broker_for_account(None)


def get_tick_broker() -> BrokerClient:
    cfg = load_settings()
    accts = cfg.get("accounts") or []
    tick_acct = next((a for a in accts if a.get("is_tick_source")), None)
    if tick_acct:
        return get_broker_for_account(tick_acct.get("account_id"))
    return get_active_broker()
