# bot.py

import logging, requests, json, subprocess, html, io
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

# Add new states for the user creation process
(
    MAIN_MENU, SELECTING_LANGUAGE, AWAITING_USERNAME, USER_MENU, AWAITING_LIMIT,
    AWAITING_EXPIRE, NODE_LIST, VIEWING_LOGS, QR_VIEW, SELECT_NODE_RESTART,
    CONFIRM_DELETE,
    # New states for adding a user
    AWAITING_NEW_USERNAME, AWAITING_NEW_LIMIT, AWAITING_NEW_EXPIRE,
    AWAITING_HWID_CHOICE, AWAITING_HWID_LIMIT, SELECTING_SQUADS
) = range(17)


def get_lang_from_file() -> str:
    try:
        with open('settings.json', 'r', encoding='utf-8') as f: return json.load(f).get('language', 'en')
    except (FileNotFoundError, json.JSONDecodeError): return 'en'

def get_lang(context: ContextTypes.DEFAULT_TYPE) -> str:
    if 'lang' not in context.user_data: context.user_data['lang'] = get_lang_from_file()
    return context.user_data['lang']

def t(key: str, context: ContextTypes.DEFAULT_TYPE, **kwargs) -> str:
    lang = get_lang(context); return LANGUAGES.get(lang, LANGUAGES['en']).get(key, key).format(**kwargs)

def set_language_file(lang: str):
    with open('settings.json', 'w', encoding='utf-8') as f: json.dump({'language': lang}, f)

def is_admin(update: Update) -> bool:
    if not update.effective_user: return False
    return update.effective_user.id == config.ADMIN_USER_ID

