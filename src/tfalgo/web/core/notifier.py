"""Multi-bot Telegram alert router."""
from __future__ import annotations

import json
import urllib.request
from typing import Any

from tfalgo.web.core.config_store import STORE, load_settings


def send_telegram_alert(event_type: str, text: str, bot_index: int | None = None) -> list[dict[str, Any]]:
    cfg = load_settings()
    bots = cfg.get("telegram_bots", [])
    results: list[dict[str, Any]] = []
    for idx, bot in enumerate(bots):
        if bot_index is not None and idx != bot_index:
            continue
        token = (bot.get("token") or "").strip()
        chat_id = (bot.get("chat_id") or "").strip()
        events = bot.get("events") or []
        if not token or not chat_id:
            if bot_index is not None:
                results.append({"bot": bot.get("name"), "ok": False, "error": "Token or Chat ID missing"})
            continue
        if event_type != "test" and events and event_type not in events:
            continue
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        body = json.dumps({"chat_id": chat_id, "text": f"[tfalgo:{event_type.upper()}] {text}"}).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=6) as resp:
                ok = resp.status == 200
            results.append({"bot": bot.get("name"), "ok": ok})
        except Exception as exc:
            results.append({"bot": bot.get("name"), "ok": False, "error": str(exc)})
    STORE.log_audit("telegram_alert", {"event_type": event_type, "results": results})
    return results
