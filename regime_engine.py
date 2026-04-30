# ============================================================
# BotX12.1 Pro — regime_engine.py
# Score-based regime: tidak strict ema7>ema25>ema99
# Cocok untuk testnet & live dengan data terbatas
# ============================================================

from dataclasses import dataclass
from enum import Enum
import pandas as pd

class Regime(Enum):
    BULLISH = "BULLISH"
    NEUTRAL = "NEUTRAL"
    BEARISH = "BEARISH"

@dataclass
class RegimeResult:
    regime: Regime
    score: float        # 0.0 – 4.0
    reasons: list

def classify_regime(df: pd.DataFrame, cfg) -> RegimeResult:
    """
    Score-based regime classification.
    Tidak bergantung pada strict ema7>ema25>ema99.
    Cocok untuk data testnet yang terbatas.
    """
    if df is None or len(df) < 20:
        return RegimeResult(Regime.NEUTRAL, 2.0, ["insufficient_data"])

    close  = df["close"].iloc[-1]
    ema7   = df["close"].ewm(span=7,  adjust=False).mean().iloc[-1]
    ema25  = df["close"].ewm(span=25, adjust=False).mean().iloc[-1]
    ema99  = df["close"].ewm(span=99, adjust=False).mean().iloc[-1]

    bull_score = 0.0
    reasons    = []

    # Komponen 1: EMA7 vs EMA25 (bobot 2)
    if ema7 > ema25:
        bull_score += 2.0
        reasons.append("ema7>ema25")
    else:
        reasons.append("ema7<ema25")

    # Komponen 2: EMA25 vs EMA99 (bobot 1)
    if ema25 > ema99:
        bull_score += 1.0
        reasons.append("ema25>ema99")
    else:
        reasons.append("ema25<ema99")

    # Komponen 3: Close vs EMA25 (bobot 1)
    if close > ema25:
        bull_score += 1.0
        reasons.append("close>ema25")
    else:
        reasons.append("close<ema25")

    # Klasifikasi
    bull_min = getattr(cfg, "REGIME_BULL_MIN", 3)
    neut_min = getattr(cfg, "REGIME_NEUT_MIN", 2)

    if bull_score >= bull_min:
        regime = Regime.BULLISH
    elif bull_score >= neut_min:
        regime = Regime.NEUTRAL
    else:
        regime = Regime.BEARISH

    return RegimeResult(regime=regime, score=bull_score, reasons=reasons)


def get_coin_regime(symbol: str, df_1h: pd.DataFrame, cfg) -> RegimeResult:
    """Wrapper per coin — gunakan timeframe 1H untuk regime."""
    return classify_regime(df_1h, cfg)