def format_bytes(byte_count):
    if byte_count is None or byte_count <= 0: return "0 GB"
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
    safe_username = html.escape(user_data.get('username') or 'N/A')
    safe_client_app = html.escape(user_data.get('subLastUserAgent') or t('unknown', context))
    safe_sub_url = html.escape(user_data.get('subscriptionUrl') or t('not_found', context))
    status = t('status_active', context) if user_data.get('status') == 'ACTIVE' else t('status_inactive', context)
    data_limit = user_data.get('trafficLimitBytes', 0)
    data_usage = user_data.get('usedTrafficBytes', 0)
    remaining_data = data_limit - data_usage if data_limit > 0 else 0
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
    
    return (f"{t('user_info_title', context, username=safe_username)}\n\n"
            f"{t('status', context)} {status}\n\n"
            f"{t('total_limit', context)} {format_bytes(data_limit)}\n"
            f"{t('usage', context)} {format_bytes(data_usage)}\n"
            f"{t('remaining_volume', context)} {format_bytes(remaining_data)}\n\n"
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
    context.user_data.clear(); get_lang(context)
    keyboard = [
        [InlineKeyboardButton(t('add_user_btn', context), callback_data='go_add_user')],
        [InlineKeyboardButton(t('manage_user_btn', context), callback_data='go_manage_user')],
        [InlineKeyboardButton(t('view_logs_btn', context), callback_data='go_view_logs')],
        [InlineKeyboardButton(t('restart_nodes_btn', context), callback_data='go_restart_nodes')],
        [InlineKeyboardButton(t('change_language_btn', context), callback_data='go_change_language')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message_text = t('main_menu_prompt', context)
    chat_id = update.effective_chat.id
    if update.callback_query:
        try:
            await update.callback_query.message.delete()
        except BadRequest as e:
            if "Message to delete not found" not in str(e): logger.error(f"Error deleting message: {e}")
        await context.bot.send_message(chat_id=chat_id, text=message_text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text=message_text, reply_markup=reply_markup)
    return MAIN_MENU

async def show_node_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    buttons = [InlineKeyboardButton(node_name, callback_data=f"lognode_{node_name}") for node_name in config.NODES.keys()]
    keyboard = [[b] for b in buttons] if len(buttons) > 1 else [buttons]
    keyboard.append([InlineKeyboardButton(t('back_to_main_menu_btn', context), callback_data='back_to_main')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    message_text = t('select_node_prompt', context)
    query = update.callback_query
    if query:
        try:
            await query.message.delete()
        except BadRequest as e:
            if "Message to delete not found" not in str(e): logger.error(f"Error deleting message: {e}")
        await context.bot.send_message(chat_id=update.effective_chat.id, text=message_text, reply_markup=reply_markup)
    return NODE_LIST

async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); action = query.data
    if action == 'go_add_user':
        context.user_data['new_user'] = {}
        await query.message.edit_text(t('ask_for_new_username_prompt', context), parse_mode=ParseMode.HTML)
        return AWAITING_NEW_USERNAME
    if action == 'go_manage_user':
        await query.message.edit_text(t('ask_for_username', context))
        context.user_data['prompt_message_id'] = query.message.message_id
        return AWAITING_USERNAME
    if action == 'go_view_logs':
        return await show_node_list(update, context)
    if action == 'go_restart_nodes':
        buttons = [InlineKeyboardButton(node_name, callback_data=f"restartnode_{node_name}") for node_name in config.NODES.keys()]
        keyboard = [[b] for b in buttons] if len(buttons) > 1 else [buttons]; keyboard.append([InlineKeyboardButton(t('back_to_main_menu_btn', context), callback_data='back_to_main')])
        await query.message.edit_text(t('select_node_restart_prompt', context), reply_markup=InlineKeyboardMarkup(keyboard)); return SELECT_NODE_RESTART
    if action == 'go_change_language':
        try:
            await query.message.delete()
        except BadRequest: pass
        keyboard = [[InlineKeyboardButton("English 🇬🇧", callback_data='set_lang_en'), InlineKeyboardButton("Русский 🇷🇺", callback_data='set_lang_ru'), InlineKeyboardButton("فارسی 🇮🇷", callback_data='set_lang_fa')], [InlineKeyboardButton(t('back_to_main_menu_btn', context), callback_data='back_to_main')]]
        await context.bot.send_message(chat_id=update.effective_chat.id, text=t('select_language_prompt', context), reply_markup=InlineKeyboardMarkup(keyboard)); return SELECTING_LANGUAGE
    return MAIN_MENU

async def set_lang_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    lang_code = query.data.split('_')[-1]
    context.user_data['lang'] = lang_code; set_language_file(lang_code)
    await context.bot.delete_my_commands(); await context.bot.set_my_commands(COMMANDS.get(lang_code, COMMANDS['en']))
    return await start(update, context)

async def show_user_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    username_to_fetch = context.user_data.get('username')
    if update.message and not username_to_fetch:
        username_to_fetch = update.message.text
    if update.message:
        try: await update.message.delete()
        except BadRequest: pass
    prompt_message_id = context.user_data.pop('prompt_message_id', None)
    if prompt_message_id:
        try: await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=prompt_message_id)
        except BadRequest: pass
    get_lang(context)
    if not username_to_fetch: return await start(update, context)
    context.user_data['username'] = username_to_fetch
    sent_message = await context.bot.send_message(chat_id=update.effective_chat.id, text=t('fetching_user_info', context, username=username_to_fetch), parse_mode=ParseMode.HTML)
    data, error = api_request('GET', f'/api/users/by-username/{username_to_fetch}')
    if error:
        await sent_message.edit_text(t('error_fetching', context, error=error), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t('back_to_main_menu_btn', context), callback_data='back_to_main')]])); return AWAITING_USERNAME
    user_data = data.get('response', {});
    context.user_data['user_data'] = user_data; context.user_data['user_uuid'] = user_data.get('uuid')
    message_text = build_user_info_message(user_data, context)
    action_buttons = [InlineKeyboardButton(t('reset_usage_btn', context), callback_data='reset_usage')]
    if user_data.get('status') == 'ACTIVE': action_buttons.append(InlineKeyboardButton(t('disable_user_btn', context), callback_data='disable_user'))
    else: action_buttons.append(InlineKeyboardButton(t('enable_user_btn', context), callback_data='enable_user'))
    keyboard_list = [
        [InlineKeyboardButton(t('edit_volume_btn', context), callback_data='edit_limit'), InlineKeyboardButton(t('edit_date_btn', context), callback_data='edit_expire')],
        action_buttons,
        [InlineKeyboardButton(t('show_qr_btn', context), callback_data='show_qr'), InlineKeyboardButton(t('get_happ_qr_btn', context), callback_data='get_happ_qr')],
        [InlineKeyboardButton(t('delete_user_btn', context), callback_data='delete_user')],
        [InlineKeyboardButton(t('refresh_btn', context), callback_data='refresh')],
        [InlineKeyboardButton(t('back_to_main_menu_btn', context), callback_data='back_to_main')]
    ]
    await sent_message.edit_text(text=message_text, reply_markup=InlineKeyboardMarkup(keyboard_list), parse_mode=ParseMode.HTML)
    return USER_MENU

