# /opt/remna_bot/notifier.py

import asyncio
import os
import sys
import json
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

# --- توابع async برای فراخوانی توسط bot.py و webhook_listener.py ---

async def user_enabled(username: str):
    msg = get_message('notif_user_enabled', username=f"<code>{username}</code>")
    await send_notification(msg)

async def user_disabled(username: str):
    msg = get_message('notif_user_disabled', username=f"<code>{username}</code>")
    await send_notification(msg)

async def limit_reached(username: str):
    msg = get_message('notif_limit_reached', username=f"<code>{username}</code>")
    await send_notification(msg)

async def subscription_expired(username: str):
    msg = get_message('notif_subscription_expired', username=f"<code>{username}</code>")
    await send_notification(msg)

async def low_traffic_warning(username: str):
    msg = get_message('notif_low_traffic_warning', username=f"<code>{username}</code>")
    await send_notification(msg)

async def near_expiry_warning(username: str):
    msg = get_message('notif_near_expiry_warning', username=f"<code>{username}</code>")
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
