"""5-second Limit Chase Engine + 10-second SL Watchdog + Panic Flatten."""
from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any

from tfalgo.web.core.brokers import get_active_broker
from tfalgo.web.core.config_store import STORE, load_settings
from tfalgo.web.core.notifier import send_telegram_alert


class ExecutionManager:
    def __init__(self) -> None:
        self.last_sync_ts: str = ""
        self.active_chases: dict[str, dict[str, Any]] = {}
        self.sl_registry: dict[str, dict[str, Any]] = {}  # symbol -> {sl_price, sl_order_id, side, qty, product}
        self._stop_evt = threading.Event()
        self._thread: threading.Thread | None = None

    def start_watchdog(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop_watchdog(self) -> None:
        self._stop_evt.set()

    def _loop(self) -> None:
        while not self._stop_evt.is_set():
            try:
                self.sync_and_guard()
            except Exception as exc:
                STORE.log_audit("watchdog_error", {"error": str(exc)})
                send_telegram_alert("error", f"Watchdog error: {exc}")
            interval = max(3, int(load_settings().get("sync_interval_sec", 10)))
            self._stop_evt.wait(interval)

    def place_smart_order(
        self,
        symbol: str,
        side: str,
        qty: int,
        product: str,
        limit_price: float,
        sl_price: float,
        target_price: float | None = None,
        targets: list[dict[str, Any]] | None = None,
        move_sl_be_after_t1: bool = True,
    ) -> dict[str, Any]:
        """Place LIMIT order, chase every 5s up to N retries while SL is unbreached, then arm SL."""
        side = side.upper()
        product = product.upper()
        if side == "SHORT" and product == "CNC":
            return {"ok": False, "error": "SHORT equity orders must use MIS (intraday)."}

        broker = get_active_broker()
        ord_res = broker.place_order(symbol, side, qty, "LIMIT", product, price=limit_price)
        STORE.log_audit("order_placed", {"order": ord_res, "sl_price": sl_price, "target_price": target_price})

        # Register SL expectation & start background 5s chase thread
        threading.Thread(
            target=self._chase_and_arm_sl,
            args=(ord_res["order_id"], symbol.upper(), side, qty, product, limit_price, sl_price, target_price, targets or [], move_sl_be_after_t1),
            daemon=True,
        ).start()
        return {"ok": True, "order": ord_res}

    def _chase_and_arm_sl(
        self,
        order_id: str,
        symbol: str,
        side: str,
        qty: int,
        product: str,
        init_price: float,
        sl_price: float,
        target_price: float | None,
        targets: list[dict[str, Any]],
        move_sl_be_after_t1: bool,
    ) -> None:
        cfg = load_settings()
        interval = max(2, int(cfg.get("chase_interval_sec", 5)))
        max_retries = max(0, int(cfg.get("chase_max_retries", 2)))
        max_slip_pct = float(cfg.get("chase_max_slip_pct", 0.5))
        broker = get_active_broker()

        for attempt in range(max_retries + 1):
            orders = {o["order_id"]: o for o in broker.get_orders()}
            cur = orders.get(order_id, {})
            if cur.get("status") == "COMPLETE":
                self._arm_sl_order(symbol, side, qty, product, sl_price, target_price, targets=targets, move_sl_be_after_t1=move_sl_be_after_t1)
                send_telegram_alert("fill", f"{symbol} {side} {qty} FILLED @ {cur.get('fill_price', init_price)}. SL armed @ {sl_price}")
                return
            if attempt == max_retries:
                break
            time.sleep(interval)
            ltp = broker.get_ltp(symbol)
            sl_breached = (ltp <= sl_price) if side == "BUY" else (ltp >= sl_price)
            slip_pct = abs(ltp - init_price) / max(init_price, 1e-6) * 100.0
            if sl_breached or slip_pct > max_slip_pct:
                broker.cancel_order(order_id)
                STORE.log_audit("chase_aborted", {"symbol": symbol, "ltp": ltp, "sl_breached": sl_breached, "slip_pct": slip_pct})
                send_telegram_alert("sl_breach", f"{symbol} entry chase aborted (LTP={ltp}, SL={sl_price}, slip={slip_pct:.2f}%).")
                return
            broker.modify_order(order_id, price=ltp)
            STORE.log_audit("chase_modified", {"order_id": order_id, "attempt": attempt + 1, "new_price": ltp})

        # After max retries, if still unfilled, convert to MARKET or cancel based on settings
        orders = {o["order_id"]: o for o in broker.get_orders()}
        cur = orders.get(order_id, {})
        if cur.get("status") != "COMPLETE":
            if cfg.get("direct_market_exit", True):
                broker.modify_order(order_id, order_type="MARKET")
                self._arm_sl_order(symbol, side, qty, product, sl_price, target_price, targets=targets, move_sl_be_after_t1=move_sl_be_after_t1)
                send_telegram_alert("fill", f"{symbol} {side} {qty} converted to MARKET after {max_retries} chase(s). SL @ {sl_price}")
            else:
                broker.cancel_order(order_id)

    def _arm_sl_order(
        self,
        symbol: str,
        entry_side: str,
        qty: int,
        product: str,
        sl_price: float,
        target_price: float | None,
        targets: list[dict[str, Any]] | None = None,
        move_sl_be_after_t1: bool = True,
    ) -> None:
        broker = get_active_broker()
        sl_side = "SELL" if entry_side == "BUY" else "BUY"
        sl_ord = broker.place_order(symbol, sl_side, qty, "SL-M", product, price=sl_price, trigger_price=sl_price)

        target_oids: list[str] = []
        rem_for_targets = qty
        for leg in (targets or []):
            if rem_for_targets <= 0:
                break
            tq = min(rem_for_targets, int(leg.get("qty", 0)))
            tpx = float(leg.get("price", 0))
            if tq > 0 and tpx > 0:
                t_ord = broker.place_order(symbol, sl_side, tq, "LIMIT", product, price=tpx)
                target_oids.append(t_ord["order_id"])
                rem_for_targets -= tq

        self.sl_registry[symbol] = {
            "sl_price": sl_price,
            "sl_order_id": sl_ord["order_id"],
            "sl_side": sl_side,
            "qty": qty,
            "product": product,
            "target_price": target_price,
            "target_order_ids": target_oids,
            "move_sl_be_after_t1": move_sl_be_after_t1,
            "be_moved": False,
        }
        for p in broker.get_positions():
            if p["symbol"] == symbol:
                p["sl_price"] = sl_price
                p["sl_order_id"] = sl_ord["order_id"]
                p["target_price"] = target_price
                if not p.get("initial_risk_inr"):
                    p["initial_risk_inr"] = round(abs(p["avg_price"] - sl_price) * p.get("peak_qty", abs(p["net_qty"])), 2)

    def sync_and_guard(self) -> dict[str, Any]:
        """10s broker sync + SL Watchdog verifying SL is intact in broker/exchange."""
        broker = get_active_broker()
        positions = broker.get_positions()
        orders = broker.get_orders()
        open_order_ids = {o["order_id"] for o in orders if o["status"] in ("OPEN", "TRIGGER_PENDING")}
        cfg = load_settings()

        for p in positions:
            sym = p["symbol"]
            reg = self.sl_registry.get(sym)
            sl_px = p.get("sl_price") or (reg["sl_price"] if reg else None)
            sl_oid = p.get("sl_order_id") or (reg["sl_order_id"] if reg else None)
            if not sl_px:
                continue
            ltp = p.get("ltp") or broker.get_ltp(sym)
            is_long = p["net_qty"] > 0
            breached = (ltp <= sl_px) if is_long else (ltp >= sl_px)

            # If partial target filled, shrink SL qty (and optionally move SL to breakeven)
            open_qty = abs(int(p["net_qty"]))
            if reg and open_qty > 0 and open_qty < int(reg.get("qty", open_qty)):
                if sl_oid and sl_oid in open_order_ids:
                    broker.cancel_order(sl_oid)
                new_sl = p["avg_price"] if (reg.get("move_sl_be_after_t1") and not reg.get("be_moved")) else sl_px
                self._arm_sl_order(sym, "BUY" if is_long else "SELL", open_qty, p["product"], new_sl, p.get("target_price"))
                self.sl_registry[sym]["be_moved"] = True
                self.sl_registry[sym]["target_order_ids"] = reg.get("target_order_ids", [])
                send_telegram_alert("fill", f"{sym} partial target filled. SL synced to {open_qty} qty @ {new_sl}")
                continue

            # Check if SL was auto-removed/cancelled by broker/exchange
            if sl_oid and sl_oid not in open_order_ids:
                STORE.log_audit("sl_missing_detected", {"symbol": sym, "ltp": ltp, "sl_price": sl_px})
                if breached:
                    exit_side = "SELL" if is_long else "BUY"
                    broker.place_order(sym, exit_side, abs(p["net_qty"]), "MARKET", p["product"])
                    send_telegram_alert("sl_breach", f"ALERT: {sym} SL missing & breached (LTP {ltp} vs SL {sl_px}). Executed MARKET exit!")
                elif cfg.get("auto_replace_missing_sl", True):
                    self._arm_sl_order(sym, "BUY" if is_long else "SELL", abs(p["net_qty"]), p["product"], sl_px, p.get("target_price"))
                    send_telegram_alert("sl_missing", f"WARNING: {sym} SL was removed by broker/exchange. Re-placed SL @ {sl_px}.")


        # Evaluate Telegram Price Alerts
        alerts_p = __import__("pathlib").Path("data/price_alerts.json")
        if alerts_p.exists():
            try:
                import json as _json
                alerts = _json.loads(alerts_p.read_text(encoding="utf-8"))
                changed = False
                remaining = []
                for a in alerts:
                    ltp_a = broker.get_ltp(a["symbol"])
                    cond = a.get("condition", ">=")
                    hit = (ltp_a >= float(a["price"])) if cond == ">=" else (ltp_a <= float(a["price"]))
                    if hit:
                        changed = True
                        send_telegram_alert("price_alert", f"{a['symbol']} @ ₹{ltp_a}: {a.get('message', 'Alert triggered')} (Alert closed)")
                    else:
                        remaining.append(a)
                if changed:
                    alerts_p.write_text(_json.dumps(remaining), encoding="utf-8")
            except Exception:
                pass


        # Record daily equity snapshot automatically (for Account P&L, Capital Used & DD charts)
        try:
            import json as _json2
            snap_p = __import__("pathlib").Path("data/equity_snapshots.json")
            snaps = _json2.loads(snap_p.read_text(encoding="utf-8")) if snap_p.exists() else []
            today_s = datetime.now().strftime("%Y-%m-%d")
            closed_t = getattr(broker, "closed_trades", [])
            realized = sum(float(t.get("net_pnl", 0.0)) for t in closed_t)
            mtm = sum(float(p.get("mtm", 0.0)) for p in positions)
            used_cap = sum(abs(int(p.get("net_qty", 0))) * float(p.get("avg_price", 0)) for p in positions)
            cap = float(cfg.get("paper_capital", 1_000_000.0))
            eq_val = round(cap + realized + mtm, 2)
            rec = {"date": today_s, "equity": eq_val, "capital_used": round(used_cap, 2), "capital": cap}
            if snaps and snaps[-1].get("date") == today_s:
                snaps[-1] = rec
            else:
                snaps.append(rec)
            snap_p.parent.mkdir(parents=True, exist_ok=True)
            snap_p.write_text(_json2.dumps(snaps[-1000:]), encoding="utf-8")
            db = STORE._get_db()
            if db is not None:
                db.equity_snapshots.update_one({"date": today_s}, {"$set": rec}, upsert=True)
        except Exception:
            pass

        self.last_sync_ts = datetime.now().strftime("%H:%M:%S")
        return {"positions": positions, "orders": orders, "last_sync_ts": self.last_sync_ts}

    def quick_exit(self, symbol: str, fraction: float = 1.0) -> dict[str, Any]:
        broker = get_active_broker()
        pos = next((p for p in broker.get_positions() if p["symbol"] == symbol.upper()), None)
        if not pos:
            return {"ok": False, "error": f"No open position for {symbol}"}
        qty = max(1, int(round(abs(pos["net_qty"]) * fraction)))
        side = "SELL" if pos["net_qty"] > 0 else "BUY"
        res = broker.place_order(pos["symbol"], side, qty, "MARKET", pos["product"])
        if fraction >= 0.99 and pos["symbol"] in self.sl_registry:
            broker.cancel_order(self.sl_registry[pos["symbol"]]["sl_order_id"])
            self.sl_registry.pop(pos["symbol"], None)
        send_telegram_alert("fill", f"Quick Exit {pos['symbol']} {side} {qty} @ MARKET")
        return {"ok": True, "order": res}

    def flatten_all(self) -> dict[str, Any]:
        broker = get_active_broker()
        for o in broker.get_orders():
            if o["status"] in ("OPEN", "TRIGGER_PENDING"):
                broker.cancel_order(o["order_id"])
        exited = []
        for p in broker.get_positions():
            side = "SELL" if p["net_qty"] > 0 else "BUY"
            exited.append(broker.place_order(p["symbol"], side, abs(p["net_qty"]), "MARKET", p["product"]))
        self.sl_registry.clear()
        send_telegram_alert("sl_breach", f"PANIC FLATTEN ALL triggered. Closed {len(exited)} position(s).")
        return {"ok": True, "exited": len(exited)}


EXEC_MGR = ExecutionManager()