# --- Start of New User Creation Handlers ---

async def handle_new_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['new_user']['username'] = update.message.text
    prompt_message_id = context.user_data.pop('prompt_message_id', None)
    if prompt_message_id:
        try: await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=prompt_message_id)
        except BadRequest: pass
    await update.message.delete()
    sent_message = await context.bot.send_message(chat_id=update.effective_chat.id, text=t('ask_for_new_limit_prompt', context), parse_mode=ParseMode.HTML)
    context.user_data['prompt_message_id'] = sent_message.message_id
    return AWAITING_NEW_LIMIT

async def handle_new_limit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        limit_gb = float(update.message.text)
        context.user_data['new_user']['trafficLimitBytes'] = int(limit_gb * 1024**3)
    except (ValueError, TypeError):
        await context.bot.send_message(chat_id=update.effective_chat.id, text=t('invalid_number', context))
        return AWAITING_NEW_LIMIT
    
    prompt_message_id = context.user_data.pop('prompt_message_id', None)
    if prompt_message_id:
        try: await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=prompt_message_id)
        except BadRequest: pass
    await update.message.delete()
    sent_message = await context.bot.send_message(chat_id=update.effective_chat.id, text=t('ask_for_new_expire_prompt', context), parse_mode=ParseMode.HTML)
    context.user_data['prompt_message_id'] = sent_message.message_id
    return AWAITING_NEW_EXPIRE

async def handle_new_expire(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        days = int(update.message.text)
        if days > 0:
            expire_at = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat().replace('+00:00', 'Z')
            context.user_data['new_user']['expireAt'] = expire_at
    except (ValueError, TypeError):
        await context.bot.send_message(chat_id=update.effective_chat.id, text=t('invalid_number', context))
        return AWAITING_NEW_EXPIRE
    
    prompt_message_id = context.user_data.pop('prompt_message_id', None)
    if prompt_message_id:
        try: await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=prompt_message_id)
        except BadRequest: pass
    await update.message.delete()
    keyboard = [[
        InlineKeyboardButton(t('hwid_disable_btn', context), callback_data='hwid_disable'),
        InlineKeyboardButton(t('hwid_set_limit_btn', context), callback_data='hwid_set_limit')
    ]]
    sent_message = await context.bot.send_message(chat_id=update.effective_chat.id, text=t('ask_for_hwid_limit_prompt', context), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    context.user_data['prompt_message_id'] = sent_message.message_id
    return AWAITING_HWID_CHOICE

async def handle_hwid_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    prompt_message_id = context.user_data.pop('prompt_message_id', None)
    if prompt_message_id:
        try: await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=prompt_message_id)
        except BadRequest: pass
        
    if query.data == 'hwid_disable':
        context.user_data['new_user']['hwidDeviceLimit'] = 0
        return await ask_for_squads_handler(update, context)
    elif query.data == 'hwid_set_limit':
        sent_message = await context.bot.send_message(chat_id=update.effective_chat.id, text=t('ask_for_hwid_limit_value_prompt', context), parse_mode=ParseMode.HTML)
        context.user_data['prompt_message_id'] = sent_message.message_id
        return AWAITING_HWID_LIMIT

