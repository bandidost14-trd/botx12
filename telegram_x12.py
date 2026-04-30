#!/usr/bin/env python3

import re
import threading
import time

import requests


class TelegramBot:
    def __init__(self, cfg):
        self.token = getattr(cfg, "TELEGRAM_TOKEN", "")
        self.chat_id = str(getattr(cfg, "TELEGRAM_CHAT_ID", ""))
        self.cfg = cfg
        self._offset = 0
        self._handlers = {}
        self._poll_started = False
        self._poll_lock = threading.Lock()
        self._last_cmd_ts = {}
        self._poll_ready = False
        self._bot_username = ""
        self._last_regime_sig = ""
        self._last_regime_ts = 0.0
        self._regime_cooldown_sec = 30 * 60

    def _fmt_money(self, value) -> str:
        try:
            return f"${float(value):+,.4f}"
        except Exception:
            return str(value)

    def _fmt_balance(self, value) -> str:
        if value is None:
            return "N/A"
        try:
            return f"${float(value):,.2f} USDT"
        except Exception:
            return str(value)

    def _fmt_score(self, value) -> str:
        try:
            score = float(value)
            if score <= 1.0:
                score *= 100
            return f"{score:.0f}"
        except Exception:
            return str(value)

    def validate_connection(self) -> bool:
        if not self.token or not self.chat_id:
            missing = []
            if not self.token:
                missing.append("TELEGRAM_TOKEN")
            if not self.chat_id:
                missing.append("TELEGRAM_CHAT_ID")
            print(f"[Telegram] disabled; missing environment variables: {', '.join(missing)}")
            return False

        ok = False
        try:
            r = requests.get(f"https://api.telegram.org/bot{self.token}/getMe", timeout=10)
            data = r.json()
            if data.get("ok") and data.get("result"):
                self._bot_username = (data["result"].get("username") or "").lower()
                print(f"[Telegram] auth ok | bot=@{self._bot_username or '-'}")
                ok = True
            else:
                print(f"[Telegram] auth failed: {data}")
        except Exception as e:
            print(f"[Telegram] auth error: {e}")
            return False

        try:
            r = requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id": self.chat_id, "text": "BotX12 startup connection check"},
                timeout=10,
            )
            data = r.json()
            if data.get("ok"):
                print(f"[Telegram] chat ok | chat_id={self.chat_id}")
            else:
                print(f"[Telegram] chat validation failed: {data}")
                ok = False
        except Exception as e:
            print(f"[Telegram] chat validation error: {e}")
            ok = False

        return ok

    def _ensure_poll_ready(self):
        if self._poll_ready or not self.token:
            return
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{self.token}/deleteWebhook",
                json={"drop_pending_updates": False},
                timeout=10,
            )
            data = r.json()
            print(f"[Telegram] deleteWebhook ok={data.get('ok')}")
        except Exception as e:
            print(f"[Telegram] deleteWebhook error: {e}")
        try:
            r = requests.get(f"https://api.telegram.org/bot{self.token}/getMe", timeout=10)
            data = r.json()
            if data.get("ok") and data.get("result"):
                self._bot_username = (data["result"].get("username") or "").lower()
                print(f"[Telegram] getMe username={self._bot_username or '-'}")
            else:
                print(f"[Telegram] getMe failed: {data}")
        except Exception as e:
            print(f"[Telegram] getMe error: {e}")
        self._poll_ready = True

    def _normalize_cmd(self, text: str) -> str:
        cmd = (text or "").strip().split()[0].lower()
        if "@" in cmd:
            base, at_user = cmd.split("@", 1)
            if (not self._bot_username) or (at_user == self._bot_username):
                return base
        return cmd

    def _is_regime_message(self, msg: str) -> bool:
        if not msg:
            return False
        m = msg.lower()
        return ("btc regime change" in m) or ("regime change" in m)

    def _extract_regime_signature(self, msg: str) -> str:
        if not msg:
            return ""
        lines = [ln.strip() for ln in msg.splitlines() if ln.strip()]
        for ln in lines:
            if "->" in ln:
                clean = re.sub(r"[^A-Z\-\> ]", " ", ln.upper())
                clean = re.sub(r"\s+", " ", clean).strip()
                if clean:
                    return clean
        return ""

    def _should_block_regime_spam(self, msg: str) -> bool:
        if not self._is_regime_message(msg):
            return False
        sig = self._extract_regime_signature(msg)
        if not sig:
            return False
        now = time.time()
        if sig == self._last_regime_sig and (now - self._last_regime_ts) < self._regime_cooldown_sec:
            return True
        self._last_regime_sig = sig
        self._last_regime_ts = now
        return False

    def send(self, msg: str):
        if not self.token or not self.chat_id:
            return
        if self._should_block_regime_spam(msg):
            print("[Telegram] duplicate regime message suppressed")
            return
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id": self.chat_id, "text": msg, "parse_mode": "HTML"},
                timeout=5,
            )
            data = r.json()
            if not data.get("ok", False):
                print(f"[Telegram] send failed: {data}")
        except Exception as e:
            print(f"[Telegram] send error: {e}")

    def notify_start(self, balance: float):
        self.send(
            f"<b>{self.cfg.BOT_NAME} v{self.cfg.BOT_VERSION} STARTED</b>\n"
            f"Balance: {self._fmt_balance(balance)}\n"
            f"Mode: {'TESTNET' if self.cfg.TESTNET else 'LIVE'}\n"
            f"Max positions: {self.cfg.MAX_POSITION}\n"
            f"Max entries/day: {self.cfg.MAX_ENTRY_PER_DAY}"
        )

    def notify_scan_report(
        self,
        candidates: list,
        btc_bias: str,
        btc_score: float,
        btc_1h: float,
        btc_4h: float,
        btc_1d: float,
        wasted: list,
        active_count: int,
    ):
        if not candidates and not wasted:
            return
        lines = [f"<b>SCAN REPORT</b> | candidates={len(candidates)} | active={active_count}"]
        for i, (sym, score, direction, sl_pct) in enumerate(candidates[:3], 1):
            lines.append(f"{i}. {sym} | {direction} | score={self._fmt_score(score)} | SL={sl_pct:.3f}%")
        lines.append(f"BTC gate: {btc_bias} | score={btc_score:.3f}")
        if wasted:
            lines.append("")
            lines.append("<b>WASTED SIGNALS</b>")
            for w_sym, w_score, w_reason in wasted[:2]:
                lines.append(f"{w_sym} | score={self._fmt_score(w_score)} | reason={w_reason}")
        self.send("\n".join(lines))

    def notify_entry(
        self,
        plan,
        entry_num: int = 0,
        btc_bias: str = "?",
        streak: int = 0,
        adx: float = 0,
        rsi: float = 0,
        vol: float = 0,
        conf: int = 0,
        adx15m: float = 0,
        score_1d: float = 0,
        score_4h: float = 0,
        score_1h: float = 0,
        balance: float | None = None,
    ):
        rr1_actual = plan.tp1_pct / plan.sl_pct if plan.sl_pct > 0 else 0
        rr2_actual = plan.tp2_pct / plan.sl_pct if plan.sl_pct > 0 else 0
        max_loss = plan.modal * plan.sl_pct / 100
        tp1_est = plan.modal * plan.tp1_pct / 100 * plan.leverage
        self.send(
            f"<b>TRADE ENTRY #{entry_num}</b>\n"
            f"Symbol: {plan.symbol}\n"
            f"Direction: {plan.direction}\n"
            f"Entry: <code>{plan.entry}</code>\n"
            f"SL: <code>{plan.sl}</code> ({plan.sl_pct:.2f}%)\n"
            f"TP1: <code>{plan.tp1}</code> [RR {rr1_actual:.1f}x]\n"
            f"TP2: <code>{plan.tp2}</code> [RR {rr2_actual:.1f}x]\n"
            f"Profit: $0.0000\n"
            f"Balance: {self._fmt_balance(balance)}\n"
            f"Score: {self._fmt_score(getattr(plan, 'score', 0))}\n"
            f"Max loss: ${max_loss:.4f} | TP1 est: +${tp1_est:.4f}\n"
            f"BTC: {btc_bias} | SL streak: {streak}"
        )
        self.send(
            f"<b>ENTRY CONFIRMATION</b>\n"
            f"Symbol: {plan.symbol}\n"
            f"Direction: {plan.direction}\n"
            f"1D: {score_1d:.2f} | 4H: {score_4h:.2f} | 1H: {score_1h:.2f}\n"
            f"ADX: {adx:.1f} | ADX15M: {adx15m:.1f} | RSI: {rsi:.1f} | Vol: {vol:.1f}x | Conf: {conf}\n"
            f"Profit: $0.0000\n"
            f"Balance: {self._fmt_balance(balance)}"
        )

    def notify_tp1(self, symbol: str, direction: str, exit_price: float, pnl: float, sl_be: float, balance: float | None = None):
        self.send(
            f"<b>TP1 HIT</b>\n"
            f"Symbol: {symbol}\n"
            f"Direction: {direction}\n"
            f"Exit: <code>{exit_price}</code>\n"
            f"Profit: {self._fmt_money(pnl)}\n"
            f"Balance: {self._fmt_balance(balance)}\n"
            f"SL moved to BE: <code>{sl_be}</code>"
        )

    def notify_tp2(self, symbol: str, direction: str, exit_price: float, pnl: float, balance: float | None = None):
        self.send(
            f"<b>TP2 HIT</b>\n"
            f"Symbol: {symbol}\n"
            f"Direction: {direction}\n"
            f"Exit: <code>{exit_price}</code>\n"
            f"Profit: {self._fmt_money(pnl)}\n"
            f"Balance: {self._fmt_balance(balance)}"
        )

    def notify_sl(self, symbol: str, direction: str, exit_price: float, pnl: float, streak: int, balance: float | None = None):
        self.send(
            f"<b>SL HIT</b>\n"
            f"Symbol: {symbol}\n"
            f"Direction: {direction}\n"
            f"Exit: <code>{exit_price}</code>\n"
            f"Profit: {self._fmt_money(pnl)}\n"
            f"Balance: {self._fmt_balance(balance)}\n"
            f"Streak: {streak}/3"
        )

    def notify_trailing(self, symbol: str, direction: str, exit_price: float, pnl: float, balance: float | None = None):
        self.send(
            f"<b>TRAILING STOP</b>\n"
            f"Symbol: {symbol}\n"
            f"Direction: {direction}\n"
            f"Exit: <code>{exit_price}</code>\n"
            f"Profit: {self._fmt_money(pnl)}\n"
            f"Balance: {self._fmt_balance(balance)}"
        )

    def notify_close(
        self,
        plan,
        reason: str,
        pnl: float = 0,
        exit_price: float | None = None,
        balance: float | None = None,
        streak: int = 0,
    ):
        px = exit_price if exit_price is not None else plan.entry
        reason_u = (reason or "").upper()
        if "TP1" in reason_u:
            self.notify_tp1(plan.symbol, plan.direction, px, pnl, plan.entry, balance)
        elif "TP2" in reason_u:
            self.notify_tp2(plan.symbol, plan.direction, px, pnl, balance)
        elif "SL" in reason_u:
            self.notify_sl(plan.symbol, plan.direction, px, pnl, streak, balance)
        else:
            self.notify_trailing(plan.symbol, plan.direction, px, pnl, balance)

    def notify_daily_summary(
        self,
        date: str,
        trades: int,
        tp: int,
        sl: int,
        win_rate: float,
        pnl: float,
        balance: float,
        wasted: int,
        top_wasted: str,
        top_score: float,
    ):
        self.send(
            f"<b>DAILY SUMMARY</b>\n"
            f"Date: {date}\n"
            f"Trades: {trades} | TP: {tp} | SL: {sl}\n"
            f"Win rate: {win_rate:.0f}%\n"
            f"Profit: {self._fmt_money(pnl)}\n"
            f"Balance: {self._fmt_balance(balance)}\n"
            f"Wasted: {wasted}\n"
            f"Top wasted: {top_wasted} score={top_score:.0f}"
        )

    def notify_kill_switch(self, reason: str, resume_time: str):
        self.send(
            f"<b>KILL SWITCH TRIGGERED</b>\n"
            f"Reason: {reason}\n"
            f"Resume: {resume_time} UTC"
        )

    def notify_hourly(
        self,
        balance: float,
        daily_count: int,
        active: int,
        btc_bias: str,
        streak: int,
        positions: dict | None = None,
        profit: float = 0.0,
    ):
        lines = [
            "<b>HOURLY SUMMARY</b>",
            f"Balance: {self._fmt_balance(balance)}",
            f"Profit: {self._fmt_money(profit)}",
            f"Entry/day: {daily_count}/{self.cfg.MAX_ENTRY_PER_DAY}",
            f"Active: {active}/{self.cfg.MAX_POSITION}",
            f"BTC gate: {btc_bias}",
            f"SL streak: {streak}",
        ]
        if positions:
            lines.append("")
            lines.append("<b>OPEN POSITIONS</b>")
            for symbol, pos in positions.items():
                plan = pos.get("plan") if isinstance(pos, dict) else None
                if plan:
                    lines.append(f"{symbol} | {plan.direction} | Profit: $0.0000 | Balance: {self._fmt_balance(balance)}")
        self.send("\n".join(lines))

    def register(self, command: str, handler):
        self._handlers[command.strip().lower()] = handler

    def poll_commands(self):
        if not self.token or not self.chat_id:
            print("[Telegram] poll_commands skipped: token/chat_id missing")
            return
        with self._poll_lock:
            if self._poll_started:
                print("[Telegram] poll_commands already running")
                return
            self._poll_started = True

        self._ensure_poll_ready()

        def _loop():
            print("[Telegram] command polling started")
            while True:
                try:
                    r = requests.get(
                        f"https://api.telegram.org/bot{self.token}/getUpdates",
                        params={
                            "offset": self._offset,
                            "timeout": 20,
                            "allowed_updates": '["message","edited_message"]',
                        },
                        timeout=30,
                    )
                    data = r.json()
                    if not data.get("ok", False):
                        print(f"[Telegram] getUpdates not ok: {data}")
                        time.sleep(3)
                        continue
                    for update in data.get("result", []):
                        self._offset = update["update_id"] + 1
                        msg = update.get("message") or update.get("edited_message") or {}
                        chat = msg.get("chat", {}) or {}
                        if str(chat.get("id", "")) != self.chat_id:
                            continue
                        text = (msg.get("text", "") or "").strip()
                        if not text.startswith("/"):
                            continue
                        cmd = self._normalize_cmd(text)
                        handler = self._handlers.get(cmd)
                        print(f"[Telegram] incoming cmd={cmd} chat={chat.get('id')} matched={bool(handler)}")
                        if not handler:
                            continue
                        now = time.time()
                        last_ts = self._last_cmd_ts.get(cmd, 0.0)
                        if now - last_ts < 2:
                            continue
                        self._last_cmd_ts[cmd] = now
                        try:
                            handler()
                        except Exception as e:
                            self.send(f"Command error {cmd}: {e}")
                except Exception as e:
                    print(f"[Telegram] poll error: {e}")
                time.sleep(1)

        threading.Thread(target=_loop, daemon=True).start()
