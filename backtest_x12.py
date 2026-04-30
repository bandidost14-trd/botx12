import os
import pandas as pd

START_BALANCE = 1000.0
TP_PCT = 0.02
SL_PCT = 0.01

DATA_PATH = r"C:\BacktestDownloader\binance_backtest_dataset\extracted_csv"


# =========================
# RSI FUNCTION
# =========================
def compute_rsi(series, period=14):
    delta = series.diff()

    gain = (delta.where(delta > 0, 0)).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()

    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))

    return rsi


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
    print(f"[LOAD] {file_path}")

    df = pd.read_csv(file_path)
    df.columns = [c.lower() for c in df.columns]

    return df


# =========================
# CORE BACKTEST
# =========================
def backtest_symbol(symbol):

    df = load_csv(symbol)
    if df is None:
        print(f"[SKIP] {symbol} data tidak ditemukan")
        return START_BALANCE, 0, 0, 0

    balance = START_BALANCE
    position = None
    entry_price = 0

    wins = 0
    losses = 0
    trades = 0

    # indikator
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

        # =========================
        # FILTER 1: TREND STRENGTH
        # =========================
        trend_strength = abs(ma20 - ma50) / price
        if trend_strength < 0.002:
            continue

        # =========================
        # FILTER 2: ENTRY DISTANCE
        # =========================
        distance = abs(price - ma20) / price
        if distance > 0.0015:
            continue

        # =========================
        # ENTRY
        # =========================
        if position is None:

            if ma20 > ma50 and rsi > 55:
                position = "LONG"
                entry_price = price
                print(f"[ENTRY LONG] {symbol} {price}")

            elif ma20 < ma50 and rsi < 45:
                position = "SHORT"
                entry_price = price
                print(f"[ENTRY SHORT] {symbol} {price}")

        # =========================
        # EXIT LONG
        # =========================
        elif position == "LONG":

            tp = entry_price * (1 + TP_PCT)
            sl = entry_price * (1 - SL_PCT)

            if price >= tp:
                balance *= (1 + TP_PCT)
                wins += 1
                trades += 1
                print(f"[TP LONG] {price} +2%")
                position = None

            elif price <= sl:
                balance *= (1 - SL_PCT)
                losses += 1
                trades += 1
                print(f"[SL LONG] {price} -1%")
                position = None

        # =========================
        # EXIT SHORT
        # =========================
        elif position == "SHORT":

            tp = entry_price * (1 - TP_PCT)
            sl = entry_price * (1 + SL_PCT)

            if price <= tp:
                balance *= (1 + TP_PCT)
                wins += 1
                trades += 1
                print(f"[TP SHORT] {price} +2%")
                position = None

            elif price >= sl:
                balance *= (1 - SL_PCT)
                losses += 1
                trades += 1
                print(f"[SL SHORT] {price} -1%")
                position = None

    return balance, wins, losses, trades


# =========================
# RUN MULTI SYMBOL
# =========================
def run_backtest(symbols):

    total_balance = START_BALANCE
    total_wins = 0
    total_losses = 0
    total_trades = 0

    print(f"\n=== TOTAL SYMBOLS: {len(symbols)} ===\n")

    for symbol in symbols:

        print(f"[RUN] {symbol}")

        balance, wins, losses, trades = backtest_symbol(symbol)

        total_balance = balance
        total_wins += wins
        total_losses += losses
        total_trades += trades

    winrate = (total_wins / total_trades * 100) if total_trades > 0 else 0

    print("\n===== FINAL RESULT =====")
    print(f"Balance : {round(total_balance, 2)}")
    print(f"Winrate : {round(winrate, 2)}%")
    print(f"Trades  : {total_trades}")
    print(f"W/L     : {total_wins}/{total_losses}")


# =========================
# MAIN
# =========================
if __name__ == "__main__":
    symbols = ["UNIUSDT", "AVAXUSDT", "DOGEUSDT"]
    run_backtest(symbols)