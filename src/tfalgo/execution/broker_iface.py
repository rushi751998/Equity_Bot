"""Abstract broker interface (SimBroker in v1; live adapters later)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass(frozen=True)
class ExecutedFill:
    symbol: str
    side: Literal["BUY", "SELL"]
    qty: int
    price: float
    product: Literal["MIS", "CNC"]
    ts: datetime
    fees: float
    slippage_cost: float
    reason: str = ""


class BrokerAdapter(ABC):
    @abstractmethod
    def execute_bar_fill(
        self,
        symbol: str,
        side: Literal["BUY", "SELL"],
        qty: int,
        product: Literal["MIS", "CNC"],
        ts: datetime,
        bar_open: float,
        bar_high: float,
        bar_low: float,
        bar_volume: float,
        is_stop: bool = False,
        stop_price: float | None = None,
        reason: str = "",
    ) -> tuple[ExecutedFill | None, int]:
        """Execute up to `qty` on the current bar; return (ExecutedFill | None, remaining_qty)."""