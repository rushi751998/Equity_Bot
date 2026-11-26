"""Settings, .env persistence, PyOTP 2FA helper, and MongoDB/JSON dual store."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

ENV_PATH = Path(".env")
LOCAL_STATE_PATH = Path("data/live_state.json")
AUDIT_LOG_PATH = Path("reports/live_audit.log")

DEFAULT_SETTINGS: dict[str, Any] = {
    "active_broker": "paper",
    "sync_interval_sec": 10,
    "chase_interval_sec": 5,
    "chase_max_retries": 2,
    "chase_max_slip_pct": 0.5,
    "direct_market_exit": True,
    "auto_replace_missing_sl": True,
    "default_capital_pct": 5.0,
    "daily_max_loss_pct": 3.0,
    "paper_capital": 1_000_000.0,
    "mongo_uri": "",
    "mongo_db": "tfalgo_live",
    "telegram_bots": [
        {"name": "Critical SL & Errors", "token": "", "chat_id": "", "events": ["sl_breach", "sl_missing", "error"]},
        {"name": "Fills & EOD Summary", "token": "", "chat_id": "", "events": ["fill", "eod", "health"]},
    ],
    "brokers": {
        "zerodha": {"api_key": "", "api_secret": "", "user_id": "", "password": "", "totp_secret": "", "access_token": ""},
        "fyers": {"app_id": "", "secret_key": "", "redirect_uri": "", "totp_secret": "", "access_token": ""},
        "kotak_neo": {"consumer_key": "", "consumer_secret": "", "mobile": "", "mpin": "", "totp_secret": "", "access_token": ""},
    },
}


def read_env() -> dict[str, str]:
    out: dict[str, str] = {}
    if not ENV_PATH.exists():
        return out
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def write_env_updates(updates: dict[str, str]) -> None:
    env = read_env()
    for k, v in updates.items():
        if v is not None:
            env[k] = str(v)
    lines = [f'{k}="{v}"' for k, v in sorted(env.items())]
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for k, v in updates.items():
        if v is not None:
            os.environ[k] = str(v)


def load_settings() -> dict[str, Any]:
    cfg = json.loads(json.dumps(DEFAULT_SETTINGS))
    env = read_env()
    if env.get("TFALGO_SETTINGS_JSON"):
        try:
            saved = json.loads(env["TFALGO_SETTINGS_JSON"])
            for k, v in saved.items():
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k].update(v)
                else:
                    cfg[k] = v
        except Exception:
            pass
    # Overlay direct .env keys
    if env.get("MONGO_URI"):
        cfg["mongo_uri"] = env["MONGO_URI"]
    if env.get("ZERODHA_API_KEY"):
        cfg["brokers"]["zerodha"]["api_key"] = env["ZERODHA_API_KEY"]
    if env.get("FYERS_APP_ID"):
        cfg["brokers"]["fyers"]["app_id"] = env["FYERS_APP_ID"]
    if env.get("KOTAK_CONSUMER_KEY"):
        cfg["brokers"]["kotak_neo"]["consumer_key"] = env["KOTAK_CONSUMER_KEY"]
    return cfg


def save_settings(payload: dict[str, Any]) -> dict[str, Any]:
    cur = load_settings()
    for k, v in payload.items():
        if isinstance(v, dict) and isinstance(cur.get(k), dict):
            cur[k].update(v)
        else:
            cur[k] = v

    env_updates = {
        "TFALGO_SETTINGS_JSON": json.dumps(cur),
        "MONGO_URI": cur.get("mongo_uri", ""),
        "ZERODHA_API_KEY": cur["brokers"]["zerodha"].get("api_key", ""),
        "ZERODHA_API_SECRET": cur["brokers"]["zerodha"].get("api_secret", ""),
        "ZERODHA_TOTP_SECRET": cur["brokers"]["zerodha"].get("totp_secret", ""),
        "FYERS_APP_ID": cur["brokers"]["fyers"].get("app_id", ""),
        "FYERS_TOTP_SECRET": cur["brokers"]["fyers"].get("totp_secret", ""),
        "KOTAK_CONSUMER_KEY": cur["brokers"]["kotak_neo"].get("consumer_key", ""),
        "KOTAK_TOTP_SECRET": cur["brokers"]["kotak_neo"].get("totp_secret", ""),
    }
    for idx, bot in enumerate(cur.get("telegram_bots", [])[:4], start=1):
        env_updates[f"TG_BOT{idx}_TOKEN"] = bot.get("token", "")
        env_updates[f"TG_BOT{idx}_CHAT_ID"] = bot.get("chat_id", "")

    write_env_updates(env_updates)
    return cur


def generate_totp_secret() -> str:
    try:
        import pyotp
        return pyotp.random_base32()
    except ImportError:
        import base64
        return base64.b32encode(os.urandom(20)).decode("ascii")


def current_totp_code(secret: str) -> tuple[str, str]:
    """Return (6-digit code, provisioning_uri)."""
    if not secret:
        return "", ""
    try:
        import pyotp
        totp = pyotp.TOTP(secret)
        return totp.now(), totp.provisioning_uri(name="pilot@tfalgo", issuer_name="tfalgo Quant")
    except ImportError:
        return "INSTALL_PYOTP", ""


def verify_totp_code(secret: str, code: str) -> bool:
    if not secret or not code:
        return False
    try:
        import pyotp
        return bool(pyotp.TOTP(secret).verify(code.strip(), valid_window=1))
    except ImportError:
        return False


class PersistenceStore:
    """Dual MongoDB (when MONGO_URI configured & pymongo installed) + local JSON/log store."""

    def __init__(self) -> None:
        self._client = None
        self._db = None

    def _get_db(self):
        cfg = load_settings()
        uri = cfg.get("mongo_uri") or os.environ.get("MONGO_URI", "")
        if not uri:
            return None
        try:
            from pymongo import MongoClient
            if self._client is None:
                self._client = MongoClient(uri, serverSelectionTimeoutMS=2500)
                self._db = self._client[cfg.get("mongo_db", "tfalgo_live")]
            return self._db
        except Exception:
            return None

    def save_live_state(self, state: dict[str, Any]) -> None:
        LOCAL_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        LOCAL_STATE_PATH.write_text(json.dumps(state, default=str), encoding="utf-8")
        db = self._get_db()
        if db is not None:
            try:
                db.live_state.update_one({"_id": "current"}, {"$set": {**state, "updated_at": datetime.utcnow()}}, upsert=True)
            except Exception:
                pass

    def load_live_state(self) -> dict[str, Any]:
        if LOCAL_STATE_PATH.exists():
            try:
                return json.loads(LOCAL_STATE_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        db = self._get_db()
        if db is not None:
            try:
                doc = db.live_state.find_one({"_id": "current"})
                if doc:
                    doc.pop("_id", None)
                    return doc
            except Exception:
                pass
        return {"positions": [], "orders": [], "closed_trades": [], "ltp_map": {}}

    def log_audit(self, event_type: str, payload: dict[str, Any]) -> None:
        AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": datetime.now().isoformat(), "event": event_type, **payload}
        with AUDIT_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
        db = self._get_db()
        if db is not None:
            try:
                db.audit_logs.insert_one(rec)
            except Exception:
                pass


STORE = PersistenceStore()
