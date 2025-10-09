# /opt/remna_bot/notifier.py

import asyncio
import os
import sys
import json
from datetime import datetime, timedelta
from telegram import Bot

# افزودن مسیر پروژه به sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
try:
    import config
except ImportError:
    print("Error: config.py not found. Make sure this script is in /opt/remna_bot/")
    sys.exit(1)

# بارگذاری تمام ترجمه‌ها از فایل
try:
    with open(os.path.join(os.path.dirname(__file__), 'locales.json'), 'r', encoding='utf-8') as f:
        LANGUAGES = json.load(f)
except Exception as e:
    print(f"Error loading locales.json: {e}")
    LANGUAGES = {}

CACHE_SPAM_FILE = os.path.join(os.path.dirname(__file__), 'spam_cache.json')

def can_send_conditional_notif(username: str, notif_type: str) -> bool:
    """جلوگیری از ارسال مکرر هشدارهای دوره‌ای (مانند تاریخ انقضا)"""
    try:
        with open(CACHE_SPAM_FILE, 'r') as f:
            cache = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        cache = {}

    user_notifs = cache.get(username, {})
    last_sent_str = user_notifs.get(notif_type)

    # اگر در 23 ساعت گذشته هشداری برای این شرط ارسال شده، دوباره ارسال نکن
    if last_sent_str:
        last_sent_dt = datetime.fromisoformat(last_sent_str)
        if datetime.now() < last_sent_dt + timedelta(hours=23):
            print(f"Spam prevention: Skipping '{notif_type}' for '{username}'.")
            return False

    if username not in cache:
        cache[username] = {}
    cache[username][notif_type] = datetime.now().isoformat()
    with open(CACHE_SPAM_FILE, 'w') as f:
        json.dump(cache, f)
    return True

def get_current_lang() -> str:
    """زبان انتخاب شده در ربات را از فایل settings.json می‌خواند."""
    try:
        settings_path = os.path.join(os.path.dirname(__file__), 'settings.json')
        with open(settings_path, 'r', encoding='utf-8') as f:
            return json.load(f).get('language', 'fa')
    except (FileNotFoundError, json.JSONDecodeError):
        return 'fa'

def get_message(key: str, **kwargs) -> str:
    """یک پیام فرمت‌شده بر اساس زبان فعلی ربات برمی‌گرداند."""
    lang = get_current_lang()
    return LANGUAGES.get(lang, LANGUAGES.get('en', {})).get(key, f"Missing translation for {key}").format(**kwargs)

async def send_notification(message_text: str):
    """تابع اصلی و ناهمزمان برای ارسال پیام به ادمین."""
    if not getattr(config, 'NOTIFICATIONS_ENABLED', False):
        return

    bot_token = getattr(config, 'TELEGRAM_BOT_TOKEN', None)
    admin_id = getattr(config, 'ADMIN_USER_ID', None)
    if not bot_token or not admin_id:
        print("Error: Bot token or admin ID is not defined in config.py.")
        return

    try:
        bot = Bot(token=bot_token)
        await bot.send_message(chat_id=admin_id, text=message_text, parse_mode='HTML')
    except Exception as e:
        print(f"Error sending Telegram notification: {e}")

# --- توابع async برای فراخوانی ---

async def user_enabled(username: str):
    msg = get_message('notif_user_enabled', username=f"<code>{username}</code>")
    await send_notification(msg)

async def user_disabled(username: str):
    msg = get_message('notif_user_disabled', username=f"<code>{username}</code>")
    await send_notification(msg)

async def user_modified(username: str):
    msg = get_message('notif_user_modified', username=f"<code>{username}</code>")
    await send_notification(msg)

async def limit_reached(username: str):
    msg = get_message('notif_limit_reached', username=f"<code>{username}</code>")
    await send_notification(msg)

async def subscription_expired(username: str):
    msg = get_message('notif_subscription_expired', username=f"<code>{username}</code>")
    await send_notification(msg)

async def near_expiry_warning(username: str):
    if can_send_conditional_notif(username, 'near_expiry'):
        msg = get_message('notif_near_expiry_warning', username=f"<code>{username}</code>")
        await send_notification(msg)

async def bandwidth_threshold_reached(username: str, threshold: int, usage: str, limit: str):
    msg = get_message('notif_bandwidth_threshold_reached', username=f"<code>{username}</code>", threshold=threshold, usage=usage, limit=limit)
    await send_notification(msg)

async def detail_limit_changed(username: str, old_limit: str, new_limit: str):
    msg = get_message('notif_detail_limit_changed', username=f"<code>{username}</code>", old_limit=old_limit, new_limit=new_limit)
    await send_notification(msg)

async def detail_expiry_changed(username: str, old_date: str, new_date: str):
    msg = get_message('notif_detail_expiry_changed', username=f"<code>{username}</code>", old_date=old_date, new_date=new_date)
    await send_notification(msg)

async def admin_user_status_changed(username: str, status_en: str):
    lang = get_current_lang()
    if lang == 'fa':
        status = "فعال ✅" if status_en == 'enable' else "غیرفعال 🚫"
    else:
        status = status_en
    msg = get_message('notif_admin_status_changed', username=f"<code>{username}</code>", status=status)
    await send_notification(msg)

async def admin_user_limit_changed(username: str, new_limit_gb: float):
    msg = get_message('notif_admin_limit_changed', username=f"<code>{username}</code>", limit=new_limit_gb)
    await send_notification(msg)

async def admin_user_expiry_changed(username: str, days: int):
    msg = get_message('notif_admin_expiry_changed', username=f"<code>{username}</code>", days=days)
    await send_notification(msg)
