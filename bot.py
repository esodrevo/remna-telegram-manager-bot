# bot.py

import logging, requests, json, subprocess, html, io, uuid, random, string, re, asyncio
from itertools import zip_longest
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

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    with open('locales.json', 'r', encoding='utf-8') as f:
        LANGUAGES = json.load(f)
except FileNotFoundError: logger.critical("locales.json not found!"); exit()
except json.JSONDecodeError: logger.critical("locales.json is not a valid JSON file."); exit()


COMMANDS = {'en': [BotCommand("start", "Show Main Menu")], 'fa': [BotCommand("start", "نمایش منوی اصلی")], 'ru': [BotCommand("start", "Показать главное меню")]}

# STATE CONSTANTS
(
    MAIN_MENU, SELECTING_LANGUAGE, AWAITING_USERNAME, USER_MENU, AWAITING_LIMIT,
    AWAITING_EXPIRE, NODE_LIST, VIEWING_LOGS, QR_VIEW, SELECT_NODE_RESTART,
    CONFIRM_DELETE, AWAITING_NEW_USERNAME, AWAITING_DATA_LIMIT, AWAITING_EXPIRE_DAYS,
    SELECTING_HWID_OPTION, AWAITING_HWID_VALUE, SELECTING_SQUADS, EDIT_ALL_USERS_MENU,
    AWAITING_BULK_VALUE, CONFIRM_BULK_ACTION, AWAITING_HOURS_FOR_UPDATED_LIST,
    SELECT_BULK_HWID_ACTION, AWAITING_BULK_HWID_VALUE, AWAITING_TIMEZONE_SETTING,
    EXPIRING_USERS_MENU, AWAITING_HWID_EDIT, USER_CREATED_MENU
) = range(27)


def get_settings() -> dict:
    try:
        with open('settings.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_settings(settings: dict):
    with open('settings.json', 'w', encoding='utf-8') as f:
        json.dump(settings, f, indent=4)

def get_lang_from_file() -> str:
    return get_settings().get('language', 'en')

def set_language_file(lang: str):
    settings = get_settings()
    settings['language'] = lang
    save_settings(settings)

def parse_timezone_setting():
    """Parses the timezone string 'GMT±H:MM/HH:MM' from settings.json"""
    settings = get_settings()
    tz_string = settings.get('expire_time_setting')
    if not tz_string:
        return None

    match = re.match(r'GMT([+-])(\d{1,2}):(\d{2})/(\d{2}):(\d{2})', tz_string.upper())
    if not match:
        return None

    sign, h_offset, m_offset, hour, minute = match.groups()
    h_offset, m_offset, hour, minute = int(h_offset), int(m_offset), int(hour), int(minute)

    if sign == '-':
        h_offset = -h_offset
        m_offset = -m_offset

    try:
        tz = timezone(timedelta(hours=h_offset, minutes=m_offset))
        time_obj = datetime.strptime(f"{hour}:{minute}", "%H:%M").time()
        return tz, time_obj
    except Exception:
        return None

def get_lang(context: ContextTypes.DEFAULT_TYPE) -> str:
    if context and hasattr(context, 'user_data') and 'lang' in context.user_data:
        return context.user_data['lang']
    return get_lang_from_file()


def t(key: str, context: ContextTypes.DEFAULT_TYPE, **kwargs) -> str:
    lang = get_lang(context); return LANGUAGES.get(lang, LANGUAGES['en']).get(key, key).format(**kwargs)

def is_admin(update: Update) -> bool:
    if not update.effective_user: return False
    return update.effective_user.id == config.ADMIN_USER_ID

def format_bytes(byte_count):
    if byte_count is None or byte_count == 0: return "نامحدود" if get_lang(None) == 'fa' else "Unlimited"
    power=1024; n=0; labels={0:' B',1:' KB',2:' MB',3:' GB'}
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

def api_request(method: str, endpoint: str, payload: dict = None, params: dict = None):
    url = f"{config.PANEL_URL}{endpoint}"; headers = {'Authorization': f'Bearer {config.PANEL_API_TOKEN}', 'Accept': 'application/json', 'Content-Type': 'application/json'}
    try:
        response = requests.request(method.upper(), url, headers=headers, json=payload, params=params, timeout=15)
        response.raise_for_status()
        return response.json() if response.status_code != 204 else {}, None
    except requests.exceptions.HTTPError as errh:
        error_response = errh.response.text
        try:
             error_details = errh.response.json().get('message', error_response)
        except json.JSONDecodeError:
             error_details = error_response

        if errh.response.status_code == 404: return None, "Endpoint or User not found"
        logger.error(f"Http Error: {errh} - Response: {error_details}"); return None, f"HTTP Error {errh.response.status_code}: {error_details}"
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}"); return None, "Unknown error"

async def api_request_get_all_users():
    """
    Fetches all users from the API by handling pagination using 'size' and 'start' parameters.
    """
    all_users = []
    start = 0
    size = 100
    
    while True:
        params = {'start': start, 'size': size}
        data, error = await asyncio.to_thread(api_request, 'GET', '/api/users', params=params)
        
        if error:
            logger.error(f"Error fetching users with start={start}: {error}")
            return None, error
            
        response_data = data.get('response', {})
        users_on_page = response_data.get('users', [])
        
        if not users_on_page:
            break
            
        all_users.extend(users_on_page)
        
        if len(users_on_page) < size:
            break
            
        start += size
        
    final_response_structure = {'response': {'users': all_users}}
    return final_response_structure, None


def generate_qr_code(data: str):
    if not data: return None
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
    qr.add_data(data); qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white"); buf = io.BytesIO()
    img.save(buf, 'PNG'); buf.seek(0)
    return buf.getvalue()

def build_user_info_message(user_data: dict, context: ContextTypes.DEFAULT_TYPE):
    safe_username = html.escape(user_data.get('username') or 'N/A')
    safe_client_app = html.escape(user_data.get('subLastUserAgent') or t('unknown', context))
    safe_sub_url = html.escape(user_data.get('subscriptionUrl') or t('not_found', context))

    data_limit = user_data.get('trafficLimitBytes')
    
    user_traffic = user_data.get('userTraffic') or {}
    data_usage = user_traffic.get('usedTrafficBytes', 0)
    
    online_at_str = user_traffic.get('onlineAt')
    online_dt = parse_iso_date(online_at_str)
    online_relative = human_readable_timediff(online_dt, context)
    
    status_label = t('status_active', context) if user_data.get('status') == 'ACTIVE' else t('status_inactive', context)
    full_status = f"{status_label} / {online_relative}"

    limit_formatted = format_bytes(data_limit)
    usage_formatted = "0.00 B"
    if data_usage and data_usage > 0:
        usage_formatted = format_bytes(data_usage)

    remaining_formatted = t('unlimited', context)
    if data_limit is not None and data_limit > 0:
        remaining_bytes = data_limit - (data_usage or 0)
        remaining_formatted = format_bytes(remaining_bytes)

    expire_dt = parse_iso_date(user_data.get('expireAt'))
    remaining_days, expire_date_fa = (t('unlimited', context), t('unlimited', context))
    if expire_dt:
        expire_date_fa = expire_dt.strftime("%Y/%m/%d")
        time_diff = expire_dt - datetime.now(timezone.utc)
        if time_diff.total_seconds() > 0:
            days = time_diff.days; hours = time_diff.seconds // 3600
            remaining_days = f"{days} {t('days_unit', context)} {t('and_conjunction', context)} {hours} {t('hours_unit', context)}"
        else: remaining_days = t('expired', context)
    sub_last_update_dt = parse_iso_date(user_data.get('subLastOpenedAt'))
    last_update_relative = human_readable_timediff(sub_last_update_dt, context)

    hwid_limit = user_data.get('hwidDeviceLimit', 0)
    hwid_status_text = t('disabled', context)
    if hwid_limit and hwid_limit > 0:
        hwid_status_text = t('hwid_limit_value', context, limit=hwid_limit)
    
    return (f"{t('user_info_title', context, username=safe_username)}\n\n"
            f"{t('status', context)} {full_status}\n"
            f"{t('hwid_limit', context)} {hwid_status_text}\n\n"
            f"{t('total_limit', context)} {limit_formatted}\n"
            f"{t('usage', context)} {usage_formatted}\n"
            f"{t('remaining_volume', context)} {remaining_formatted}\n\n"
            f"{t('expire_date', context)} {expire_date_fa}\n"
            f"{t('remaining_time', context)} {remaining_days}\n\n"
            f"{t('client_software', context)} <code>{safe_client_app}</code>\n"
            f"{t('last_update', context)} {last_update_relative}\n\n"
            f"{t('subscription_link', context)}\n"
            f"<code>{safe_sub_url}</code>")

