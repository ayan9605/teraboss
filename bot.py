import time
import logging
import requests
import asyncio

from datetime import datetime, timedelta

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
)

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

import config
import database as db


# ==========================================================
# Logging Setup
# ==========================================================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

logger = logging.getLogger(__name__)


# ==========================================================
# PrivzPay SDK
# ==========================================================
class OrderStatusSDK:

    def __init__(self, base_url):
        self.base_url = base_url

    async def check_order_status(self, user_token, order_id):

        url = f"{self.base_url}/api/check-order-status"

        payload = {
            "user_token": user_token,
            "order_id": order_id
        }

        try:
            response = requests.post(
                url,
                data=payload,
                timeout=15
            )

            if response.status_code == 200:
                return response.json()

            return {
                "status": "ERROR",
                "message": "API request failed"
            }

        except Exception as e:
            return {
                "status": "ERROR",
                "message": str(e)
            }


payment_sdk = OrderStatusSDK("https://privzpay.com")


# ==========================================================
# FastAPI App
# ==========================================================
app = FastAPI()


# ==========================================================
# Telegram Bot Application
# ==========================================================
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
# Telegram Webhook Route
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

        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


# ==========================================================
# PrivzPay Webhook
# ==========================================================
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

        order_id = data.get("order_id")
        status = data.get("status")

        if not order_id and "result" in data:
            order_id = data["result"].get("orderId")

        if not status and "result" in data:
            status = data["result"].get("status", "")

        status_str = str(status).lower()

        # ======================================================
        # SUCCESS PAYMENT
        # ======================================================
        if status_str in ["success", "true", "1"]:

            order = db.get_order(order_id)

            if not order:
                return JSONResponse(
                    status_code=404,
                    content={"status": "error", "msg": "order not found"}
                )

            if order.get("status") == "success":
                return {"status": "already_done"}

            db.update_order_status(order_id, "success")

            days = order.get("days")
            buyer_id = order.get("user_id")

            db.add_premium(buyer_id, days)

           

            return {"status": "processed"}

        return {"status": "pending"}

    except Exception as e:
        logger.exception("Webhook processing error")

        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


# ==========================================================
# AUTO PAYMENT CHECKER
# ==========================================================
async def auto_check_payment(
    order_id,
    user_id,
    days,
    message,
    context
):

    logger.info(f"Started payment checker: {order_id}")

    expiry_time = datetime.utcnow() + timedelta(minutes=30)

    while datetime.utcnow() < expiry_time:

        try:

            result = await payment_sdk.check_order_status(
                config.PRIVZPAY_TOKEN,
                order_id
            )

            logger.info(f"Payment check result: {result}")

            if (
                result.get("status") == "COMPLETED"
                and result.get("result", {}).get("status") == "SUCCESS"
            ):

                order = db.get_order(order_id)

                if not order:
                    return

                if order.get("status") == "success":
                    return

                db.update_order_status(order_id, "success")

                db.add_premium(user_id, days)

                utr = (
                    result.get("result", {}).get("utr")
                    or "N/A"
                )

                success_text = (
                    f"✅ PAYMENT SUCCESSFUL\n\n"
                    f"💎 Premium Activated\n"
                    f"📅 Duration: {days} Days\n"
                    f"🧾 Order ID: {order_id}\n"
                    f"🏦 UTR: {utr}"
                )

                try:
                    await message.edit_text(success_text)
                except:
                    pass

                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=success_text
                    )
                except:
                    pass

                logger.info(f"Payment success: {order_id}")

                return

            await asyncio.sleep(10)

        except Exception as e:

            logger.error(
                f"Auto payment checker error: {e}"
            )

            await asyncio.sleep(10)

    try:
        await message.edit_text(
            "⌛ Payment link expired.\n\n"
            "Please generate a new payment link."
        )
    except:
        pass

    logger.info(f"Payment expired: {order_id}")


