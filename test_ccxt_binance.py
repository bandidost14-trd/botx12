import os
import ccxt
from dotenv import load_dotenv

# ==============================
# LOAD ENV
# ==============================
load_dotenv()

API_KEY = os.getenv("BINANCE_TESTNET_API_KEY")
API_SECRET = os.getenv("BINANCE_TESTNET_SECRET_KEY")

if not API_KEY or not API_SECRET:
    raise Exception("❌ API KEY / SECRET belum diset di .env")

# ==============================
# SETUP EXCHANGE (FINAL)
# ==============================
exchange = ccxt.binance({
    'apiKey': API_KEY,
    'secret': API_SECRET,
    'enableRateLimit': True,
    'options': {
        'defaultType': 'future',  # WAJIB untuk futures
    }
})

# 🔥 KUNCI UTAMA (JANGAN DIHAPUS)
exchange.set_sandbox_mode(True)


# ==============================
# TEST CONNECTION
# ==============================
def test_connection():
    try:
        print("🔍 TEST PUBLIC API...")
        server_time = exchange.fetch_time()
        print(f"✅ Server Time: {server_time}")

        print("\n🔐 TEST PRIVATE API...")
        balance = exchange.fetch_balance()
        usdt = balance['total'].get('USDT', 0)
        print(f"✅ Balance USDT: {usdt}")

        print("\n📊 TEST POSITIONS...")
        positions = exchange.fetch_positions(['BTCUSDT'])
        print(f"✅ Positions found: {len(positions)}")

        print("\n🚀 SEMUA TEST BERHASIL (TESTNET CONNECTED)")

    except Exception as e:
        print("❌ ERROR:", str(e))


# ==============================
# MAIN
# ==============================
if __name__ == "__main__":
    test_connection()