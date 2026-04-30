import os
import pandas as pd

START_BALANCE = 1000.0
TP_PCT = 0.02
SL_PCT = 0.01

DATA_PATH = r"C:\BacktestDownloader\binance_backtest_dataset\extracted_csv"


# =========================
# RSI
# =========================
def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


# =========================
# LOAD DATA
# =========================
def load_csv(symbol):
    folder = os.path.join(DATA_PATH, symbol, "15m")

    if not os.path.exists(folder):
        return None

    files = [f for f in os.listdir(folder) if f.endswith(".csv")]
    if not files:
        return None

    file_path = os.path.join(folder, files[0])
    print(f"[LOAD] {symbol}")

    df = pd.read_csv(file_path)
    df.columns = [c.lower() for c in df.columns]

    return df


# =========================
# BACKTEST PER COIN
# =========================
def backtest_symbol(symbol):

    df = load_csv(symbol)
    if df is None:
        print(f"[SKIP] {symbol}")
        return None

    balance = START_BALANCE
    position = None
    entry_price = 0

    wins = 0
    losses = 0
    trades = 0

    df["ma20"] = df["close"].rolling(20).mean()
    df["ma50"] = df["close"].rolling(50).mean()
    df["rsi"] = compute_rsi(df["close"], 14)

    for i in range(50, len(df)):
        row = df.iloc[i]

        price = row["close"]
        ma20 = row["ma20"]
        ma50 = row["ma50"]
        rsi = row["rsi"]

        if pd.isna(ma20) or pd.isna(ma50) or pd.isna(rsi):
            continue

        # ===== FILTER TREND =====
        trend = abs(ma20 - ma50) / price
        if trend < 0.002:
            continue

        # ===== FILTER ENTRY =====
        dist = abs(price - ma20) / price
        if dist > 0.0015:
            continue

        # ===== ENTRY =====
        if position is None:

            if ma20 > ma50 and rsi > 55:
                position = "LONG"
                entry_price = price

            elif ma20 < ma50 and rsi < 45:
                position = "SHORT"
                entry_price = price

        # ===== EXIT LONG =====
        elif position == "LONG":

            if price >= entry_price * (1 + TP_PCT):
                balance *= (1 + TP_PCT)
                wins += 1
                trades += 1
                position = None

            elif price <= entry_price * (1 - SL_PCT):
                balance *= (1 - SL_PCT)
                losses += 1
                trades += 1
                position = None

        # ===== EXIT SHORT =====
        elif position == "SHORT":

            if price <= entry_price * (1 - TP_PCT):
                balance *= (1 + TP_PCT)
                wins += 1
                trades += 1
                position = None

            elif price >= entry_price * (1 + SL_PCT):
                balance *= (1 - SL_PCT)
                losses += 1
                trades += 1
                position = None

    if trades == 0:
        winrate = 0
    else:
        winrate = (wins / trades) * 100

    return {
        "symbol": symbol,
        "balance": round(balance, 2),
        "profit_pct": round((balance - START_BALANCE) / START_BALANCE * 100, 2),
        "trades": trades,
        "winrate": round(winrate, 2),
        "wins": wins,
        "losses": losses
    }


# =========================
# MULTI COIN RUN
# =========================
def run_multi():

    symbols = [
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "AVAXUSDT",
        "DOGEUSDT",
        "BNBUSDT",
        "LINKUSDT",
        "XRPUSDT"
    ]

    results = []

    print("\n=== MULTI COIN BACKTEST ===\n")

    for s in symbols:
        print(f"[RUN] {s}")
        res = backtest_symbol(s)

        if res:
            results.append(res)

    # =========================
    # SORT RANKING
    # =========================
    results = sorted(results, key=lambda x: x["profit_pct"], reverse=True)

    print("\n===== RANKING =====\n")

    for r in results:
        print(f"{r['symbol']} | Profit: {r['profit_pct']}% | WR: {r['winrate']}% | Trades: {r['trades']}")

    # =========================
    # SUMMARY
    # =========================
    avg_profit = sum(r["profit_pct"] for r in results) / len(results)
    avg_wr = sum(r["winrate"] for r in results) / len(results)

    print("\n===== SUMMARY =====")
    print(f"Avg Profit : {round(avg_profit,2)}%")
    print(f"Avg WR     : {round(avg_wr,2)}%")
    print(f"Coins Test : {len(results)}")


# =========================
# MAIN
# =========================
if __name__ == "__main__":
    run_multi()