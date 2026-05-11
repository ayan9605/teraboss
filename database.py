from pymongo import MongoClient
from datetime import datetime, timedelta
import config

# Initialize MongoDB Connection
client = MongoClient(config.MONGO_URI)
db = client['terabox_bot']
users_col = db['users']
orders_col = db['orders']

# ==========================================
# User Operations
# ==========================================
def get_user(user_id):
    return users_col.find_one({"user_id": user_id})

def add_user(user_id, referred_by=None):
    if not get_user(user_id):
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

def check_referral_reward(referrer_id):
    """Increments referral count and returns True if they hit a multiple of 3"""
    users_col.update_one({"user_id": referrer_id}, {"$inc": {"referral_count": 1}})
    referrer = get_user(referrer_id)
    if referrer and referrer.get("referral_count", 0) % 3 == 0:
        return True
    return False

def add_premium(user_id, days):
    user = get_user(user_id)
    if not user:
        return

    current_premium = user.get("premium_until")
    
    if current_premium and current_premium > datetime.now():
        new_date = current_premium + timedelta(days=days)
    else:
        new_date = datetime.now() + timedelta(days=days)

    users_col.update_one(
        {"user_id": user_id}, 
        {"$set": {"premium_until": new_date}}
    )

def is_premium(user_id):
    user = get_user(user_id)
    if not user:
        return False
    return bool(user.get("premium_until") and user["premium_until"] > datetime.now())

def handle_daily_limits(user_id, is_prem):
    """Resets daily limit if it's a new day, increments usage if free, checks limits."""
    user = get_user(user_id)
    if not user:
        return False

    today_str = datetime.now().date().isoformat()
    
    # Reset if new day
    if user.get("last_link_date") != today_str:
        users_col.update_one(
            {"user_id": user_id}, 
            {"$set": {"links_today": 0, "last_link_date": today_str}}
        )
        user["links_today"] = 0

    # Limit check
    if not is_prem and user.get("links_today", 0) >= 5:
        return False # Limit reached
        
    # Increment if free user
    if not is_prem:
        users_col.update_one({"user_id": user_id}, {"$inc": {"links_today": 1}})
        
    return True # Allowed

# ==========================================
# Order & Payment Operations
# ==========================================
def create_order(order_id, user_id, amount, days):
    orders_col.insert_one({
        "order_id": order_id,
        "user_id": user_id,
        "amount": amount,
        "days": days,
        "status": "pending",
        "created_at": datetime.now()
    })

def get_order(order_id):
    return orders_col.find_one({"order_id": order_id})

def update_order_status(order_id, status):
    orders_col.update_one({"order_id": order_id}, {"$set": {"status": status}})

# ==========================================
# Admin Operations
# ==========================================
def get_stats():
    total_users = users_col.count_documents({})
    premium_users = users_col.count_documents({"premium_until": {"$gt": datetime.now()}})
    return total_users, premium_users

def get_all_users():
    return users_col.find({}, {"user_id": 1})
