# ============================================================
# BotX12.1 Pro — data_loader_x12.py
# Fetch OHLCV dari Binance Futures (testnet/live) atau CSV lokal
# ============================================================

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import requests

_TF_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1h", "4h": "4h", "1d": "1d"
}

_CSV_CACHE: dict[tuple[str, str, str], pd.DataFrame] = {}


def _get_base_url(cfg) -> str:
    return "https://testnet.binancefuture.com"


def _is_backtest(cfg) -> bool:
    return bool(cfg and getattr(cfg, "BACKTEST_MODE", False))


def _load_symbol_tf_csv(symbol: str, interval: str, cfg) -> pd.DataFrame:
    data_dir = Path(getattr(cfg, "BACKTEST_DATA_DIR", ""))
    cache_key = (str(data_dir), symbol, interval)
    if cache_key in _CSV_CACHE:
        return _CSV_CACHE[cache_key].copy()

    folder = data_dir / symbol / interval
    if not folder.exists():
        _CSV_CACHE[cache_key] = pd.DataFrame()
        return pd.DataFrame()

    files = sorted(folder.glob(f"{symbol}-{interval}-*.csv"))
    if not files:
        _CSV_CACHE[cache_key] = pd.DataFrame()
        return pd.DataFrame()

    frames = []
    for fp in files:
        try:
            df = pd.read_csv(fp)
            if "open_time" not in df.columns:
                continue
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
            df = df.dropna(subset=["open_time", "open", "high", "low", "close", "volume"])
            df = df[["open_time", "open", "high", "low", "close", "volume"]]
            frames.append(df)
        except Exception as e:
            print(f"[DataLoader] CSV read error {fp}: {e}")

    if not frames:
        _CSV_CACHE[cache_key] = pd.DataFrame()
        return pd.DataFrame()

    all_df = pd.concat(frames, ignore_index=True).sort_values("open_time").drop_duplicates("open_time")
    all_df = all_df.set_index("open_time")
    _CSV_CACHE[cache_key] = all_df
    return all_df.copy()


def _fetch_ohlcv_csv(symbol: str, interval: str, limit: int = 200, cfg=None) -> pd.DataFrame:
    df = _load_symbol_tf_csv(symbol, interval, cfg)
    if df.empty:
        return df

    current_ts = getattr(cfg, "BACKTEST_CURRENT_TS", None)
    if current_ts is not None:
        ts = pd.Timestamp(current_ts)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        df = df.loc[df.index <= ts]

    if limit and len(df) > limit:
        df = df.tail(limit)
    return df.copy()


def _fetch_ohlcv_api(symbol: str, interval: str, limit: int = 200, cfg=None) -> pd.DataFrame:
    base = _get_base_url(cfg) if cfg else "https://testnet.binancefuture.com"
    url = f"{base}/fapi/v1/klines"
    params = {"symbol": symbol, "interval": _TF_MAP.get(interval, interval), "limit": limit}

    for attempt in range(3):
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            raw = resp.json()

            df = pd.DataFrame(raw, columns=[
                "open_time", "open", "high", "low", "close", "volume",
                "close_time", "quote_vol", "trades", "taker_buy_base",
                "taker_buy_quote", "ignore"
            ])
            for col in ["open", "high", "low", "close", "volume"]:
                df[col] = df[col].astype(float)
            df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
            df.set_index("open_time", inplace=True)
            return df
        except Exception as e:
            if attempt == 2:
                print(f"[DataLoader] ERROR {symbol} {interval}: {e}")
                return pd.DataFrame()
            time.sleep(1)
    return pd.DataFrame()


def fetch_ohlcv(symbol: str, interval: str, limit: int = 200, cfg=None) -> pd.DataFrame:
    if _is_backtest(cfg):
        return _fetch_ohlcv_csv(symbol, interval, limit, cfg)
    return _fetch_ohlcv_api(symbol, interval, limit, cfg)


def fetch_multi_tf(symbol: str, cfg=None) -> dict:
    return {
        "5m": fetch_ohlcv(symbol, "5m", 100, cfg),
        "15m": fetch_ohlcv(symbol, "15m", 200, cfg),
        "30m": fetch_ohlcv(symbol, "30m", 200, cfg),
        "1h": fetch_ohlcv(symbol, "1h", 200, cfg),
        "4h": fetch_ohlcv(symbol, "4h", 200, cfg),
        "1d": fetch_ohlcv(symbol, "1d", 200, cfg),
    }


def fetch_btc_multi_tf(cfg=None) -> dict:
    return {
        "1h": fetch_ohlcv("BTCUSDT", "1h", 200, cfg),
        "4h": fetch_ohlcv("BTCUSDT", "4h", 200, cfg),
        "1d": fetch_ohlcv("BTCUSDT", "1d", 200, cfg),
    }


def get_futures_symbols(cfg=None) -> list:
    if _is_backtest(cfg):
        syms = list(getattr(cfg, "BACKTEST_SYMBOLS", []))
        if "BTCUSDT" not in syms:
            syms.insert(0, "BTCUSDT")
        return syms

    base = _get_base_url(cfg) if cfg else "https://testnet.binancefuture.com"
    try:
        resp = requests.get(f"{base}/fapi/v1/exchangeInfo", timeout=10)
        data = resp.json()
        return [
            s["symbol"] for s in data.get("symbols", [])
            if s["quoteAsset"] == "USDT" and s["status"] == "TRADING" and s["contractType"] == "PERPETUAL"
        ]
    except Exception as e:
        print(f"[DataLoader] get_futures_symbols error: {e}")
        return []
