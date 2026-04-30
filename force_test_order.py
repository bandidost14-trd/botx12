import os
from position_manager_x12 import PositionManager

def main():
    print("[TEST] Starting force order...")

    if os.getenv("FORCE_TRADE_CONFIRM") != "YES":
        raise Exception("Set FORCE_TRADE_CONFIRM=YES dulu")

    symbol = os.getenv("FORCE_SYMBOL", "BTC/USDT")
    direction = os.getenv("FORCE_DIRECTION", "LONG")
    notional = float(os.getenv("FORCE_NOTIONAL_USDT", "20"))

    side = "buy" if direction == "LONG" else "sell"

    pm = PositionManager()
    pm.validate_connection()

    pm.open_position(symbol, side, notional)


if __name__ == "__main__":
    main()