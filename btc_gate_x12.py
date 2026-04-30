from dataclasses import dataclass


@dataclass
class BTCGateResult:
    mode: str = "NEUTRAL"
    bias: str = "NEUTRAL"
    score: float = 0.5
    score_1h: float = 0.5
    score_4h: float = 0.5
    score_1d: float = 0.5
    wave_b_block: bool = False


_cache = {"result": BTCGateResult()}


class BTCGate:
    def __init__(self, cfg):
        self.cfg = cfg
        self.mode = "NEUTRAL"
        self.score = 0.5

    def update(self):
        # simulasi BTC trend
        import random
        self.score = random.uniform(0.3, 0.7)

        if self.score > 0.6:
            self.mode = "BULL"
        elif self.score < 0.4:
            self.mode = "BEAR"
        else:
            self.mode = "SIDEWAYS"
        bias = "BULLISH" if self.mode == "BULL" else "BEARISH" if self.mode == "BEAR" else "NEUTRAL"
        _cache["result"] = BTCGateResult(
            mode=self.mode,
            bias=bias,
            score=self.score,
            score_1h=self.score,
            score_4h=self.score,
            score_1d=self.score,
            wave_b_block=False,
        )

    def allow_long(self):
        return self.mode in ["BULL", "SIDEWAYS"]

    def allow_short(self):
        return self.mode in ["BEAR", "SIDEWAYS"]

    def summary(self):
        return f"{self.mode} | score={self.score:.2f}"
