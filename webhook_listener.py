# /opt/remna_bot/webhook_listener.py

from flask import Flask, request, jsonify
import os
import sys
import hmac
import hashlib
import asyncio
from datetime import datetime, timezone, timedelta

# افزودن مسیر پروژه برای دسترسی به ماژول‌ها
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
try:
    import config
    import notifier
    import cache_manager
except ImportError as e:
    print(f"Error importing modules: {e}")
    sys.exit(1)

app = Flask(__name__)

def verify_signature(req):
    """
    امضای ارسال شده در هدر را با امضای ساخته شده از بدنه درخواست مقایسه می‌کند.
    """
    secret = getattr(config, 'WEBHOOK_SECRET', '').encode('utf-8')
    if not secret:
        print("Warning: WEBHOOK_SECRET is not set. Skipping verification.")
        return True

    signature_header = req.headers.get('x-remnawave-signature')
    if not signature_header:
        print("Webhook security check failed: Signature header missing.")
        return False

    body = req.get_data()
    message = body
    
    expected_signature = hmac.new(secret, message, hashlib.sha256).hexdigest()
    
    if not hmac.compare_digest(expected_signature, signature_header):
        print(f"Webhook security check failed: Invalid signature.")
        return False
        
    return True

@app.route('/webhook', methods=['POST'])
def handle_webhook():
    if not getattr(config, 'NOTIFICATIONS_ENABLED', False):
        return jsonify({"status": "ok", "message": "Notifications are disabled."}), 200

    if not verify_signature(request):
        return jsonify({"error": "Unauthorized"}), 401

    payload = request.json
    event = payload.get('event')
    user_data = payload.get('data', {})
    username = user_data.get('username')

    if not event or not username:
        return jsonify({"error": "Missing 'event' or 'data.username' in payload"}), 400

    print(f"Webhook received: Event '{event}' for user '{username}'")

    if event == 'user.enabled' or event == 'user.disabled':
        cache_manager.update_user_in_cache(user_data)
        if event == 'user.enabled':
            asyncio.run(notifier.user_enabled(username))
        else:
            asyncio.run(notifier.user_disabled(username))

    elif event == 'user.modified':
        asyncio.run(cache_manager.compare_and_notify(user_data))
        
    elif event == 'user.bandwidth_usage_threshold_reached':
        cache_manager.update_user_in_cache(user_data)
        threshold = user_data.get('lastTriggeredThreshold')
        usage = cache_manager.format_bytes_to_gb(user_data.get('usedTrafficBytes'))
        limit = cache_manager.format_bytes_to_gb(user_data.get('trafficLimitBytes'))
        asyncio.run(notifier.bandwidth_threshold_reached(username, threshold, usage, limit))
    
    elif event == 'user.traffic_limit_reached':
        cache_manager.update_user_in_cache(user_data)
        asyncio.run(notifier.limit_reached(username))
        
    elif event == 'user.expired':
        cache_manager.update_user_in_cache(user_data)
        asyncio.run(notifier.subscription_expired(username))
        
    else:
        print(f"Unknown or unhandled event type: {event}")

    return jsonify({"status": "success"}), 200

if __name__ == '__main__':
    print("Starting Remna Webhook Listener on http://0.0.0.0:5556")
    app.run(host='0.0.0.0', port=5556)
