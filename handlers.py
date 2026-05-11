import time
import logging
import requests
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ContextTypes

import config
import database as db
from payments import auto_check_payment

logger = logging.getLogger(__name__)

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
                    text="🎉 Congratulations!\nYou completed 3 referrals.\n7 days premium added!"
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

async def my_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = db.get_user(user_id)

    if not user:
        return await update.message.reply_text("Please send /start first.")

    refer_link = f"https://t.me/{context.bot.username}?start={user_id}"
    is_prem = db.is_premium(user_id)

    if is_prem:
        prem_date = user["premium_until"].strftime("%Y-%m-%d %H:%M")
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

async def premium_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not config.PRIVZPAY_TOKEN:
        return await update.message.reply_text("⚠️ Payments are offline.")

    keyboard = [
        [InlineKeyboardButton("🥉 7 Days - ₹10", callback_data="buy_plan_7_10")],
        [InlineKeyboardButton("🥈 15 Days - ₹15", callback_data="buy_plan_15_15")],
        [InlineKeyboardButton("🥇 30 Days - ₹25", callback_data="buy_plan_30_25")]
    ]
    await update.message.reply_text("💎 Premium Plans\n\nChoose your plan:", reply_markup=InlineKeyboardMarkup(keyboard))

# ==========================================================
# TeraBox Handler
# ==========================================================
async def handle_terabox(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    url = update.message.text.strip().lower()

    if "terabox" not in url and "nephobox" not in url:
        return

    db.add_user(user_id)
    if not db.handle_daily_limits(user_id, db.is_premium(user_id)):
        return await update.message.reply_text("⚠️ Daily limit reached.\nUse /premium.")

    status_msg = await update.message.reply_text("🔎 Processing...")
    original_url = update.message.text.strip()

    if hasattr(config, 'DUMP_CHANNEL_ID') and config.DUMP_CHANNEL_ID:
        try:
            dump_text = f"📥 New TeraBox Link\n\n👤 User: {update.effective_user.first_name} ({user_id})\n\n🔗 URL:\n{original_url}"
            await context.bot.send_message(chat_id=config.DUMP_CHANNEL_ID, text=dump_text)
        except Exception as e:
            logger.exception(f"Dump channel error: {e}")

    try:
        api_url = "https://gold-newt-367030.hostingersite.com/tera.php"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "en-US,en;q=0.9"
        }
        
        api_response = requests.get(api_url, params={"url": original_url}, headers=headers, timeout=15)

        try:
            response = api_response.json()
        except Exception:
            logger.error(f"Non-JSON API Response: {api_response.status_code} - {api_response.text[:200]}")
            return await status_msg.edit_text("❌ The TeraBox API is currently down or returning a security challenge. Please try again later.")

        if response.get("success"):
            file_data = response["data"][0]
            caption = f"✅ File Found\n\n📂 {file_data['file_name']}\n⚖️ {file_data['file_size']}"
            keyboard = [
                [InlineKeyboardButton("📺 STREAM NOW", web_app=WebAppInfo(url=file_data["stream_final_url"]))],
                [InlineKeyboardButton("🚀 FAST DOWNLOAD", url=file_data["download_url"])]
            ]

            await status_msg.delete()
            thumbnail = file_data.get("thumb") or file_data.get("thumbnail") or file_data.get("image")

            if thumbnail:
                await update.message.reply_photo(photo=thumbnail, caption=caption, reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                await update.message.reply_text(caption, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await status_msg.edit_text("❌ Failed to fetch file details. The link might be invalid.")

    except Exception as e:
        logger.error(f"Error processing Terabox link: {e}")
        await status_msg.edit_text("❌ An unexpected error occurred while processing your link.")

# ==========================================================
# Callback Handler
# ==========================================================
async def global_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id

    if data.startswith("buy_plan_"):
        await query.answer("Creating payment...")
        parts = data.split("_")
        days, amount = int(parts[2]), int(parts[3])
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
            raw_response = requests.post("https://privzpay.com/api/create-order", data=payload, timeout=15)
            res = raw_response.json()

            if res.get("status") in [True, "true", "success", 1]:
                payment_url = res.get("result", {}).get("payment_url") or res.get("payment_url")
                keyboard = [[InlineKeyboardButton("💸 Pay Now", url=payment_url)]]
                text = f"🧾 Invoice Created\n\nPlan: {days} Days\nAmount: ₹{amount}\nOrder ID: {order_id}\n\n⏳ Waiting for payment confirmation..."
                
                payment_message = await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
                asyncio.create_task(auto_check_payment(order_id, user_id, days, payment_message, context))
            else:
                await query.edit_message_text("❌ Payment API Error")
        except Exception as e:
            logger.error(f"Payment error: {e}")
            await query.edit_message_text("❌ Payment server error.")

# ==========================================================
# Admin Panel
# ==========================================================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.ADMIN_ID: return
    await update.message.reply_text("🛠️ Admin Panel")

async def admin_add_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.ADMIN_ID: return
    if len(context.args) != 2: return await update.message.reply_text("Usage: /addpremium user_id days")
    
    try:
        target_id, days = int(context.args[0]), int(context.args[1])
        db.add_premium(target_id, days)
        await update.message.reply_text(f"✅ Added {days} days.")
    except:
        await update.message.reply_text("❌ Invalid input.")

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.ADMIN_ID: return
    msg = " ".join(context.args)
    users = db.get_all_users()
    success, fail = 0, 0

    for user in users:
        try:
            await context.bot.send_message(chat_id=user["user_id"], text=msg)
            success += 1
        except:
            fail += 1
    await update.message.reply_text(f"✅ Broadcast Done\nSuccess: {success}\nFailed: {fail}")
