import time
import logging
import threading
import requests
from datetime import datetime
from flask import Flask, jsonify, request

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

import config
import database as db

# ==========================================================
# Web Server (Handles UPIMate Payment Webhooks)
# ==========================================================
web_app = Flask(__name__)

@web_app.route("/")
def home():
    return "🤖 TeraBox Telegram Bot is Running!"

@web_app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "telegram-terabox-bot"})

@web_app.route("/upimate-webhook", methods=["POST", "GET"])
def upimate_webhook():
    try:
        data = request.json if request.is_json else request.form
        order_id = data.get("order_id")
        status = data.get("status")

        if status in ["success", "True", True] or data.get("result", {}).get("status") == "success":
            order = db.get_order(order_id)
            if order and order[3] != 'success':
                buyer_id, _, days_to_add, _ = order
                db.update_order_status(order_id, 'success')
                db.add_premium(buyer_id, days_to_add)

                msg = f"✅ **Payment Received Automatically!**\n\nThank you! **{days_to_add} Days** of Premium has been instantly added."
                requests.post(f"https://api.telegram.org/bot{config.TOKEN}/sendMessage", json={
                    "chat_id": buyer_id, "text": msg, "parse_mode": "Markdown"
                })
        return jsonify({"status": "received"})
    except Exception as e:
        logging.error(f"Webhook error: {e}")
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
    referred_by = int(args[0]) if args and args[0].isdigit() and int(args[0]) != user_id else None

    if db.add_user(user_id, referred_by) and referred_by:
        ref_count = db.process_referral(referred_by)
        if ref_count % 3 == 0:
            db.add_premium(referred_by, 7)
            try:
                await context.bot.send_message(chat_id=referred_by, text="🎉 3 referrals completed! You received 7 days Premium!")
            except: pass

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
    user = db.get_user(update.effective_user.id)
    if not user: return await update.message.reply_text("Please send /start first.")

    is_premium = user[3] and datetime.fromisoformat(user[3]) > datetime.now()
    status = f"🌟 Premium (Until: {datetime.fromisoformat(user[3]).strftime('%Y-%m-%d %H:%M')})" if is_premium else "👤 Free User (5/day)"

    msg = (
        f"📊 Your Account Info:\n\nStatus: {status}\nToday's Usage: {user[4]}/5\nTotal Referrals: {user[2]}\n\n"
        f"🎁 Referral Link:\nhttps://t.me/{context.bot.username}?start={user[0]}\n\nRefer 3 people for 7 days Premium!"
    )
    await update.message.reply_text(msg)

async def premium_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not config.UPIMATE_TOKEN: return await update.message.reply_text("⚠️ Payments offline. Contact Admin.")
    
    keyboard = [
        [InlineKeyboardButton("🥉 7 Days - ₹9", callback_data="buy_plan_7_9")],
        [InlineKeyboardButton("🥈 15 Days - ₹15", callback_data="buy_plan_15_15")],
        [InlineKeyboardButton("🥇 30 Days - ₹20", callback_data="buy_plan_30_20")]
    ]
    await update.message.reply_text("💎 **Premium Plans**\nSelect a plan to purchase:", reply_markup=InlineKeyboardMarkup(keyboard))

