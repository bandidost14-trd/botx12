# ============================================================
# BotX12.1 Pro — trade_plan_x12.py
# SL/TP berbasis ATR, trailing stop, position sizing
# ============================================================

import pandas as pd
from dataclasses import dataclass
from scoring_engine import ScoreResult

@dataclass
class TradePlan:
    symbol: str
    direction: str      # LONG / SHORT
    tier: str
    entry: float
    sl: float
    tp1: float
    tp2: float
    qty: float
    modal: float
    leverage: int
    risk_multiplier: float
    sl_pct: float
    tp1_pct: float
    tp2_pct: float
    atr: float

def _atr(df, period=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean().iloc[-1]

def build_trade_plan(symbol: str, score: ScoreResult, df15: pd.DataFrame, cfg) -> TradePlan:
    close = df15["close"].iloc[-1]
    atr   = _atr(df15)

    tier = score.tier
    sl_mult  = getattr(cfg, "SL_ATR_MULT_T1",  1.5) if tier == "T1" else getattr(cfg, "SL_ATR_MULT_T2", 2.0)
    tp1_rr   = getattr(cfg, "TP1_RR", 1.5)
    tp2_rr   = getattr(cfg, "TP2_RR", 2.5)
    modal    = getattr(cfg, "MODAL_USDT", 15.0)
    leverage = getattr(cfg, "LEVERAGE", 2)
    regime = str(score.components.get("adaptive_regime", "") or "").upper()
    if regime == "TREND":
        risk_multiplier = getattr(cfg, "RISK_MULTIPLIER_TREND", 1.2)
    elif regime == "BREAKOUT":
        risk_multiplier = getattr(cfg, "RISK_MULTIPLIER_BREAKOUT", 1.0)
    elif regime == "MEAN_REVERT":
        risk_multiplier = getattr(cfg, "RISK_MULTIPLIER_MEAN_REVERT", 0.8)
    else:
        risk_multiplier = getattr(cfg, "RISK_MULTIPLIER_SIDEWAYS", 0.0)

    sl_dist  = atr * sl_mult
    tp1_dist = sl_dist * tp1_rr
    tp2_dist = sl_dist * tp2_rr

    if score.direction == "LONG":
        sl  = round(close - sl_dist,  6)
        tp1 = round(close + tp1_dist, 6)
        tp2 = round(close + tp2_dist, 6)
    else:
        sl  = round(close + sl_dist,  6)
        tp1 = round(close - tp1_dist, 6)
        tp2 = round(close - tp2_dist, 6)

    notional = modal * leverage * risk_multiplier
    qty      = round(notional / close, 4)

    sl_pct   = round(sl_dist / close * 100, 2)
    tp1_pct  = round(tp1_dist / close * 100, 2)
    tp2_pct  = round(tp2_dist / close * 100, 2)

    return TradePlan(
        symbol=symbol, direction=score.direction, tier=tier,
        entry=close, sl=sl, tp1=tp1, tp2=tp2,
        qty=qty, modal=modal, leverage=leverage, risk_multiplier=risk_multiplier,
        sl_pct=sl_pct, tp1_pct=tp1_pct, tp2_pct=tp2_pct,
        atr=round(atr, 6)
    )
