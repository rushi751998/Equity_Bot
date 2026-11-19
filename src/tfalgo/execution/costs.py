"""Transaction cost models (Zerodha delivery/intraday and flat percentage)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Literal

import yaml

from tfalgo.registry import Registry


class CostModel(ABC):
    name: str = ""

    @abstractmethod
    def compute(
        self,
        side: Literal["BUY", "SELL"],
        product: Literal["MIS", "CNC"],
        notional: float,
        charge_dp: bool = False,
    ) -> float:
        """Return total transaction fees in INR for one fill."""


COSTS: Registry[CostModel] = Registry("cost model")


@COSTS.register("zerodha_costs")
class ZerodhaCostModel(CostModel):
    name = "zerodha_costs"

    def __init__(self, profile: dict[str, Any] | Path | str = Path("config/brokers/zerodha.yaml")) -> None:
        if isinstance(profile, (str, Path)):
            with open(profile, encoding="utf-8") as f:
                self.profile = yaml.safe_load(f)
        else:
            self.profile = profile

    def compute(
        self,
        side: Literal["BUY", "SELL"],
        product: Literal["MIS", "CNC"],
        notional: float,
        charge_dp: bool = False,
    ) -> float:
        if notional <= 0:
            return 0.0
        sec = self.profile["delivery" if product == "CNC" else "intraday"]
        brok_cfg = sec["brokerage"]
        if brok_cfg["type"] == "flat":
            brokerage = float(brok_cfg["value"])
        else:
            brokerage = min(float(brok_cfg["flat"]), notional * float(brok_cfg["pct"]) / 100.0)

        if product == "CNC":
            stt_pct = float(sec["stt_buy_pct"] if side == "BUY" else sec["stt_sell_pct"])
        else:
            stt_pct = float(sec["stt_sell_pct"]) if side == "SELL" else 0.0
        stt = notional * stt_pct / 100.0

        exch = notional * float(sec["exch_txn_pct"]) / 100.0
        sebi = notional * float(sec["sebi_per_crore"]) / 1e7
        stamp = notional * float(sec["stamp_buy_pct"]) / 100.0 if side == "BUY" else 0.0
        gst = (brokerage + exch + sebi) * float(sec["gst_pct"]) / 100.0
        dp = float(sec.get("dp_per_scrip_sell_incl_gst", 0.0)) if (product == "CNC" and side == "SELL" and charge_dp) else 0.0
        return brokerage + stt + exch + sebi + stamp + gst + dp


@COSTS.register("flat_pct")
class FlatPctCostModel(CostModel):
    name = "flat_pct"

    def __init__(self, flat_cost_pct: float = 0.30) -> None:
        self.flat_cost_pct = flat_cost_pct

    def compute(
        self,
        side: Literal["BUY", "SELL"],
        product: Literal["MIS", "CNC"],
        notional: float,
        charge_dp: bool = False,
    ) -> float:
        return notional * (self.flat_cost_pct / 100.0)