async def handle_hwid_limit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        limit = int(update.message.text)
        context.user_data['new_user']['hwidDeviceLimit'] = limit
    except (ValueError, TypeError):
        await context.bot.send_message(chat_id=update.effective_chat.id, text=t('invalid_number', context))
        return AWAITING_HWID_LIMIT

    prompt_message_id = context.user_data.pop('prompt_message_id', None)
    if prompt_message_id:
        try: await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=prompt_message_id)
        except BadRequest: pass
    await update.message.delete()
    return await ask_for_squads_handler(update, context)

async def ask_for_squads_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    chat_id = update.effective_chat.id

    # If this is a button press, answer the callback query
    if query:
        await query.answer()

    # Initialize squad list in user_data if not present
    if 'selected_squads' not in context.user_data.get('new_user', {}):
        context.user_data['new_user']['selected_squads'] = []

    # Fetch squads from API
    data, error = api_request('GET', '/api/internal-squads')
    if error:
        await context.bot.send_message(chat_id=chat_id, text=t('error_squad_fetch', context, error=error))
        return await start(update, context)
    
    # Build the keyboard based on current selection
    squads = data.get('response', [])
    keyboard = []
    selected_squads = context.user_data['new_user']['selected_squads']
    for squad in squads:
        squad_name = squad.get('name')
        squad_uuid = squad.get('uuid')
        is_selected = squad_uuid in selected_squads
        button_text = f"✅ {squad_name}" if is_selected else squad_name
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"squad_{squad_uuid}")])

    keyboard.append([InlineKeyboardButton(t('squad_selection_done_btn', context), callback_data='squad_done')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    message_text = t('ask_for_squads_prompt', context)

    # Decide whether to send a new message or edit an existing one
    if query:
        # We are in a callback query context (e.g., toggling a squad or coming from HWID choice buttons),
        # so we EDIT the existing message.
        try:
            await query.edit_message_text(text=message_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        except BadRequest as e:
            logger.error(f"Error editing squad message: {e}")
    else:
        # We are in a message handler context (coming from entering the HWID limit number),
        # so we SEND a new message because the previous prompt has been deleted.
        sent_message = await context.bot.send_message(chat_id=chat_id, text=message_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        # Store the ID of this new message so we can edit it later when buttons are pressed
        context.user_data['prompt_message_id'] = sent_message.message_id
    
    return SELECTING_SQUADS

async def handle_squad_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    action = query.data

    if action == 'squad_done':
        return await create_user_handler(update, context)
        
    squad_uuid = action.split('_')[1]
    selected_squads = context.user_data['new_user']['selected_squads']
    if squad_uuid in selected_squads:
        selected_squads.remove(squad_uuid)
    else:
        selected_squads.append(squad_uuid)
    
    return await ask_for_squads_handler(update, context)

async def create_user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    
    prompt_message_id = context.user_data.pop('prompt_message_id', None)
    if prompt_message_id:
        try: await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=prompt_message_id)
        except BadRequest: pass

    await query.message.edit_text(t('creating_user', context))

    new_user_data = context.user_data.get('new_user', {})
    payload = {
        "username": new_user_data.get('username'),
        "trafficLimitBytes": new_user_data.get('trafficLimitBytes'),
        "expireAt": new_user_data.get('expireAt'),
        "hwidDeviceLimit": new_user_data.get('hwidDeviceLimit'),
        "internalSquadUuids": new_user_data.get('selected_squads', [])
    }
    
    # Filter out null values for keys that are optional
    payload = {k: v for k, v in payload.items() if v is not None}

    data, error = api_request('POST', '/api/users', payload=payload)

    if error:
        await query.message.edit_text(t('update_failed', context, error=error))
        await context.bot.send_message(chat_id=query.message.chat_id, text=t('main_menu_prompt', context), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t('back_to_main_menu_btn', context), callback_data='back_to_main')]]))
        return MAIN_MENU

    await query.message.edit_text(t('user_created_success', context))
    context.user_data['username'] = new_user_data.get('username')
    return await show_user_card(update, context)

# --- End of New User Creation Handlers ---


