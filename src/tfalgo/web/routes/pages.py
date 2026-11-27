"""HTML page routes extending base.html."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()


def _tpl(request: Request) -> Jinja2Templates:
    return request.app.state.templates


@router.get("/", response_class=HTMLResponse)
def root():
    return RedirectResponse(url="/portfolio")

@router.get("/portfolio", response_class=HTMLResponse)
def page_portfolio(request: Request):
    return _tpl(request).TemplateResponse(request, "portfolio.html", {"active_nav": "portfolio"})


@router.get("/scanners", response_class=HTMLResponse)
def page_scanners(request: Request):
    return _tpl(request).TemplateResponse(request, "scanners.html", {"active_nav": "scanners"})


@router.get("/backtest/simulator", response_class=HTMLResponse)
def page_backtest_sim(request: Request):
    return _tpl(request).TemplateResponse(request, "backtest_simulator.html", {"active_nav": "backtest_sim"})


@router.get("/backtest/runner", response_class=HTMLResponse)
def page_backtest_runner(request: Request):
    return _tpl(request).TemplateResponse(request, "backtest_runner.html", {"active_nav": "backtest_runner"})


@router.get("/backtest/data", response_class=HTMLResponse)
def page_backtest_data(request: Request):
    return _tpl(request).TemplateResponse(request, "backtest_data.html", {"active_nav": "backtest_data"})


@router.get("/settings", response_class=HTMLResponse)
def page_settings(request: Request):
    return _tpl(request).TemplateResponse(request, "settings.html", {"active_nav": "settings"})