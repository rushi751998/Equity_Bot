"""Portfolio live trading, 10s sync, quick order, and 27-metric R:R + Kelly/Compounding API."""
from __future__ import annotations

import math
from typing import Any

from fastapi import APIRouter, Body

from tfalgo.web.core.brokers import PaperBroker, get_active_broker
from tfalgo.web.core.config_store import STORE, load_settings
from tfalgo.web.core.execution import EXEC_MGR

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("/state")
def get_portfolio_state() -> dict[str, Any]:
    snap = EXEC_MGR.sync_and_guard()
    cfg = load_settings()
    broker = get_active_broker()
    closed = getattr(broker, "closed_trades", [])
    for _t in closed:
        if "charges" not in _t:
            _q = float(_t.get("qty", 0))
            _ch = _calc_live_charges(_q * float(_t.get("entry_price", 0)), _q * float(_t.get("exit_price", 0)), _t.get("product", "MIS"))
            _t["charges"] = _ch["total"]
            _t["charges_detail"] = _ch
    realized = sum(float(t.get("net_pnl", 0.0)) for t in closed)
    mtm = sum(float(p.get("mtm", 0.0)) for p in snap["positions"])
    cap = float(cfg.get("paper_capital", 1_000_000.0))
    return {
        "ok": True,
        "broker": broker.name,
        "capital": cap,
        "realized_pnl": round(realized, 2),
        "unrealized_mtm": round(mtm, 2),
        "equity": round(cap + realized + mtm, 2),
        "positions": snap["positions"],
        "orders": snap["orders"][-50:][::-1],
        "closed_trades": closed[-30:][::-1],
        "last_sync_ts": snap["last_sync_ts"],
    }


