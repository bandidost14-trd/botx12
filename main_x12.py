#!/usr/bin/env python3
# ============================================================
# BotX12.1 Pro — main_x12.py  (FINAL PATCH)
# - Telegram commands stabil
# - tambah /help
# - kompatibel dengan struktur bot aktif saat ini
# ============================================================

import time, sys, os
from datetime import UTC, datetime, date

sys.path.insert(0, os.path.dirname(__file__))

import config_x12 as cfg
from telegram_x12         import TelegramBot
from kill_switch_x12      import KillSwitch
from daily_manager        import DailyManager
from position_manager_x12 import PositionManager
from scanner_x12          import Scanner
from btc_gate_x12         import _cache as btc_cache
from learning_engine_x12  import LearningEngine

SCAN_INTERVAL    = 15 * 60   # 15 menit
PRICE_CHECK_SECS = 60        # cek SL/TP tiap 1 menit

_entry_counter   = 0
_last_entry_day  = None


def _get_entry_num(dm):
    global _entry_counter, _last_entry_day
    today = str(date.today())
    if _last_entry_day != today:
        _entry_counter = 0
        _last_entry_day = today
    _entry_counter += 1
    return _entry_counter


def _fmt_num(x, dec=4):
    try:
        return f"{float(x):.{dec}f}"
    except Exception:
        return str(x)


