from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import config_x12 as cfg


@dataclass
class ScoreResult:
    total: float
    direction: str
    reason: str = "VALID"
    entry_ok: bool = True
    tier: str = "T1"
    components: dict = field(default_factory=dict)
    raw_metrics: dict = field(default_factory=dict)

    def __getitem__(self, key):
        if key == "score":
            return self.total
        return getattr(self, key)


class ScoringEngine:
    def compute_rsi(self, series, period=14):
        delta = series.diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / loss.replace(0, np.nan)
        return (100 - (100 / (1 + rs))).fillna(50)

    def compute_atr(self, df, period=14):
        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift()).abs()
        low_close = (df["low"] - df["close"].shift()).abs()
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return true_range.rolling(period).mean()

    def compute_adx(self, df, period=14):
        high = df["high"]
        low = df["low"]
        close = df["close"]
        plus_dm = (high.diff()).where((high.diff() > -low.diff()) & (high.diff() > 0), 0.0)
        minus_dm = (-low.diff()).where((-low.diff() > high.diff()) & (-low.diff() > 0), 0.0)
        atr = self.compute_atr(df, period).replace(0, np.nan)
        plus_di = 100 * plus_dm.rolling(period).mean() / atr
        minus_di = 100 * minus_dm.rolling(period).mean() / atr
        dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)) * 100
        return dx.rolling(period).mean().fillna(0)

    def _blocked(self, reason: str, components: dict, raw: dict) -> ScoreResult:
        return ScoreResult(0.0, "NONE", reason, False, "NA", components, raw)

    def _alternating_chop(self, df, candles=10) -> bool:
        if len(df) < candles + 1:
            return False
        signs = np.sign(df["close"].diff().tail(candles).to_numpy())
        signs = signs[signs != 0]
        if len(signs) < candles - 2:
            return False
        return all(signs[i] != signs[i - 1] for i in range(1, len(signs)))

    def calculate(self, df):
        if df is None or len(df) < 120:
            return ScoreResult(0.0, "NONE", "INSUFFICIENT_DATA", False)

        df = df.copy()
        ema_fast_len = getattr(cfg, "EMA_FAST", 9)
        ema_slow_len = getattr(cfg, "EMA_SLOW", 21)
        df["rsi"] = self.compute_rsi(df["close"])
        df["ema_fast"] = df["close"].ewm(span=ema_fast_len, adjust=False).mean()
        df["ema_slow"] = df["close"].ewm(span=ema_slow_len, adjust=False).mean()
        df["atr_short"] = self.compute_atr(df, 14)
        df["atr_long"] = self.compute_atr(df, 100)
        df["adx"] = self.compute_adx(df, 14)
        df["bb_mid"] = df["close"].rolling(20).mean()
        df["bb_std"] = df["close"].rolling(20).std()
        df["vol_ma"] = df["volume"].rolling(20).mean()

        last = df.iloc[-1]
        if pd.isna(last[["ema_fast", "ema_slow", "atr_short", "atr_long", "adx", "bb_mid", "bb_std"]]).any():
            return ScoreResult(0.0, "NONE", "INDICATORS_NOT_READY", False)

        direction = "LONG" if last["ema_fast"] > last["ema_slow"] else "SHORT"
        trend_raw = abs(last["ema_fast"] - last["ema_slow"]) / max(last["ema_slow"], 1e-12)
        trend_component = min(1.0, (trend_raw / 0.015) * 0.55 + min(last["adx"] / 40, 1.0) * 0.45)

        change_5 = (last["close"] - df["close"].iloc[-6]) / max(df["close"].iloc[-6], 1e-12)
        if direction == "LONG":
            rsi_component = max(0.0, min(1.0, (last["rsi"] - 50) / 20))
            price_momentum = max(0.0, min(1.0, change_5 / 0.015))
        else:
            rsi_component = max(0.0, min(1.0, (50 - last["rsi"]) / 20))
            price_momentum = max(0.0, min(1.0, -change_5 / 0.015))
        momentum_component = rsi_component * 0.55 + price_momentum * 0.45
        prev_change_5 = (df["close"].iloc[-2] - df["close"].iloc[-7]) / max(df["close"].iloc[-7], 1e-12)
        prev_rsi = float(df["rsi"].iloc[-2])
        if direction == "LONG":
            prev_rsi_component = max(0.0, min(1.0, (prev_rsi - 50) / 20))
            prev_price_momentum = max(0.0, min(1.0, prev_change_5 / 0.015))
            confirmation_candle = bool(last["close"] > last["open"] and last["close"] > df["close"].iloc[-2])
        else:
            prev_rsi_component = max(0.0, min(1.0, (50 - prev_rsi) / 20))
            prev_price_momentum = max(0.0, min(1.0, -prev_change_5 / 0.015))
            confirmation_candle = bool(last["close"] < last["open"] and last["close"] < df["close"].iloc[-2])
        prev_momentum_component = prev_rsi_component * 0.55 + prev_price_momentum * 0.45
        momentum_drops = bool(momentum_component < prev_momentum_component)

        vol_ratio = float(last["atr_short"] / max(last["atr_long"], 1e-12))
        if vol_ratio > getattr(cfg, "VOL_EXPANSION_RATIO", 1.2):
            volatility_regime = "EXPANSION"
        elif vol_ratio < getattr(cfg, "VOL_COMPRESSION_RATIO", 0.8):
            volatility_regime = "COMPRESSION"
        else:
            volatility_regime = "NORMAL"
        volatility_component = max(0.0, min(1.0, (vol_ratio - 0.8) / 0.7))

        compressed = (df["atr_short"] / df["atr_long"].replace(0, np.nan)) < getattr(cfg, "VOL_COMPRESSION_RATIO", 0.8)
        compression_count = 0
        for value in reversed(compressed.fillna(False).tolist()):
            if not value:
                break
            compression_count += 1
        squeeze_breakout = compression_count > getattr(cfg, "SQUEEZE_CANDLES", 10)
        volatility_rising = bool(last["atr_short"] > df["atr_short"].iloc[-2])

        volume_ratio = float(last["volume"] / max(last["vol_ma"], 1e-12))
        volume_component = max(0.0, min(1.0, volume_ratio / 1.5))
        volume_spike = volume_ratio > 1.0
        volume_above_average = volume_ratio > 1.0
        breakout_volume_valid = volume_ratio > getattr(cfg, "BREAKOUT_VOLUME_MULT", 1.2)

        prev = df.iloc[-2]
        candle_body = abs(last["close"] - last["open"])
        upper_wick = max(0.0, last["high"] - max(last["open"], last["close"]))
        lower_wick = max(0.0, min(last["open"], last["close"]) - last["low"])
        largest_wick = max(upper_wick, lower_wick)
        body_gt_wick = candle_body > largest_wick
        if direction == "LONG":
            close_breaks_prev = last["close"] > prev["high"]
        else:
            close_breaks_prev = last["close"] < prev["low"]

        bb_low_mid = last["bb_mid"] - (last["bb_std"] * 0.5)
        bb_high_mid = last["bb_mid"] + (last["bb_std"] * 0.5)
        inside_bollinger_mid = bb_low_mid <= last["close"] <= bb_high_mid
        sideways = (
            last["adx"] < getattr(cfg, "ADX_CHOP_MAX", 25)
            and getattr(cfg, "RSI_CHOP_LOW", 40) <= last["rsi"] <= getattr(cfg, "RSI_CHOP_HIGH", 60)
            and inside_bollinger_mid
        )
        alternating_chop = self._alternating_chop(df, 10)
        breakout_signal = bool(
            squeeze_breakout
            or (
                volatility_regime == "EXPANSION"
                and breakout_volume_valid
                and close_breaks_prev
                and body_gt_wick
                and momentum_component > getattr(cfg, "BREAKOUT_MOMENTUM_MIN", 0.5)
                and abs(change_5) >= 0.006
            )
        )
        sideways_breakout_allowed = bool(sideways and breakout_signal and volatility_rising)

        weighted_score = (
            trend_component * getattr(cfg, "WEIGHT_TREND", 0.40)
            + momentum_component * getattr(cfg, "WEIGHT_MOMENTUM", 0.25)
            + volatility_component * getattr(cfg, "WEIGHT_VOLATILITY", 0.20)
            + volume_component * getattr(cfg, "WEIGHT_VOLUME", 0.15)
        )

        if sideways_breakout_allowed:
            adaptive_regime = "BREAKOUT"
        elif sideways:
            adaptive_regime = "SIDEWAYS"
        elif breakout_signal:
            adaptive_regime = "BREAKOUT"
        elif trend_component >= 0.65 and last["adx"] >= getattr(cfg, "ADX_CHOP_MAX", 25):
            adaptive_regime = "TREND"
        else:
            adaptive_regime = "MEAN_REVERT"

        score_boost = 0.0
        boost_reasons = []
        if adaptive_regime == "TREND" and momentum_component > 0.65:
            score_boost += getattr(cfg, "TREND_MOMENTUM_BOOST", 0.06)
            boost_reasons.append("trend_momentum")
        if adaptive_regime == "BREAKOUT" and volume_spike:
            score_boost += getattr(cfg, "BREAKOUT_VOLUME_BOOST", 0.05)
            boost_reasons.append("breakout_volume")
        if trend_component > 0.7:
            score_boost += getattr(cfg, "STRONG_TREND_BOOST", 0.04)
            boost_reasons.append("strong_trend")
        score_decay = 0.0
        decay_reasons = []
        if not confirmation_candle:
            score_decay += getattr(cfg, "NO_CONFIRMATION_DECAY", 0.03)
            decay_reasons.append("no_confirmation_candle")
        if momentum_drops:
            score_decay += getattr(cfg, "MOMENTUM_DROP_DECAY", 0.05)
            decay_reasons.append("momentum_drop")
        boosted_score = min(1.0, max(0.0, weighted_score + score_boost - score_decay))

        components = {
            "trend": float(trend_component),
            "momentum": float(momentum_component),
            "volatility": float(volatility_component),
            "volume": float(volume_component),
            "volume_ratio": float(volume_ratio),
            "volume_spike": bool(volume_spike),
            "volume_above_average": bool(volume_above_average),
            "breakout_volume_valid": bool(breakout_volume_valid),
            "breakout_momentum_valid": bool(momentum_component > getattr(cfg, "BREAKOUT_MOMENTUM_MIN", 0.5)),
            "close_breaks_prev": bool(close_breaks_prev),
            "body_gt_wick": bool(body_gt_wick),
            "candle_body": float(candle_body),
            "largest_wick": float(largest_wick),
            "adx": float(last["adx"]),
            "rsi": float(last["rsi"]),
            "volatility_ratio": float(vol_ratio),
            "volatility_regime": volatility_regime,
            "volatility_rising": bool(volatility_rising),
            "compression_count": int(compression_count),
            "squeeze_breakout": bool(squeeze_breakout),
            "breakout_signal": bool(breakout_signal),
            "sideways_breakout_allowed": bool(sideways_breakout_allowed),
            "sideways": bool(sideways),
            "alternating_chop": bool(alternating_chop),
            "strong_trend": bool(trend_component >= 0.75 and last["adx"] >= 30),
            "adaptive_regime": adaptive_regime,
            "base_score": float(weighted_score),
            "score_boost": float(score_boost),
            "boost_reasons": boost_reasons,
            "score_decay": float(score_decay),
            "decay_reasons": decay_reasons,
            "confirmation_candle": bool(confirmation_candle),
            "momentum_drops": bool(momentum_drops),
        }
        raw = {
            "adx_raw": float(last["adx"]),
            "rsi_raw": float(last["rsi"]),
            "rsi_slope": float(df["rsi"].diff().iloc[-1]),
            "atr_short": float(last["atr_short"]),
            "atr_long": float(last["atr_long"]),
            "ema_fast": float(last["ema_fast"]),
            "ema_slow": float(last["ema_slow"]),
            "change_5": float(change_5),
            **components,
        }

        if getattr(cfg, "ANTI_CHOP_ENABLED", True) and sideways and not sideways_breakout_allowed:
            return self._blocked("SIDEWAYS_MARKET", components, raw)
        if getattr(cfg, "ANTI_CHOP_ENABLED", True) and alternating_chop:
            return self._blocked("ALTERNATING_CHOP", components, raw)
        if getattr(cfg, "VOLATILITY_FILTER_ENABLED", True) and volatility_regime == "COMPRESSION":
            return self._blocked("VOLATILITY_COMPRESSION", components, raw)
        if last["adx"] < getattr(cfg, "ANTI_CHOP_ADX_HARD_MAX", 18) and volatility_regime != "EXPANSION":
            return self._blocked("HARD_CHOP_ADX_LOW", components, raw)
        if last["adx"] <= getattr(cfg, "ENTRY_ADX_MIN", 20):
            return self._blocked("ADX_TOO_LOW", components, raw)
        if getattr(cfg, "ENTRY_RSI_NEUTRAL_LOW", 45) <= last["rsi"] <= getattr(cfg, "ENTRY_RSI_NEUTRAL_HIGH", 55):
            return self._blocked("RSI_NEUTRAL_ZONE", components, raw)
        if not volume_above_average:
            return self._blocked("VOLUME_BELOW_AVERAGE", components, raw)
        if momentum_component < getattr(cfg, "MOMENTUM_MIN", 0.45):
            return self._blocked("MOMENTUM_TOO_WEAK", components, raw)
        if volatility_component < getattr(cfg, "VOLATILITY_COMPONENT_MIN", 0.3):
            return self._blocked("VOLATILITY_TOO_WEAK", components, raw)

        tier = "T1" if components["strong_trend"] else "T2"
        return ScoreResult(round(float(boosted_score), 4), direction, "VALID", True, tier, components, raw)
