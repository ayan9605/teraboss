import os

# Telegram Settings
TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DUMP_CHANNEL_ID = os.getenv("DUMP_CHANNEL_ID") 

# Server Settings
PORT = int(os.getenv("PORT", "5000"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL") 

# PrivzPay Settings (Update this in Render Environment Variables)
PRIVZPAY_TOKEN = os.getenv("PRIVZPAY_TOKEN", "")

# Database Settings
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")

# API Endpoints
API_ENDPOINT = "https://gold-newt-367030.hostingersite.com/tera.php?url="