# ==========================================================
# Downloader Logic
# ==========================================================
async def handle_terabox(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    if "terabox" not in url.lower() and "nephobox" not in url.lower(): return 

    user_id = update.effective_user.id
    if not db.get_user(user_id): db.add_user(user_id)
    user = db.get_user(user_id)

    today_str = datetime.now().date().isoformat()
    is_premium = user[3] and datetime.fromisoformat(user[3]) > datetime.now()

    if user[5] != today_str:
        db.reset_daily_links(user_id, today_str)
        user = db.get_user(user_id)

    if not is_premium and user[4] >= 5:
        return await update.message.reply_text("⚠️ Daily limit over! Use /premium or refer friends.")

    status_msg = await update.message.reply_text("🔎 Processing...")

    try:
        response = requests.get(f"{config.API_ENDPOINT}{url}", timeout=15).json()
        if response.get("success"):
            if not is_premium: db.increment_daily_links(user_id)

            file_data = response["data"][0]
            caption = f"✅ File found!\n\n📂 Name: {file_data['file_name']}\n⚖️ Size: {file_data['file_size']}"
            keyboard = [
                [InlineKeyboardButton("📺 Stream Online", web_app=WebAppInfo(url=file_data["stream_final_url"]))],
                [InlineKeyboardButton("📥 Download", url=file_data["download_url"])]
            ]
            
            await status_msg.delete()
            await update.message.reply_text(caption, reply_markup=InlineKeyboardMarkup(keyboard))

            # Send to Dump Channel
            if config.DUMP_CHANNEL_ID:
                try:
                    dump_caption = (f"📤 **New TeraBox**\n👤 {update.effective_user.first_name} (`{user_id}`)\n"
                                    f"📂 {file_data['file_name']}\n🔗 `{url}`")
                    await context.bot.send_message(chat_id=config.DUMP_CHANNEL_ID, text=dump_caption, parse_mode="Markdown")
                except: pass
        else:
            await status_msg.edit_text("❌ File not found or expired.")
    except Exception:
        await status_msg.edit_text("⚠️ Server is experiencing issues.")

# ==========================================================
# Callbacks (Admin + Payments)
# ==========================================================
async def global_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data, user_id = query.data, query.from_user.id

    if data.startswith("admin_"):
        if user_id != config.ADMIN_ID: return await query.answer("⛔ Unauthorized.", show_alert=True)
        await query.answer()

        if data == "admin_stats":
            total, premium = db.get_stats()
            text = f"📊 **Stats**\n👥 Users: {total}\n🌟 Premium: {premium}"
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_main")]]))
        
        elif data == "admin_main":
            keyboard = [
                [InlineKeyboardButton("📊 Stats", callback_data="admin_stats")],
                [InlineKeyboardButton("❌ Close", callback_data="admin_close")]
            ]
            await query.edit_message_text("🛠️ **Admin Panel**", reply_markup=InlineKeyboardMarkup(keyboard))
        
        elif data == "admin_close":
            await query.message.delete()

    elif data.startswith("buy_plan_"):
        await query.answer("Generating payment link...")
        parts = data.split("_")
        days, amount = int(parts[2]), int(parts[3])
        order_id = f"TG{user_id}{int(time.time())}"

        db.create_order(order_id, user_id, amount, days)

        payload = {
            "customer_mobile": "9999999999", "user_token": config.UPIMATE_TOKEN,
            "amount": str(amount), "order_id": order_id,
            "redirect_url": f"https://t.me/{context.bot.username}",
            "remark1": f"User_{user_id}", "remark2": f"{days}_days"
        }
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Content-Type": "application/json"}

        try:
            res = requests.post("https://api.upimate.com/api/create-order", json=payload, headers=headers, timeout=15).json()
            if res.get("status") in [True, "true", "True"]:
                keyboard = [
                    [InlineKeyboardButton("💸 Pay Now", url=res["result"]["payment_url"])],
                    [InlineKeyboardButton("🔄 Check Status", callback_data=f"check_ord_{order_id}")]
                ]
                await query.edit_message_text(f"🧾 **Invoice Created**\nAmount: ₹{amount}\nOrder: `{order_id}`", reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                await query.edit_message_text("❌ Payment API Error.")
        except:
            await query.edit_message_text("❌ Server failed to connect to the gateway.")

    elif data.startswith("check_ord_"):
        await query.answer("Verifying...")
        order_id = data.split("check_ord_")[1]
        order = db.get_order(order_id)

        if not order: return await query.answer("❌ Order not found!", show_alert=True)
        if order[3] == 'success': return await query.answer("✅ Already processed!", show_alert=True)

        try:
            payload = {"user_token": config.UPIMATE_TOKEN, "order_id": order_id}
            headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Content-Type": "application/json"}
            res = requests.post("https://api.upimate.com/api/check-order-status", json=payload, headers=headers, timeout=10).json()

            if res.get("status") in [True, "true", "True"] and res.get("result", {}).get("status") == "success":
                db.update_order_status(order_id, 'success')
                db.add_premium(order[0], order[2])
                await query.edit_message_text(f"✅ **Success!** Added {order[2]} Days Premium.")
            else:
                await query.answer("⏳ Payment pending...", show_alert=True)
        except:
            await query.answer("⚠️ Gateway timeout.", show_alert=True)

# ==========================================================
# Admin Commands
# ==========================================================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.ADMIN_ID: return
    keyboard = [[InlineKeyboardButton("📊 Stats", callback_data="admin_stats")], [InlineKeyboardButton("❌ Close", callback_data="admin_close")]]
    await update.message.reply_text("🛠️ **Admin Panel**", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_add_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.ADMIN_ID: return
    try:
        user_id, days = int(context.args[0]), int(context.args[1])
        db.add_premium(user_id, days)
        await update.message.reply_text(f"✅ Added {days} days to {user_id}.")
    except:
        await update.message.reply_text("❌ Usage: /addpremium <user_id> <days>")

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.ADMIN_ID: return
    msg = " ".join(context.args)
    if not msg: return await update.message.reply_text("Usage: /broadcast <msg>")

    await update.message.reply_text("📢 Broadcasting...")
    success = 0
    for uid in db.get_all_user_ids():
        try:
            await context.bot.send_message(chat_id=uid, text=msg)
            success += 1
        except: pass
    await update.message.reply_text(f"✅ Broadcast finished. Sent to {success} users.")

# ==========================================================
# Main Entry
# ==========================================================
if __name__ == "__main__":
    db.init_db()
    if not config.TOKEN: raise SystemExit("❌ Error: TELEGRAM_TOKEN missing!")

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
        bot.run_webhook(listen="0.0.0.0", port=config.PORT, webhook_url=clean_url)
    else:
        threading.Thread(target=run_web_server, daemon=True).start()
        bot.run_polling()
