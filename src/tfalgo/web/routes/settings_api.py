"""Settings API: .env, MongoDB auto-init, PyOTP 2FA, individual Telegram bot test, Zerodha Kite v3 OAuth."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body

from tfalgo.web.core.brokers import ZerodhaBroker
from tfalgo.web.core.config_store import (
    STORE,
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


@router.post("/mongo_test")
def test_and_init_mongo(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    return STORE.ensure_mongo_schema(
        uri_override=str(body.get("mongo_uri") or ""),
        db_override=str(body.get("mongo_db") or ""),
    )


@router.post("/telegram_test")
def test_telegram(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    msg = str(body.get("message") or "Test ping from tfalgo Quant Workstation")
    bot_idx = body.get("bot_index")
    idx = int(bot_idx) if bot_idx is not None else None
    results = send_telegram_alert("test", msg, bot_index=idx)
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


@router.post("/zerodha/login_url")
def zerodha_login_url(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    api_key = str(body.get("api_key") or load_settings()["brokers"]["zerodha"].get("api_key", "")).strip()
    if not api_key:
        return {"ok": False, "error": "Enter Zerodha API Key first."}
    return {"ok": True, "url": ZerodhaBroker.login_url(api_key)}


@router.post("/zerodha/exchange_token")
def zerodha_exchange_token(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    cfg = load_settings()
    z = cfg["brokers"]["zerodha"]
    api_key = str(body.get("api_key") or z.get("api_key", "")).strip()
    api_secret = str(body.get("api_secret") or z.get("api_secret", "")).strip()
    req_token = str(body.get("request_token") or "").strip()
    if not api_key or not api_secret or not req_token:
        return {"ok": False, "error": "API Key, API Secret, and request_token are required."}
    try:
        res = ZerodhaBroker.exchange_request_token(api_key, api_secret, req_token)
        access_token = res.get("data", {}).get("access_token", "")
        if not access_token:
            return {"ok": False, "error": f"Token missing in response: {res}"}
        z["api_key"] = api_key
        z["api_secret"] = api_secret
        z["access_token"] = access_token
        save_settings({"brokers": {"zerodha": z}})
        return {"ok": True, "access_token": access_token}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
