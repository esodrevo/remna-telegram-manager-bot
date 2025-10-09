# /opt/remna_bot/notifier.py

import asyncio
import os
import sys
import json
from telegram import Bot

# ... (کدهای قبلی بدون تغییر) ...

async def send_notification(message_text: str):
# ... (کدهای قبلی بدون تغییر) ...

# --- توابع async برای فراخوانی ---

async def user_enabled(username: str):
# ... (کدهای قبلی بدون تغییر) ...

async def user_disabled(username: str):
# ... (کدهای قبلی بدون تغییر) ...

async def user_modified(username: str):
    msg = get_message('notif_user_modified', username=f"<code>{username}</code>")
    await send_notification(msg)

async def limit_reached(username: str):
# ... (کدهای قبلی بدون تغییر) ...

async def subscription_expired(username: str):
# ... (کدهای قبلی بدون تغییر) ...

async def low_traffic_warning(username: str):
# ... (کدهای قبلی بدون تغییر) ...

async def near_expiry_warning(username: str):
# ... (کدهای قبلی بدون تغییر) ...

# --- توابع دقیق جدید ---
async def detail_limit_changed(username: str, old_limit: str, new_limit: str):
    msg = get_message('notif_detail_limit_changed', username=f"<code>{username}</code>", old_limit=old_limit, new_limit=new_limit)
    await send_notification(msg)

async def detail_expiry_changed(username: str, old_date: str, new_date: str):
    msg = get_message('notif_detail_expiry_changed', username=f"<code>{username}</code>", old_date=old_date, new_date=new_date)
    await send_notification(msg)

# --- توابع برای فراخوانی از bot.py ---
async def admin_user_status_changed(username: str, status_en: str):
# ... (کدهای قبلی بدون تغییر) ...

async def admin_user_limit_changed(username: str, new_limit_gb: float):
# ... (کدهای قبلی بدون تغییر) ...

async def admin_user_expiry_changed(username: str, days: int):
# ... (کدهای قبلی بدون تغییر) ...
