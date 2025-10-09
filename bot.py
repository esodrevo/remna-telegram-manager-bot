# /opt/remna_bot/bot.py

import logging, requests, json, subprocess, html, io, asyncio
from urllib.parse import urlparse
from datetime import datetime, timezone, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, InputMediaPhoto
from telegram.ext import (
    Application, CommandHandler, ConversationHandler,
    CallbackQueryHandler, MessageHandler, filters, ContextTypes
)
from telegram.constants import ParseMode
from telegram.error import BadRequest
import qrcode

import config
import notifier

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    with open('locales.json', 'r', encoding='utf-8') as f:
        LANGUAGES = json.load(f)
except FileNotFoundError: logger.critical("locales.json not found!"); exit()
except json.JSONDecodeError: logger.critical("locales.json is not a valid JSON file."); exit()

COMMANDS = {'en': [BotCommand("start", "Show Main Menu")], 'fa': [BotCommand("start", "نمایش منوی اصلی")], 'ru': [BotCommand("start", "Показать главное меню")]}
MAIN_MENU, SELECTING_LANGUAGE, AWAITING_USERNAME, USER_MENU, AWAITING_LIMIT, AWAITING_EXPIRE, NODE_LIST, VIEWING_LOGS, QR_VIEW, SELECT_NODE_RESTART = range(10)

def get_lang_from_file() -> str:
    try:
        with open('settings.json', 'r', encoding='utf-8') as f: return json.load(f).get('language', 'en')
    except (FileNotFoundError, json.JSONDecodeError): return 'en'

def get_lang(context: ContextTypes.DEFAULT_TYPE) -> str:
    if 'lang' not in context.user_data: context.user_data['lang'] = get_lang_from_file()
    return context.user_data['lang']

def t(key: str, context: ContextTypes.DEFAULT_TYPE, **kwargs) -> str:
    lang = get_lang(context); return LANGUAGES.get(lang, LANGUAGES.get('en', {})).get(key, key).format(**kwargs)

def set_language_file(lang: str):
    with open('settings.json', 'w', encoding='utf-8') as f: json.dump({'language': lang}, f)

def is_admin(update: Update) -> bool:
    if not update.effective_user: return False
    return update.effective_user.id == config.ADMIN_USER_ID

def format_bytes(byte_count):
    if byte_count is None or int(byte_count) <= 0: return "0 GB"
    power=1024; n=0; labels={0:' B',1:' KB',2:' MB',3:' GB'}
    byte_count = int(byte_count)
    while byte_count >= power and n < 3: byte_count /= power; n += 1
    return f"{byte_count:.2f}{labels[n]}"

def parse_iso_date(date_string: str | None):
    if not date_string: return None
    try: return datetime.fromisoformat(date_string.replace('Z', '+00:00'))
    except (ValueError, TypeError): return None

def human_readable_timediff(dt: datetime, context: ContextTypes.DEFAULT_TYPE):
    if not dt: return t('not_updated_yet', context)
    now = datetime.now(timezone.utc); diff = now - dt; seconds = diff.total_seconds()
    if seconds < 60: return t('just_now', context)
    minutes = int(seconds/60);
    if minutes < 60: return t('minutes_ago', context, minutes=minutes)
    hours = int(minutes/60)
    if hours < 24: return t('hours_ago', context, hours=hours)
    days = int(hours/24)
    return t('days_ago', context, days=days)

def api_request(method: str, endpoint: str, payload: dict = None):
    url = f"{config.PANEL_URL}{endpoint}"; headers = {'Authorization': f'Bearer {config.PANEL_API_TOKEN}', 'Accept': 'application/json', 'Content-Type': 'application/json'}
    try:
        response = requests.request(method.upper(), url, headers=headers, json=payload, timeout=15)
        response.raise_for_status()
        return response.json() if response.status_code != 204 else {}, None
    except requests.exceptions.HTTPError as errh:
        if errh.response.status_code == 404: return None, "User not found"
        logger.error(f"Http Error: {errh} - Response: {errh.response.text}"); return None, f"HTTP Error: {errh.response.status_code}"
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}"); return None, "Unknown error"

def generate_qr_code(data: str):
    if not data: return None
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
    qr.add_data(data); qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white"); buf = io.BytesIO()
    img.save(buf, 'PNG'); buf.seek(0)
    return buf.getvalue()