def get_logs_from_node(node_name: str):
    node_config = config.NODES.get(node_name)
    if not node_config: return None, "Node not found in config."
    if node_config['type'] == 'local':
        command = ["docker", "exec", "remnanode", "tail", "-n30", "/var/log/supervisor/xray.out.log"]
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=True, encoding='utf-8')
            return result.stdout.strip(), None
        except Exception as e: return None, str(e)
    elif node_config['type'] == 'remote':
        try:
            headers = {'Authorization': f"Bearer {node_config['token']}"}
            response = requests.get(node_config['url'], headers=headers, timeout=10)
            response.raise_for_status()
            return response.json().get('logs'), None
        except Exception as e: return None, str(e)
    return None, "Invalid node type in config."

async def post_init(application: Application):
    lang = get_lang_from_file()
    await application.bot.set_my_commands(COMMANDS.get(lang, COMMANDS['en']))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_admin(update): return ConversationHandler.END
    
    context.user_data.clear()
    get_lang(context)
    
    keyboard = [
        [InlineKeyboardButton(t('add_user_btn', context), callback_data='go_add_user'),
         InlineKeyboardButton(t('manage_user_btn', context), callback_data='go_manage_user')],
        [InlineKeyboardButton(t('restart_nodes_btn', context), callback_data='go_restart_nodes'),
         InlineKeyboardButton(t('view_logs_btn', context), callback_data='go_view_logs')],
        [InlineKeyboardButton(t('edit_all_users_btn', context), callback_data='go_edit_all_users')],
        [InlineKeyboardButton(t('updated_users_btn', context), callback_data='go_updated_users'),
         InlineKeyboardButton(t('expiring_users_btn', context), callback_data='go_expiring_users')],
        [InlineKeyboardButton(t('set_expire_time_btn', context), callback_data='go_set_expire_time'),
         InlineKeyboardButton(t('change_language_btn', context), callback_data='go_change_language')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    message_text = t('main_menu_prompt', context)
    
    chat_id = update.effective_chat.id
    
    if update.callback_query:
        # این خط باعث می‌شود لودینگ دکمه متوقف شود
        await update.callback_query.answer()
        try:
            # تلاش برای ویرایش پیام (اگر متن باشد)
            await update.callback_query.message.edit_text(message_text, reply_markup=reply_markup)
        except BadRequest:
            # اگر پیام عکس باشد، ویرایش شکست می‌خورد. پس عکس قبلی را پاک می‌کنیم
            try:
                await update.callback_query.message.delete()
            except Exception:
                pass
            # و منوی جدید را ارسال می‌کنیم
            await context.bot.send_message(chat_id=chat_id, text=message_text, reply_markup=reply_markup)
    else:
        await context.bot.send_message(chat_id=chat_id, text=message_text, reply_markup=reply_markup)

    return MAIN_MENU


async def show_node_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    buttons = [InlineKeyboardButton(node_name, callback_data=f"lognode_{node_name}") for node_name in config.NODES.keys()]
    keyboard = [[b] for b in buttons] if len(buttons) > 1 else [buttons]
    keyboard.append([InlineKeyboardButton(t('back_to_main_menu_btn', context), callback_data='back_to_main')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    message_text = t('select_node_prompt', context)
    query = update.callback_query
    if query:
        await query.message.edit_text(text=message_text, reply_markup=reply_markup)
    return NODE_LIST

def get_creation_date(user: dict):
    created_at_str = user.get('createdAt')
    if not created_at_str or not isinstance(created_at_str, str):
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)

async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); action = query.data
    
    if action == 'go_add_user':
        await query.message.edit_text(text="⏳ در حال دریافت آخرین کاربر...")
        
        last_username = "N/A"
        users_data, error = await asyncio.to_thread(api_request, 'GET', '/api/users')
        
        if not error and users_data and 'response' in users_data:
            response_obj = users_data.get('response')
            if response_obj and isinstance(response_obj, dict):
                users_list = response_obj.get('users')
                
                if users_list and isinstance(users_list, list):
                    try:
                        sorted_users = sorted(users_list, key=get_creation_date, reverse=True)
                        
                        if sorted_users:
                            last_username = sorted_users[0].get('username', "N/A")
                    except Exception as e:
                        logger.error(f"Error processing users list for last user: {e}")

        context.user_data['new_user_data'] = {}
        prompt_text = t('ask_for_new_username_with_suggestion', context, last_user=last_username)
        prompt_message = await query.message.edit_text(prompt_text, parse_mode=ParseMode.HTML)
        
        context.user_data['prompt_message_id'] = prompt_message.message_id
        return AWAITING_NEW_USERNAME

    if action == 'go_manage_user':
        prompt_message = await query.message.edit_text(t('ask_for_username', context))
        context.user_data['prompt_message_id'] = prompt_message.message_id
        return AWAITING_USERNAME
    if action == 'go_view_logs':
        return await show_node_list(update, context)
    if action == 'go_restart_nodes':
        buttons = [InlineKeyboardButton(node_name, callback_data=f"restartnode_{node_name}") for node_name in config.NODES.keys()]
        keyboard = [[b] for b in buttons] if len(buttons) > 1 else [buttons]; keyboard.append([InlineKeyboardButton(t('back_to_main_menu_btn', context), callback_data='back_to_main')])
        await query.message.edit_text(t('select_node_restart_prompt', context), reply_markup=InlineKeyboardMarkup(keyboard)); return SELECT_NODE_RESTART
    if action == 'go_change_language':
        keyboard = [[InlineKeyboardButton("English 🇬🇧", callback_data='set_lang_en'), InlineKeyboardButton("Русский 🇷🇺", callback_data='set_lang_ru'), InlineKeyboardButton("فارسی 🇮🇷", callback_data='set_lang_fa')], [InlineKeyboardButton(t('back_to_main_menu_btn', context), callback_data='back_to_main')]]
        await query.message.edit_text(text=t('select_language_prompt', context), reply_markup=InlineKeyboardMarkup(keyboard)); return SELECTING_LANGUAGE
    if action == 'go_set_expire_time':
        settings = get_settings()
        current_setting = settings.get('expire_time_setting', t('not_set', context))
        keyboard = [[InlineKeyboardButton(t('back_to_main_menu_btn', context), callback_data='back_to_main')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        prompt_message = await query.message.edit_text(
            t('ask_for_timezone_and_time', context, current_setting=current_setting),
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
        context.user_data['prompt_message_id'] = prompt_message.message_id
        return AWAITING_TIMEZONE_SETTING
    if action == 'go_edit_all_users':
        return await show_edit_all_users_menu(update, context)
    if action == 'go_expiring_users':
        return await show_expiring_users_menu(update, context)
    
    if action == 'go_updated_users':
        prompt_message = await query.message.edit_text(t('ask_for_hours_ago', context), parse_mode=ParseMode.HTML)
        context.user_data['prompt_message_id'] = prompt_message.message_id
        return AWAITING_HOURS_FOR_UPDATED_LIST
        
    return MAIN_MENU

# --- Start of Bulk Edit Feature ---

async def show_edit_all_users_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    keyboard = [
        [InlineKeyboardButton(t('bulk_edit_volume_btn', context), callback_data='bulk_edit_volume')],
        [InlineKeyboardButton(t('bulk_edit_date_btn', context), callback_data='bulk_edit_date')],
        [InlineKeyboardButton(t('bulk_edit_hwid_btn', context), callback_data='bulk_edit_hwid')],
        [InlineKeyboardButton(t('back_to_main_menu_btn', context), callback_data='back_to_main')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text=t('edit_all_users_prompt', context), reply_markup=reply_markup)
    return EDIT_ALL_USERS_MENU

async def edit_all_users_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    action = query.data
    
    if action == 'bulk_edit_volume' or action == 'bulk_edit_date':
        context.user_data['bulk_edit_type'] = 'volume' if action == 'bulk_edit_volume' else 'date'
        prompt_text = t('ask_for_bulk_volume_change', context) if context.user_data['bulk_edit_type'] == 'volume' else t('ask_for_bulk_date_change', context)
        prompt_message = await query.message.edit_text(prompt_text, parse_mode=ParseMode.HTML)
        context.user_data['prompt_message_id'] = prompt_message.message_id
        return AWAITING_BULK_VALUE
        
    elif action == 'bulk_edit_hwid':
        context.user_data['bulk_edit_type'] = 'hwid'
        keyboard = [
            [InlineKeyboardButton(t('enable_hwid_bulk_btn', context), callback_data='bulk_hwid_enable')],
            [InlineKeyboardButton(t('disable_hwid_bulk_btn', context), callback_data='bulk_hwid_disable')],
            [InlineKeyboardButton(t('back_to_main_menu_btn', context), callback_data='back_to_main')]
        ]
        prompt_message = await query.message.edit_text(t('ask_hwid_bulk_action', context), reply_markup=InlineKeyboardMarkup(keyboard))
        context.user_data['prompt_message_id'] = prompt_message.message_id
        return SELECT_BULK_HWID_ACTION

async def show_bulk_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    prompt_message_id = context.user_data.get('prompt_message_id')
    
    await context.bot.edit_message_text(chat_id=chat_id, message_id=prompt_message_id, text=t('fetching_all_users', context))

    users_data, error = await api_request_get_all_users()

    if error or 'response' not in users_data or 'users' not in users_data['response']:
        await context.bot.edit_message_text(chat_id=chat_id, message_id=prompt_message_id, text=t('error_fetching_all_users', context, error=error))
        return ConversationHandler.END
        
    all_users = users_data['response']['users']
    context.user_data['bulk_users_list'] = all_users
    
    edit_type = context.user_data['bulk_edit_type']
    change_value = context.user_data['bulk_change_value']
    change_type_text = t(f'change_type_{edit_type}', context)
    
    change_value_text = ""
    if edit_type == 'volume':
        change_value_text = f"+{change_value} GB" if change_value > 0 else f"{change_value} GB"
    elif edit_type == 'date':
        change_value_text = f"+{int(change_value)} {t('days_unit', context)}" if change_value > 0 else f"{int(change_value)} {t('days_unit', context)}"
    elif edit_type == 'hwid':
        change_value_text = str(int(change_value)) if change_value > 0 else t('disable_hwid_bulk_btn', context)

    confirmation_text = t('confirm_bulk_update_prompt', context, 
                          change_type=change_type_text, 
                          change_value=change_value_text, 
                          user_count=len(all_users))
    
    keyboard = [
        [InlineKeyboardButton(t('confirm_btn', context), callback_data='confirm_bulk_action')],
        [InlineKeyboardButton(t('cancel_btn', context), callback_data='cancel_bulk_action')]
    ]
    await context.bot.edit_message_text(chat_id=chat_id, message_id=prompt_message_id, 
                                        text=confirmation_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    
    return CONFIRM_BULK_ACTION

async def process_bulk_hwid_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    if query.data == 'bulk_hwid_disable':
        context.user_data['bulk_change_value'] = 0
        return await show_bulk_confirmation(update, context) 
        
    elif query.data == 'bulk_hwid_enable':
        await query.message.edit_text(t('ask_for_bulk_hwid_value', context))
        return AWAITING_BULK_HWID_VALUE

async def process_bulk_hwid_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        limit = int(update.message.text)
        if limit <= 0: raise ValueError
        context.user_data['bulk_change_value'] = limit
        await update.message.delete()
        return await show_bulk_confirmation(update, context)
    except (ValueError, TypeError):
        await update.message.reply_text(t('invalid_number', context))
        return AWAITING_BULK_HWID_VALUE

async def process_bulk_change_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        await update.message.delete()
    except BadRequest: pass

    text = update.message.text
    match = re.match(r'^\s*([+-])\s*(\d+(\.\d+)?)\s*$', text)
    if not match:
        await update.message.reply_text(t('invalid_bulk_input', context))
        return AWAITING_BULK_VALUE
        
    sign = match.group(1)
    value = float(match.group(2))
    change_value = value if sign == '+' else -value
    context.user_data['bulk_change_value'] = change_value

    return await show_bulk_confirmation(update, context)

async def confirm_bulk_action_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    if query.data == 'cancel_bulk_action':
        await query.message.edit_text(t('bulk_update_cancelled', context))
        return await start(query, context)

    user_count = len(context.user_data.get('bulk_users_list', []))
    await query.message.edit_text(t('bulk_update_started', context, user_count=user_count), parse_mode=ParseMode.HTML)
    
    background_task_data = {
        'bot': context.bot,
        'chat_id': update.effective_chat.id,
        'message_id_to_delete': query.message.message_id,
        'lang': get_lang(context),
        'languages_dict': LANGUAGES,
        'bulk_users_list': context.user_data['bulk_users_list'],
        'bulk_edit_type': context.user_data['bulk_edit_type'],
        'bulk_change_value': context.user_data['bulk_change_value']
    }
    
    logger.info("Scheduling background task with asyncio.create_task")
    asyncio.create_task(run_bulk_update_background(background_task_data))
    
    return ConversationHandler.END

async def run_bulk_update_background(task_data: dict):
    bot = task_data['bot']
    chat_id = task_data['chat_id']
    lang = task_data['lang']
    languages_dict = task_data['languages_dict']
    
    def job_t(key, **kwargs):
        return languages_dict.get(lang, languages_dict['en']).get(key, key).format(**kwargs)

    try:
        logger.info(f"BACKGROUND TASK: Starting for chat_id: {chat_id}")
        users = task_data['bulk_users_list']
        edit_type = task_data['bulk_edit_type']
        change_value = task_data['bulk_change_value']
        
        success_count = 0
        failed_count = 0
        skipped_count = 0
        
        for user in users:
            user_uuid = user.get('uuid')
            username = user.get('username', 'N/A')
            
            if not user_uuid:
                failed_count += 1
                continue
            
            payload = {'uuid': user_uuid}
            should_update = False
            
            if edit_type == 'volume':
                current_limit = user.get('trafficLimitBytes')
                if current_limit is None or current_limit == 0:
                    skipped_count += 1
                    continue
                
                bytes_to_change = int(change_value * (1024**3))
                new_limit = current_limit + bytes_to_change
                payload['trafficLimitBytes'] = max(0, new_limit)
                should_update = True
            
            elif edit_type == 'date':
                current_expire_str = user.get('expireAt')
                if not current_expire_str:
                    skipped_count += 1
                    continue

                current_expire_dt = parse_iso_date(current_expire_str)
                if not current_expire_dt:
                    failed_count += 1
                    continue
                
                new_expire_dt = current_expire_dt + timedelta(days=int(change_value))
                payload['expireAt'] = new_expire_dt.isoformat().replace('+00:00', 'Z')
                should_update = True
            
            elif edit_type == 'hwid':
                payload['hwidDeviceLimit'] = int(change_value)
                should_update = True
            
            if should_update:
                _, error = await asyncio.to_thread(
                    api_request, 'PATCH', '/api/users', payload=payload
                )
                
                if error:
                    failed_count += 1
                    logger.error(f"Bulk update FAILED for user {username}: {error}")
                else:
                    success_count += 1

        logger.info(f"BACKGROUND TASK finished. Success: {success_count}, Failed: {failed_count}, Skipped: {skipped_count}")
        
        final_message = job_t('bulk_update_complete_detailed', 
                              success_count=success_count, 
                              failed_count=failed_count, 
                              skipped_count=skipped_count,
                              skipped_reason_unlimited=job_t('skipped_reason_unlimited') if edit_type != 'hwid' else "")
        
        keyboard = [[InlineKeyboardButton(job_t('back_to_main_menu_btn'), callback_data='back_to_main')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await bot.send_message(
            chat_id=chat_id, 
            text=final_message, 
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )

    except Exception as e:
        logger.error(f"FATAL ERROR in background task for chat_id {chat_id}: {e}", exc_info=True)
        error_message = f"❌ یک خطای پیش‌بینی نشده در حین عملیات گروهی رخ داد. لطفاً لاگ‌های ربات را بررسی کنید.\n\n`{e}`"
        await bot.send_message(chat_id=chat_id, text=error_message, parse_mode=ParseMode.MARKDOWN)
    
    finally:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=task_data['message_id_to_delete'])
        except Exception as e:
            logger.warning(f"Could not delete 'in progress' message {task_data['message_id_to_delete']}: {e}")

# --- End of Bulk Edit Feature ---

# --- User Update Report Feature ---
async def process_hours_and_fetch_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        hours = int(update.message.text)
        if hours <= 0: raise ValueError
    except (ValueError, TypeError):
        await update.message.reply_text(t('invalid_hours_input', context))
        return AWAITING_HOURS_FOR_UPDATED_LIST

    prompt_message_id = context.user_data.pop('prompt_message_id', None)
    try:
        if prompt_message_id: await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=prompt_message_id)
        await update.message.delete()
    except BadRequest:
        pass
        
    wait_message = await context.bot.send_message(chat_id=update.effective_chat.id, text=t('fetching_updated_users', context))

    all_users_response, error = await api_request_get_all_users()
    
    if error:
        await wait_message.edit_text(t('error_fetching_all_users', context, error=error))
        return ConversationHandler.END

    all_users_list = all_users_response.get('response', {}).get('users', [])
    now_utc = datetime.now(timezone.utc)
    time_threshold = now_utc - timedelta(hours=hours)
    
    updated_users = []
    inactive_users = []
    
    for user in all_users_list:
        username = user.get('username')
        if not username: continue
        
        last_opened_str = user.get('subLastOpenedAt')
        if last_opened_str:
            last_opened_dt = parse_iso_date(last_opened_str)
            if last_opened_dt and last_opened_dt >= time_threshold:
                updated_users.append(username)
                continue
        
        inactive_users.append(username)

    updated_users.sort()
    inactive_users.sort()
    
    if not updated_users and not inactive_users and len(all_users_list) > 0:
        await wait_message.edit_text(t('no_users_found_in_period', context, hours=hours), parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t('back_to_main_menu_btn', context), callback_data='back_to_main')]]))
        return ConversationHandler.END

    summary_text = t('updated_users_summary', context, 
                     total_count=len(all_users_list), 
                     updated_count=len(updated_users), 
                     not_updated_count=len(inactive_users),
                     hours=hours)
    
    keyboard = [[InlineKeyboardButton(t('back_to_main_menu_btn', context), callback_data='back_to_main')]]
    
    await wait_message.edit_text(summary_text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))

    report_content = ""
    report_content += f"--- {t('updated_list_header', context)} ({len(updated_users)}) ---\n"
    if updated_users:
        report_content += "\n".join(updated_users)
    else:
        report_content += "-\n"
        
    report_content += f"\n\n--- {t('inactive_list_header', context)} ({len(inactive_users)}) ---\n"
    if inactive_users:
        report_content += "\n".join(inactive_users)
    else:
        report_content += "-\n"

    report_file = io.BytesIO(report_content.encode('utf-8'))
    
    await context.bot.send_document(
        chat_id=update.effective_chat.id,
        document=report_file,
        filename=f'user_update_report_{hours}h.txt',
        caption=t('user_activity_report_caption', context, hours=hours)
    )

    return ConversationHandler.END
# --- END OF NEW FEATURE ---

async def process_timezone_setting(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        await update.message.delete()
        prompt_message_id = context.user_data.pop('prompt_message_id', None)
        if prompt_message_id:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=prompt_message_id)
    except BadRequest:
        pass

    tz_string = update.message.text.strip()
    match = re.match(r'GMT([+-])(\d{1,2}):(\d{2})/(\d{2}):(\d{2})', tz_string.upper())

    if not match:
        msg = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=t('invalid_timezone_format', context),
            parse_mode=ParseMode.HTML
        )
        context.job_queue.run_once(lambda ctx: ctx.bot.delete_message(msg.chat_id, msg.message_id), 10)
        # Resend the prompt
        settings = get_settings()
        current_setting = settings.get('expire_time_setting', t('not_set', context))
        keyboard = [[InlineKeyboardButton(t('back_to_main_menu_btn', context), callback_data='back_to_main')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        prompt_message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=t('ask_for_timezone_and_time', context, current_setting=current_setting),
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
        context.user_data['prompt_message_id'] = prompt_message.message_id
        return AWAITING_TIMEZONE_SETTING

    settings = get_settings()
    settings['expire_time_setting'] = tz_string.upper()
    save_settings(settings)

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=t('timezone_set_success', context),
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t('back_to_main_menu_btn', context), callback_data='back_to_main')]]),
        parse_mode=ParseMode.HTML
    )
    return MAIN_MENU