# ==========================================================
# User Commands
# ==========================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id
    args = context.args

    referred_by = None

    if args and args[0].isdigit():
        ref_id = int(args[0])

        if ref_id != user_id:
            referred_by = ref_id

    if db.add_user(user_id, referred_by):

        if referred_by and db.check_referral_reward(referred_by):

            db.add_premium(referred_by, 7)

            try:
                await context.bot.send_message(
                    chat_id=referred_by,
                    text=(
                        "🎉 Congratulations!\n"
                        "You completed 3 referrals.\n"
                        "7 days premium added!"
                    )
                )
            except:
                pass

    welcome_text = (
        f"👋 Welcome, {update.effective_user.first_name}!\n\n"
        "I am the TeraBox Downloader Bot.\n"
        "🔸 Free User: 5 links per day\n"
        "🔸 Premium User: Unlimited\n\n"
        "🔗 Send me a TeraBox link.\n"
        "🎁 Use /myaccount for referrals.\n"
        "💎 Use /premium for plans."
    )

    await update.message.reply_text(welcome_text)


# ==========================================================
# My Account
# ==========================================================
async def my_account(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    user = db.get_user(user_id)

    if not user:
        return await update.message.reply_text(
            "Please send /start first."
        )

    refer_link = (
        f"https://t.me/{context.bot.username}?start={user_id}"
    )

    is_prem = db.is_premium(user_id)

    if is_prem:
        prem_date = user["premium_until"].strftime(
            "%Y-%m-%d %H:%M"
        )

        status = f"🌟 Premium (Until: {prem_date})"

    else:
        status = "👤 Free User (5 links/day)"

    msg = (
        "📊 Your Account Info\n\n"
        f"Status: {status}\n"
        f"Today's Usage: {user.get('links_today', 0)}/5\n"
        f"Referrals: {user.get('referral_count', 0)}\n\n"
        f"🎁 Referral Link:\n{refer_link}"
    )

    await update.message.reply_text(msg)


# ==========================================================
# Premium Menu
# ==========================================================
async def premium_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not config.PRIVZPAY_TOKEN:
        return await update.message.reply_text(
            "⚠️ Payments are offline."
        )

    text = (
        "💎 Premium Plans\n\n"
        "Choose your plan:"
    )

    keyboard = [
        [
            InlineKeyboardButton(
                "🥉 7 Days - ₹9",
                callback_data="buy_plan_7_9"
            )
        ],
        [
            InlineKeyboardButton(
                "🥈 15 Days - ₹15",
                callback_data="buy_plan_15_15"
            )
        ],
        [
            InlineKeyboardButton(
                "🥇 30 Days - ₹20",
                callback_data="buy_plan_30_20"
            )
        ]
    ]

    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ==========================================================
# TeraBox Handler
# ==========================================================
async def handle_terabox(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    url = update.message.text.strip().lower()

    if "terabox" not in url and "nephobox" not in url:
        return

    db.add_user(user_id)

    is_prem = db.is_premium(user_id)

    if not db.handle_daily_limits(user_id, is_prem):

        return await update.message.reply_text(
            "⚠️ Daily limit reached.\nUse /premium."
        )

    status_msg = await update.message.reply_text(
        "🔎 Processing..."
    )

    original_url = update.message.text.strip()

    try:
        response = requests.get(
            f"{config.API_ENDPOINT}{original_url}",
            timeout=15
        ).json()

        if response.get("success"):

            file_data = response["data"][0]

            caption = (
                f"✅ File Found\n\n"
                f"📂 {file_data['file_name']}\n"
                f"⚖️ {file_data['file_size']}"
            )

            keyboard = [
                [
                    InlineKeyboardButton(
                        "📺 Stream",
                        web_app=WebAppInfo(
                            url=file_data["stream_final_url"]
                        )
                    )
                ],
                [
                    InlineKeyboardButton(
                        "📥 Download",
                        url=file_data["download_url"]
                    )
                ]
            ]

            await status_msg.delete()

            await update.message.reply_text(
                caption,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        else:
            await status_msg.edit_text(
                "❌ File not found."
            )

    except Exception:
        logger.exception("TeraBox error")

        await status_msg.edit_text(
            "⚠️ Server error."
        )


# ==========================================================
# Callback Handler
# ==========================================================
async def global_callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query
    data = query.data
    user_id = query.from_user.id

    # ======================================================
    # BUY PLAN
    # ======================================================
    if data.startswith("buy_plan_"):

        await query.answer("Creating payment...")

        parts = data.split("_")

        days = int(parts[2])
        amount = int(parts[3])

        order_id = f"TG{user_id}{int(time.time())}"

        db.create_order(order_id, user_id, amount, days)

        payload = {
            "customer_mobile": "9999999999",
            "user_token": config.PRIVZPAY_TOKEN,
            "amount": str(amount),
            "order_id": order_id,
            "redirect_url": f"https://t.me/{context.bot.username}",
            "remark1": f"User_{user_id}",
            "remark2": f"{days}_days_premium"
        }

        try:
            raw_response = requests.post(
                "https://privzpay.com/api/create-order",
                data=payload,
                timeout=15
            )

            res = raw_response.json()

            if res.get("status") in [
                True,
                "true",
                "success",
                1
            ]:

                payment_url = (
                    res.get("result", {}).get("payment_url")
                    or res.get("payment_url")
                )

                keyboard = [
                    [
                        InlineKeyboardButton(
                            "💸 Pay Now",
                            url=payment_url
                        )
                    ]
                ]

                text = (
                    f"🧾 Invoice Created\n\n"
                    f"Plan: {days} Days\n"
                    f"Amount: ₹{amount}\n"
                    f"Order ID: {order_id}\n\n"
                    f"⏳ Waiting for payment confirmation..."
                )

                payment_message = await query.edit_message_text(
                    text,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )

                asyncio.create_task(
                    auto_check_payment(
                        order_id=order_id,
                        user_id=user_id,
                        days=days,
                        message=payment_message,
                        context=context
                    )
                )

            else:
                await query.edit_message_text(
                    "❌ Payment API Error"
                )

        except Exception as e:
            logger.error(f"Payment error: {e}")

            await query.edit_message_text(
                "❌ Payment server error."
            )


# ==========================================================
# Admin Panel
# ==========================================================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != config.ADMIN_ID:
        return

    await update.message.reply_text(
        "🛠️ Admin Panel"
    )


# ==========================================================
# Add Premium
# ==========================================================
async def admin_add_premium(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_user.id != config.ADMIN_ID:
        return

    if len(context.args) != 2:

        return await update.message.reply_text(
            "Usage: /addpremium user_id days"
        )

    try:
        target_id = int(context.args[0])
        days = int(context.args[1])

        db.add_premium(target_id, days)

        await update.message.reply_text(
            f"✅ Added {days} days."
        )

    except:
        await update.message.reply_text(
            "❌ Invalid input."
        )


# ==========================================================
# Broadcast
# ==========================================================
async def admin_broadcast(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_user.id != config.ADMIN_ID:
        return

    msg = " ".join(context.args)

    users = db.get_all_users()

    success = 0
    fail = 0

    for user in users:

        try:
            await context.bot.send_message(
                chat_id=user["user_id"],
                text=msg
            )

            success += 1

        except:
            fail += 1

    await update.message.reply_text(
        f"✅ Broadcast Done\nSuccess: {success}\nFailed: {fail}"
    )


# ==========================================================
# Register Handlers
# ==========================================================
bot.add_handler(CommandHandler("start", start))
bot.add_handler(CommandHandler("myaccount", my_account))
bot.add_handler(CommandHandler("premium", premium_menu))

bot.add_handler(CommandHandler("admin", admin_panel))
bot.add_handler(CommandHandler("addpremium", admin_add_premium))
bot.add_handler(CommandHandler("broadcast", admin_broadcast))

bot.add_handler(CallbackQueryHandler(global_callback_handler))

bot.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_terabox
    )
)


# ==========================================================
# Startup Event
# ==========================================================
@app.on_event("startup")
async def startup():

    logger.info("🚀 Starting bot...")

    await bot.initialize()
    await bot.start()

    webhook_url = (
        f"{config.WEBHOOK_URL}/telegram-webhook"
    )

    await bot.bot.set_webhook(webhook_url)

    logger.info(f"✅ Webhook set: {webhook_url}")


# ==========================================================
# Shutdown Event
# ==========================================================
@app.on_event("shutdown")
async def shutdown():

    logger.info("🛑 Shutting down bot...")

    await bot.stop()
    await bot.shutdown()