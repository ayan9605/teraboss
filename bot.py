import time
import logging
import threading
import requests
from flask import Flask, jsonify, request

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
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# ==========================================================
# Web Server (Handles PrivzPay Payment Webhooks)
# ==========================================================
web_app = Flask(__name__)

@web_app.route("/")
def home():
    return "🤖 TeraBox Telegram Bot is Running!"

@web_app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "telegram-terabox-bot"})

# 🚀 NEW: PrivzPay Webhook Route
@web_app.route("/privzpay-webhook", methods=["POST", "GET"])
def privzpay_webhook():
    try:
        # Accept both JSON and Form Data formats
        data = request.json if request.is_json else request.form
        order_id = data.get("order_id")
        status = data.get("status")

        if status in ["success", "True", True] or data.get("result", {}).get("status") == "success":
            order = db.get_order(order_id)
            
            if order and order.get("status") != 'success':
                db.update_order_status(order_id, 'success')
                days_to_add = order.get("days")
                buyer_id = order.get("user_id")
                
                db.add_premium(buyer_id, days_to_add)

                msg = f"✅ **Payment Received Automatically!**\n\nThank you! **{days_to_add} Days** of Premium has been instantly added to your account."
                requests.post(f"https://api.telegram.org/bot{config.TOKEN}/sendMessage", json={
                    "chat_id": buyer_id,
                    "text": msg,
                    "parse_mode": "Markdown"
                })
        return jsonify({"status": "received"})
    except Exception as e:
        logging.error(f"Webhook processing error: {e}")
        return jsonify({"status": "error"}), 500

