import requests
import asyncio
import logging
from datetime import datetime, timedelta

import config
import database as db

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
            response = requests.post(url, data=payload, timeout=15)
            if response.status_code == 200:
                return response.json()
            return {"status": "ERROR", "message": "API request failed"}
        except Exception as e:
            return {"status": "ERROR", "message": str(e)}

payment_sdk = OrderStatusSDK("https://privzpay.com")

# ==========================================================
# AUTO PAYMENT CHECKER
# ==========================================================
async def auto_check_payment(order_id, user_id, days, message, context):
    logger.info(f"Started payment checker: {order_id}")
    expiry_time = datetime.utcnow() + timedelta(minutes=30)

    while datetime.utcnow() < expiry_time:
        try:
            result = await payment_sdk.check_order_status(config.PRIVZPAY_TOKEN, order_id)
            logger.info(f"Payment check result: {result}")

            if result.get("status") == "COMPLETED" and result.get("result", {}).get("status") == "SUCCESS":
                order = db.get_order(order_id)
                if not order or order.get("status") == "success":
                    return

                db.update_order_status(order_id, "success")
                db.add_premium(user_id, days)

                utr = result.get("result", {}).get("utr") or "N/A"
                success_text = (
                    f"✅ PAYMENT SUCCESSFUL\n\n"
                    f"💎 Premium Activated\n"
                    f"🗓️ Duration: {days} Days\n"
                    f"🧾 Order ID: {order_id}\n"
                    f"🏦 UTR: {utr}"
                )

                try:
                    await message.edit_text(success_text)
                except Exception as e:
                    logger.error(f"Message edit error: {e}")

                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=(
                            "🎉 Welcome to Premium!\n\n"
                            "✅ Unlimited TeraBox Downloads\n"
                            "✅ No Daily Limits\n"
                            "✅ Faster Access\n\n"
                            f"🗓️ Your Premium is active for {days} days.\n\n"
                            "Thank you for supporting the bot ❤️"
                        )
                    )
                except Exception as e:
                    logger.error(f"Premium welcome message error: {e}")

                logger.info(f"Payment success: {order_id}")
                return

            await asyncio.sleep(10)

        except Exception as e:
            logger.error(f"Auto payment checker error: {e}")
            await asyncio.sleep(10)

    try:
        await message.edit_text("⌛ Payment link expired.\n\nPlease generate a new payment link.")
    except Exception as e:
        logger.error(f"Expiry message error: {e}")

    logger.info(f"Payment expired: {order_id}")
