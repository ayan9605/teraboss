import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

import config
import database as db
import handlers  # Your new handlers file

# ==========================================================
# Logging Setup
# ==========================================================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==========================================================
# Application Init
# ==========================================================
app = FastAPI()

# FIX: Renamed 'bot' to 'application' to match the handler registrations below
application = ApplicationBuilder().token(config.TOKEN).build()

# ==========================================================
# Basic Routes
# ==========================================================
@app.get("/")
async def home():
    return {"message": "🤖 TeraBox Telegram Bot is Running!"}

@app.get("/health")
async def health():
    return {"status": "ok", "service": "telegram-terabox-bot"}

# ==========================================================
# Webhook Routes
# ==========================================================
@app.post("/telegram-webhook")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        # Updated to use 'application'
        update = Update.de_json(data, application.bot)
        await application.process_update(update)
        return {"ok": True}
    except Exception as e:
        logger.exception("Telegram webhook error")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/privzpay-webhook")
@app.get("/privzpay-webhook")
async def privzpay_webhook(request: Request):
    try:
        logger.info("=== Payment webhook received ===")
        try:
            data = await request.json()
        except:
            form = await request.form()
            data = dict(form)

        logger.info(f"Webhook Data: {data}")
        order_id = data.get("order_id") or data.get("result", {}).get("orderId")
        status = data.get("status") or data.get("result", {}).get("status", "")

        if str(status).lower() in ["success", "true", "1"]:
            order = db.get_order(order_id)
            if not order:
                return JSONResponse(status_code=404, content={"status": "error", "msg": "order not found"})
            if order.get("status") == "success":
                return {"status": "already_done"}

            db.update_order_status(order_id, "success")
            db.add_premium(order.get("user_id"), order.get("days"))
            return {"status": "processed"}

        return {"status": "pending"}
    except Exception as e:
        logger.exception("Webhook processing error")
        return JSONResponse(status_code=500, content={"error": str(e)})

# ==========================================================
# Register Handlers
# ==========================================================
application.add_handler(CommandHandler("start", handlers.start))
application.add_handler(CommandHandler("myaccount", handlers.my_account))
application.add_handler(CommandHandler("premium", handlers.premium_menu))

# Admin commands
application.add_handler(CommandHandler("admin", handlers.admin_panel))
application.add_handler(CommandHandler("addpremium", handlers.admin_add_premium))
application.add_handler(CommandHandler("broadcast", handlers.admin_broadcast))
application.add_handler(CommandHandler("userinfo", handlers.admin_user_info)) # <-- New command added!

# Callback queries (inline buttons) and general text (links)
application.add_handler(CallbackQueryHandler(handlers.global_callback_handler))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_terabox))

# ==========================================================
# FastAPI Lifecycle Events
# ==========================================================
@app.on_event("startup")
async def startup():
    logger.info("🚀 Starting bot...")
    # Updated to use 'application'
    await application.initialize()
    await application.start()
    webhook_url = f"{config.WEBHOOK_URL}/telegram-webhook"
    await application.bot.set_webhook(webhook_url)
    logger.info(f"✅ Webhook set: {webhook_url}")

@app.on_event("shutdown")
async def shutdown():
    logger.info("🛑 Shutting down bot...")
    # Updated to use 'application'
    await application.stop()
    await application.shutdown()