def build_user_info_message(user_data: dict, context: ContextTypes.DEFAULT_TYPE):
    safe_username = html.escape(user_data.get('username') or 'N/A'); safe_client_app = html.escape(user_data.get('subLastUserAgent') or t('unknown', context)); safe_sub_url = html.escape(user_data.get('subscriptionUrl') or t('not_found', context))
    status = t('status_active', context) if user_data.get('status') == 'ACTIVE' else t('status_inactive', context); data_limit = user_data.get('trafficLimitBytes', 0); data_usage = user_data.get('usedTrafficBytes', 0); remaining_data = int(data_limit) - int(data_usage) if int(data_limit) > 0 else 0; expire_dt = parse_iso_date(user_data.get('expireAt')); remaining_days, expire_date_fa = (t('unlimited', context), t('unlimited', context))
    if expire_dt:
        expire_date_fa = expire_dt.strftime("%Y/%m/%d"); time_diff = expire_dt - datetime.now(timezone.utc)
        if time_diff.total_seconds() > 0:
            days = time_diff.days; hours = time_diff.seconds // 3600; remaining_days = f"{days} {t('days_unit', context)} {t('and_conjunction', context)} {hours} {t('hours_unit', context)}"
        else: remaining_days = t('expired', context)
    sub_last_update_dt = parse_iso_date(user_data.get('subLastOpenedAt')); last_update_relative = human_readable_timediff(sub_last_update_dt, context)
    return (f"{t('user_info_title', context, username=safe_username)}\n\n" f"{t('status', context)} {status}\n\n" f"{t('total_limit', context)} {format_bytes(data_limit)}\n" f"{t('usage', context)} {format_bytes(data_usage)}\n" f"{t('remaining_volume', context)} {format_bytes(remaining_data)}\n\n" f"{t('expire_date', context)} {expire_date_fa}\n" f"{t('remaining_time', context)} {remaining_days}\n\n" f"{t('client_software', context)} <code>{safe_client_app}</code>\n" f"{t('last_update', context)} {last_update_relative}\n\n" f"{t('subscription_link', context)}\n" f"<code>{safe_sub_url}</code>")

async def check_expiring_users(context: ContextTypes.DEFAULT_TYPE):
    """
    این تابع به صورت دوره‌ای اجرا شده و کاربرانی که تاریخ انقضایشان نزدیک است را بررسی می‌کند.
    """
    logger.info("Running job: check_expiring_users")
    if not getattr(config, 'NOTIFICATIONS_ENABLED', False):
        logger.info("Notifications are disabled, skipping expiry check job.")
        return
        
    try:
        all_users_data, error = api_request('GET', '/api/users')
        if error or not all_users_data:
            logger.error(f"Could not fetch users for expiry check. Error: {error}")
            return

        users = all_users_data.get('response', {}).get('users', [])
        now_utc = datetime.now(timezone.utc)

        for user in users:
            expire_at_str = user.get('expireAt')
            username = user.get('username')
            status = user.get('status')

            if not expire_at_str or not username or status != 'ACTIVE':
                continue

            try:
                expire_dt = parse_iso_date(expire_at_str)
                time_left = expire_dt - now_utc
                if timedelta(seconds=0) < time_left < timedelta(hours=24):
                    await notifier.near_expiry_warning(username)
            except Exception as e:
                logger.warning(f"Could not process user '{username}' for expiry check. Error: {e}")

    except Exception as e:
        logger.error(f"An unexpected error occurred in check_expiring_users job: {e}")

async def post_init(application: Application):
    lang = get_lang_from_file()
    await application.bot.set_my_commands(COMMANDS.get(lang, COMMANDS['en']))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # ... (بدون تغییر) ...
async def show_node_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # ... (بدون تغییر) ...
async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # ... (بدون تغییر) ...
async def set_lang_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # ... (بدون تغییر) ...
async def show_user_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # ... (بدون تغییر) ...
async def user_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # ... (بدون تغییر) ...
async def back_to_user_info_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # ... (بدون تغییر) ...
async def set_new_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # ... (بدون تغییر) ...
async def logs_node_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # ... (بدون تغییر) ...
async def restart_node_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # ... (بدون تغییر) ...

def main() -> None:
    application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    # --- Job Queue for background tasks ---
    job_queue = application.job_queue
    # وظیفه را طوری تنظیم می‌کنیم که هر 12 ساعت یک بار اجرا شود
    job_queue.run_repeating(check_expiring_users, interval=12 * 3600, first=10) # 10 ثانیه بعد از استارت برای اولین بار اجرا می‌شود

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            MAIN_MENU: [CallbackQueryHandler(main_menu_handler), CallbackQueryHandler(start, pattern='^back_to_main$')],
            SELECTING_LANGUAGE: [CallbackQueryHandler(set_lang_callback, pattern='^set_lang_'), CallbackQueryHandler(start, pattern='^back_to_main$')],
            AWAITING_USERNAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, show_user_card),
                CallbackQueryHandler(start, pattern='^back_to_main$')
            ],
            USER_MENU: [CallbackQueryHandler(user_menu_handler)],
            QR_VIEW: [CallbackQueryHandler(back_to_user_info_handler, pattern='^back_to_user_info$')],
            AWAITING_LIMIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_new_value)],
            AWAITING_EXPIRE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_new_value)],
            NODE_LIST: [CallbackQueryHandler(logs_node_handler)],
            VIEWING_LOGS: [CallbackQueryHandler(logs_node_handler)],
            SELECT_NODE_RESTART: [CallbackQueryHandler(restart_node_handler, pattern='^restartnode_'), CallbackQueryHandler(main_menu_handler, pattern='^go_restart_nodes$'), CallbackQueryHandler(start, pattern='^back_to_main$')]
        },
        fallbacks=[CommandHandler('start', start)], allow_reentry=True
    )
    application.add_handler(conv_handler)
    logger.info("Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()
