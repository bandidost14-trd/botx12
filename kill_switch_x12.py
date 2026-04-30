# ============================================================
# BotX12.1 Pro — kill_switch_x12.py
# Loss streak + daily loss guard + smart pause
# ============================================================

import json, os
from datetime import datetime, date, timedelta

STATE_FILE = "data/kill_switch_state.json"


def _now_utc(cfg=None):
    ts = getattr(cfg, "BACKTEST_CURRENT_TS", None) if cfg else None
    if ts is None:
        return datetime.utcnow()
    try:
        return ts.to_pydatetime().replace(tzinfo=None)
    except Exception:
        return datetime.utcnow()


class KillSwitch:
    def __init__(self, cfg):
        self.cfg             = cfg
        self.loss_streak     = 0
        self.daily_loss      = 0.0
        self.paused_until    = None
        self.is_active       = True
        self._last_reset_day = None
        if not getattr(cfg, "BACKTEST_MODE", False):
            self._load()

    def _load(self):
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE) as f:
                    s = json.load(f)
                self.loss_streak     = s.get("loss_streak", 0)
                self.daily_loss      = s.get("daily_loss", 0.0)
                self.paused_until    = s.get("paused_until")
                self._last_reset_day = s.get("last_reset_day")
            except Exception:
                pass

    def _save(self):
        if getattr(self.cfg, "BACKTEST_MODE", False):
            return
        os.makedirs("data", exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump({
                "loss_streak": self.loss_streak,
                "daily_loss": self.daily_loss,
                "paused_until": self.paused_until,
                "last_reset_day": self._last_reset_day
            }, f)

    def daily_reset(self):
        today = str(_now_utc(self.cfg).date())
        if self._last_reset_day != today:
            self.daily_loss      = 0.0
            self._last_reset_day = today
            self._save()

    def record_trade(self, pnl: float, balance: float):
        self.daily_reset()
        if pnl < 0:
            self.loss_streak += 1
            self.daily_loss  += abs(pnl)
        else:
            self.loss_streak  = 0
        self._check_triggers(balance)
        self._save()

    def _check_triggers(self, balance: float):
        max_streak = getattr(self.cfg, "MAX_LOSS_STREAK", 10)
        max_dd_pct = getattr(self.cfg, "MAX_DAILY_LOSS_PCT", 3.0)
        pause_hrs  = getattr(self.cfg, "SMART_PAUSE_HOURS", 4)
        trigger_msg = None

        if self.loss_streak >= max_streak:
            trigger_msg = f"loss_streak={self.loss_streak}/{max_streak}"

        if balance > 0:
            dd_pct = self.daily_loss / balance * 100
            if dd_pct >= max_dd_pct:
                trigger_msg = f"daily_loss={dd_pct:.1f}%>={max_dd_pct}%"

        if trigger_msg:
            self.paused_until = (_now_utc(self.cfg) + timedelta(hours=pause_hrs)).isoformat()
            self.is_active    = False
            self._save()
            print(f"[KillSwitch] PAUSED: {trigger_msg} | resume: {self.paused_until}")

    def check_resume(self):
        if self.paused_until:
            now = _now_utc(self.cfg)
            try:
                until = datetime.fromisoformat(self.paused_until)
                if now >= until:
                    self.is_active    = True
                    self.paused_until = None
                    self.loss_streak  = 0
                    self._save()
                    print("[KillSwitch] RESUMED — streak reset")
            except Exception:
                pass

    def can_trade(self) -> tuple:
        self.check_resume()
        if not self.is_active:
            return False, f"paused until {self.paused_until}"
        return True, "OK"

    def force_reset(self):
        self.loss_streak  = 0
        self.daily_loss   = 0.0
        self.paused_until = None
        self.is_active    = True
        self._save()
        print("[KillSwitch] FORCE RESET by operator")