async def user_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); action = query.data
    if action == 'back_to_main': return await start(update, context)
    if action == 'refresh':
        await query.message.delete(); return await show_user_card(update, context)
    
    user_data = context.user_data.get('user_data', {})

    if action == 'delete_user':
        username = user_data.get('username')
        text = t('delete_confirm_prompt', context, username=username)
        keyboard = [[
            InlineKeyboardButton(t('confirm_delete_btn', context), callback_data='confirm_delete'),
            InlineKeyboardButton(t('cancel_delete_btn', context), callback_data='cancel_delete')
        ]]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
        return CONFIRM_DELETE
    
    if action == 'get_happ_qr':
        happ_link = user_data.get('happ', {}).get('cryptoLink')
        qr_code_bytes = generate_qr_code(happ_link)
        if qr_code_bytes:
            username = user_data.get('username')
            caption = t('happ_qr_caption', context, username=username)
            full_caption = f"{caption}\n<code>{html.escape(happ_link)}</code>"
            media = InputMediaPhoto(media=qr_code_bytes, caption=full_caption, parse_mode=ParseMode.HTML)
            keyboard = [[InlineKeyboardButton(t('back_to_user_info_btn', context), callback_data='back_to_user_info')]]
            await query.message.edit_media(media=media, reply_markup=InlineKeyboardMarkup(keyboard))
            return QR_VIEW
        else:
            await query.answer(text=t('not_found', context), show_alert=True)
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
        _, error = api_request('POST', endpoint)
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
        
    username = context.user_data.get('username')
    if action == 'edit_limit':
        await query.message.edit_text(text=t('ask_for_new_limit', context, username=username), parse_mode=ParseMode.HTML)
        context.user_data['editing'] = 'limit'; return AWAITING_LIMIT
    elif action == 'edit_expire':
        await query.message.edit_text(text=t('ask_for_new_expire', context, username=username), parse_mode=ParseMode.HTML)
        context.user_data['editing'] = 'expire'; return AWAITING_EXPIRE
    return USER_MENU

async def delete_user_confirmation_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    action = query.data

    username = context.user_data.get('user_data', {}).get('username', '')
    await query.message.delete()

    if action == 'cancel_delete':
        return await show_user_card(update, context)

    if action == 'confirm_delete':
        user_uuid = context.user_data.get('user_uuid')
        if not user_uuid:
            await context.bot.send_message(chat_id=query.message.chat_id, text="Error: User UUID not found.")
            return await start(update, context)

        _, error = api_request('DELETE', f'/api/users/{user_uuid}')

        if error:
            await context.bot.send_message(chat_id=query.message.chat_id, text=f"❌ Error deleting user: {error}")
        else:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=t('user_deleted_success', context, username=username),
                parse_mode=ParseMode.HTML
            )
        
        return await start(update, context)
        
    return USER_MENU

async def back_to_user_info_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    await query.message.delete()
    return await show_user_card(update, context)

async def set_new_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.delete()
    prompt_message_id = context.user_data.pop('prompt_message_id', None)
    if prompt_message_id:
        try: await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=prompt_message_id)
        except BadRequest: pass
    if not context.user_data.get('user_uuid'): return await start(update, context)
    payload = {}
    try:
        if context.user_data.get('editing') == 'limit':
            new_limit_gb = float(update.message.text); payload = {"uuid": context.user_data.get('user_uuid'), "trafficLimitBytes": int(new_limit_gb * 1024**3)}
        elif context.user_data.get('editing') == 'expire':
            days = int(update.message.text); payload = {"uuid": context.user_data.get('user_uuid'), "expireAt": (datetime.now(timezone.utc) + timedelta(days=days)).isoformat().replace('+00:00', 'Z')}
    except (ValueError, TypeError):
        await context.bot.send_message(chat_id=update.effective_chat.id, text=t('invalid_number', context)); return await show_user_card(update, context)
    _, error = api_request('PATCH', '/api/users', payload=payload)
    if error: await context.bot.send_message(chat_id=update.effective_chat.id, text=t('update_failed', context, error=error))
    return await show_user_card(update, context)

