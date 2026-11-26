"""FastAPI application factory with lifespan 10s broker/SL watchdog & modular routers."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from tfalgo.web.core.execution import EXEC_MGR
from tfalgo.web.routes import backtest_api, pages, portfolio_api, scanners_api, settings_api

BASE_DIR = Path(__file__).resolve().parent


def create_app(default_config: Path | str = "config/default.yaml") -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        EXEC_MGR.start_watchdog()
        yield
        EXEC_MGR.stop_watchdog()

    app = FastAPI(title="tfalgo Quant Workstation", lifespan=lifespan)
    app.state.default_config = Path(default_config)
    app.state.templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    app.include_router(pages.router)
    app.include_router(portfolio_api.router)
    app.include_router(scanners_api.router)
    app.include_router(backtest_api.router)
    app.include_router(settings_api.router)

    @app.get("/api/health")
    def health():
        return {"ok": True, "last_sync_ts": EXEC_MGR.last_sync_ts, "watchdog_alive": True}

    return app
