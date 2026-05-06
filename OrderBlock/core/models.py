from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass(slots=True)
class Trade:
    side: str
    entry_time: datetime
    entry_index: int
    entry_price: float
    stop_loss: float
    take_profit: float
    lot_size: float
    rr_target: float
    reason: str
    exit_time: Optional[datetime] = None
    exit_index: Optional[int] = None
    exit_price: Optional[float] = None
    result: Optional[str] = None
    pnl_usd: float = 0.0
    pnl_pct: float = 0.0
    rr_realized: float = 0.0
    session: str = "unknown"


@dataclass(slots=True)
class BacktestMetrics:
    timeframe: str
    initial_balance: float
    final_balance: float
    total_pnl_usd: float
    total_return_pct: float
    win_rate: float
    profit_factor: float
    max_drawdown_pct: float
    sharpe_ratio: float
    total_trades: int
    wins: int
    losses: int
    avg_rr: float
    consecutive_wins_max: int
    consecutive_losses_max: int
    buy_trades: int
    sell_trades: int
    monthly_stats: dict[str, dict[str, float]] = field(default_factory=dict)
    session_stats: dict[str, dict[str, float]] = field(default_factory=dict)
