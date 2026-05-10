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

API_ENDPOINT = "https://gold-newt-367030.hostingersite.com/tera.php?url="

# ==========================================================
# Dummy Flask Server (for Web Service Deployment)
# ==========================================================
web_app = Flask(__name__)

@web_app.route("/")
def home():
    return "🤖 TeraBox Telegram Bot is Running!"

@web_app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "service": "telegram-terabox-bot"
    })

def run_web_server():
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
            c.execute(
                "UPDATE users SET referral_count = referral_count + 1 WHERE user_id=?",
                (referred_by,)
            )
            conn.commit()

            ref_user = get_user(referred_by)
            if ref_user and ref_user[2] % 3 == 0:
                add_premium(referred_by, 7)
                try:
                    await context.bot.send_message(
                        chat_id=referred_by,
                        text="🎉 অভিনন্দন! আপনার ৩টি রেফারেল পূর্ণ হয়েছে। "
                             "আপনি ৭ দিনের Premium পেয়েছেন!"
                    )
                except:
                    pass

            conn.close()

    welcome_text = (
        f"👋 স্বাগতম, {update.effective_user.first_name}!\n\n"
        "আমি TeraBox Downloader Bot.\n"
        "🔸 Free User: দিনে ৫টি লিঙ্ক\n"
        "🔸 Premium User: Unlimited\n\n"
        "রেফারেল লিঙ্ক পেতে /myaccount ব্যবহার করুন।"
    )

    await update.message.reply_text(welcome_text)

async def my_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)

    if not user:
        return await update.message.reply_text("দয়া করে আগে /start দিন।")

    refer_link = f"https://t.me/{context.bot.username}?start={user_id}"

    is_premium = (
        user[3] and datetime.fromisoformat(user[3]) > datetime.now()
    )

    if is_premium:
        prem_date = datetime.fromisoformat(user[3]).strftime('%Y-%m-%d %H:%M')
        status = f"🌟 Premium (পর্যন্ত: {prem_date})"
    else:
        status = "👤 Free User (দিনে ৫টি লিঙ্ক)"

    msg = (
        "📊 আপনার একাউন্ট তথ্য:\n\n"
        f"স্ট্যাটাস: {status}\n"
        f"আজকের ব্যবহার: {user[4]}/5\n"
        f"মোট রেফার: {user[2]} জন\n\n"
        f"🎁 রেফারেল লিঙ্ক:\n{refer_link}\n\n"
        "৩ জন রেফার করলেই ৭ দিনের Premium!"
    )

    await update.message.reply_text(msg)

# ==========================================================
# Main Downloader
# ==========================================================
async def handle_terabox(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    url = update.message.text.strip()

    if "terabox" not in url and "nephobox" not in url:
        return await update.message.reply_text(
            "❌ এটি সঠিক TeraBox লিঙ্ক নয়।"
        )

    user = get_user(user_id)
    if not user:
        add_user(user_id)
        user = get_user(user_id)

    today_str = datetime.now().date().isoformat()
    is_premium = (
        user[3] and datetime.fromisoformat(user[3]) > datetime.now()
    )

    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()

    try:
        # Reset daily limit
        if user[5] != today_str:
            c.execute(
                "UPDATE users SET links_today=0, last_link_date=? WHERE user_id=?",
                (today_str, user_id)
            )
            conn.commit()
            user = get_user(user_id)

        # Limit check
        if not is_premium and user[4] >= 5:
            return await update.message.reply_text(
                "⚠️ আপনার আজকের ৫টি ফ্রি লিঙ্কের লিমিট শেষ!\n\n"
                "Unlimited access পেতে বন্ধুদের রেফার করুন।"
            )

        status_msg = await update.message.reply_text("🔎 প্রসেসিং হচ্ছে...")

        response = requests.get(
            f"{API_ENDPOINT}{url}",
            timeout=15
        ).json()

        if response.get("success"):
            if not is_premium:
                c.execute(
                    "UPDATE users SET links_today = links_today + 1 WHERE user_id=?",
                    (user_id,)
                )
                conn.commit()

            file_data = response["data"][0]

            caption = (
                "✅ ফাইল পাওয়া গেছে!\n\n"
                f"📂 নাম: {file_data['file_name']}\n"
                f"⚖️ সাইজ: {file_data['file_size']}"
            )

            keyboard = [
                [
                    InlineKeyboardButton(
                        "📺 অনলাইন স্ট্রিম",
                        web_app=WebAppInfo(
                            url=file_data["stream_final_url"]
                        )
                    )
                ],
                [
                    InlineKeyboardButton(
                        "📥 ডাউনলোড",
                        url=file_data["download_url"]
                    )
                ]
            ]

            reply_markup = InlineKeyboardMarkup(keyboard)

            await status_msg.delete()
            await update.message.reply_text(
                caption,
                reply_markup=reply_markup
            )
        else:
            await status_msg.edit_text(
                "❌ ফাইল পাওয়া যায়নি বা লিঙ্ক এক্সপায়ার হয়ে গেছে।"
            )

    except Exception as e:
        logging.exception("Error while processing TeraBox link")
        try:
            await status_msg.edit_text(
                "⚠️ সার্ভারে সমস্যা হচ্ছে। পরে চেষ্টা করুন।"
            )
        except:
            pass
    finally:
        conn.close()

# ==========================================================
# Admin Commands
# ==========================================================
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    conn.close()

    await update.message.reply_text(
        f"📈 বট স্ট্যাটাস:\nমোট ইউজার: {total_users} জন"
    )

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    msg_to_send = " ".join(context.args)

    if not msg_to_send:
        return await update.message.reply_text(
            "ব্যবহার: /broadcast আপনার মেসেজ"
        )

    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    users = c.fetchall()
    conn.close()

    success, fail = 0, 0

    await update.message.reply_text("📢 ব্রডকাস্ট শুরু হয়েছে...")

    for user in users:
        try:
            await context.bot.send_message(
                chat_id=user[0],
                text=msg_to_send
            )
            success += 1
        except:
            fail += 1

    await update.message.reply_text(
        f"✅ ব্রডকাস্ট শেষ!\nসফল: {success}\nব্যর্থ: {fail}"
    )

# ==========================================================
# Main Entry Point
# ==========================================================
if __name__ == "__main__":
    init_db()

    if not TOKEN:
        print("❌ Error: TELEGRAM_TOKEN missing!")
        raise SystemExit(1)

    # Start Flask server in background thread
    threading.Thread(
        target=run_web_server,
        daemon=True
    ).start()

    print(f"🌐 Dummy web server running on port {PORT}")

    # Start Telegram bot
    bot = ApplicationBuilder().token(TOKEN).build()

    bot.add_handler(CommandHandler("start", start))
    bot.add_handler(CommandHandler("myaccount", my_account))
    bot.add_handler(CommandHandler("stats", admin_stats))
    bot.add_handler(CommandHandler("broadcast", admin_broadcast))
    bot.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_terabox
        )
    )

    print("✅ Telegram Bot is running...")
    bot.run_polling()
