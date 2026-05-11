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
bot = ApplicationBuilder().token(config.TOKEN).build()

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
        update = Update.de_json(data, bot.bot)
        await bot.process_update(update)
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
bot.add_handler(CommandHandler("start", handlers.start))
bot.add_handler(CommandHandler("myaccount", handlers.my_account))
bot.add_handler(CommandHandler("premium", handlers.premium_menu))
bot.add_handler(CommandHandler("admin", handlers.admin_panel))
bot.add_handler(CommandHandler("addpremium", handlers.admin_add_premium))
bot.add_handler(CommandHandler("broadcast", handlers.admin_broadcast))
bot.add_handler(CallbackQueryHandler(handlers.global_callback_handler))
bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_terabox))

# ==========================================================
# FastAPI Lifecycle Events
# ==========================================================
@app.on_event("startup")
async def startup():
    logger.info("🚀 Starting bot...")
    await bot.initialize()
    await bot.start()
    webhook_url = f"{config.WEBHOOK_URL}/telegram-webhook"
    await bot.bot.set_webhook(webhook_url)
    logger.info(f"✅ Webhook set: {webhook_url}")

@app.on_event("shutdown")
async def shutdown():
    logger.info("🛑 Shutting down bot...")
    await bot.stop()
    await bot.shutdown()