async def get_new_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['new_user_data']['username'] = update.message.text
    try:
        await update.message.delete()
    except BadRequest: pass
    await context.bot.edit_message_text(
        chat_id=update.effective_chat.id,
        message_id=context.user_data.get('prompt_message_id'),
        text=t('ask_for_data_limit', context),
        parse_mode=ParseMode.HTML
    )
    return AWAITING_DATA_LIMIT

async def get_data_limit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        limit_gb = int(update.message.text)
        if limit_gb < 0: raise ValueError
        context.user_data['new_user_data']['trafficLimitBytes'] = limit_gb * (1024**3)
        await update.message.delete()
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=context.user_data.get('prompt_message_id'),
            text=t('ask_for_expire_days', context)
        )
        return AWAITING_EXPIRE_DAYS
    except (ValueError, TypeError):
        msg = await update.message.reply_text(t('invalid_number', context))
        context.job_queue.run_once(lambda ctx: ctx.bot.delete_message(msg.chat_id, msg.message_id), 5)
        return AWAITING_DATA_LIMIT

async def get_expire_days(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        days = int(update.message.text)
        if days < 0: raise ValueError
        
        expire_time_setting = parse_timezone_setting()
        if expire_time_setting:
            target_tz, target_time = expire_time_setting
            now_in_target_tz = datetime.now(target_tz)
            expire_date_local = now_in_target_tz + timedelta(days=days)
            expire_datetime_local = expire_date_local.replace(
                hour=target_time.hour, minute=target_time.minute, second=0, microsecond=0
            )
            expire_datetime_utc = expire_datetime_local.astimezone(timezone.utc)
        else:
            # Fallback to original behavior
            expire_datetime_utc = datetime.now(timezone.utc) + timedelta(days=days)
            expire_datetime_utc = expire_datetime_utc.replace(hour=18, minute=30, second=0, microsecond=0)
        
        context.user_data['new_user_data']['expireAt'] = expire_datetime_utc.isoformat().replace('+00:00', 'Z')
        
        await update.message.delete()
        
        keyboard = [
            [InlineKeyboardButton(t('enable_hwid_btn', context), callback_data='hwid_enable')],
            [InlineKeyboardButton(t('disable_hwid_btn', context), callback_data='hwid_disable')]
        ]
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=context.user_data.get('prompt_message_id'),
            text=t('ask_hwid_limit_prompt', context),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return SELECTING_HWID_OPTION
    except (ValueError, TypeError):
        msg = await update.message.reply_text(t('invalid_number', context))
        context.job_queue.run_once(lambda ctx: ctx.bot.delete_message(msg.chat_id, msg.message_id), 5)
        return AWAITING_EXPIRE_DAYS


async def hwid_option_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    action = query.data

    if action == 'hwid_disable':
        context.user_data['new_user_data']['hwidDeviceLimit'] = 0
        await query.message.edit_text(t('fetching_squads_prompt', context))
        return await fetch_and_show_squads(update, context, message_id=query.message.message_id)
    
    elif action == 'hwid_enable':
        await query.message.edit_text(t('ask_for_hwid_value', context))
        return AWAITING_HWID_VALUE

async def get_hwid_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        limit = int(update.message.text)
        if limit <= 0: raise ValueError
        context.user_data['new_user_data']['hwidDeviceLimit'] = limit
        await update.message.delete()
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=context.user_data.get('prompt_message_id'),
            text=t('fetching_squads_prompt', context)
        )
        return await fetch_and_show_squads(update, context, message_id=context.user_data.get('prompt_message_id'))
    except (ValueError, TypeError):
        msg = await update.message.reply_text(t('invalid_number', context))
        context.job_queue.run_once(lambda ctx: ctx.bot.delete_message(msg.chat_id, msg.message_id), 5)
        return AWAITING_HWID_VALUE