@router.post("/order")
def place_portfolio_order(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    symbol = str(body.get("symbol", "")).strip().upper()
    side = str(body.get("side", "BUY")).strip().upper()
    product = str(body.get("product", "MIS")).strip().upper()
    qty = int(body.get("qty", 0))
    limit_price = float(body.get("limit_price", 0.0))
    sl_price = float(body.get("sl_price", 0.0))
    target_price = float(body["target_price"]) if body.get("target_price") else None
    if not symbol or qty <= 0 or limit_price <= 0 or sl_price <= 0:
        return {"ok": False, "error": "Symbol, Qty, Limit Price, and SL Price are required."}
    targets = body.get("targets") or []
    move_be = bool(body.get("move_sl_be_after_t1", True))
    return EXEC_MGR.place_smart_order(symbol, side, qty, product, limit_price, sl_price, target_price, targets=targets, move_sl_be_after_t1=move_be)


@router.post("/exit")
def exit_portfolio_position(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return EXEC_MGR.quick_exit(str(body.get("symbol", "")), fraction=float(body.get("fraction", 1.0)), exact_qty=int(body["qty"]) if body.get("qty") else None)


@router.post("/flatten")
def flatten_all_positions() -> dict[str, Any]:
    return EXEC_MGR.flatten_all()


@router.post("/tick")
def update_paper_tick(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    broker = get_active_broker()
    if not isinstance(broker, PaperBroker):
        return {"ok": False, "error": "Tick override only applies in Paper mode."}
    broker.set_ltp(str(body.get("symbol", "")), float(body.get("ltp", 0.0)))
    return {"ok": True}


@router.post("/calc")
def calculate_trade_metrics(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Compute all 27 position sizing, R:R, Expectancy, Kelly & Compounding metrics (independent of backtest)."""
    cap = max(1.0, float(body.get("capital", 1_000_000.0)))
    risk_pct = max(0.01, float(body.get("risk_pct", 1.0)))
    max_pos_pct = max(0.1, float(body.get("invest_pct", 5.0)))
    entry = max(0.01, float(body.get("entry_price", 100.0)))
    stop = max(0.01, float(body.get("stop_price", 98.0)))
    target = float(body.get("target_price", 106.0))
    win_rate = max(0.01, min(0.99, float(body.get("win_rate_pct", 45.0)) / 100.0))
    avg_win_r = max(0.1, float(body.get("avg_win_r", 2.5)))
    avg_loss_r = max(0.1, float(body.get("avg_loss_r", 1.0)))
    cost_pct_rt = max(0.0, float(body.get("cost_pct_rt", 0.12))) / 100.0
    target_profit_inr = max(1.0, float(body.get("target_profit_inr", cap)))

    risk_per_share = abs(entry - stop)
    if risk_per_share <= 0:
        return {"ok": False, "error": "Entry and Stop cannot be equal."}

    risk_amt = cap * (risk_pct / 100.0)
    qty_needed = risk_amt / risk_per_share
    pos_needed = qty_needed * entry
    max_pos_inr = cap * (max_pos_pct / 100.0)
    pos_applied = min(pos_needed, max_pos_inr)
    qty_shares = max(1, int(math.floor(pos_applied / entry)))
    pos_applied = qty_shares * entry
    pos_pct = (pos_applied / cap) * 100.0

    # Include round-trip costs in actual risk
    cost_inr = pos_applied * cost_pct_rt
    actual_risk_inr = qty_shares * risk_per_share + cost_inr
    actual_risk_pct = (actual_risk_inr / cap) * 100.0

    reward_per_share = abs(target - entry)
    trade_rr = reward_per_share / risk_per_share
    net_avg_win_pct = ((avg_win_r * (risk_per_share / entry)) - cost_pct_rt) * 100.0
    net_avg_loss_pct = ((avg_loss_r * (risk_per_share / entry)) + cost_pct_rt) * 100.0
    avg_win_inr = pos_applied * (net_avg_win_pct / 100.0)
    avg_loss_inr = pos_applied * (net_avg_loss_pct / 100.0)

    breakeven_wr = (avg_loss_inr / max(avg_win_inr + avg_loss_inr, 1e-6)) * 100.0
    exp_inr = win_rate * avg_win_inr - (1.0 - win_rate) * avg_loss_inr
    exp_r = (exp_inr / actual_risk_inr) if actual_risk_inr > 0 else 0.0
    exp_cap_pct = (exp_inr / cap) * 100.0

    trades_fixed = (target_profit_inr / exp_inr) if exp_inr > 0 else float("inf")
    winners_needed = trades_fixed * win_rate if math.isfinite(trades_fixed) else float("inf")
    losers_expected = trades_fixed * (1.0 - win_rate) if math.isfinite(trades_fixed) else float("inf")

    # Kelly / Log-Growth per trade (spec vs capital-scaled)
    w_frac_pos = max(-0.99, net_avg_win_pct / 100.0)
    l_frac_pos = max(-0.99, -(net_avg_loss_pct / 100.0))
    log_g_spec = win_rate * math.log1p(w_frac_pos) + (1.0 - win_rate) * math.log1p(l_frac_pos)

    f_cap = pos_applied / cap
    log_g_scaled = win_rate * math.log1p(f_cap * w_frac_pos) + (1.0 - win_rate) * math.log1p(f_cap * l_frac_pos)

    target_mult = (cap + target_profit_inr) / cap
    trades_comp_spec = (math.log(target_mult) / log_g_spec) if log_g_spec > 0 else float("inf")
    trades_comp_scaled = (math.log(target_mult) / log_g_scaled) if log_g_scaled > 0 else float("inf")

    pf = (win_rate * avg_win_inr) / max((1.0 - win_rate) * avg_loss_inr, 1e-6)
    verdict = "STRONG EDGE" if (exp_r > 0.25 and log_g_scaled > 0 and trade_rr >= 2.0) else ("MARGINAL" if exp_inr > 0 else "NEGATIVE EXPECTANCY")

    def _fmt(v: float) -> str:
        return "∞" if not math.isfinite(v) else f"{v:,.1f}"

    return {
        "ok": True,
        "trade_rr": round(trade_rr, 2),
        "metrics": [
            ["Risk Amount per Trade (₹)", f"₹{risk_amt:,.0f}"],
            ["Position Size Needed (₹)", f"₹{pos_needed:,.0f}"],
            ["Position Size Applied (₹, Capped)", f"₹{pos_applied:,.0f}"],
            ["Position as % of Capital", f"{pos_pct:.2f}%"],
            ["Actual Risk per Trade (₹)", f"₹{actual_risk_inr:,.0f}"],
            ["Actual Risk (% of Capital)", f"{actual_risk_pct:.2f}%"],
            ["Quantity (Shares)", f"{qty_shares:,}"],
            ["Stop Price (₹)", f"₹{stop:,.2f}"],
            ["Target Price (₹)", f"₹{target:,.2f}"],
            ["Net Avg Win (% of position, net of costs)", f"{net_avg_win_pct:.2f}%"],
            ["Net Avg Loss (% of position, net of costs)", f"{net_avg_loss_pct:.2f}%"],
            ["Avg Win (₹)", f"₹{avg_win_inr:,.0f}"],
            ["Avg Loss (₹)", f"₹{avg_loss_inr:,.0f}"],
            ["Breakeven Win Rate (%)", f"{breakeven_wr:.1f}%"],
            ["Expectancy per Trade (₹)", f"₹{exp_inr:,.0f}"],
            ["Expectancy (R-Multiples)", f"{exp_r:.2f}R"],
            ["Expectancy (% of Capital per Trade)", f"{exp_cap_pct:.3f}%"],
            ["Target Profit Amount (₹)", f"₹{target_profit_inr:,.0f}"],
            ["Trades Needed – Fixed Size (No Compounding)", _fmt(trades_fixed)],
            ["Expected Log-Growth per Trade (Kelly/Compounding) – per spec", f"{log_g_spec * 100:.3f}%"],
            ["Trades Needed – Compounding – per spec", _fmt(trades_comp_spec)],
            ["Winners Needed (from fixed-size trades needed)", _fmt(winners_needed)],
            ["Losers Expected", _fmt(losers_expected)],
            ["Expected Profit Factor", f"{pf:.2f}"],
            ["VERDICT", verdict],
            ["Extra: Log-Growth per Trade – capital-scaled (realistic)", f"{log_g_scaled * 100:.3f}%"],
            ["Extra: Trades Needed – Compounding, capital-scaled", _fmt(trades_comp_scaled)],
        ],
        "qty_shares": qty_shares,
    }

import base64
import json
import uuid
from pathlib import Path

JOURNAL_PATH = Path("data/trade_journal.json")
JOURNAL_IMG_DIR = Path("data/journal_imgs")
ALERTS_PATH = Path("data/price_alerts.json")


def _load_json_list(path: Path) -> list[dict[str, Any]]:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_json_list(path: Path, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, default=str), encoding="utf-8")


@router.get("/journal/{trade_key}")
def get_trade_journal(trade_key: str) -> dict[str, Any]:
    all_items = _load_json_list(JOURNAL_PATH)
    items = [x for x in all_items if x.get("trade_key") == trade_key]
    return {"ok": True, "entries": items}


@router.post("/journal")
def add_trade_journal(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    trade_key = str(body.get("trade_key", "")).strip()
    comment = str(body.get("comment", "")).strip()
    img_b64 = str(body.get("image_base64") or "").strip()
    if not trade_key or (not comment and not img_b64):
        return {"ok": False, "error": "Trade key and comment or image required."}

    img_data_url = ""
    if img_b64:
        img_data_url = img_b64
        try:
            JOURNAL_IMG_DIR.mkdir(parents=True, exist_ok=True)
            raw_b64 = img_b64.split(",", 1)[1] if "," in img_b64 else img_b64
            (JOURNAL_IMG_DIR / f"{trade_key}_{uuid.uuid4().hex[:6]}.png").write_bytes(base64.b64decode(raw_b64))
        except Exception:
            pass

    rec = {
        "id": uuid.uuid4().hex[:8],
        "trade_key": trade_key,
        "comment": comment,
        "image_data_url": img_data_url,
        "ts": __import__("datetime").datetime.now().isoformat(),
    }
    items = _load_json_list(JOURNAL_PATH)
    items.append(rec)
    _save_json_list(JOURNAL_PATH, items)
    STORE.log_audit("trade_journal", {"trade_key": trade_key, "comment": comment, "has_image": bool(img_data_url)})
    return {"ok": True, "entry": rec}


@router.get("/alerts")
def list_price_alerts() -> dict[str, Any]:
    return {"ok": True, "alerts": _load_json_list(ALERTS_PATH)}


@router.post("/alerts")
def create_price_alert(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    sym = str(body.get("symbol", "")).strip().upper()
    cond = str(body.get("condition", ">="))
    price = float(body.get("price", 0.0))
    msg = str(body.get("message", "")).strip() or f"{sym} hit {cond} {price}"
    if not sym or price <= 0:
        return {"ok": False, "error": "Symbol and valid target price required."}
    alerts = _load_json_list(ALERTS_PATH)
    rec = {"id": uuid.uuid4().hex[:8], "symbol": sym, "condition": cond, "price": price, "message": msg, "triggered": False}
    alerts.append(rec)
    _save_json_list(ALERTS_PATH, alerts)
    return {"ok": True, "alert": rec}


@router.delete("/alerts/{alert_id}")
def delete_price_alert(alert_id: str) -> dict[str, Any]:
    alerts = [a for a in _load_json_list(ALERTS_PATH) if a.get("id") != alert_id]
    _save_json_list(ALERTS_PATH, alerts)
    return {"ok": True}


FUNDS_PATH = Path("data/funds_history.json")


def _calc_live_charges(buy_n: float, sell_n: float, product: str) -> dict[str, float]:
    turnover = buy_n + sell_n
    if product.upper() == "MIS":
        brok = min(20.0, 0.0003 * buy_n) + min(20.0, 0.0003 * sell_n)
        stt = 0.00025 * sell_n
        stamp = 0.00003 * buy_n
    else:
        brok = 0.0
        stt = 0.001 * turnover
        stamp = 0.00015 * buy_n
    exch = 0.0000335 * turnover
    gst = 0.18 * (brok + exch)
    tot = round(brok + stt + stamp + exch + gst, 2)
    return {"brokerage": round(brok, 2), "stt": round(stt, 2), "stamp": round(stamp, 2), "exch_sebi": round(exch, 2), "gst": round(gst, 2), "total": tot}


@router.post("/cancel/{order_id}")
def cancel_portfolio_order(order_id: str) -> dict[str, Any]:
    res = get_active_broker().cancel_order(order_id)
    return {"ok": True, "order": res}


@router.get("/funds")
def get_funds_summary() -> dict[str, Any]:
    cfg = load_settings()
    base_cap = float(cfg.get("paper_capital", 1_000_000.0))
    txns = _load_json_list(FUNDS_PATH)
    added = sum(float(x.get("amount", 0)) for x in txns if x.get("kind") == "DEPOSIT")
    withdrawn = sum(float(x.get("amount", 0)) for x in txns if x.get("kind") == "WITHDRAW")

    broker = get_active_broker()
    closed = getattr(broker, "closed_trades", [])
    for _t in closed:
        if "charges" not in _t:
            _q = float(_t.get("qty", 0))
            _ch = _calc_live_charges(_q * float(_t.get("entry_price", 0)), _q * float(_t.get("exit_price", 0)), _t.get("product", "MIS"))
            _t["charges"] = _ch["total"]
            _t["charges_detail"] = _ch
    positions = broker.get_positions()
    realized = sum(float(t.get("net_pnl", 0.0)) for t in closed)
    total_charges = 0.0
    charges_rows = []
    for t in closed:
        q = float(t.get("qty", 0))
        b_n = q * float(t.get("entry_price", 0))
        s_n = q * float(t.get("exit_price", 0))
        ch = _calc_live_charges(b_n, s_n, t.get("product", "MIS"))
        t["charges"] = ch["total"]
        t["charges_detail"] = ch
        total_charges += ch["total"]
        charges_rows.append({"trade_id": t.get("trade_id"), "symbol": t.get("symbol"), "product": t.get("product"), **ch})

    used_margin = sum(abs(int(p.get("net_qty", 0))) * float(p.get("avg_price", 0)) for p in positions)
    available = base_cap + added - withdrawn + realized - total_charges - used_margin
    return {
        "ok": True,
        "base_capital": round(base_cap, 2),
        "added": round(added, 2),
        "withdrawn": round(withdrawn, 2),
        "realized_pnl": round(realized, 2),
        "total_charges": round(total_charges, 2),
        "used_margin": round(used_margin, 2),
        "available_funds": round(available, 2),
        "transactions": txns[::-1],
        "charges_rows": charges_rows[::-1],
    }


@router.post("/funds")
def add_fund_txn(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    kind = str(body.get("kind", "DEPOSIT")).upper()
    amt = float(body.get("amount", 0.0))
    note = str(body.get("note", "")).strip() or kind
    if amt <= 0 or kind not in ("DEPOSIT", "WITHDRAW"):
        return {"ok": False, "error": "Valid amount and DEPOSIT/WITHDRAW required."}
    txns = _load_json_list(FUNDS_PATH)
    rec = {"id": uuid.uuid4().hex[:8], "ts": __import__("datetime").datetime.now().isoformat(), "kind": kind, "amount": round(amt, 2), "note": note}
    txns.append(rec)
    _save_json_list(FUNDS_PATH, txns)
    STORE.log_audit("fund_txn", rec)
    return {"ok": True, "txn": rec}