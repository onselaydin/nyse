from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

Timeframe = Literal["M15", "H1", "H4"]


@dataclass(slots=True)
class AccountConfig:
    initial_balance: float = 10000.0
    fixed_lot: float = 0.05
    leverage: int = 100


@dataclass(slots=True)
class SessionWindow:
    start_hour_utc: int
    end_hour_utc: int


@dataclass(slots=True)
class SessionConfig:
    enabled: bool = True
    utc_offset_hours: int = 0
    london: SessionWindow = field(default_factory=lambda: SessionWindow(7, 11))
    new_york: SessionWindow = field(default_factory=lambda: SessionWindow(12, 16))


@dataclass(slots=True)
class RiskConfig:
    rr_targets: tuple[float, ...] = (2.0, 3.0)
    sl_buffer_points: float = 20.0
    max_open_positions: int = 1


@dataclass(slots=True)
class StrategyConfig:
    symbol: str = "EURUSD"
    timeframes: tuple[Timeframe, ...] = ("M15", "H1", "H4")
    history_months: int = 6
    pivot_sensitivity: int = 2
    ob_impulse_multiplier: float = 1.5
    wick_to_body_ratio_min: float = 1.5
    momentum_body_to_range_min: float = 0.65
    min_displacement_points: float = 80.0
    require_bos_or_choch: bool = True
    allow_wick_confirmation: bool = True
    allow_momentum_confirmation: bool = True


@dataclass(slots=True)
class MT5Config:
    login_env: str = "MT5_LOGIN"
    password_env: str = "MT5_PASSWORD"
    server_env: str = "MT5_SERVER"
    path_env: str = "MT5_PATH"
    reconnect_attempts: int = 3
    reconnect_wait_seconds: int = 3
    max_missing_candle_ratio: float = 0.02


@dataclass(slots=True)
class AIConfig:
    enabled: bool = True
    image_size: int = 96
    batch_size: int = 64
    epochs: int = 12
    learning_rate: float = 1e-3
    confidence_threshold: float = 0.60
    use_cuda_if_available: bool = True
    labels: tuple[str, ...] = (
        "strong_bullish_candle",
        "strong_bearish_candle",
        "fake_breakout",
        "liquidity_sweep",
        "rejection_candle",
        "momentum_candle",
        "bad_setup",
        "high_probability_setup",
    )


@dataclass(slots=True)
class OptimizationConfig:
    enabled: bool = True
    optuna_trials: int = 30
    grid_rr_targets: tuple[float, ...] = (2.0, 3.0)
    grid_wick_ratios: tuple[float, ...] = (1.2, 1.5, 1.8)
    grid_momentum_thresholds: tuple[float, ...] = (0.55, 0.65, 0.75)
    grid_ob_impulse_multipliers: tuple[float, ...] = (1.2, 1.5, 1.8)


@dataclass(slots=True)
class PathConfig:
    project_root: Path = Path(__file__).resolve().parent
    data_dir: Path = field(init=False)
    dataset_dir: Path = field(init=False)
    ai_models_dir: Path = field(init=False)
    charts_dir: Path = field(init=False)
    logs_dir: Path = field(init=False)
    backtests_dir: Path = field(init=False)
    optimization_dir: Path = field(init=False)
    strategy_dir: Path = field(init=False)
    mt5_dir: Path = field(init=False)

    def __post_init__(self) -> None:
        self.data_dir = self.project_root / "data"
        self.dataset_dir = self.project_root / "dataset"
        self.ai_models_dir = self.project_root / "ai_models"
        self.charts_dir = self.project_root / "charts"
        self.logs_dir = self.project_root / "logs"
        self.backtests_dir = self.project_root / "backtests"
        self.optimization_dir = self.project_root / "optimization"
        self.strategy_dir = self.project_root / "strategy"
        self.mt5_dir = self.project_root / "mt5"


@dataclass(slots=True)
class AppConfig:
    account: AccountConfig = field(default_factory=AccountConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    mt5: MT5Config = field(default_factory=MT5Config)
    ai: AIConfig = field(default_factory=AIConfig)
    optimization: OptimizationConfig = field(default_factory=OptimizationConfig)
    paths: PathConfig = field(default_factory=PathConfig)


def get_config() -> AppConfig:
    return AppConfig()
