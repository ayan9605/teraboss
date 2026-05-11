import os
import logging
import threading
import requests
import sqlite3
from datetime import datetime, timedelta
from flask import Flask, jsonify

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

# ==========================================================
# Logging Setup
# ==========================================================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# ==========================================================
# Environment Variables
# ==========================================================
TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
PORT = int(os.getenv("PORT", "5000"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL") 

API_ENDPOINT = "https://gold-newt-367030.hostingersite.com/tera.php?url="

# ==========================================================
# Dummy Flask Server (Used ONLY in Polling Mode for PaaS)
# ==========================================================
web_app = Flask(__name__)

@web_app.route("/")
def home():
    return "🤖 TeraBox Telegram Bot is Running!"

@web_app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "telegram-terabox-bot"})

def run_web_server():
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    web_app.run(host="0.0.0.0", port=PORT)

# ==========================================================
# Database Setup
# ==========================================================
def init_db():
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            referred_by INTEGER,
            referral_count INTEGER DEFAULT 0,
            premium_until TEXT,
            links_today INTEGER DEFAULT 0,
            last_link_date TEXT
        )
    ''')
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    user = c.fetchone()
    conn.close()
    return user

def add_user(user_id, referred_by=None):
    if not get_user(user_id):
        conn = sqlite3.connect('bot_database.db')
        c = conn.cursor()
        c.execute(
            "INSERT INTO users (user_id, referred_by) VALUES (?, ?)",
            (user_id, referred_by)
        )
        conn.commit()
        conn.close()
        return True
    return False

def add_premium(user_id, days):
    user = get_user(user_id)
    if not user:
        return

    current_premium = user[3]

    if current_premium and datetime.fromisoformat(current_premium) > datetime.now():
        new_date = datetime.fromisoformat(current_premium) + timedelta(days=days)
    else:
        new_date = datetime.now() + timedelta(days=days)

    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute(
        "UPDATE users SET premium_until=? WHERE user_id=?",
        (new_date.isoformat(), user_id)
    )
    conn.commit()
    conn.close()

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

    if add_user(user_id, referred_by):
        if referred_by:
            conn = sqlite3.connect('bot_database.db')
            c = conn.cursor()
            c.execute("UPDATE users SET referral_count = referral_count + 1 WHERE user_id=?", (referred_by,))
            conn.commit()

            ref_user = get_user(referred_by)
            if ref_user and ref_user[2] % 3 == 0:
                add_premium(referred_by, 7)
                try:
                    await context.bot.send_message(
                        chat_id=referred_by,
                        text="🎉 Congratulations! You have completed 3 referrals. You've received 7 days of Premium!"
                    )
                except:
                    pass
            conn.close()

    welcome_text = (
        f"👋 Welcome, {update.effective_user.first_name}!\n\n"
        "I am the TeraBox Downloader Bot.\n"
        "🔸 Free User: 5 links per day\n"
        "🔸 Premium User: Unlimited\n\n"
        "Use /myaccount to get your referral link."
    )
    await update.message.reply_text(welcome_text)

async def my_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)

    if not user:
        return await update.message.reply_text("Please send /start first.")

    refer_link = f"https://t.me/{context.bot.username}?start={user_id}"
    is_premium = user[3] and datetime.fromisoformat(user[3]) > datetime.now()

    if is_premium:
        prem_date = datetime.fromisoformat(user[3]).strftime('%Y-%m-%d %H:%M')
        status = f"🌟 Premium (Until: {prem_date})"
    else:
        status = "👤 Free User (5 links per day)"

    msg = (
        "📊 Your Account Info:\n\n"
        f"Status: {status}\n"
        f"Today's Usage: {user[4]}/5\n"
        f"Total Referrals: {user[2]}\n\n"
        f"🎁 Referral Link:\n{refer_link}\n\n"
        "Refer 3 people to get 7 days of Premium!"
    )
    await update.message.reply_text(msg)

# ==========================================================
# Main Downloader
# ==========================================================
async def handle_terabox(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    url = update.message.text.strip()

    if "terabox" not in url and "nephobox" not in url:
        return await update.message.reply_text("❌ This is not a valid TeraBox link.")

    user = get_user(user_id)
    if not user:
        add_user(user_id)
        user = get_user(user_id)

    today_str = datetime.now().date().isoformat()
    is_premium = user[3] and datetime.fromisoformat(user[3]) > datetime.now()

    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()

    try:
        if user[5] != today_str:
            c.execute("UPDATE users SET links_today=0, last_link_date=? WHERE user_id=?", (today_str, user_id))
            conn.commit()
            user = get_user(user_id)

        if not is_premium and user[4] >= 5:
            return await update.message.reply_text("⚠️ Your daily limit of 5 free links is over!\nRefer friends to get unlimited access.")

        status_msg = await update.message.reply_text("🔎 Processing...")

        response = requests.get(f"{API_ENDPOINT}{url}", timeout=15).json()

        if response.get("success"):
            if not is_premium:
                c.execute("UPDATE users SET links_today = links_today + 1 WHERE user_id=?", (user_id,))
                conn.commit()

            file_data = response["data"][0]
            caption = f"✅ File found!\n\n📂 Name: {file_data['file_name']}\n⚖️ Size: {file_data['file_size']}"

            keyboard = [
                [InlineKeyboardButton("📺 Stream Online", web_app=WebAppInfo(url=file_data["stream_final_url"]))],
                [InlineKeyboardButton("📥 Download", url=file_data["download_url"])]
            ]
            await status_msg.delete()
            await update.message.reply_text(caption, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await status_msg.edit_text("❌ File not found or the link has expired.")

    except Exception:
        logging.exception("Error while processing TeraBox link")
        try:
            await status_msg.edit_text("⚠️ Server is experiencing issues. Please try again later.")
        except:
            pass
    finally:
        conn.close()

# ==========================================================
# Interactive Admin Panel & Commands
# ==========================================================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text("⛔ You are not authorized.")

    keyboard = [
        [InlineKeyboardButton("📊 Bot Statistics", callback_data="admin_stats")],
        [
            InlineKeyboardButton("📢 Broadcast", callback_data="admin_help_broadcast"),
            InlineKeyboardButton("🎁 Add Premium", callback_data="admin_help_premium")
        ],
        [InlineKeyboardButton("❌ Close Panel", callback_data="admin_close")]
    ]
    
    await update.message.reply_text(
        "🛠️ **Admin Control Panel**\n\nSelect an option below:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    # Security check for buttons
    if query.from_user.id != ADMIN_ID:
        return await query.answer("⛔ Unauthorized access.", show_alert=True)

    await query.answer()
    data = query.data

    if data == "admin_stats":
        conn = sqlite3.connect('bot_database.db')
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users")
        total_users = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM users WHERE premium_until > ?", (datetime.now().isoformat(),))
        premium_users = c.fetchone()[0]
        conn.close()

        text = f"📊 **Bot Statistics**\n\n👥 Total Users: {total_users}\n🌟 Active Premium Users: {premium_users}"
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="admin_main")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "admin_help_broadcast":
        text = "📢 **How to Broadcast**\n\nTo send a message to all users, type the following command in chat:\n\n`/broadcast Your message goes here`"
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="admin_main")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "admin_help_premium":
        text = "🎁 **How to Add Premium**\n\nTo give a user premium access manually, type the following command in chat:\n\n`/addpremium <user_id> <days>`\n\n*Example:* `/addpremium 123456789 30`"
        keyboard = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="admin_main")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "admin_main":
        keyboard = [
            [InlineKeyboardButton("📊 Bot Statistics", callback_data="admin_stats")],
            [
                InlineKeyboardButton("📢 Broadcast", callback_data="admin_help_broadcast"),
                InlineKeyboardButton("🎁 Add Premium", callback_data="admin_help_premium")
            ],
            [InlineKeyboardButton("❌ Close Panel", callback_data="admin_close")]
        ]
        await query.edit_message_text("🛠️ **Admin Control Panel**\n\nSelect an option below:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "admin_close":
        await query.message.delete()

async def admin_add_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if len(context.args) != 2:
        return await update.message.reply_text("⚠️ Usage: /addpremium <user_id> <days>")

    try:
        target_user_id = int(context.args[0])
        days = int(context.args[1])
        
        target_user = get_user(target_user_id)
        if not target_user:
            return await update.message.reply_text("❌ User not found in the database. Ask them to send /start first.")

        add_premium(target_user_id, days)
        await update.message.reply_text(f"✅ Successfully added {days} days of premium to user {target_user_id}.")
        
        try:
            await context.bot.send_message(chat_id=target_user_id, text=f"🎉 Congratulations! You have been granted {days} days of Premium access by the Admin!")
        except:
            pass
    except ValueError:
        await update.message.reply_text("❌ Please enter valid numbers for user_id and days.")

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    msg_to_send = " ".join(context.args)
    if not msg_to_send:
        return await update.message.reply_text("Usage: /broadcast your message")

    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    users = c.fetchall()
    conn.close()

    success, fail = 0, 0
    await update.message.reply_text("📢 Broadcast started...")

    for user in users:
        try:
            await context.bot.send_message(chat_id=user[0], text=msg_to_send)
            success += 1
        except:
            fail += 1

    await update.message.reply_text(f"✅ Broadcast finished!\nSuccess: {success}\nFailed: {fail}")

# ==========================================================
# Main Entry Point
# ==========================================================
if __name__ == "__main__":
    init_db()

    if not TOKEN:
        print("❌ Error: TELEGRAM_TOKEN missing!")
        raise SystemExit(1)

    bot = ApplicationBuilder().token(TOKEN).build()

    # User Handlers
    bot.add_handler(CommandHandler("start", start))
    bot.add_handler(CommandHandler("myaccount", my_account))
    
    # Admin Handlers
    bot.add_handler(CommandHandler("admin", admin_panel))
    bot.add_handler(CommandHandler("addpremium", admin_add_premium))
    bot.add_handler(CommandHandler("broadcast", admin_broadcast))
    bot.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_"))

    # Message Handler
    bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_terabox))

    # Dynamic Execution Mode
    if WEBHOOK_URL:
        clean_url = WEBHOOK_URL.rstrip("/")
        print(f"🌐 Running in WEBHOOK mode.\nURL: {clean_url}\nPort: {PORT}")
        bot.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=clean_url
        )
    else:
        print("🔄 Running in POLLING mode.")
        threading.Thread(target=run_web_server, daemon=True).start()
        print(f"🖥️ Dummy Flask web server running on port {PORT}")
        bot.run_polling()