def run_web_server():
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    web_app.run(host="0.0.0.0", port=config.PORT)

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
                    text="🎉 Congratulations! You have completed 3 referrals. You've received 7 days of Premium!"
                )
            except:
                pass

    welcome_text = (
        f"👋 Welcome, {update.effective_user.first_name}!\n\n"
        "I am the TeraBox Downloader Bot.\n"
        "🔸 Free User: 5 links per day\n"
        "🔸 Premium User: Unlimited\n\n"
        "🔗 Send me a TeraBox link to download.\n"
        "🎁 Use /myaccount for your referral link.\n"
        "💎 Use /premium to view paid plans."
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
        prem_date = user["premium_until"].strftime('%Y-%m-%d %H:%M')
        status = f"🌟 Premium (Until: {prem_date})"
    else:
        status = "👤 Free User (5 links per day)"

    msg = (
        "📊 Your Account Info:\n\n"
        f"Status: {status}\n"
        f"Today's Usage: {user.get('links_today', 0)}/5\n"
        f"Total Referrals: {user.get('referral_count', 0)}\n\n"
        f"🎁 Referral Link:\n{refer_link}\n\n"
        "Refer 3 people to get 7 days of Premium!"
    )
    await update.message.reply_text(msg)

async def premium_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not config.PRIVZPAY_TOKEN:
        return await update.message.reply_text("⚠️ Payments are currently offline. Contact the admin.")

    text = "💎 **Premium Subscription Plans**\n\nUpgrade to Premium to get Unlimited Links and zero limits!\nSelect a plan below to purchase:"
    keyboard = [
        [InlineKeyboardButton("🥉 7 Days Plan - ₹9", callback_data="buy_plan_7_9")],
        [InlineKeyboardButton("🥈 15 Days Plan - ₹15", callback_data="buy_plan_15_15")],
        [InlineKeyboardButton("🥇 30 Days Plan - ₹20", callback_data="buy_plan_30_20")]
    ]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ==========================================================
# Main Downloader
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
            "⚠️ Your daily limit of 5 free links is over!\nUse /premium to buy unlimited access, or refer friends."
        )

    status_msg = await update.message.reply_text("🔎 Processing...")
    original_url = update.message.text.strip()

    try:
        response = requests.get(f"{config.API_ENDPOINT}{original_url}", timeout=15).json()

        if response.get("success"):
            file_data = response["data"][0]
            caption = f"✅ File found!\n\n📂 Name: {file_data['file_name']}\n⚖️ Size: {file_data['file_size']}"

            keyboard = [
                [InlineKeyboardButton("📺 Stream Online", web_app=WebAppInfo(url=file_data["stream_final_url"]))],
                [InlineKeyboardButton("📥 Download", url=file_data["download_url"])]
            ]
            
            await status_msg.delete()
            await update.message.reply_text(caption, reply_markup=InlineKeyboardMarkup(keyboard))

            if config.DUMP_CHANNEL_ID:
                try:
                    dump_caption = (
                        f"📤 **New TeraBox Processed**\n\n"
                        f"👤 **User:** {update.effective_user.first_name} (`{user_id}`)\n"
                        f"📂 **File:** {file_data['file_name']}\n"
                        f"⚖️ **Size:** {file_data['file_size']}\n\n"
                        f"🔗 **Original Link:**\n`{original_url}`"
                    )
                    await context.bot.send_message(
                        chat_id=config.DUMP_CHANNEL_ID,
                        text=dump_caption,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    logging.error(f"Failed to send to Dump Channel: {e}")
        else:
            await status_msg.edit_text("❌ File not found or the link has expired.")

    except Exception:
        logging.exception("Error while processing TeraBox link")
        try:
            await status_msg.edit_text("⚠️ Server is experiencing issues. Please try again later.")
        except:
            pass

# ==========================================================
# Callback Query Handler (Admin Panel + Payments)
# ==========================================================
async def global_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id

    # ---- ADMIN LOGIC ----
    if data.startswith("admin_"):
        if user_id != config.ADMIN_ID:
            return await query.answer("⛔ Unauthorized access.", show_alert=True)
        
        await query.answer()

        if data == "admin_stats":
            total_users, premium_users = db.get_stats()
            text = f"📊 **Bot Statistics**\n\n👥 Total Users: {total_users}\n🌟 Active Premium Users: {premium_users}"
            keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="admin_main")]]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

        elif data == "admin_help_broadcast":
            text = "📢 **How to Broadcast**\n\n`/broadcast Your message goes here`"
            keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="admin_main")]]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

        elif data == "admin_help_premium":
            text = "🎁 **How to Add Premium Manually**\n\n`/addpremium <user_id> <days>`\n*Example:* `/addpremium 123456789 30`"
            keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="admin_main")]]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

        elif data == "admin_main":
            keyboard = [
                [InlineKeyboardButton("📊 Bot Statistics", callback_data="admin_stats")],
                [InlineKeyboardButton("📢 Broadcast", callback_data="admin_help_broadcast"), InlineKeyboardButton("🎁 Add Premium", callback_data="admin_help_premium")],
                [InlineKeyboardButton("❌ Close Panel", callback_data="admin_close")]
            ]
            await query.edit_message_text("🛠️ **Admin Control Panel**\n\nSelect an option below:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

        elif data == "admin_close":
            await query.message.delete()

    # ---- PAYMENT INITIATION LOGIC (PRIVZPAY) ----
    elif data.startswith("buy_plan_"):
        await query.answer("Creating your payment link...", show_alert=False)
        parts = data.split("_")
        days = int(parts[2])
        amount = int(parts[3])
        order_id = f"TG{user_id}{int(time.time())}"

        db.create_order(order_id, user_id, amount, days)

        # Form-Encoded Payload requires data=payload format
        payload = {
            "customer_mobile": "9999999999", 
            "user_token": config.PRIVZPAY_TOKEN,
            "amount": str(amount),
            "order_id": order_id,
            "redirect_url": f"https://t.me/{context.bot.username}",
            "remark1": f"User_{user_id}",
            "remark2": f"{days}_days_premium"
        }

        # Explicitly set x-www-form-urlencoded
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Content-Type": "application/x-www-form-urlencoded"
        }

        try:
            # Using data=payload instead of json=payload ensures it sends as form-data
            raw_response = requests.post("https://privzpay.com/api/create-order", data=payload, headers=headers, timeout=15)
            
            try:
                res = raw_response.json()
            except ValueError:
                logging.error(f"PrivzPay Create Order Error - Raw Response: {raw_response.text}")
                return await query.edit_message_text("❌ Payment Gateway Error: The server returned an invalid response. Check bot logs.")

            if res.get("status") in [True, "true", "True", "success", 1]:
                payment_url = res.get("result", {}).get("payment_url") or res.get("payment_url") 
                
                if not payment_url:
                    return await query.edit_message_text("❌ Payment API Error: Could not extract payment URL.")

                keyboard = [
                    [InlineKeyboardButton("💸 Pay Now", url=payment_url)],
                    [InlineKeyboardButton("🔄 Check Payment Status", callback_data=f"check_ord_{order_id}")]
                ]
                text = f"🧾 **Invoice Created**\n\n**Plan:** {days} Days Premium\n**Amount:** ₹{amount}\n**Order ID:** `{order_id}`\n\n⚠️ *This link will expire in 30 minutes.*\nThe system will automatically grant premium when paid, or click **Check Payment Status** manually."
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            else:
                await query.edit_message_text(f"❌ Payment API Error: {res.get('message', 'Unknown Error')}")
        except Exception as e:
            logging.error(f"Error creating order: {e}")
            await query.edit_message_text("❌ Server failed to connect to the payment gateway.")

    # ---- PAYMENT VERIFICATION LOGIC (Manual Fallback) ----
    elif data.startswith("check_ord_"):
        await query.answer("Verifying payment...", show_alert=False)
        order_id = data.split("check_ord_")[1]

        order = db.get_order(order_id)
        if not order:
            return await query.answer("❌ Order not found in database!", show_alert=True)
        
        if order.get("status") == 'success':
            return await query.answer("✅ This payment has already been processed!", show_alert=True)

        payload = {"user_token": config.PRIVZPAY_TOKEN, "order_id": order_id}
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Content-Type": "application/x-www-form-urlencoded"
        }

        try:
            # Assumed Check Order API URL based on standard PG formatting
            raw_response = requests.post("https://privzpay.com/api/check-order-status", data=payload, headers=headers, timeout=10)
            try:
                res = raw_response.json()
            except ValueError:
                return await query.answer("❌ Payment Gateway returned an invalid response.", show_alert=True)

            if res.get("status") in [True, "true", "True"] and res.get("result", {}).get("status") == "success":
                db.update_order_status(order_id, 'success')
                days_to_add = order.get("days")
                buyer_id = order.get("user_id")
                db.add_premium(buyer_id, days_to_add)
                await query.edit_message_text(f"✅ **Payment Successful!**\n\n**{days_to_add} Days** of Premium has been added to your account.")
            else:
                await query.answer("⏳ Payment pending or not found. Wait 30 seconds and click again.", show_alert=True)
        except Exception as e:
            logging.error(f"Error checking order: {e}")
            await query.answer("⚠️ Could not reach the payment gateway.", show_alert=True)