def main():
    print(f"[Main] Starting {cfg.BOT_NAME} v{cfg.BOT_VERSION}")
    missing_exchange = cfg.missing_exchange_auth() if hasattr(cfg, "missing_exchange_auth") else []
    if missing_exchange:
        raise RuntimeError(
            "Missing Binance auth environment variables: "
            + ", ".join(missing_exchange)
            + ". Set them before running live/testnet mode, or enable BACKTEST_MODE=1."
        )

    telegram = TelegramBot(cfg)
    ks       = KillSwitch(cfg)
    dm       = DailyManager(cfg)
    learning = LearningEngine(cfg)
    pm       = PositionManager(cfg, telegram, ks, learning)
    scanner  = Scanner(cfg, ks, dm, pm, telegram, learning)

    balance = pm.validate_connection()
    telegram.validate_connection()

    ks.daily_reset()
    print(f"[Main] Balance: ${balance:,.2f}")
    telegram.notify_start(balance)

    _daily = {
        "trades": 0,
        "tp": 0,
        "sl": 0,
        "pnl": 0.0,
        "wasted": 0,
        "top_wasted": "",
        "top_score": 0,
    }

    # ── Telegram commands ───────────────────────────────────
    def cmd_status():
        bal    = pm.get_balance()
        can, r = ks.can_trade()
        btc_r  = btc_cache.get("result")
        btc_b  = btc_r.bias if btc_r else "?"
        telegram.send(
            f"📊 <b>STATUS — {cfg.BOT_NAME}</b>\n"
            f"💰 Balance  : ${bal:,.2f}\n"
            f"📌 Posisi   : {len(pm.positions)}/{cfg.MAX_POSITION}\n"
            f"📈 Entry/Day: {dm.daily_entry_count()}/{cfg.MAX_ENTRY_PER_DAY}\n"
            f"₿ BTC Gate  : {btc_b}\n"
            f"⚡ Streak    : {ks.loss_streak}/{cfg.MAX_LOSS_STREAK}\n"
            f"🛡️ KS Status : {'RUNNING ✅' if can else f'PAUSED ⛔ ({r})'}\n"
            f"🌐 Mode      : {'TESTNET' if cfg.TESTNET else 'LIVE'}"
        )

    def cmd_pause():
        ks.is_active = False
        ks._save()
        telegram.send("⏸️ <b>BOT PAUSED</b>\nEntry baru dihentikan sementara.")

    def cmd_resume():
        ks.force_reset()
        telegram.send("▶️ <b>BOT RESUMED</b>\nBot aktif kembali untuk scan & entry.")

    def cmd_positions():
        if not pm.positions:
            telegram.send("📭 <b>OPEN POSITIONS</b>\nTidak ada posisi aktif.")
            return

        lines = [f"📌 <b>OPEN POSITIONS ({len(pm.positions)}/{cfg.MAX_POSITION})</b>"]
        for i, (symbol, pos) in enumerate(pm.positions.items(), 1):
            plan = pos.get("plan")
            if not plan:
                lines.append(f"{i}. {symbol} | data plan tidak tersedia")
                continue
            lines.append(
                f"{i}. {symbol} | {plan.direction} | qty={_fmt_num(plan.qty, 4)} | "
                f"entry={_fmt_num(plan.entry, 6)} | sl={_fmt_num(plan.sl, 6)} | "
                f"tp1={_fmt_num(plan.tp1, 6)} | tp2={_fmt_num(plan.tp2, 6)}"
            )
        telegram.send("\n".join(lines))

    def cmd_help():
        telegram.send(
            "🤖 <b>COMMANDS AKTIF</b>\n"
            "/status - status bot\n"
            "/pause - pause entry baru\n"
            "/resume - lanjutkan bot\n"
            "/positions - lihat posisi aktif\n"
            "/help - bantuan"
        )

    telegram.register("/status",    cmd_status)
    telegram.register("/pause",     cmd_pause)
    telegram.register("/resume",    cmd_resume)
    telegram.register("/positions", cmd_positions)
    telegram.register("/help",      cmd_help)
    telegram.poll_commands()

    print(
        f"[Main] Running. Interval={SCAN_INTERVAL//60}m | "
        f"MaxPos={cfg.MAX_POSITION} | MaxDay={cfg.MAX_ENTRY_PER_DAY}"
    )

    last_price_check = 0
    last_daily_summary = str(date.today())

    while True:
        try:
            cycle_start = time.time()
            now_utc     = datetime.now(UTC)
            now_str     = now_utc.strftime('%H:%M:%S')
            print(f"\n[Main] ── Cycle {now_str} UTC | pos={len(pm.positions)} day={dm.daily_entry_count()}")

            today = str(date.today())
            if today != last_daily_summary:
                bal = pm.get_balance()
                wr  = (_daily["tp"] / max(_daily["trades"], 1)) * 100
                telegram.notify_daily_summary(
                    last_daily_summary,
                    _daily["trades"], _daily["tp"], _daily["sl"],
                    wr, _daily["pnl"], bal,
                    _daily["wasted"], _daily["top_wasted"], _daily["top_score"]
                )
                _daily.update({
                    "trades": 0,
                    "tp": 0,
                    "sl": 0,
                    "pnl": 0.0,
                    "wasted": 0,
                    "top_wasted": "",
                    "top_score": 0,
                })
                last_daily_summary = today

            now_ts = time.time()
            if now_ts - last_price_check >= PRICE_CHECK_SECS:
                for sym in list(pm.positions.keys()):
                    try:
                        from data_loader_x12 import fetch_ohlcv
                        df1m = fetch_ohlcv(sym, "1m", 3, cfg)
                        if not df1m.empty:
                            price = df1m["close"].iloc[-1]
                            pm.check_sl_tp(sym, price)
                            pm.update_trailing(sym, price)
                    except Exception as e:
                        print(f"[Main] price check {sym}: {e}")
                last_price_check = now_ts

            result = scanner.run_cycle()
            candidates, wasted = result if isinstance(result, tuple) else (result, [])

            for w_sym, w_score, w_reason in wasted:
                _daily["wasted"] += 1
                if w_score > _daily["top_score"]:
                    _daily["top_score"] = w_score
                    _daily["top_wasted"] = w_sym

            if candidates or wasted:
                btc_r = btc_cache.get("result")
                if btc_r:
                    scan_items = [
                        (sym, sc.total, sc.direction,
                         abs(pl.sl_pct) if hasattr(pl, 'sl_pct') else 0)
                        for sym, sc, pl, _ in candidates
                    ]
                    telegram.notify_scan_report(
                        scan_items, btc_r.bias, btc_r.score,
                        btc_r.score_1h, btc_r.score_4h, btc_r.score_1d,
                        wasted[:2], len(pm.positions)
                    )

            for symbol, score, plan, regime in candidates:
                can_dm, reason_dm = dm.can_open_trade(symbol)
                if not can_dm:
                    print(f"[Main] {symbol} blocked: {reason_dm}")
                    continue

                plan.score = score.total

                success = pm.open_position(plan)
                if success:
                    dm.record_entry(symbol)
                    _daily["trades"] += 1
                    num = _get_entry_num(dm)
                    try:
                        entry_balance = pm.get_balance()
                    except Exception as e:
                        print(f"[Main] entry balance fetch failed: {e}")
                        entry_balance = None

                    btc_r = btc_cache.get("result")
                    telegram.notify_entry(
                        plan, num,
                        btc_r.bias if btc_r else "?",
                        ks.loss_streak,
                        adx=score.components.get("adx", 0),
                        rsi=score.components.get("rsi", 0),
                        vol=score.components.get("volume", 0) / 20.0,
                        conf=int(score.total * 100),
                        adx15m=score.components.get("adx", 0),
                        score_1d=btc_r.score_1d if btc_r else 0,
                        score_4h=btc_r.score_4h if btc_r else 0,
                        score_1h=btc_r.score_1h if btc_r else 0,
                        balance=entry_balance,
                    )
                    print(f"[Main] OPENED #{num} {symbol} {plan.direction} score={score.total:.2f}")

            if dm.should_send_hourly_summary():
                bal   = pm.get_balance()
                btc_r = btc_cache.get("result")
                hourly_profit = sum(float(t.get("pnl", 0.0) or 0.0) for t in getattr(pm, "closed_trades", []))
                telegram.notify_hourly(
                    bal, dm.daily_entry_count(), len(pm.positions),
                    btc_r.bias if btc_r else "?", ks.loss_streak,
                    positions=pm.positions,
                    profit=hourly_profit,
                )

        except KeyboardInterrupt:
            print("\n[Main] Stopped.")
            telegram.send("🔴 Bot dihentikan (KeyboardInterrupt)")
            break
        except Exception as e:
            print(f"[Main] Loop error: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(30)
            continue

        elapsed = time.time() - cycle_start
        sleep_t = max(0, SCAN_INTERVAL - elapsed)
        print(f"[Main] Sleep {sleep_t/60:.1f} menit...")
        time.sleep(sleep_t)


if __name__ == "__main__":
    main()
