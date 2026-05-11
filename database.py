from pymongo import MongoClient, ReturnDocument
from datetime import datetime, timedelta
import config

# Initialize MongoDB Connection
client = MongoClient(config.MONGO_URI)
db = client['terabot_db']
users_col = db['users']
orders_col = db['orders']

def init_db():
    # Instead of creating tables, MongoDB creates collections dynamically.
    # We just create indexes here to make searching super fast!
    users_col.create_index("user_id", unique=True)
    orders_col.create_index("order_id", unique=True)

# --- User Functions ---
def get_user(user_id):
    user = users_col.find_one({"user_id": user_id})
    if not user:
        return None
    # Return as a tuple so bot.py doesn't need to be rewritten
    return (
        user.get("user_id"),
        user.get("referred_by"),
        user.get("referral_count", 0),
        user.get("premium_until"),
        user.get("links_today", 0),
        user.get("last_link_date")
    )

def add_user(user_id, referred_by=None):
    if not users_col.find_one({"user_id": user_id}):
        users_col.insert_one({
            "user_id": user_id,
            "referred_by": referred_by,
            "referral_count": 0,
            "premium_until": None,
            "links_today": 0,
            "last_link_date": None
        })
        return True
    return False

def add_premium(user_id, days):
    user = users_col.find_one({"user_id": user_id})
    if not user: return

    current_premium = user.get("premium_until")
    
    if current_premium and datetime.fromisoformat(current_premium) > datetime.now():
        new_date = datetime.fromisoformat(current_premium) + timedelta(days=days)
    else:
        new_date = datetime.now() + timedelta(days=days)

    users_col.update_one(
        {"user_id": user_id}, 
        {"$set": {"premium_until": new_date.isoformat()}}
    )

def process_referral(referred_by):
    """Increments referral count and returns the new count."""
    updated_user = users_col.find_one_and_update(
        {"user_id": referred_by},
        {"$inc": {"referral_count": 1}},
        return_document=ReturnDocument.AFTER
    )
    return updated_user.get("referral_count", 0) if updated_user else 0

def reset_daily_links(user_id, today_str):
    users_col.update_one(
        {"user_id": user_id},
        {"$set": {"links_today": 0, "last_link_date": today_str}}
    )

def increment_daily_links(user_id):
    users_col.update_one(
        {"user_id": user_id},
        {"$inc": {"links_today": 1}}
    )

# --- Order Functions ---
def create_order(order_id, user_id, amount, days):
    orders_col.insert_one({
        "order_id": order_id,
        "user_id": user_id,
        "amount": amount,
        "days": days,
        "status": "pending"
    })

def get_order(order_id):
    order = orders_col.find_one({"order_id": order_id})
    if not order: 
        return None
    # Return as a tuple so bot.py doesn't need to be rewritten
    return (
        order.get("user_id"),
        order.get("amount"),
        order.get("days"),
        order.get("status")
    )

def update_order_status(order_id, status):
    orders_col.update_one(
        {"order_id": order_id}, 
        {"$set": {"status": status}}
    )

# --- Admin Functions ---
def get_stats():
    total = users_col.count_documents({})
    # Check for dates greater than right now
    premium = users_col.count_documents({
        "premium_until": {"$gt": datetime.now().isoformat()}
    })
    return total, premium

def get_all_user_ids():
    # Return a list of just the user IDs
    return [u["user_id"] for u in users_col.find({}, {"user_id": 1})]
