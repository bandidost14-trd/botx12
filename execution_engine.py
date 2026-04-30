import config_x12 as cfg

class ExecutionEngine:

    def __init__(self):
        self.positions = {}

    def execute(self, symbol, direction, price, conf):

        risk_multiplier = conf.get("risk", 1.0)

        position_size = cfg.MODAL_USDT * cfg.LEVERAGE * risk_multiplier

        entry = price
        tp = entry * (1 + cfg.TP_PCT) if direction == "LONG" else entry * (1 - cfg.TP_PCT)
        sl = entry * (1 - cfg.SL_PCT) if direction == "LONG" else entry * (1 + cfg.SL_PCT)

        self.positions[symbol] = {
            "direction": direction,
            "entry": entry,
            "tp": tp,
            "sl": sl,
            "peak": entry
        }

        print(f"[ENTRY] {symbol} {direction} @ {entry}")

    def update(self, symbol, price):

        if symbol not in self.positions:
            return None

        pos = self.positions[symbol]

        # ===== TRAILING LOGIC =====
        if cfg.TRAILING_ENABLE:

            if pos["direction"] == "LONG":
                if price > pos["peak"]:
                    pos["peak"] = price

                profit = (price - pos["entry"]) / pos["entry"]

                if profit > cfg.TRAILING_ACTIVATE:
                    trail_sl = pos["peak"] * (1 - cfg.TRAILING_CALLBACK)
                    if price < trail_sl:
                        return self.close(symbol, price, "TRAILING TP")

            if pos["direction"] == "SHORT":
                if price < pos["peak"]:
                    pos["peak"] = price

                profit = (pos["entry"] - price) / pos["entry"]

                if profit > cfg.TRAILING_ACTIVATE:
                    trail_sl = pos["peak"] * (1 + cfg.TRAILING_CALLBACK)
                    if price > trail_sl:
                        return self.close(symbol, price, "TRAILING TP")

        # ===== NORMAL TP / SL =====
        if pos["direction"] == "LONG":
            if price >= pos["tp"]:
                return self.close(symbol, price, "TP")
            if price <= pos["sl"]:
                return self.close(symbol, price, "SL")

        if pos["direction"] == "SHORT":
            if price <= pos["tp"]:
                return self.close(symbol, price, "TP")
            if price >= pos["sl"]:
                return self.close(symbol, price, "SL")

    def close(self, symbol, price, reason):

        pos = self.positions[symbol]

        pnl = (
            (price - pos["entry"]) / pos["entry"]
            if pos["direction"] == "LONG"
            else (pos["entry"] - price) / pos["entry"]
        )

        print(f"[EXIT] {symbol} {reason} | PnL: {round(pnl*100,2)}%")

        del self.positions[symbol]

        return pnl