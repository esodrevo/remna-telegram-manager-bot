# /opt/remna_bot/webhook_listener.py

from flask import Flask, request, jsonify
import os
import sys
import hmac
import hashlib
from datetime import datetime, timezone, timedelta

# افزودن مسیر پروژه برای دسترسی به ماژول‌ها
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
try:
    import config
    import notifier
except ImportError as e:
    print(f"Error importing modules: {e}")
    sys.exit(1)

app = Flask(__name__)
GB = 1024 * 1024 * 1024

def verify_signature(req):
    """
    امضای ارسال شده در هدر را با امضای ساخته شده از بدنه درخواست مقایسه می‌کند.
    """
    secret = getattr(config, 'WEBHOOK_SECRET', '').encode('utf-8')
    if not secret:
        print("Warning: WEBHOOK_SECRET is not set. Skipping verification.")
        return True

    signature_header = req.headers.get('x-remnawave-signature')
    timestamp_header = req.headers.get('x-remnawave-timestamp')
    if not signature_header or not timestamp_header:
        return False

    body = req.get_data()
    message = timestamp_header.encode('utf-8') + b'.' + body
    
    expected_signature = hmac.new(secret, message, hashlib.sha256).hexdigest()

    return hmac.compare_digest(expected_signature, signature_header)

def handle_user_modified(user_data):
    """
    رویداد user.modified را پردازش کرده و هشدارهای لازم را ارسال می‌کند.
    """
    username = user_data.get('username')
    if not username:
        return

    # 1. بررسی هشدار حجم باقی‌مانده
    used_bytes = int(user_data.get('usedTrafficBytes', 0))
    limit_bytes = int(user_data.get('trafficLimitBytes', 0))

    if limit_bytes > 0:
        remaining_bytes = limit_bytes - used_bytes
        if 0 < remaining_bytes < (2 * GB):
            notifier.low_traffic_warning(username)
        elif remaining_bytes <= 0:
            notifier.limit_reached(username)

    # 2. بررسی هشدار نزدیک بودن به تاریخ انقضا
    expire_at_str = user_data.get('expireAt')
    if expire_at_str:
        try:
            expire_dt = datetime.fromisoformat(expire_at_str.replace('Z', '+00:00'))
            now_utc = datetime.now(timezone.utc)
            time_left = expire_dt - now_utc

            if timedelta(seconds=0) < time_left < timedelta(hours=24):
                notifier.near_expiry_warning(username)
        except (ValueError, TypeError) as e:
            print(f"Could not parse expireAt date: {expire_at_str} | Error: {e}")

@app.route('/webhook', methods=['POST'])
def handle_webhook():
    if not getattr(config, 'NOTIFICATIONS_ENABLED', False):
        return jsonify({"status": "ok", "message": "Notifications are disabled."}), 200

    if not verify_signature(request):
        print("Webhook security check failed: Invalid signature.")
        return jsonify({"error": "Unauthorized"}), 401

    payload = request.json
    event = payload.get('event')
    user_data = payload.get('data', {})
    username = user_data.get('username')

    if not event or not username:
        return jsonify({"error": "Missing 'event' or 'data.username' in payload"}), 400

    print(f"Webhook received: Event '{event}' for user '{username}'")

    if event == 'user.enabled':
        notifier.user_enabled(username)
    elif event == 'user.disabled':
        notifier.user_disabled(username)
    elif event == 'user.modified':
        handle_user_modified(user_data)
    elif event == 'user.traffic_limit_reached':
        notifier.limit_reached(username)
    elif event == 'user.expired':
        notifier.subscription_expired(username)
    else:
        print(f"Unknown or unhandled event type: {event}")

    return jsonify({"status": "success"}), 200

if __name__ == '__main__':
    print("Starting Remna Webhook Listener on http://0.0.0.0:5556")
    app.run(host='0.0.0.0', port=5556)