async def logs_node_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); action = query.data
    if action == 'back_to_main': return await start(update, context)
    if action == 'go_view_logs': return await show_node_list(update, context)
    try: await query.message.delete()
    except BadRequest: pass
    node_name = action.split('_')[1]; context.user_data['selected_node'] = node_name
    message = await context.bot.send_message(chat_id=query.message.chat_id, text=t('fetching_logs', context, node_name=node_name), parse_mode=ParseMode.HTML)
    logs, error = get_logs_from_node(node_name); MAX_LOG_LENGTH = 3800
    if logs and len(logs) > MAX_LOG_LENGTH: logs = f"...\n{logs[-MAX_LOG_LENGTH:]}"
    if error:
        message_text = t('error_fetching_logs', context, node_name=node_name, details=html.escape(str(error or "")))
        keyboard = [[InlineKeyboardButton(t('back_to_nodes_btn', context), callback_data='go_view_logs')]]
    else:
        safe_logs = html.escape(logs or t('logs_empty', context))
        message_text = f"{t('logs_title', context, node_name=node_name)}\n\n<pre><code>{safe_logs}</code></pre>"
        keyboard = [[InlineKeyboardButton(t('refresh_logs_btn', context), callback_data=f'lognode_{node_name}')], [InlineKeyboardButton(t('back_to_nodes_btn', context), callback_data='go_view_logs')]]
    await message.edit_text(text=message_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    return VIEWING_LOGS

async def restart_node_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    node_name = query.data.split('_')[1]
    await query.message.edit_text(t('restarting_node', context, node_name=node_name), parse_mode=ParseMode.HTML)
    node_config = config.NODES.get(node_name)
    output, error = "", ""
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
    if error: message_text = f"{t('node_restart_failed', context, node_name=node_name)}\n\n<pre><code>{html.escape(error)}</code></pre>"
    else: message_text = f"{t('node_restart_success', context, node_name=node_name)}\n\n<b>{t('logs_title', context, node_name=node_name)}</b>\n<pre><code>{html.escape(output)}</code></pre>"
    keyboard = [[InlineKeyboardButton(t('back_to_restart_list_btn', context), callback_data='go_restart_nodes')]]
    await query.message.edit_text(message_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    return MAIN_MENU

def main() -> None:
    application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).post_init(post_init).build()
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            MAIN_MENU: [CallbackQueryHandler(main_menu_handler), CallbackQueryHandler(start, pattern='^back_to_main$')],
            SELECTING_LANGUAGE: [CallbackQueryHandler(set_lang_callback, pattern='^set_lang_'), CallbackQueryHandler(start, pattern='^back_to_main$')],
            AWAITING_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, show_user_card), CallbackQueryHandler(start, pattern='^back_to_main$')],
            USER_MENU: [CallbackQueryHandler(user_menu_handler)],
            QR_VIEW: [CallbackQueryHandler(back_to_user_info_handler, pattern='^back_to_user_info$')],
            AWAITING_LIMIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_new_value)],
            AWAITING_EXPIRE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_new_value)],
            NODE_LIST: [CallbackQueryHandler(logs_node_handler)],
            VIEWING_LOGS: [CallbackQueryHandler(logs_node_handler)],
            SELECT_NODE_RESTART: [CallbackQueryHandler(restart_node_handler, pattern='^restartnode_'), CallbackQueryHandler(main_menu_handler, pattern='^go_restart_nodes$'), CallbackQueryHandler(start, pattern='^back_to_main$')],
            CONFIRM_DELETE: [CallbackQueryHandler(delete_user_confirmation_handler)],
            # Add handlers for the new user creation flow
            AWAITING_NEW_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_new_username)],
            AWAITING_NEW_LIMIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_new_limit)],
            AWAITING_NEW_EXPIRE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_new_expire)],
            AWAITING_HWID_CHOICE: [CallbackQueryHandler(handle_hwid_choice)],
            AWAITING_HWID_LIMIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_hwid_limit)],
            SELECTING_SQUADS: [CallbackQueryHandler(handle_squad_selection, pattern='^squad_')],
        },
        fallbacks=[CommandHandler('start', start)], allow_reentry=True
    )
    application.add_handler(conv_handler)
    logger.info("Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()