# ==========================================================
# Admin Slash Commands
# ==========================================================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.ADMIN_ID:
        return await update.message.reply_text("⛔ You are not authorized.")

    keyboard = [
        [InlineKeyboardButton("📊 Bot Statistics", callback_data="admin_stats")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_help_broadcast"), InlineKeyboardButton("🎁 Add Premium", callback_data="admin_help_premium")],
        [InlineKeyboardButton("❌ Close Panel", callback_data="admin_close")]
    ]
    await update.message.reply_text("🛠️ **Admin Control Panel**\n\nSelect an option below:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def admin_add_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.ADMIN_ID:
        return
    if len(context.args) != 2:
        return await update.message.reply_text("⚠️ Usage: /addpremium <user_id> <days>")

    try:
        target_id = int(context.args[0])
        days = int(context.args[1])
        if not db.get_user(target_id):
            return await update.message.reply_text("❌ User not found.")
        
        db.add_premium(target_id, days)
        await update.message.reply_text(f"✅ Added {days} days of premium to user {target_id}.")
        try:
            await context.bot.send_message(chat_id=target_id, text=f"🎉 Congratulations! You have been granted {days} days of Premium access by the Admin!")
        except:
            pass
    except ValueError:
        await update.message.reply_text("❌ Please enter valid numbers.")

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.ADMIN_ID:
        return
    msg_to_send = " ".join(context.args)
    if not msg_to_send:
        return await update.message.reply_text("Usage: /broadcast your message")

    users = db.get_all_users()
    success, fail = 0, 0
    await update.message.reply_text("📢 Broadcast started...")

    for user in users:
        try:
            await context.bot.send_message(chat_id=user["user_id"], text=msg_to_send)
            success += 1
        except:
            fail += 1

    await update.message.reply_text(f"✅ Broadcast finished!\nSuccess: {success}\nFailed: {fail}")

# ==========================================================
# Main Entry Point
# ==========================================================
if __name__ == "__main__":
    print("🚀 --- MODULAR MONGO BOT IS STARTING --- 🚀", flush=True)

    if not config.TOKEN:
        print("❌ Error: TELEGRAM_TOKEN missing!", flush=True)
        raise SystemExit(1)

    bot = ApplicationBuilder().token(config.TOKEN).build()

    bot.add_handler(CommandHandler("start", start))
    bot.add_handler(CommandHandler("myaccount", my_account))
    bot.add_handler(CommandHandler("premium", premium_menu)) 
    bot.add_handler(CommandHandler("admin", admin_panel))
    bot.add_handler(CommandHandler("addpremium", admin_add_premium))
    bot.add_handler(CommandHandler("broadcast", admin_broadcast))
    bot.add_handler(CallbackQueryHandler(global_callback_handler))
    bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_terabox))

    if config.WEBHOOK_URL:
        clean_url = config.WEBHOOK_URL.rstrip("/")
        print(f"🌐 Running in WEBHOOK mode.\nURL: {clean_url}\nPort: {config.PORT}", flush=True)
        bot.run_webhook(listen="0.0.0.0", port=config.PORT, webhook_url=clean_url)
    else:
        print("🔄 Running in POLLING mode. Web Server handles PrivzPay Webhooks.", flush=True)
        threading.Thread(target=run_web_server, daemon=True).start()
        print(f"🖥️ Flask web server listening for payments on port {config.PORT}", flush=True)
        bot.run_polling()
