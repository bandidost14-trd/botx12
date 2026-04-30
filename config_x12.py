# ==============================
# CONFIG X12 PRO FINAL (CCXT CLEAN)
# ==============================

import os

BOT_NAME = "BotX12.2 Pro"
BOT_VERSION = "FINAL_CCXT"

# ===== AUTH =====
API_KEY = os.getenv("HrU3xF4fG3gcZn92x7vxCZlVcR6jlb9WSON6acvrnJ8PGuuV3LPxc1YNKrjYYlHN", "")
API_SECRET = os.getenv("yrBwJSfEY4KiLBnXh8Xou8HCSlxVb5XF4coEZWMcZubzSzUOJXj6iLW1ZRvxgobR", "")

TELEGRAM_TOKEN = os.getenv("8657018807:AAGi88NhwUUvrRzKfKohsC7faZdycGboC2s", "")
TELEGRAM_CHAT_ID = os.getenv("5487520303", "")

# ===== MODE =====
TESTNET = True   # WAJIB TRUE untuk sandbox

# ===== TRADING =====
DEFAULT_SYMBOL = "BTC/USDT"
DEFAULT_LEVERAGE = 3
DEFAULT_RISK_USDT = 20

# ===== SAFETY =====
MAX_POSITIONS = 2
MAX_TRADES_PER_DAY = 5