async def fetch_and_show_squads(update: Update, context: ContextTypes.DEFAULT_TYPE, message_id: int) -> int:
    squads_data, error = await asyncio.to_thread(api_request, 'GET', '/api/internal-squads')
    
    if error or not squads_data or 'response' not in squads_data or 'internalSquads' not in squads_data['response']:
        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=message_id, text=t('fetching_squads_error', context))
        return await start(update, context)
    
    context.user_data['available_squads'] = squads_data['response']['internalSquads']
    context.user_data['selected_squads'] = set() 

    keyboard = build_squad_keyboard(context)
    await context.bot.edit_message_text(
        chat_id=update.effective_chat.id,
        message_id=message_id,
        text=t('select_squads_prompt', context),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SELECTING_SQUADS

def build_squad_keyboard(context: ContextTypes.DEFAULT_TYPE) -> list:
    keyboard = []
    available = context.user_data.get('available_squads', [])
    selected = context.user_data.get('selected_squads', set())
    
    for squad in available:
        squad_name = squad['name']
        squad_uuid = squad['uuid']
        display_name = f"✅ {squad_name}" if squad_uuid in selected else squad_name
        keyboard.append([InlineKeyboardButton(display_name, callback_data=f"squad_{squad_uuid}")])
    
    keyboard.append([InlineKeyboardButton(t('done_squad_selection_btn', context), callback_data='create_user_final')])
    return keyboard

async def squad_selection_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    action = query.data
    
    if action == 'create_user_final':
        return await create_user(update, context)
        
    squad_uuid = action.split('_', 1)[1]
    selected_squads = context.user_data.get('selected_squads', set())
    
    if squad_uuid in selected_squads:
        selected_squads.remove(squad_uuid)
    else:
        selected_squads.add(squad_uuid)
        
    context.user_data['selected_squads'] = selected_squads
    
    keyboard = build_squad_keyboard(context)
    try:
        await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
    except BadRequest: pass
    return SELECTING_SQUADS

def generate_random_string(length):
    letters_and_digits = string.ascii_letters + string.digits
    return ''.join(random.choice(letters_and_digits) for i in range(length))

def build_user_created_message(response_data: dict, context: ContextTypes.DEFAULT_TYPE) -> str:
    username = html.escape(response_data.get('username', ''))
    limit = format_bytes(response_data.get('trafficLimitBytes'))
    sub_link = html.escape(response_data.get('subscriptionUrl', t('not_found', context)))
    
    expire_date = t('unlimited', context)
    expire_dt = parse_iso_date(response_data.get('expireAt'))
    if expire_dt:
        expire_date = expire_dt.strftime("%Y/%m/%d")

    return t('user_created_success_detailed', context, 
             username=username, 
             limit=limit, 
             expire_date=expire_date, 
             sub_link=sub_link)

async def create_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    new_user_info = context.user_data.get('new_user_data', {})
    selected_squad_uuids = list(context.user_data.get('selected_squads', []))
    
    username = new_user_info.get('username')
    
    await query.message.edit_text(
        t('creating_user', context, username=username),
        parse_mode=ParseMode.HTML
    )
    
    traffic_limit = new_user_info.get('trafficLimitBytes')
    hwid_limit = new_user_info.get('hwidDeviceLimit')

    payload = {
        "username": username,
        "status": "ACTIVE",
        "trojanPassword": generate_random_string(10),
        "vlessUuid": str(uuid.uuid4()),
        "ssPassword": generate_random_string(10),
        "trafficLimitBytes": traffic_limit,
        "trafficLimitStrategy": "NO_RESET",
        "expireAt": new_user_info.get('expireAt'),
        "description": "",
        "tag": generate_random_string(8).upper(),
        "email": f"{generate_random_string(5)}@placeholder.com",
        "telegramId": 0,
        "hwidDeviceLimit": hwid_limit,
        "activeInternalSquads": selected_squad_uuids
    }
    
    data, error = await asyncio.to_thread(api_request, 'POST', '/api/users', payload=payload)
    
    if error:
        keyboard = [[InlineKeyboardButton(t('back_to_main_menu_btn', context), callback_data='back_to_main')]]
        message_text = t('error_creating_user', context, error=html.escape(error))
        await query.message.edit_text(
            text=message_text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return MAIN_MENU

    # Store created user data specifically for the banner menu
    context.user_data['created_user_response'] = data.get('response', {})
    
    # Show the selection menu
    return await show_banner_selection_menu(update, context)
    
async def show_banner_selection_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Helper to determine if we are editing a message or sending a new one (after photo deletion)
    query = update.callback_query
    
    user_response = context.user_data.get('created_user_response', {})
    username = user_response.get('username', 'Unknown')

    keyboard = [
        [InlineKeyboardButton(t('btn_happ_banner', context), callback_data='banner_happ')],
        [InlineKeyboardButton(t('btn_sub_banner', context), callback_data='banner_sub')],
        [InlineKeyboardButton(t('back_to_main_menu_btn', context), callback_data='back_to_main')]
    ]
    
    text = t('user_created_select_format', context, username=html.escape(username))
    
    # Try to edit, if fails (e.g. previous was a photo), send new
    try:
        if query and query.message:
            await query.message.edit_text(text=text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
        else:
            # Fallback if accessed differently
            await context.bot.send_message(chat_id=update.effective_chat.id, text=text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    except BadRequest:
        # Likely trying to edit a photo message to text, delete and send text
        if query and query.message:
            await query.message.delete()
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
        
    return USER_CREATED_MENU

async def banner_generation_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    action = query.data
    
    if action == 'back_to_banner_menu':
        return await show_banner_selection_menu(update, context)
        
    user_response = context.user_data.get('created_user_response', {})
    if not user_response:
        await query.message.reply_text("Session expired. Please verify user in Manage User.")
        return MAIN_MENU

    # Extract Info
    username = user_response.get('username')
    limit = format_bytes(user_response.get('trafficLimitBytes'))
    raw_sub_link = user_response.get('subscriptionUrl', '')
    
    expire_dt = parse_iso_date(user_response.get('expireAt'))
    expire_date_str = t('unlimited', context)
    if expire_dt:
        expire_date_str = expire_dt.strftime("%Y/%m/%d")

    # Determine Link type
    final_link = raw_sub_link
    loading_msg = await context.bot.send_message(chat_id=update.effective_chat.id, text="⏳ Generating Banner...")
    
    try:
        if action == 'banner_happ':
            # Encrypt for Happ
            encrypt_payload = {"linkToEncrypt": raw_sub_link}
            enc_data, enc_error = await asyncio.to_thread(api_request, 'POST', '/api/system/tools/happ/encrypt', payload=encrypt_payload)
            if not enc_error and enc_data and 'response' in enc_data:
                final_link = enc_data['response'].get('encryptedLink')
        
        # Format Caption
        caption = t('banner_caption_template', context,
                    username=html.escape(username),
                    limit=limit,
                    expire_date=expire_date_str,
                    link=html.escape(final_link))

        # Generate QR
        qr_bytes = generate_qr_code(final_link)
        
        # Keyboard
        keyboard = [
            [InlineKeyboardButton(t('back_to_banner_select', context), callback_data='back_to_banner_menu')],
            [InlineKeyboardButton(t('back_to_main_menu_btn', context), callback_data='back_to_main')]
        ]

        # Cleanup previous menu/loading
        try: await query.message.delete()
        except: pass
        await loading_msg.delete()

        # Send Photo
        if qr_bytes:
            # Check caption length limit (1024 chars). If too long, send as text.
            if len(caption) > 1024:
                await context.bot.send_photo(chat_id=update.effective_chat.id, photo=qr_bytes)
                await context.bot.send_message(chat_id=update.effective_chat.id, text=caption, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                await context.bot.send_photo(chat_id=update.effective_chat.id, photo=qr_bytes, caption=caption, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=caption, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))

        return USER_CREATED_MENU

    except Exception as e:
        logger.error(f"Error generating banner: {e}")
        try: await loading_msg.delete()
        except: pass
        await query.message.reply_text(f"Error: {str(e)}")
        return USER_CREATED_MENU

async def set_lang_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    lang_code = query.data.split('_')[-1]
    context.user_data['lang'] = lang_code; set_language_file(lang_code)
    await context.bot.delete_my_commands(); await context.bot.set_my_commands(COMMANDS.get(lang_code, COMMANDS['en']))
    return await start(update, context)

# === CHANGE START ===
async def show_user_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    username_to_fetch = context.user_data.get('username')
    if update.message and not username_to_fetch:
        username_to_fetch = update.message.text
    
    try:
        if update.message: await update.message.delete()
        prompt_message_id = context.user_data.pop('prompt_message_id', None)
        if prompt_message_id:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=prompt_message_id)
    except BadRequest: pass

    get_lang(context)
    if not username_to_fetch: return await start(update, context)
    context.user_data['username'] = username_to_fetch
    sent_message = await context.bot.send_message(chat_id=update.effective_chat.id, text=t('fetching_user_info', context, username=username_to_fetch), parse_mode=ParseMode.HTML)
    
    data, error = await asyncio.to_thread(api_request, 'GET', f'/api/users/by-username/{username_to_fetch}')

    if error:
        await sent_message.edit_text(t('error_fetching', context, error=error), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t('back_to_main_menu_btn', context), callback_data='back_to_main')]])); return AWAITING_USERNAME
    user_data = data.get('response', {});
    context.user_data['user_data'] = user_data; context.user_data['user_uuid'] = user_data.get('uuid')
    message_text = build_user_info_message(user_data, context)

    enable_disable_button = InlineKeyboardButton(t('disable_user_btn', context), callback_data='disable_user') \
        if user_data.get('status') == 'ACTIVE' \
        else InlineKeyboardButton(t('enable_user_btn', context), callback_data='enable_user')
    
    keyboard_list = [
        [
            InlineKeyboardButton(t('edit_volume_btn', context), callback_data='edit_limit'),
            InlineKeyboardButton(t('edit_date_btn', context), callback_data='edit_expire')
        ],
        [
            InlineKeyboardButton(t('edit_hwid_btn', context), callback_data='edit_hwid'),
            InlineKeyboardButton(t('reset_usage_btn', context), callback_data='reset_usage')
        ],
        [
            enable_disable_button,
            InlineKeyboardButton(t('refresh_btn', context), callback_data='refresh')
        ],
        [
            InlineKeyboardButton(t('show_qr_btn', context), callback_data='show_qr'),
            InlineKeyboardButton(t('get_happ_qr_btn', context), callback_data='get_happ_qr')
        ],
        [
            InlineKeyboardButton(t('delete_user_btn', context), callback_data='delete_user')
            InlineKeyboardButton(t('user_links_btn', context), callback_data='show_all_links')
        ],
        [
            InlineKeyboardButton(t('back_to_main_menu_btn', context), callback_data='back_to_main')
        ]
    ]
    
    await sent_message.edit_text(text=message_text, reply_markup=InlineKeyboardMarkup(keyboard_list), parse_mode=ParseMode.HTML)
    return USER_MENU
