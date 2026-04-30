import ccxt
import os

class PositionManager:

    def __init__(self):
        api_key = os.getenv("BINANCE_API_KEY")
        api_secret = os.getenv("BINANCE_API_SECRET")

        if not api_key or not api_secret:
            raise Exception("API KEY / SECRET tidak terbaca")

        self.exchange = ccxt.binance({
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            "options": {
                "defaultType": "future"
            },
            "urls": {
                "api": {
                    "public": "https://demo-fapi.binance.com/fapi/v1",
                    "private": "https://demo-fapi.binance.com/fapi/v1"
                }
            }
        })