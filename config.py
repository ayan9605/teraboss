import os
import logging

# Logging Setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Environment Variables
TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
PORT = int(os.getenv("PORT", "5000"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
UPIMATE_TOKEN = os.getenv("UPIMATE_TOKEN", "")
DUMP_CHANNEL_ID = os.getenv("DUMP_CHANNEL_ID")

# APIs
API_ENDPOINT = "https://gold-newt-367030.hostingersite.com/tera.php?url="