# === CHANGE END ===

async def user_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); action = query.data
    
    if action == 'edit_limit':
        prompt_message = await query.message.edit_text(text=t('ask_for_new_limit', context, username=html.escape(context.user_data.get('username', ''))), parse_mode=ParseMode.HTML)
        context.user_data['edit_prompt_message_id'] = prompt_message.message_id
        context.user_data['editing'] = 'limit'
        return AWAITING_LIMIT
    elif action == 'edit_expire':
        prompt_message = await query.message.edit_text(text=t('ask_for_new_expire', context, username=html.escape(context.user_data.get('username', ''))), parse_mode=ParseMode.HTML)
        context.user_data['edit_prompt_message_id'] = prompt_message.message_id
        context.user_data['editing'] = 'expire'
        return AWAITING_EXPIRE
    elif action == 'edit_hwid':
        prompt_message = await query.message.edit_text(text=t('ask_for_new_hwid_limit', context, username=html.escape(context.user_data.get('username', ''))), parse_mode=ParseMode.HTML)
        context.user_data['edit_prompt_message_id'] = prompt_message.message_id
        context.user_data['editing'] = 'hwid'
        return AWAITING_HWID_EDIT
    
    if action == 'refresh':
        await query.message.delete(); return await show_user_card(update, context)
    
    user_data = context.user_data.get('user_data', {})

    if action == 'delete_user':
        username = user_data.get('username')
        text = t('delete_confirm_prompt', context, username=html.escape(username))
        keyboard = [[
            InlineKeyboardButton(t('confirm_delete_btn', context), callback_data='confirm_delete'),
            InlineKeyboardButton(t('cancel_delete_btn', context), callback_data='cancel_delete')
        ]]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
        return CONFIRM_DELETE
        
    if action == 'show_all_links':
        username = context.user_data.get('username')
        await query.answer()
        wait_msg = await query.message.reply_text("⏳ دریافت لینک‌ها...")
        
        sub_data, sub_error = await asyncio.to_thread(api_request, 'GET', f'/api/subscriptions/by-username/{username}')
        await wait_msg.delete()

        if sub_error or not sub_data:
            await query.message.reply_text(t('error_fetching', context, error=sub_error))
            return USER_MENU

        links = sub_data.get('response', {}).get('links', [])
        if not links:
            await query.message.reply_text(t('no_links_found', context))
            return USER_MENU

        links_text = t('user_links_title', context, username=html.escape(username)) + "\n\n"
        for link in links:
            links_text += f"<code>{html.escape(link)}</code>\n\n"

        keyboard = [[InlineKeyboardButton(t('back_to_user_info_btn', context), callback_data='back_to_user_info')]]
        
        await query.message.edit_text(text=links_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
        return QR_VIEW
    
    if action == 'get_happ_qr':
        username = context.user_data.get('username')
        if not username:
            await query.answer(text=t('not_found', context), show_alert=True)
            return USER_MENU

        wait_msg = await query.message.reply_text("⏳ در حال تولید لینک Happ...")
        
        # مرحله 1: دریافت لینک سابسکریپشن خام
        sub_data, sub_error = await asyncio.to_thread(api_request, 'GET', f'/api/subscriptions/by-username/{username}')
        
        if sub_error or not sub_data or 'response' not in sub_data:
            try: await wait_msg.delete()
            except: pass
            await query.answer(text=f"خطا در دریافت اشتراک: {sub_error}", show_alert=True)
            return USER_MENU

        # لینک معمولی (https://...)
        raw_sub_url = sub_data['response'].get('subscriptionUrl')
        
        if not raw_sub_url:
            try: await wait_msg.delete()
            except: pass
            await query.answer(text="لینک اشتراک یافت نشد.", show_alert=True)
            return USER_MENU

        # مرحله 2: تبدیل به لینک Happ (رمزنگاری)
        # طبق مستندات: POST /api/system/tools/happ/encrypt
        encrypt_payload = {"linkToEncrypt": raw_sub_url}
        enc_data, enc_error = await asyncio.to_thread(api_request, 'POST', '/api/system/tools/happ/encrypt', payload=encrypt_payload)
        
        try: await wait_msg.delete() 
        except: pass

        final_happ_link = None
        
        if not enc_error and enc_data and 'response' in enc_data:
            final_happ_link = enc_data['response'].get('encryptedLink')
        
        # فال‌بک: اگر رمزنگاری انجام نشد، همان لینک اصلی را بده
        if not final_happ_link:
            final_happ_link = raw_sub_url

        # نمایش QR کد و لینک کامل
        if final_happ_link:
            qr_code_bytes = generate_qr_code(final_happ_link)
            if qr_code_bytes:
                caption = t('happ_qr_caption', context, username=html.escape(username))
                
                # --- اصلاحیه: نمایش لینک کامل بدون کوتاه کردن ---
                # تلگرام محدودیت 1024 کاراکتر برای کپشن عکس دارد.
                # اگر لینک خیلی طولانی باشد، ممکن است ارور دهد، اما معمولاً لینک‌های Happ جا می‌شوند.
                full_caption = f"{caption}\n<pre>{html.escape(final_happ_link)}</pre>"
                
                # بررسی محدودیت طول کپشن تلگرام (1024 کاراکتر)
                if len(full_caption) > 1024:
                    # اگر لینک خیلی خیلی طولانی بود و در کپشن جا نشد، آن را به عنوان یک پیام متنی جداگانه می‌فرستیم
                    # اول عکس QR را با کپشن کوتاه بفرست
                    short_caption = f"{caption}\n(لینک طولانی است، آن را در پیام بعدی کپی کنید 👇)"
                    media = InputMediaPhoto(media=qr_code_bytes, caption=short_caption, parse_mode=ParseMode.HTML)
                    
                    # دکمه بازگشت
                    keyboard = [[InlineKeyboardButton(t('back_to_user_info_btn', context), callback_data='back_to_user_info')]]
                    
                    try:
                        await query.message.edit_media(media=media, reply_markup=InlineKeyboardMarkup(keyboard))
                    except BadRequest:
                        await query.message.delete()
                        await context.bot.send_photo(chat_id=update.effective_chat.id, photo=qr_code_bytes, caption=short_caption, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
                    
                    # سپس لینک کامل را به صورت متن بفرست تا کاربر بتواند کپی کند
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id, 
                        text=f"<pre>{html.escape(final_happ_link)}</pre>", 
                        parse_mode=ParseMode.HTML
                    )
                    return QR_VIEW

                else:
                    # حالت عادی: لینک در کپشن جا می‌شود
                    media = InputMediaPhoto(media=qr_code_bytes, caption=full_caption, parse_mode=ParseMode.HTML)
                    keyboard = [[InlineKeyboardButton(t('back_to_user_info_btn', context), callback_data='back_to_user_info')]]
                    
                    try:
                        await query.message.edit_media(media=media, reply_markup=InlineKeyboardMarkup(keyboard))
                    except BadRequest:
                        await query.message.delete()
                        await context.bot.send_photo(chat_id=update.effective_chat.id, photo=qr_code_bytes, caption=full_caption, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
                    
                    return QR_VIEW
        else:
            await query.answer(text="خطا در تولید لینک.", show_alert=True)
            return USER_MENU

    if action in ['enable_user', 'disable_user', 'reset_usage']:
        action_str, popup_text, success_text = '', '', ''
        if action == 'enable_user': action_str, popup_text, success_text = 'enable', t('enabling_user', context), t('user_enabled_success', context)
        elif action == 'disable_user': action_str, popup_text, success_text = 'disable', t('disabling_user', context), t('user_disabled_success', context)
        elif action == 'reset_usage': action_str, popup_text, success_text = 'reset-traffic', t('reseting_usage', context), t('reset_usage_success', context)
        await query.answer(text=popup_text, show_alert=False)
        user_uuid = context.user_data.get('user_uuid')
        if not user_uuid: await query.answer(text="Error: User UUID not found.", show_alert=True); return USER_MENU
        endpoint = f'/api/users/{user_uuid}/actions/{action_str}'
        _, error = await asyncio.to_thread(api_request, 'POST', endpoint)
        if error: await query.answer(text=f"API Error: {error}", show_alert=True)
        else:
            await query.answer(text=success_text, show_alert=False)
            await query.message.delete()
            return await show_user_card(update, context)
        return USER_MENU
        
    if action == 'show_qr':
        subscription_url = user_data.get('subscriptionUrl')
        qr_code_bytes = generate_qr_code(subscription_url)
        if qr_code_bytes:
            media = InputMediaPhoto(media=qr_code_bytes)
            keyboard = [[InlineKeyboardButton(t('back_to_user_info_btn', context), callback_data='back_to_user_info')]]
            await query.message.edit_media(media=media, reply_markup=InlineKeyboardMarkup(keyboard))
            return QR_VIEW
        return USER_MENU
        
    return USER_MENU

async def delete_user_confirmation_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    action = query.data

    if action == 'cancel_delete':
        await query.message.delete()
        return await show_user_card(update, context)

    if action == 'confirm_delete':
        user_uuid = context.user_data.get('user_uuid')
        username = context.user_data.get('username', '')
        
        await query.message.edit_text(f"⏳ در حال حذف کاربر {username}...")
        
        _, error = await asyncio.to_thread(api_request, 'DELETE', f'/api/users/{user_uuid}')
        
        final_text = ""
        if error:
            final_text = f"❌ Error deleting user: {error}"
        else:
            final_text = t('user_deleted_success', context, username=html.escape(username))
        
        await query.message.edit_text(text=final_text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t('back_to_main_menu_btn', context), callback_data='back_to_main')]]))
        return MAIN_MENU
        
    return USER_MENU

