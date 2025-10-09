# /opt/remna_bot/cache_manager.py (نسخه نهایی و اصلاح‌شده)

import os
import sys
import json
import requests
from datetime import datetime

# افزودن مسیر پروژه برای دسترسی به ماژول‌های دیگر
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
try:
    import config
    import notifier
except ImportError as e:
    print(f"Error: Failed to import required modules. {e}")
    sys.exit(1)

CACHE_FILE = os.path.join(os.path.dirname(__file__), 'user_cache.json')
GB = 1024 * 1024 * 1024

# --- Helper Functions ---
def format_bytes_to_gb(byte_count):
    if byte_count is None or int(byte_count) == 0:
        return "0 GB"
    return f"{int(byte_count) / GB:.2f} GB"

def format_iso_date(date_string):
    if not date_string:
        return ""
    try:
        return datetime.fromisoformat(date_string.replace('Z', '+00:00')).strftime('%Y/%m/%d')
    except (ValueError, TypeError):
        return date_string

# --- Cache Management ---
def load_cache():
    try:
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_cache(cache_data):
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache_data, f, indent=2, ensure_ascii=False)

def update_user_in_cache(user_data):
    username = user_data.get('username')
    if not username:
        return
    cache = load_cache()
    cache[username] = user_data
    save_cache(cache)
    print(f"Cache updated for user: {username}")

async def compare_and_notify(new_user_data):
    username = new_user_data.get('username')
    if not username:
        return

    cache = load_cache()
    old_user_data = cache.get(username)

    if not old_user_data:
        update_user_in_cache(new_user_data)
        await notifier.user_modified(username)
        return

    if old_user_data.get('status') != new_user_data.get('status'):
        if new_user_data.get('status') == 'ACTIVE':
            await notifier.user_enabled(username)
        else:
            await notifier.user_disabled(username)
    
    if old_user_data.get('trafficLimitBytes') != new_user_data.get('trafficLimitBytes'):
        old_limit = format_bytes_to_gb(old_user_data.get('trafficLimitBytes', 0))
        new_limit = format_bytes_to_gb(new_user_data.get('trafficLimitBytes', 0))
        await notifier.detail_limit_changed(username, old_limit, new_limit)

    if old_user_data.get('expireAt') != new_user_data.get('expireAt'):
        old_date = format_iso_date(old_user_data.get('expireAt'))
        new_date = format_iso_date(new_user_data.get('expireAt'))
        await notifier.detail_expiry_changed(username, old_date, new_date)
    
    update_user_in_cache(new_user_data)

def populate_cache():
    print("Attempting to populate user cache from panel API...")
    api_url = f"{config.PANEL_URL}/api/users"
    headers = {'Authorization': f'Bearer {config.PANEL_API_TOKEN}', 'Accept': 'application/json'}
    
    try:
        response = requests.get(api_url, headers=headers, timeout=30)
        response.raise_for_status()
        
        response_json = response.json()
        
        # --- FIX: Correctly access the nested 'users' list ---
        response_data = response_json.get('response', {})
        users = response_data.get('users', [])
        # ----------------------------------------------------
        
        if not users:
            print("Warning: Received no users from the panel. The 'users' list in the response was empty.")
            return

        cache_data = {user['username']: user for user in users if 'username' in user}
        save_cache(cache_data)
        print(f"Successfully populated cache with {len(cache_data)} users.")

    except Exception as e:
        print(f"FATAL ERROR: Could not populate cache. Please check your PANEL_URL and PANEL_API_TOKEN in config.py.")
        print(f"Details: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == 'populate':
        populate_cache()
    else:
        print("Usage: python3 cache_manager.py populate")
