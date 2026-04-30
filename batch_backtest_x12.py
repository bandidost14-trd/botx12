#!/usr/bin/env python3
# ============================================================
# BotX12.1 Pro — batch_backtest_x12.py
# Stage 2 patch: batch backtest multi-coin
# ============================================================

import argparse
import config_x12 as cfg
from backtest_x12 import run_backtest


def parse_args():
    parser = argparse.ArgumentParser(description="Batch Backtest BotX12 CLEAN")

    parser.add_argument("--symbols", nargs="+", default=None)
    parser.add_argument("--batch-size", type=int, default=cfg.BACKTEST_BATCH_SIZE)
    parser.add_argument("--data-dir", default=cfg.BACKTEST_DATA_DIR)
    parser.add_argument("--start", default=cfg.BACKTEST_START)
    parser.add_argument("--end", default=cfg.BACKTEST_END)
    parser.add_argument("--initial-balance", type=float, default=cfg.BACKTEST_INITIAL_BALANCE)
    parser.add_argument("--export-root", default="backtest_reports_batch")

    return parser.parse_args()


def chunk_list(lst, size):
    for i in range(0, len(lst), size):
        yield lst[i:i + size]


def main():
    args = parse_args()

    # gunakan symbols dari CLI, kalau tidak pakai whitelist config
    symbols = args.symbols if args.symbols else getattr(cfg, "WHITELIST_ALL", [])

    if not symbols:
        print("❌ ERROR: Tidak ada symbol")
        return

    print(f"\n=== TOTAL SYMBOLS: {len(symbols)} ===")

    batches = list(chunk_list(symbols, args.batch_size))

    for i, batch in enumerate(batches, 1):
        print(f"\n=== RUN BATCH {i}/{len(batches)} ===")
        print(f"Symbols: {batch}")

        for sym in batch:
            try:
                print(f"[RUN] {sym}")

                run_backtest(
                    [sym],
                    args.data_dir,
                    args.start,
                    args.end,
                    args.initial_balance,
                    f"{args.export_root}/batch_{i:02d}_{sym}"
                )

            except Exception as e:
                print(f"[ERROR] {sym}: {e}")


if __name__ == "__main__":
    main()