async def back_to_user_info_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    await query.message.delete()
    return await show_user_card(update, context)

async def set_new_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        await update.message.delete()
    except BadRequest: pass

    prompt_message_id = context.user_data.pop('edit_prompt_message_id', None)
    if prompt_message_id:
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=prompt_message_id)
        except BadRequest:
            pass

    user_uuid = context.user_data.get('user_uuid')
    if not user_uuid: return await start(update, context)
    
    payload = {'uuid': user_uuid}
    current_state = AWAITING_LIMIT

    try:
        editing_type = context.user_data.get('editing')
        if editing_type == 'limit':
            new_limit_gb = float(update.message.text)
            payload["trafficLimitBytes"] = int(new_limit_gb * 1024**3)
            current_state = AWAITING_LIMIT
        elif editing_type == 'expire':
            days = int(update.message.text)
            expire_time_setting = parse_timezone_setting()
            if expire_time_setting:
                target_tz, target_time = expire_time_setting
                now_in_target_tz = datetime.now(target_tz)
                new_expire_date_local = now_in_target_tz + timedelta(days=days)
                new_expire_datetime_local = new_expire_date_local.replace(
                    hour=target_time.hour, minute=target_time.minute, second=0, microsecond=0
                )
                new_expire_datetime_utc = new_expire_datetime_local.astimezone(timezone.utc)
            else:
                new_expire_datetime_utc = datetime.now(timezone.utc) + timedelta(days=days)
                new_expire_datetime_utc = new_expire_datetime_utc.replace(hour=18, minute=30, second=0, microsecond=0)

            payload["expireAt"] = new_expire_datetime_utc.isoformat().replace('+00:00', 'Z')
            current_state = AWAITING_EXPIRE
        elif editing_type == 'hwid':
            new_hwid_limit = int(update.message.text)
            if new_hwid_limit < 0: raise ValueError
            payload["hwidDeviceLimit"] = new_hwid_limit
            current_state = AWAITING_HWID_EDIT

    except (ValueError, TypeError):
        msg = await context.bot.send_message(chat_id=update.effective_chat.id, text=t('invalid_number', context))
        context.job_queue.run_once(lambda j: j.context.delete(), 5, context=msg)
        return current_state

    _, error = await asyncio.to_thread(api_request, 'PATCH', '/api/users', payload=payload)
    
    if error: 
        msg = await context.bot.send_message(chat_id=update.effective_chat.id, text=t('update_failed', context, error=error))
        context.job_queue.run_once(lambda j: j.context.delete(), 5, context=msg)
    
    return await show_user_card(update, context)


