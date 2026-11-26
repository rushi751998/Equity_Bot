"""Settings API: .env broker credentials, PyOTP 2FA, Multi-Bot Telegram, MongoDB & execution guards."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body

from tfalgo.web.core.config_store import (
    current_totp_code,
    generate_totp_secret,
    load_settings,
    save_settings,
    verify_totp_code,
)
from tfalgo.web.core.notifier import send_telegram_alert

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
def get_settings() -> dict[str, Any]:
    return {"ok": True, "settings": load_settings()}


@router.post("")
def update_settings(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    saved = save_settings(body)
    return {"ok": True, "settings": saved}


@router.post("/telegram_test")
def test_telegram(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    msg = str(body.get("message") or "Test ping from tfalgo Quant Workstation")
    results = send_telegram_alert("test", msg)
    return {"ok": True, "results": results}


@router.post("/pyotp_setup")
def setup_pyotp(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    secret = str(body.get("secret") or "").strip() or generate_totp_secret()
    code, uri = current_totp_code(secret)
    return {"ok": True, "secret": secret, "current_code": code, "provisioning_uri": uri}


@router.post("/pyotp_verify")
def verify_pyotp(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    ok = verify_totp_code(str(body.get("secret", "")), str(body.get("code", "")))
    return {"ok": ok}
