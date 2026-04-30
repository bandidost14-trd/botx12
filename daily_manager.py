# ============================================================
# BotX12.1 Pro — daily_manager.py
# Tracking entry harian, session window, coin cooldown
# ============================================================

import json, os
from datetime import date, datetime

STATE_FILE = "data/daily_manager_state.json"


def _now_utc(cfg=None):
    ts = getattr(cfg, "BACKTEST_CURRENT_TS", None) if cfg else None
    if ts is None:
        return datetime.utcnow()
    try:
        return ts.to_pydatetime().replace(tzinfo=None)
    except Exception:
        return datetime.utcnow()


class DailyManager:
    def __init__(self, cfg):
        self.cfg          = cfg
        self._today       = str(_now_utc(cfg).date())
        self._entries     = []   # list of symbol
        self._last_summary_hour = -1
        if not getattr(cfg, "BACKTEST_MODE", False):
            self._load()

    def _load(self):
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE) as f:
                    s = json.load(f)
                if s.get("date") == self._today:
                    self._entries = s.get("entries", [])
                    self._last_summary_hour = s.get("last_summary_hour", -1)
                else:
                    self._entries = []
                    self._last_summary_hour = -1
            except Exception:
                pass

    def _save(self):
        if getattr(self.cfg, "BACKTEST_MODE", False):
            return
        os.makedirs("data", exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump({
                "date": self._today,
                "entries": self._entries,
                "last_summary_hour": self._last_summary_hour
            }, f)

    def _refresh_today(self):
        today = str(_now_utc(self.cfg).date())
        if today != self._today:
            self._today   = today
            self._entries = []
            self._last_summary_hour = -1
            self._save()

    def can_open_trade(self, symbol: str) -> tuple:
        self._refresh_today()
        max_daily = getattr(self.cfg, "MAX_ENTRY_PER_DAY", 5)
        if len(self._entries) >= max_daily:
            return False, f"daily_limit={len(self._entries)}/{max_daily}"

        hour_wib = (_now_utc(self.cfg).hour + 7) % 24
        windows  = getattr(self.cfg, "SESSION_WINDOWS_WIB", [(7, 13), (19, 24)])
        in_session = any(s <= hour_wib < e for s, e in windows)
        if not in_session:
            return False, f"jam_wib={hour_wib} di luar session window"

        return True, "OK"

    def record_entry(self, symbol: str):
        self._refresh_today()
        self._entries.append(symbol)
        self._save()

    def daily_entry_count(self) -> int:
        self._refresh_today()
        return len(self._entries)

    def should_send_hourly_summary(self) -> bool:
        hour = _now_utc(self.cfg).hour
        if hour != self._last_summary_hour:
            self._last_summary_hour = hour
            self._save()
            return True
        return False