async def logs_node_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer();
    node_name = query.data.split('_')[1]
    
    await query.message.edit_text(text=t('fetching_logs', context, node_name=node_name), parse_mode=ParseMode.HTML)
    
    logs, error = await asyncio.to_thread(get_logs_from_node, node_name)
    MAX_LOG_LENGTH = 3800
    if logs and len(logs) > MAX_LOG_LENGTH: logs = f"...\n{logs[-MAX_LOG_LENGTH:]}"
    if error:
        message_text = t('error_fetching_logs', context, node_name=node_name, details=html.escape(str(error or "")))
        keyboard = [[InlineKeyboardButton(t('back_to_nodes_btn', context), callback_data='go_view_logs')]]
    else:
        safe_logs = html.escape(logs or t('logs_empty', context))
        message_text = f"{t('logs_title', context, node_name=node_name)}\n\n<pre><code>{safe_logs}</code></pre>"
        keyboard = [[InlineKeyboardButton(t('refresh_logs_btn', context), callback_data=f'lognode_{node_name}')], [InlineKeyboardButton(t('back_to_nodes_btn', context), callback_data='go_view_logs')]]
    
    await query.message.edit_text(text=message_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    return VIEWING_LOGS

async def restart_node_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    node_name = query.data.split('_')[1]
    await query.message.edit_text(t('restarting_node', context, node_name=node_name), parse_mode=ParseMode.HTML)
    
    def run_restart():
        node_config = config.NODES.get(node_name)
        output, error = "", ""
        if not node_config:
            return "", "Node not found in config"
            
        if node_config['type'] == 'local':
            command = "cd /opt/remnanode && docker compose down && docker compose up -d && sleep 5 && docker compose logs --tail=20"
            try:
                result = subprocess.run(command, shell=True, capture_output=True, text=True, check=True, encoding='utf-8')
                output = result.stdout.strip()
            except subprocess.CalledProcessError as e: error = e.stderr.strip()
        elif node_config['type'] == 'remote':
            try:
                parsed_url = urlparse(node_config.get('url', '')); ip = parsed_url.hostname
                if ip:
                    restart_url = f"http://{ip}:5555/restart"; headers = {'Authorization': f"Bearer {node_config['token']}"}
                    response = requests.post(restart_url, headers=headers, timeout=90); response.raise_for_status()
                    data = response.json(); output = data.get('logs')
                    if data.get('status') != 'success': error = data.get('details', 'Unknown remote error')
                else: error = "Could not parse IP from node URL."
            except Exception as e: error = str(e)
        return output, error

    output, error = await asyncio.to_thread(run_restart)

    if error: message_text = f"{t('node_restart_failed', context, node_name=node_name)}\n\n<pre><code>{html.escape(error)}</code></pre>"
    else: message_text = f"{t('node_restart_success', context, node_name=node_name)}\n\n<b>{t('logs_title', context, node_name=node_name)}</b>\n<pre><code>{html.escape(output)}</code></pre>"
    keyboard = [[InlineKeyboardButton(t('back_to_restart_list_btn', context), callback_data='go_restart_nodes')]]
    await query.message.edit_text(message_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    return MAIN_MENU

# --- Start of Expiring Users Feature ---
async def show_expiring_users_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    keyboard = [
        [InlineKeyboardButton(t('expiring_today_btn', context), callback_data='expiring_0')],
        [InlineKeyboardButton(t('expiring_tomorrow_btn', context), callback_data='expiring_1')],
        [InlineKeyboardButton(t('expiring_day_after_tomorrow_btn', context), callback_data='expiring_2')],
        [InlineKeyboardButton(t('back_to_main_menu_btn', context), callback_data='back_to_main')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.edit_text(text=t('expiring_users_prompt', context), reply_markup=reply_markup)
    return EXPIRING_USERS_MENU

async def expiring_users_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    days_offset = int(query.data.split('_')[1])
    
    await query.message.edit_text(text=t('fetching_expiring_users', context))
    
    all_users_response, error = await api_request_get_all_users()
    
    keyboard_back = [[InlineKeyboardButton(t('back_btn', context), callback_data='go_expiring_users')]]
    reply_markup_back = InlineKeyboardMarkup(keyboard_back)

    if error:
        await query.message.edit_text(
            t('error_fetching_all_users', context, error=error), 
            reply_markup=reply_markup_back
        )
        return EXPIRING_USERS_MENU

    all_users_list = all_users_response.get('response', {}).get('users', [])
    
    now_utc = datetime.now(timezone.utc)
    
    if days_offset == 0: # Today
        start_range = now_utc
        end_range = now_utc.replace(hour=23, minute=59, second=59, microsecond=999999)
    else: # Tomorrow or Day after
        target_day_start = (now_utc + timedelta(days=days_offset)).replace(hour=0, minute=0, second=0, microsecond=0)
        start_range = target_day_start
        end_range = target_day_start.replace(hour=23, minute=59, second=59, microsecond=999999)

    expiring_users = []
    for user in all_users_list:
        expire_at_str = user.get('expireAt')
        if not expire_at_str:
            continue
        
        expire_dt = parse_iso_date(expire_at_str)
        if expire_dt and start_range <= expire_dt <= end_range:
            expiring_users.append({
                'username': user.get('username', 'N/A'),
                'expire_dt': expire_dt
            })
    
    expiring_users.sort(key=lambda x: x['expire_dt'])
    
    period_key_map = {0: 'today', 1: 'tomorrow', 2: 'day_after_tomorrow'}
    period_text = t(f'period_{period_key_map[days_offset]}', context)
    
    if not expiring_users:
        await query.message.edit_text(t('no_expiring_users_found', context), reply_markup=reply_markup_back)
        return EXPIRING_USERS_MENU

    target_tz_info = parse_timezone_setting()
    target_tz = target_tz_info[0] if target_tz_info else timezone.utc

    report_lines = [t('expiring_users_report_title', context, period=period_text)]
    for user in expiring_users:
        local_expire_dt = user['expire_dt'].astimezone(target_tz)
        expire_str = local_expire_dt.strftime('%Y-%m-%d %H:%M')
        report_lines.append(f"👤 `{user['username']}` - ⏳ {expire_str}")
        
    report_content = "\n".join(report_lines)
    
    if len(report_content) > 4000:
        file_lines = []
        for user in expiring_users:
            local_dt = user['expire_dt'].astimezone(target_tz)
            line = f"{user['username']} - {local_dt.strftime('%Y-%m-%d %H:%M:%S')}"
            file_lines.append(line)
        file_content = "\n".join(file_lines)
        report_file = io.BytesIO(file_content.encode('utf-8'))
        await context.bot.send_document(
            chat_id=query.effective_chat.id,
            document=report_file,
            filename=f'expiring_users_{period_key_map[days_offset]}.txt',
            caption=t('expiring_users_report_title', context, period=period_text)
        )
        await query.message.edit_text(t('user_list_sent_as_file', context), reply_markup=reply_markup_back)
    else:
        await query.message.edit_text(report_content, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup_back)

    return EXPIRING_USERS_MENU

# --- End of Expiring Users Feature ---

def main() -> None:
    application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).post_init(post_init).build()
    
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CallbackQueryHandler(start, pattern='^back_to_main$') 
        ],
        states={
            MAIN_MENU: [CallbackQueryHandler(main_menu_handler)],
            SELECTING_LANGUAGE: [CallbackQueryHandler(set_lang_callback, pattern='^set_lang_')],
            AWAITING_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, show_user_card)],
            USER_MENU: [CallbackQueryHandler(user_menu_handler)],
            QR_VIEW: [CallbackQueryHandler(back_to_user_info_handler, pattern='^back_to_user_info$')],
            AWAITING_LIMIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_new_value)],
            AWAITING_EXPIRE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_new_value)],
            AWAITING_HWID_EDIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_new_value)],
            NODE_LIST: [CallbackQueryHandler(logs_node_handler, pattern='^lognode_')],
            VIEWING_LOGS: [
                CallbackQueryHandler(logs_node_handler, pattern='^lognode_'),
                CallbackQueryHandler(show_node_list, pattern='^go_view_logs$')
            ],
            SELECT_NODE_RESTART: [CallbackQueryHandler(restart_node_handler, pattern='^restartnode_')],
            CONFIRM_DELETE: [CallbackQueryHandler(delete_user_confirmation_handler)],
            
            AWAITING_NEW_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_new_username)],
            AWAITING_DATA_LIMIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_data_limit)],
            AWAITING_EXPIRE_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_expire_days)],
            SELECTING_HWID_OPTION: [CallbackQueryHandler(hwid_option_handler, pattern='^hwid_')],
            AWAITING_HWID_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_hwid_value)],
            SELECTING_SQUADS: [CallbackQueryHandler(squad_selection_handler, pattern='^squad_|^create_user_final$')],
            
            USER_CREATED_MENU: [
                CallbackQueryHandler(banner_generation_handler, pattern='^banner_'),
                CallbackQueryHandler(show_banner_selection_menu, pattern='^back_to_banner_menu$')
            ],
            
            EDIT_ALL_USERS_MENU: [CallbackQueryHandler(edit_all_users_menu_handler)],
            AWAITING_BULK_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_bulk_change_value)],
            CONFIRM_BULK_ACTION: [CallbackQueryHandler(confirm_bulk_action_handler, pattern='^(confirm|cancel)_bulk_action$')],
            SELECT_BULK_HWID_ACTION: [CallbackQueryHandler(process_bulk_hwid_action)],
            AWAITING_BULK_HWID_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_bulk_hwid_value)],
            
            AWAITING_HOURS_FOR_UPDATED_LIST: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_hours_and_fetch_users)],
            AWAITING_TIMEZONE_SETTING: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_timezone_setting)],
            
            EXPIRING_USERS_MENU: [
                CallbackQueryHandler(expiring_users_handler, pattern=r'^expiring_'),
                CallbackQueryHandler(show_expiring_users_menu, pattern=r'^go_expiring_users$')
            ],
        },
        fallbacks=[
            CommandHandler('start', start),
            CallbackQueryHandler(start, pattern='^back_to_main$')
        ], 
        allow_reentry=True
    )
    
    application.add_handler(conv_handler)
    
    logger.info("Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()
