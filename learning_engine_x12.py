import json
import os
from collections import Counter
from datetime import datetime


STATE_FILE = "data/learning_state.json"


class LearningEngine:
    def __init__(self, cfg, state_file: str = STATE_FILE):
        self.cfg = cfg
        self.state_file = state_file
        self.trades = []
        self.tuning = {
            "min_score_adjust": 0.0,
            "breakout_momentum_adjust": 0.0,
            "risk_multiplier_adjust": {
                "TREND": 1.0,
                "BREAKOUT": 1.0,
                "MEAN_REVERT": 1.0,
            },
            "loss_temp_trades_left": 0,
            "loss_temp_min_score": 0.0,
            "loss_temp_size_factor": 1.0,
        }
        self._load()

    def _load(self):
        if not os.path.exists(self.state_file):
            return
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.trades = list(data.get("trades", []))[-100:]
            self.tuning.update(data.get("tuning", {}))
            self.tuning.setdefault("risk_multiplier_adjust", {})
            for regime in ["TREND", "BREAKOUT", "MEAN_REVERT"]:
                self.tuning["risk_multiplier_adjust"].setdefault(regime, 1.0)
        except Exception as e:
            print(f"[Learning] load failed: {e}")

    def _save(self):
        if getattr(self.cfg, "BACKTEST_MODE", False):
            return
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump({"trades": self.trades[-100:], "tuning": self.tuning}, f, indent=2)
        except Exception as e:
            print(f"[Learning] save failed: {e}")

    def _learning_enabled(self) -> bool:
        return len(self.trades) >= 20

    def _smooth_limited(self, old: float, calculated: float, max_change: float) -> float:
        smoothed = (old * 0.7) + (calculated * 0.3)
        delta = max(-max_change, min(max_change, smoothed - old))
        return old + delta

    def effective_min_score(self, base: float) -> float:
        if not self._learning_enabled():
            return float(base)
        value = float(base) + float(self.tuning.get("min_score_adjust", 0.0))
        value += float(self.tuning.get("loss_temp_min_score", 0.0))
        return min(0.65, max(0.55, value))

    def effective_breakout_momentum_min(self, base: float) -> float:
        if not self._learning_enabled():
            return float(base)
        value = float(base) + float(self.tuning.get("breakout_momentum_adjust", 0.0))
        return min(0.65, max(0.45, value))

    def risk_factor(self, regime: str) -> float:
        if not self._learning_enabled():
            return 1.0
        regime = (regime or "").upper()
        factor = float(self.tuning.get("risk_multiplier_adjust", {}).get(regime, 1.0))
        factor *= float(self.tuning.get("loss_temp_size_factor", 1.0))
        return max(0.0, factor)

    def _last_n(self, n: int):
        return self.trades[-n:]

    def _winrate(self, trades) -> float:
        if not trades:
            return 0.0
        wins = sum(1 for t in trades if t.get("exit_result") == "win")
        return wins / len(trades)

    def _consecutive_losses(self) -> int:
        count = 0
        for trade in reversed(self.trades):
            if trade.get("exit_result") != "loss":
                break
            count += 1
        return count

    def _retune_global_threshold(self):
        if len(self.trades) < 20 or len(self.trades) % 20 != 0:
            return
        wr = self._winrate(self._last_n(20))
        old_adjust = float(self.tuning.get("min_score_adjust", 0.0))
        calculated = old_adjust
        if wr < 0.50:
            calculated += 0.02
        elif wr > 0.65:
            calculated -= 0.01
        base = float(getattr(self.cfg, "MIN_SCORE", 0.58))
        calculated = min(0.65 - base, max(0.55 - base, calculated))
        new_adjust = self._smooth_limited(old_adjust, calculated, 0.02)
        self.tuning["min_score_adjust"] = min(0.65 - base, max(0.55 - base, new_adjust))

    def _retune_regime_risk(self):
        for regime in ["TREND", "BREAKOUT", "MEAN_REVERT"]:
            trades = [t for t in self.trades[-100:] if t.get("regime") == regime]
            if len(trades) < 5:
                continue
            wr = self._winrate(trades)
            old_factor = float(self.tuning["risk_multiplier_adjust"].get(regime, 1.0))
            calculated = old_factor
            if wr < 0.45:
                calculated *= 0.8
            elif wr > 0.65:
                calculated *= 1.1
            calculated = min(1.5, max(0.4, calculated))
            new_factor = self._smooth_limited(old_factor, calculated, 0.1)
            self.tuning["risk_multiplier_adjust"][regime] = min(1.5, max(0.4, new_factor))

    def _retune_breakout_momentum(self):
        breakouts = [t for t in self.trades[-30:] if t.get("regime") == "BREAKOUT"]
        if len(breakouts) < 5:
            return
        losses = sum(1 for t in breakouts if t.get("exit_result") == "loss")
        strong_wins = sum(1 for t in breakouts if t.get("exit_result") == "win" and float(t.get("profit_pct", 0.0)) >= 1.5)
        old_adjust = float(self.tuning.get("breakout_momentum_adjust", 0.0))
        calculated = old_adjust
        if losses >= max(3, len(breakouts) // 2):
            calculated += 0.05
        elif strong_wins >= max(3, len(breakouts) // 2):
            calculated -= 0.02
        base = float(getattr(self.cfg, "BREAKOUT_MOMENTUM_MIN", 0.5))
        calculated = min(0.65 - base, max(0.45 - base, calculated))
        new_adjust = self._smooth_limited(old_adjust, calculated, 0.03)
        self.tuning["breakout_momentum_adjust"] = min(0.65 - base, max(0.45 - base, new_adjust))

    def _retune_loss_behavior(self):
        if not self._learning_enabled():
            self.tuning["loss_temp_trades_left"] = 0
            self.tuning["loss_temp_min_score"] = 0.0
            self.tuning["loss_temp_size_factor"] = 1.0
            return

        if int(self.tuning.get("loss_temp_trades_left", 0)) > 0:
            self.tuning["loss_temp_trades_left"] = int(self.tuning["loss_temp_trades_left"]) - 1
            if int(self.tuning["loss_temp_trades_left"]) <= 0:
                self.tuning["loss_temp_min_score"] = 0.0
                self.tuning["loss_temp_size_factor"] = 1.0

        if self._consecutive_losses() >= 3:
            self.tuning["loss_temp_trades_left"] = 5
            self.tuning["loss_temp_min_score"] = 0.03
            self.tuning["loss_temp_size_factor"] = 0.7

    def record_trade(self, plan, pnl: float, exit_price: float):
        entry = float(getattr(plan, "entry", 0.0) or 0.0)
        if getattr(plan, "direction", "") == "LONG":
            profit_pct = ((float(exit_price) - entry) / entry * 100) if entry else 0.0
        else:
            profit_pct = ((entry - float(exit_price)) / entry * 100) if entry else 0.0
        trade = {
            "ts": datetime.utcnow().isoformat(),
            "symbol": getattr(plan, "symbol", ""),
            "direction": getattr(plan, "direction", ""),
            "regime": str(getattr(plan, "adaptive_regime", "UNKNOWN") or "UNKNOWN").upper(),
            "entry_score": float(getattr(plan, "score", 0.0) or 0.0),
            "exit_result": "win" if float(pnl) > 0 else "loss",
            "profit_pct": round(profit_pct, 4),
        }
        self.trades.append(trade)
        self.trades = self.trades[-100:]

        self._retune_global_threshold()
        self._retune_regime_risk()
        self._retune_breakout_momentum()
        self._retune_loss_behavior()
        self._save()
        self.log_summary()

    def log_summary(self):
        last20 = self._last_n(20)
        wr = self._winrate(last20) * 100 if last20 else 0.0
        regimes = Counter(t.get("regime", "UNKNOWN") for t in self.trades[-20:])
        print(
            "[Learning] "
            f"trades={len(self.trades)} last20_wr={wr:.1f}% "
            f"min_score_adj={self.tuning.get('min_score_adjust', 0.0):+.3f} "
            f"breakout_mom_adj={self.tuning.get('breakout_momentum_adjust', 0.0):+.3f} "
            f"loss_temp_left={self.tuning.get('loss_temp_trades_left', 0)} "
            f"regimes={dict(regimes)}"
        )
