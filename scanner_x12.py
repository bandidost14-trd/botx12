import config_x12 as cfg
from btc_gate_x12 import BTCGate, BTCGateResult, _cache
from data_loader_x12 import fetch_ohlcv
from trade_plan_x12 import build_trade_plan
from scoring_engine import ScoringEngine

class Scanner:

    def __init__(self, *args):
        self.learning = None
        if len(args) == 2:
            self.cfg = cfg
            self.scoring_engine = args[0]
            self.execution_engine = args[1]
            self.ks = None
            self.dm = None
            self.pm = None
            self.telegram = None
        else:
            self.cfg = args[0] if args else cfg
            self.ks = args[1] if len(args) > 1 else None
            self.dm = args[2] if len(args) > 2 else None
            self.pm = args[3] if len(args) > 3 else None
            self.telegram = args[4] if len(args) > 4 else None
            self.learning = args[5] if len(args) > 5 else None
            self.scoring_engine = ScoringEngine()
            self.execution_engine = None
        self.btc_gate = BTCGate(self.cfg)
        self._pending_entries = {}
        self._market_override = {
            "score_add": 0.0,
            "size_factor": 1.0,
            "risk_add": 0.0,
            "skip_delay": False,
            "block_all": False,
            "reason": "normal",
        }

    def _min_score_for_regime(self, regime: str) -> float:
        regime = (regime or "").upper()
        if regime == "TREND":
            base = getattr(self.cfg, "TREND_MIN_SCORE", 0.60)
            value = self.learning.effective_min_score(base) if self.learning else base
            return min(0.90, value + self._market_override.get("score_add", 0.0))
        if regime == "BREAKOUT":
            base = getattr(self.cfg, "BREAKOUT_MIN_SCORE", 0.55)
            value = self.learning.effective_min_score(base) if self.learning else base
            return min(0.90, value + self._market_override.get("score_add", 0.0))
        if regime == "MEAN_REVERT":
            base = getattr(self.cfg, "MEAN_REVERT_MIN_SCORE", 0.57)
            value = self.learning.effective_min_score(base) if self.learning else base
            return min(0.90, value + self._market_override.get("score_add", 0.0))
        base = getattr(self.cfg, "MIN_SCORE", 0.58)
        value = self.learning.effective_min_score(base) if self.learning else base
        return min(0.90, value + self._market_override.get("score_add", 0.0))

    def _atr(self, df, period=14):
        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift()).abs()
        low_close = (df["low"] - df["close"].shift()).abs()
        return high_low.to_frame("hl").join(high_close.rename("hc")).join(low_close.rename("lc")).max(axis=1).rolling(period).mean()

    def _adx(self, df, period=14):
        high = df["high"]
        low = df["low"]
        plus_dm = (high.diff()).where((high.diff() > -low.diff()) & (high.diff() > 0), 0.0)
        minus_dm = (-low.diff()).where((-low.diff() > high.diff()) & (-low.diff() > 0), 0.0)
        atr = self._atr(df, period).replace(0, float("nan"))
        plus_di = 100 * plus_dm.rolling(period).mean() / atr
        minus_di = 100 * minus_dm.rolling(period).mean() / atr
        dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, float("nan"))) * 100
        return dx.rolling(period).mean().fillna(0)

    def _update_market_override(self, btc_df):
        override = {
            "score_add": 0.0,
            "size_factor": 1.0,
            "risk_add": 0.0,
            "skip_delay": False,
            "block_all": False,
            "reason": "normal",
        }
        if btc_df is None or btc_df.empty or len(btc_df) < 100:
            self._market_override = override
            return

        atr = self._atr(btc_df, 14)
        avg_atr = atr.rolling(50).mean()
        adx = self._adx(btc_df, 14)
        last_atr = float(atr.iloc[-1])
        last_avg_atr = float(avg_atr.iloc[-1])
        last_adx = float(adx.iloc[-1])
        atr_long = self._atr(btc_df, 100)
        vol_ratio = last_atr / max(float(atr_long.iloc[-1]), 1e-12)
        volatility = "EXPANSION" if vol_ratio > getattr(self.cfg, "VOL_EXPANSION_RATIO", 1.2) else "NORMAL"

        if last_adx < getattr(self.cfg, "BTC_EXTREME_CHOP_ADX", 15):
            override["block_all"] = True
            override["reason"] = f"btc_extreme_chop_adx_{last_adx:.1f}"
        elif last_avg_atr > 0 and last_atr > getattr(self.cfg, "BTC_VOL_SPIKE_ATR_MULT", 1.5) * last_avg_atr:
            override["score_add"] = getattr(self.cfg, "BTC_VOL_SPIKE_SCORE_ADD", 0.03)
            override["size_factor"] = getattr(self.cfg, "BTC_VOL_SPIKE_SIZE_FACTOR", 0.8)
            override["reason"] = "btc_volatility_spike"

        if last_adx > getattr(self.cfg, "BTC_STRONG_TREND_ADX", 30) and volatility == "EXPANSION":
            override["risk_add"] = getattr(self.cfg, "BTC_STRONG_TREND_RISK_ADD", 0.15)
            override["skip_delay"] = True
            override["reason"] = "btc_strong_trend_expansion"

        self._market_override = override

    def _btc_allows(self, btc, score) -> tuple[bool, str]:
        if not getattr(self.cfg, "STRICT_BTC_FILTER", True) or not btc:
            return True, "ok"
        if btc.bias == "BULLISH" and score.direction == "SHORT":
            return False, "btc_bullish_blocks_short"
        if btc.bias == "BEARISH" and score.direction == "LONG":
            return False, "btc_bearish_blocks_long"
        if btc.bias == "NEUTRAL":
            min_neutral = getattr(self.cfg, "BTC_NEUTRAL_MIN_SCORE", 0.65)
            regime = score.components.get("adaptive_regime", "")
            if score.total < min_neutral and regime != "BREAKOUT":
                return False, f"btc_neutral_requires_score_{min_neutral:.2f}_or_breakout"
        return True, "ok"

    def _candle_key(self, df):
        try:
            return str(df.index[-1])
        except Exception:
            return str(len(df))

    def _direction_confirmed(self, df, direction: str) -> bool:
        last = df.iloc[-1]
        prev = df.iloc[-2]
        if direction == "LONG":
            return bool(last["close"] > last["open"] and last["close"] > prev["high"])
        return bool(last["close"] < last["open"] and last["close"] < prev["low"])

    def _breakout_valid(self, score) -> tuple[bool, str]:
        if score.components.get("adaptive_regime") != "BREAKOUT":
            return True, "ok"
        if not score.components.get("close_breaks_prev"):
            return False, "breakout_close_not_beyond_prev"
        if not score.components.get("breakout_volume_valid"):
            return False, "breakout_volume_lt_1_2x_avg"
        if not score.components.get("breakout_momentum_valid"):
            return False, "breakout_momentum_lte_0_5"
        if self.learning:
            min_momentum = self.learning.effective_breakout_momentum_min(
                getattr(self.cfg, "BREAKOUT_MOMENTUM_MIN", 0.5)
            )
            if score.components.get("momentum", 0) <= min_momentum:
                return False, f"breakout_momentum_lte_{min_momentum:.2f}"
        if not score.components.get("body_gt_wick"):
            return False, "breakout_body_not_gt_wick"
        if score.components.get("volatility_regime") != "EXPANSION":
            return False, "breakout_requires_expansion"
        return True, "ok"

    def _breakout_gate_ok(self, score) -> tuple[bool, str]:
        if score.components.get("adaptive_regime") != "BREAKOUT":
            return True, "ok"
        if not (
            score.components.get("breakout_volume_valid")
            and score.components.get("volatility_regime") == "EXPANSION"
            and score.components.get("breakout_momentum_valid")
            and score.components.get("close_breaks_prev")
            and score.components.get("body_gt_wick")
        ):
            return self._breakout_valid(score)
        if self.learning:
            min_momentum = self.learning.effective_breakout_momentum_min(
                getattr(self.cfg, "BREAKOUT_MOMENTUM_MIN", 0.5)
            )
            if score.components.get("momentum", 0) <= min_momentum:
                return False, f"breakout_momentum_lte_{min_momentum:.2f}"
        return True, "ok"

    def _regime_rank(self, regime: str) -> int:
        return {
            "BREAKOUT": 3,
            "TREND": 2,
            "MEAN_REVERT": 1,
        }.get((regime or "").upper(), 0)

    def _candidate_rank_key(self, item):
        _symbol, score, _plan, regime = item
        return (
            self._regime_rank(regime),
            float(score.total),
            float(score.components.get("momentum", 0.0)),
            float(score.components.get("volatility", 0.0)),
        )

    def _rank_and_weight_candidates(self, candidates, wasted):
        candidates.sort(key=self._candidate_rank_key, reverse=True)
        max_positions = int(getattr(self.cfg, "MAX_OPEN_POSITIONS", 2))
        active_count = len(getattr(self.pm, "positions", {}) or {}) if self.pm else 0
        free_slots = max(0, max_positions - active_count)
        limit = min(2, free_slots)
        selected = []
        for idx, item in enumerate(candidates):
            symbol, score, plan, regime = item
            if idx >= limit:
                wasted.append((symbol, score.total, "lower_ranked_or_max_positions_reached"))
                continue
            weight = 1.0 if idx == 0 else 0.5
            if weight != 1.0:
                original_qty = float(plan.qty)
                plan.qty = round(max(0.0, original_qty * weight), 8)
                print(f"[Ranking] {symbol} rank={idx + 1} capital_weight={weight}; qty {original_qty} -> {plan.qty}")
            plan.signal_rank = idx + 1
            plan.capital_weight = weight
            selected.append((symbol, score, plan, regime))
        return selected, wasted

    def _entry_timing_ok(self, df, direction: str) -> tuple[bool, str]:
        last = df.iloc[-1]
        candle_range = float(last["high"] - last["low"])
        if candle_range <= 0:
            return False, "entry_timing_zero_range"
        entry_price = float(last["close"])
        pct = float(getattr(self.cfg, "ENTRY_TIMING_RANGE_PCT", 0.30))
        if direction == "LONG":
            max_entry = float(last["high"]) - (pct * candle_range)
            if entry_price > max_entry:
                return False, "late_entry_near_high"
        else:
            min_entry = float(last["low"]) + (pct * candle_range)
            if entry_price < min_entry:
                return False, "late_entry_near_low"
        return True, "ok"

    def _candle_strength_ok(self, df) -> tuple[bool, str]:
        if df is None or df.empty or len(df) < 20:
            return False, "low_momentum_candle"
        ranges = df["high"] - df["low"]
        candle_range = float(ranges.iloc[-1])
        avg_range = float(ranges.rolling(20).mean().iloc[-1])
        if avg_range <= 0:
            return False, "low_momentum_candle"
        required = float(getattr(self.cfg, "CANDLE_STRENGTH_RANGE_MULT", 0.6)) * avg_range
        if candle_range <= required:
            return False, "low_momentum_candle"
        return True, "ok"

    def run(self, symbol, df):

        conf = cfg.WHITELIST.get(symbol, {})
        if not conf.get("enabled", False):
            return

        result = self.scoring_engine.calculate(df)

        direction = result.direction

        regime = result.components.get("adaptive_regime", "")
        if regime == "SIDEWAYS" and not (
            result.components.get("breakout_signal")
            and result.components.get("volatility_rising")
        ):
            return
        breakout_ok, _ = self._breakout_gate_ok(result)
        if not breakout_ok:
            return
        btc = _cache.get("result")
        btc_ok, _ = self._btc_allows(btc, result)
        if not btc_ok:
            return
        if not result.entry_ok or direction == "NONE" or result.total < self._min_score_for_regime(regime):
            return

        candle_ok, _ = self._candle_strength_ok(df)
        if not candle_ok:
            return

        timing_ok, _ = self._entry_timing_ok(df, direction)
        if not timing_ok:
            return

        # ===== PRIORITY FILTER =====
        if conf.get("priority") == "LONG" and direction != "LONG":
            return

        if conf.get("priority") == "SHORT" and direction != "SHORT":
            return

        price = df.iloc[-1]["close"]

        risk_multiplier = {
            "TREND": getattr(self.cfg, "RISK_MULTIPLIER_TREND", 1.2),
            "BREAKOUT": getattr(self.cfg, "RISK_MULTIPLIER_BREAKOUT", 1.0),
            "MEAN_REVERT": getattr(self.cfg, "RISK_MULTIPLIER_MEAN_REVERT", 0.8),
        }.get(regime, getattr(self.cfg, "RISK_MULTIPLIER_SIDEWAYS", 0.0))
        if risk_multiplier <= 0:
            return
        conf = dict(conf)
        conf["risk"] = risk_multiplier
        self.execution_engine.execute(symbol, direction, price, conf)

    def _refresh_btc_bias(self):
        try:
            df = fetch_ohlcv("BTCUSDT", "1h", 120, self.cfg)
            if df is None or df.empty or len(df) < 30:
                self._update_market_override(None)
                self.btc_gate.update()
                return _cache.get("result")
            self._update_market_override(df)

            close = df["close"]
            ema_fast = close.ewm(span=getattr(self.cfg, "EMA_FAST", 9), adjust=False).mean().iloc[-1]
            ema_slow = close.ewm(span=getattr(self.cfg, "EMA_SLOW", 21), adjust=False).mean().iloc[-1]
            trend = (ema_fast - ema_slow) / max(ema_slow, 1e-12)
            score = min(1.0, max(0.0, 0.5 + trend * 25))
            if ema_fast > ema_slow:
                mode = "BULL"
                bias = "BULLISH"
            elif ema_fast < ema_slow:
                mode = "BEAR"
                bias = "BEARISH"
            else:
                mode = "SIDEWAYS"
                bias = "NEUTRAL"
            _cache["result"] = BTCGateResult(
                mode=mode,
                bias=bias,
                score=score,
                score_1h=score,
                score_4h=score,
                score_1d=score,
                wave_b_block=False,
            )
            return _cache["result"]
        except Exception as e:
            print(f"[Scanner] BTC bias refresh failed: {e}")
            self.btc_gate.update()
            return _cache.get("result")

    def run_cycle(self):
        if self.ks:
            can_trade, reason = self.ks.can_trade()
            if not can_trade:
                return [], [("ALL", 0, f"kill_switch_{reason}")]

        btc = self._refresh_btc_bias()
        if self._market_override.get("block_all"):
            return [], [("ALL", 0, self._market_override.get("reason", "market_override_block"))]
        candidates = []
        wasted = []
        for symbol in getattr(self.cfg, "ACTIVE_WHITELIST", []):
            try:
                conf = getattr(self.cfg, "WHITELIST", {}).get(symbol, {})
                if not conf.get("enabled", False):
                    wasted.append((symbol, 0, "not_whitelisted"))
                    continue
                df = fetch_ohlcv(symbol, "15m", 200, self.cfg)
                if df is None or df.empty or len(df) < 120:
                    wasted.append((symbol, 0, "no_data"))
                    continue
                score = self.scoring_engine.calculate(df)
                if not score.entry_ok or score.direction == "NONE":
                    wasted.append((symbol, score.total, score.reason))
                    continue
                adaptive_regime = score.components.get("adaptive_regime", "")
                if adaptive_regime == "SIDEWAYS" and not (
                    score.components.get("breakout_signal")
                    and score.components.get("volatility_rising")
                ):
                    wasted.append((symbol, score.total, "sideways_regime"))
                    continue
                breakout_ok, breakout_reason = self._breakout_gate_ok(score)
                if not breakout_ok:
                    wasted.append((symbol, score.total, breakout_reason))
                    continue
                min_score = self._min_score_for_regime(adaptive_regime)
                if score.total < min_score:
                    wasted.append((symbol, score.total, f"score_below_{adaptive_regime or 'default'}_{min_score:.2f}"))
                    continue
                priority = getattr(self.cfg, "SYMBOL_DIRECTION_PRIORITY", {}).get(symbol, "BOTH")
                if priority == "LONG" and score.direction != "LONG":
                    wasted.append((symbol, score.total, "priority_long_only"))
                    continue
                if priority == "SHORT" and score.direction != "SHORT":
                    wasted.append((symbol, score.total, "priority_short_only"))
                    continue
                btc_ok, btc_reason = self._btc_allows(btc, score)
                if not btc_ok:
                    wasted.append((symbol, score.total, btc_reason))
                    continue
                if score.components.get("momentum", 0) < getattr(self.cfg, "MOMENTUM_MIN", 0.5):
                    wasted.append((symbol, score.total, "momentum_too_weak"))
                    continue
                if score.components.get("volatility", 0) < getattr(self.cfg, "VOLATILITY_COMPONENT_MIN", 0.3):
                    wasted.append((symbol, score.total, "volatility_too_weak"))
                    continue
                if (
                    (score.components.get("sideways") and not score.components.get("sideways_breakout_allowed"))
                    or score.components.get("alternating_chop")
                ):
                    wasted.append((symbol, score.total, "anti_chop_block"))
                    continue

                candle_ok, candle_reason = self._candle_strength_ok(df)
                if not candle_ok:
                    wasted.append((symbol, score.total, candle_reason))
                    continue

                timing_ok, timing_reason = self._entry_timing_ok(df, score.direction)
                if not timing_ok:
                    wasted.append((symbol, score.total, timing_reason))
                    continue

                candle_key = self._candle_key(df)
                if not self._market_override.get("skip_delay"):
                    pending = self._pending_entries.get(symbol)
                    if pending is None:
                        self._pending_entries[symbol] = {
                            "direction": score.direction,
                            "regime": adaptive_regime,
                            "score": score.total,
                            "candle_key": candle_key,
                        }
                        wasted.append((symbol, score.total, "pending_next_candle_confirmation"))
                        continue
                    if pending.get("candle_key") == candle_key:
                        wasted.append((symbol, score.total, "waiting_next_candle"))
                        continue
                    if pending.get("direction") != score.direction or not self._direction_confirmed(df, score.direction):
                        self._pending_entries.pop(symbol, None)
                        wasted.append((symbol, score.total, "confirmation_failed_cancelled"))
                        continue
                    self._pending_entries.pop(symbol, None)

                plan = build_trade_plan(symbol, score, df, self.cfg)
                size_factor = float(self._market_override.get("size_factor", 1.0))
                risk_add = float(self._market_override.get("risk_add", 0.0))
                if size_factor != 1.0 or risk_add:
                    original_qty = float(plan.qty)
                    plan.qty = round(max(0.0, original_qty * size_factor * (1.0 + risk_add)), 8)
                    plan.market_override = dict(self._market_override)
                    print(
                        f"[MarketOverride] {symbol} {self._market_override.get('reason')} "
                        f"qty {original_qty} -> {plan.qty}"
                    )
                if float(plan.qty) <= 0:
                    wasted.append((symbol, score.total, "risk_multiplier_zero"))
                    continue
                plan.strong_trend = bool(score.components.get("strong_trend", False))
                plan.volatility_regime = score.components.get("volatility_regime", "NORMAL")
                plan.squeeze_breakout = bool(score.components.get("squeeze_breakout", False))
                plan.adaptive_regime = adaptive_regime
                plan.learning_min_score = min_score
                candidates.append((symbol, score, plan, adaptive_regime or (btc.mode if btc else "NEUTRAL")))
            except Exception as e:
                wasted.append((symbol, 0, f"scan_error:{e}"))
        selected, wasted = self._rank_and_weight_candidates(candidates, wasted)
        return selected, wasted
