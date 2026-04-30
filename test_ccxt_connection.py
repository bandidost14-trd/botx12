import os

import ccxt
from dotenv import load_dotenv


load_dotenv()


def _env(name: str, fallback: str = "") -> str:
    return os.getenv(name) or os.getenv(fallback) or ""


exchange = ccxt.binance({
    "apiKey": _env("BINANCE_TESTNET_API_KEY", "BINANCE_API_KEY"),
    "secret": _env("BINANCE_TESTNET_SECRET_KEY", "BINANCE_API_SECRET"),
    "enableRateLimit": True,
    "options": {
        "defaultType": "future",
        "adjustForTimeDifference": True,
    },
})

exchange.set_sandbox_mode(True)
exchange.verbose = True


def test_connection():
    try:
        print("\n1. Test public API...")
        print("Server time:", exchange.fetch_time())

        print("\n2. Test private API (balance)...")
        balance = exchange.fetch_balance()
        usdt = balance.get("USDT", {})
        print("Balance USDT:", usdt.get("total", 0))

        print("\n3. Test positions...")
        positions = exchange.fetch_positions(["BTCUSDT"])
        print("Positions:", len(positions))

    except Exception as e:
        print("ERROR:", str(e))


if __name__ == "__main__":
    test_connection()
