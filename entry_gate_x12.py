# ============================================================
# BotX12 Adaptive Whitelist Engine — entry_gate_x12.py
# Stage 1 patch: adaptive allow/block by symbol, direction, btc_mode
# ============================================================

from __future__ import annotations

from dataclasses import dataclass
from scoring_engine import ScoreResult
from btc_gate_x12 import BTCGateResult


@dataclass
class GateResult:
    passed: bool
    gate_name: str
    reason: str
    min_score_required: float = 0.0
    final_score: float = 0.0


def get_min_score(symbol: str, direction: str, btc_mode: str, cfg) -> float:
    base = getattr(cfg, "MIN_SCORE_LONG_BASE", 85) if direction == "LONG" else getattr(cfg, "MIN_SCORE_SHORT_BASE", 95)
    symbol_adj = getattr(cfg, "SYMBOL_SCORE_ADJUST", {}).get(symbol, {}).get(direction, 0)
    mode_adj = getattr(cfg, "BTC_MODE_SCORE_ADJUST", {}).get(btc_mode, {}).get(direction, 0)
    return float(base + symbol_adj + mode_adj)


def _symbol_set_for_mode(btc_mode: str, direction: str, cfg):
    mode_cfg = getattr(cfg, "BTC_MODE_ACTIVE", {}).get(btc_mode, {})
    return set(mode_cfg.get(direction, [])), set(mode_cfg.get("SELECTIVE", [])), set(mode_cfg.get("PAUSE", []))


def is_symbol_active_for_mode(symbol: str, direction: str, btc_mode: str, cfg) -> bool:
    active_set, selective_set, pause_set = _symbol_set_for_mode(btc_mode, direction, cfg)
    if symbol in pause_set:
        return False
    return symbol in active_set or symbol in selective_set


def _priority_penalty(symbol: str, direction: str, cfg) -> float:
    priority = getattr(cfg, "SYMBOL_DIRECTION_PRIORITY", {}).get(symbol, "DUAL")
    if priority == "LONG_FIRST" and direction == "SHORT":
        return 8.0
    if priority == "SHORT_FIRST" and direction == "LONG":
        return 8.0
    if priority == "LONG_SELECTIVE" and direction == "SHORT":
        return 10.0
    if priority == "SHORT_LEAN" and direction == "LONG":
        return 4.0
    if priority == "LOW_PRIORITY":
        return 10.0
    return 0.0


def check_all_gates(symbol: str, score: ScoreResult, btc: BTCGateResult, daily_count: int, active_count: int, hour_utc: int, cfg, rsi_val: float = 50.0, rsi_slope: float = 0.0, adx_val: float = 0.0) -> GateResult:
    if symbol not in getattr(cfg, "ACTIVE_WHITELIST", []):
        return GateResult(False, "blocked_symbol_not_whitelisted", f"{symbol} not in active whitelist", 0.0, score.total)

    if hour_utc in getattr(cfg, "DEAD_HOURS_UTC", [22, 23, 0]):
        return GateResult(False, "blocked_dead_hour", f"dead hour UTC {hour_utc}", 0.0, score.total)

    if active_count >= getattr(cfg, "MAX_OPEN_POSITIONS", getattr(cfg, "MAX_POSITION", 3)):
        return GateResult(False, "blocked_max_positions", f"positions penuh {active_count}", 0.0, score.total)

    if daily_count >= getattr(cfg, "MAX_ENTRY_PER_DAY", 5):
        return GateResult(False, "blocked_daily_limit", f"max entry/day {daily_count}", 0.0, score.total)

    if not score.entry_ok:
        return GateResult(False, "blocked_invalid_score_state", score.reason, 0.0, score.total)

    if btc.wave_b_block and score.direction == "SHORT":
        return GateResult(False, "blocked_wave_b", "BTC wave-B guard aktif", 0.0, score.total)

    if not is_symbol_active_for_mode(symbol, score.direction, btc.mode, cfg):
        return GateResult(False, "blocked_symbol_paused_by_btc_mode", f"{symbol}/{score.direction} paused in {btc.mode}", 0.0, score.total)

    min_score = get_min_score(symbol, score.direction, btc.mode, cfg) + _priority_penalty(symbol, score.direction, cfg)
    if score.total < min_score:
        return GateResult(False, "blocked_low_score", f"score={score.total:.1f}<{min_score:.1f}", min_score, score.total)

    raw_adx = adx_val if adx_val > 0 else score.raw_metrics.get("adx_raw", score.components.get("adx_raw", 0))
    raw_rsi = rsi_val if rsi_val > 0 else score.raw_metrics.get("rsi_raw", score.components.get("rsi_raw", 50))
    raw_rsi_slope = rsi_slope if abs(rsi_slope) > 0 else score.raw_metrics.get("rsi_slope", 0)

    if score.direction == "LONG":
        if raw_adx < getattr(cfg, "ADX_MIN_TIER1", 15):
            return GateResult(False, "blocked_invalid_raw_metrics", f"ADX={raw_adx:.1f}<{getattr(cfg, 'ADX_MIN_TIER1', 15)}", min_score, score.total)
    else:
        if raw_adx < getattr(cfg, "ADX_MIN_SHORT", 18):
            return GateResult(False, "blocked_invalid_raw_metrics", f"ADX={raw_adx:.1f}<{getattr(cfg, 'ADX_MIN_SHORT', 18)}", min_score, score.total)
        if raw_rsi >= getattr(cfg, "RSI_SHORT_MIN_MAX", 55.0):
            return GateResult(False, "blocked_invalid_raw_metrics", f"RSI={raw_rsi:.1f}>=55", min_score, score.total)
        if btc.mode in {"strong_bull", "bull_weak"}:
            return GateResult(False, "blocked_btc_mode_conflict", f"short blocked in {btc.mode}", min_score, score.total)
        if raw_rsi_slope > 2.0:
            return GateResult(False, "blocked_invalid_raw_metrics", f"RSI slope too positive={raw_rsi_slope:.2f}", min_score, score.total)

    return GateResult(True, "ALL_PASS", f"OK mode={btc.mode}", min_score, score.total)
