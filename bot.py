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

# Conversation states
(
    MAIN_MENU, SELECTING_LANGUAGE, AWAITING_USERNAME, USER_MENU, AWAITING_LIMIT,
    AWAITING_EXPIRE, NODE_LIST, VIEWING_LOGS, QR_VIEW, SELECT_NODE_RESTART,
    CONFIRM_DELETE, AWAITING_NEW_USERNAME, AWAITING_NEW_LIMIT, AWAITING_NEW_EXPIRE,
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
        error_message = f"HTTP Error: {errh.response.status_code}"
        try:
            error_details = errh.response.json()
            if "message" in error_details: error_message += f" - {error_details['message']}"
        except json.JSONDecodeError: pass
        logger.error(f"Http Error: {errh} - Response: {errh.response.text}"); return None, error_message
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

async def post_init(application: Application):
    lang = get_lang_from_file()
    await application.bot.set_my_commands(COMMANDS.get(lang, COMMANDS['en']))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_admin(update): return ConversationHandler.END
    context.user_data.clear(); get_lang(context)
    keyboard = [
        [InlineKeyboardButton(t('add_user_btn', context), callback_data='go_add_user'), InlineKeyboardButton(t('manage_user_btn', context), callback_data='go_manage_user')],
        [InlineKeyboardButton(t('view_logs_btn', context), callback_data='go_view_logs'), InlineKeyboardButton(t('restart_nodes_btn', context), callback_data='go_restart_nodes')],
        [InlineKeyboardButton(t('change_language_btn', context), callback_data='go_change_language')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message_text = t('main_menu_prompt', context)
    if update.callback_query:
        try:
            await update.callback_query.message.edit_text(text=message_text, reply_markup=reply_markup)
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                logger.error(f"Error editing message to main menu: {e}")
    else:
        if update.message: await update.message.reply_text(text=message_text, reply_markup=reply_markup)
    return MAIN_MENU

async def show_user_card(update: Update, context: ContextTypes.DEFAULT_TYPE, message_id: int = None) -> int:
    username_to_fetch = context.user_data.get('username')
    if update.message and not username_to_fetch:
        username_to_fetch = update.message.text
        try: await update.message.delete()
        except BadRequest: pass

    if not username_to_fetch: return await start(update, context)
    context.user_data['username'] = username_to_fetch

    chat_id = update.effective_chat.id
    if message_id:
        sent_message = await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=t('fetching_user_info', context, username=username_to_fetch), parse_mode=ParseMode.HTML)
    else:
        prompt_message_id = context.user_data.pop('prompt_message_id', None)
        if prompt_message_id:
            try: await context.bot.delete_message(chat_id=chat_id, message_id=prompt_message_id)
            except BadRequest: pass
        sent_message = await context.bot.send_message(chat_id=chat_id, text=t('fetching_user_info', context, username=username_to_fetch), parse_mode=ParseMode.HTML)

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

# --- Start Main Menu Handlers ---
async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); action = query.data
    if action == 'go_manage_user':
        await query.message.edit_text(t('ask_for_username', context), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t('back_to_main_menu_btn', context), callback_data='back_to_main')]]))
        context.user_data['prompt_message_id'] = query.message.message_id
        return AWAITING_USERNAME
    if action == 'go_add_user': return await add_user_start(update, context)
    if action == 'go_view_logs': return await show_node_list(update, context)
    if action == 'go_restart_nodes': return await show_restart_node_list(update, context)
    if action == 'go_change_language':
        keyboard = [[InlineKeyboardButton("English 🇬🇧", callback_data='set_lang_en'), InlineKeyboardButton("Русский 🇷🇺", callback_data='set_lang_ru'), InlineKeyboardButton("فارسی 🇮🇷", callback_data='set_lang_fa')], [InlineKeyboardButton(t('back_to_main_menu_btn', context), callback_data='back_to_main')]]
        await query.message.edit_text(text=t('select_language_prompt', context), reply_markup=InlineKeyboardMarkup(keyboard)); return SELECTING_LANGUAGE
    return MAIN_MENU

async def set_lang_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    lang_code = query.data.split('_')[-1]
    context.user_data['lang'] = lang_code; set_language_file(lang_code)
    await context.bot.delete_my_commands(); await context.bot.set_my_commands(COMMANDS.get(lang_code, COMMANDS['en']))
    return await start(update, context)
# --- End Main Menu Handlers ---

# --- Start User Management Handlers ---
async def user_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); action = query.data
    if action == 'back_to_main': return await start(update, context)
    if action == 'refresh': return await show_user_card(update, context, message_id=query.message.message_id)
    
    user_data = context.user_data.get('user_data', {}); username = user_data.get('username', '')

    if action == 'delete_user':
        text = t('delete_confirm_prompt', context, username=username)
        keyboard = [[InlineKeyboardButton(t('confirm_delete_btn', context), callback_data='confirm_delete'), InlineKeyboardButton(t('cancel_delete_btn', context), callback_data='cancel_delete')]]
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
        return CONFIRM_DELETE
    
    if action in ['get_happ_qr', 'show_qr']:
        link = user_data.get('happ', {}).get('cryptoLink') if action == 'get_happ_qr' else user_data.get('subscriptionUrl')
        qr_code_bytes = generate_qr_code(link)
        if qr_code_bytes:
            caption_text = t('happ_qr_caption', context, username=username) if action == 'get_happ_qr' else ""
            full_caption = f"{caption_text}\n<code>{html.escape(link)}</code>" if action == 'get_happ_qr' else ""
            media = InputMediaPhoto(media=qr_code_bytes, caption=full_caption, parse_mode=ParseMode.HTML)
            keyboard = [[InlineKeyboardButton(t('back_to_user_info_btn', context), callback_data='back_to_user_info')]]
            await query.message.edit_media(media=media, reply_markup=InlineKeyboardMarkup(keyboard))
            return QR_VIEW
        else:
            await query.answer(text=t('not_found', context), show_alert=True)
            return USER_MENU

    if action in ['enable_user', 'disable_user', 'reset_usage']:
        popup_map = {'enable_user': (t('enabling_user', context), t('user_enabled_success', context)), 'disable_user': (t('disabling_user', context), t('user_disabled_success', context)), 'reset_usage': (t('reseting_usage', context), t('reset_usage_success', context))}
        api_action = action.replace('_user', '').replace('_', '-')
        await query.answer(text=popup_map[action][0], show_alert=False)
        user_uuid = context.user_data.get('user_uuid')
        if not user_uuid: await query.answer(text="Error: User UUID not found.", show_alert=True); return USER_MENU
        _, error = api_request('POST', f'/api/users/{user_uuid}/actions/{api_action}')
        if error: await query.answer(text=f"API Error: {error}", show_alert=True)
        else:
            await query.answer(text=popup_map[action][1], show_alert=False)
            return await show_user_card(update, context, message_id=query.message.message_id)
        return USER_MENU
        
    context.user_data['prompt_message_id'] = query.message.message_id
    if action == 'edit_limit':
        await query.message.edit_text(text=t('ask_for_new_limit', context, username=username), parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t('cancel_btn', context), callback_data='cancel_edit')]]))
        context.user_data['editing'] = 'limit'; return AWAITING_LIMIT
    elif action == 'edit_expire':
        await query.message.edit_text(text=t('ask_for_new_expire', context, username=username), parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t('cancel_btn', context), callback_data='cancel_edit')]]))
        context.user_data['editing'] = 'expire'; return AWAITING_EXPIRE
    return USER_MENU

async def set_new_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    prompt_message_id = context.user_data.pop('prompt_message_id', None)
    if not prompt_message_id: return await start(update, context)
    try: await update.message.delete()
    except BadRequest: pass
    if not context.user_data.get('user_uuid'): return await start(update, context)
    
    payload = {}
    try:
        if context.user_data.get('editing') == 'limit':
            new_limit_gb = float(update.message.text); payload = {"uuid": context.user_data.get('user_uuid'), "trafficLimitBytes": int(new_limit_gb * 1024**3)}
        elif context.user_data.get('editing') == 'expire':
            days = int(update.message.text); payload = {"uuid": context.user_data.get('user_uuid'), "expireAt": (datetime.now(timezone.utc) + timedelta(days=days)).isoformat().replace('+00:00', 'Z')}
    except (ValueError, TypeError):
        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=prompt_message_id, text=t('invalid_number', context))
        return await show_user_card(update, context, message_id=prompt_message_id)
    
    _, error = api_request('PATCH', '/api/users', payload=payload)
    if error: await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=prompt_message_id, text=t('update_failed', context, error=error))
    return await show_user_card(update, context, message_id=prompt_message_id)

async def cancel_edit_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    return await show_user_card(update, context, message_id=query.message.message_id)

async def delete_user_confirmation_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    action = query.data; username = context.user_data.get('user_data', {}).get('username', '')
    if action == 'cancel_delete': return await show_user_card(update, context, message_id=query.message.message_id)
    if action == 'confirm_delete':
        await query.message.edit_text(t('deleting_user', context))
        user_uuid = context.user_data.get('user_uuid')
        if not user_uuid:
            await query.message.edit_text("Error: User UUID not found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t('back_to_main_menu_btn', context), callback_data='back_to_main')]]))
            return MAIN_MENU
        _, error = api_request('DELETE', f'/api/users/{user_uuid}')
        text = t('user_deleted_success', context, username=username) if not error else f"❌ Error deleting user: {error}"
        await query.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t('back_to_main_menu_btn', context), callback_data='back_to_main')]]))
        return MAIN_MENU
    return USER_MENU

async def back_to_user_info_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    await query.message.delete()
    return await show_user_card(update, context)
# --- End User Management Handlers ---

# --- Start Add User Flow ---
async def add_user_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    context.user_data['new_user'] = {}
    keyboard = [[InlineKeyboardButton(t('cancel_btn', context), callback_data='back_to_main')]]
    await query.message.edit_text(t('ask_new_username', context), reply_markup=InlineKeyboardMarkup(keyboard))
    context.user_data['prompt_message_id'] = query.message.message_id
    return AWAITING_NEW_USERNAME

async def add_user_get_username(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['new_user']['username'] = update.message.text
    try: await update.message.delete()
    except BadRequest: pass
    prompt_message_id = context.user_data.get('prompt_message_id')
    keyboard = [[InlineKeyboardButton(t('cancel_btn', context), callback_data='back_to_main')]]
    await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=prompt_message_id, text=t('ask_new_limit', context), reply_markup=InlineKeyboardMarkup(keyboard))
    return AWAITING_NEW_LIMIT

async def add_user_get_limit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    prompt_message_id = context.user_data.get('prompt_message_id')
    try:
        limit_gb = int(update.message.text)
        if limit_gb < 0: raise ValueError
        context.user_data['new_user']['limit_gb'] = limit_gb
        try: await update.message.delete()
        except BadRequest: pass
        keyboard = [[InlineKeyboardButton(t('cancel_btn', context), callback_data='back_to_main')]]
        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=prompt_message_id, text=t('ask_new_expire', context), reply_markup=InlineKeyboardMarkup(keyboard))
        return AWAITING_NEW_EXPIRE
    except (ValueError, TypeError):
        try: await update.message.delete()
        except BadRequest: pass
        keyboard = [[InlineKeyboardButton(t('cancel_btn', context), callback_data='back_to_main')]]
        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=prompt_message_id, text=f"❌ {t('invalid_number', context)}\n\n{t('ask_new_limit', context)}", reply_markup=InlineKeyboardMarkup(keyboard))
        return AWAITING_NEW_LIMIT

async def add_user_get_expire(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    prompt_message_id = context.user_data.get('prompt_message_id')
    try:
        days = int(update.message.text)
        if days <= 0: raise ValueError
        context.user_data['new_user']['expire_days'] = days
        try: await update.message.delete()
        except BadRequest: pass
        keyboard = [[InlineKeyboardButton(t('disable_hwid_btn', context), callback_data='hwid_disable')], [InlineKeyboardButton(t('set_hwid_btn', context), callback_data='hwid_set')], [InlineKeyboardButton(t('cancel_btn', context), callback_data='back_to_main')]]
        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=prompt_message_id, text=t('ask_hwid_limit_q', context), reply_markup=InlineKeyboardMarkup(keyboard))
        return AWAITING_HWID_CHOICE
    except (ValueError, TypeError):
        try: await update.message.delete()
        except BadRequest: pass
        keyboard = [[InlineKeyboardButton(t('cancel_btn', context), callback_data='back_to_main')]]
        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=prompt_message_id, text=f"❌ {t('invalid_number', context)}\n\n{t('ask_new_expire', context)}", reply_markup=InlineKeyboardMarkup(keyboard))
        return AWAITING_NEW_EXPIRE

async def add_user_get_hwid_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    context.user_data['prompt_message_id'] = query.message.message_id
    if query.data == 'hwid_disable':
        context.user_data['new_user']['hwid'] = 0
        return await add_user_show_squads(query.message.chat_id, query.message.message_id, context)
    else: # hwid_set
        keyboard = [[InlineKeyboardButton(t('cancel_btn', context), callback_data='back_to_main')]]
        await query.message.edit_text(text=t('ask_hwid_limit_val', context), reply_markup=InlineKeyboardMarkup(keyboard))
        return AWAITING_HWID_LIMIT

async def add_user_get_hwid_limit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    prompt_message_id = context.user_data.get('prompt_message_id')
    try:
        limit = int(update.message.text)
        if limit <= 0: raise ValueError
        context.user_data['new_user']['hwid'] = limit
        try: await update.message.delete()
        except BadRequest: pass
        return await add_user_show_squads(update.effective_chat.id, prompt_message_id, context)
    except (ValueError, TypeError):
        try: await update.message.delete()
        except BadRequest: pass
        keyboard = [[InlineKeyboardButton(t('cancel_btn', context), callback_data='back_to_main')]]
        await context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=prompt_message_id, text=f"❌ {t('invalid_number', context)}\n\n{t('ask_hwid_limit_val', context)}", reply_markup=InlineKeyboardMarkup(keyboard))
        return AWAITING_HWID_LIMIT

async def add_user_show_squads(chat_id: int, message_id: int, context: ContextTypes.DEFAULT_TYPE) -> int:
    await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=t('fetching_squads', context))
    squads_data, error = api_request('GET', '/api/internal-squads')
    if error or not squads_data.get('response'):
        error_text = t('error_fetching', context, error=error or t('no_squads_found', context))
        await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=error_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t('back_to_main_menu_btn', context), callback_data='back_to_main')]]))
        return MAIN_MENU

    context.user_data['squads_list'] = squads_data['response']
    if 'selected_squads' not in context.user_data: context.user_data['selected_squads'] = set()

    keyboard = []
    for squad in context.user_data['squads_list']:
        squad_name = f"✅ {squad['name']}" if squad['uuid'] in context.user_data['selected_squads'] else squad['name']
        keyboard.append([InlineKeyboardButton(squad_name, callback_data=f"squad_{squad['uuid']}")])
    keyboard.append([InlineKeyboardButton(t('create_user_btn', context), callback_data='squad_done')])
    keyboard.append([InlineKeyboardButton(t('cancel_btn', context), callback_data='back_to_main')])
    
    await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=t('select_squads_prompt', context), reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECTING_SQUADS

async def add_user_toggle_squad(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    squad_uuid = query.data.split('_', 1)[1]
    if 'selected_squads' not in context.user_data: context.user_data['selected_squads'] = set()
    if squad_uuid in context.user_data['selected_squads']: context.user_data['selected_squads'].remove(squad_uuid)
    else: context.user_data['selected_squads'].add(squad_uuid)
    return await add_user_show_squads(query.message.chat_id, query.message.message_id, context)

async def add_user_create(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    await query.message.edit_text(t('creating_user', context))
    user_details = context.user_data['new_user']
    payload = {
        "username": user_details['username'],
        "trafficLimitBytes": user_details['limit_gb'] * 1024**3 if user_details['limit_gb'] > 0 else 0,
        "expireAt": (datetime.now(timezone.utc) + timedelta(days=user_details['expire_days'])).isoformat().replace('+00:00', 'Z'),
        "hwidDeviceLimit": user_details['hwid'],
        "squadUuids": list(context.user_data.get('selected_squads', []))
    }
    data, error = api_request('POST', '/api/users', payload=payload)
    if error:
        await query.message.edit_text(t('user_created_failed', context, error=error), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t('back_to_main_menu_btn', context), callback_data='back_to_main')]]))
    else:
        new_user_data = data.get('response', {})
        message_text = build_user_info_message(new_user_data, context)
        await query.message.edit_text(
            f"✅ {t('user_created_success', context, username=user_details['username'])}\n\n{message_text}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(t('back_to_main_menu_btn', context), callback_data='back_to_main')]])
        )
    return MAIN_MENU
# --- End Add User Flow ---

# --- Start Node Handlers ---
async def show_node_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    buttons = [InlineKeyboardButton(node_name, callback_data=f"lognode_{node_name}") for node_name in config.NODES.keys()]
    keyboard = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    keyboard.append([InlineKeyboardButton(t('back_to_main_menu_btn', context), callback_data='back_to_main')])
    await query.message.edit_text(text=t('select_node_prompt', context), reply_markup=InlineKeyboardMarkup(keyboard))
    return NODE_LIST

async def logs_node_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer(); node_name = query.data.split('_')[1]
    await query.message.edit_text(text=t('fetching_logs', context, node_name=node_name), parse_mode=ParseMode.HTML)
    logs, error = get_logs_from_node(node_name); MAX_LOG_LENGTH = 3800
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

async def show_restart_node_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    buttons = [InlineKeyboardButton(node_name, callback_data=f"restartnode_{node_name}") for node_name in config.NODES.keys()]
    keyboard = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    keyboard.append([InlineKeyboardButton(t('back_to_main_menu_btn', context), callback_data='back_to_main')])
    await query.message.edit_text(t('select_node_restart_prompt', context), reply_markup=InlineKeyboardMarkup(keyboard));
    return SELECT_NODE_RESTART

async def restart_node_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query; await query.answer()
    node_name = query.data.split('_')[1]
    await query.message.edit_text(t('restarting_node', context, node_name=node_name), parse_mode=ParseMode.HTML)
    node_config = config.NODES.get(node_name); output, error = "", ""
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
    message_text = f"{t('node_restart_success', context, node_name=node_name)}\n\n<b>{t('logs_title', context, node_name=node_name)}</b>\n<pre><code>{html.escape(output)}</code></pre>" if not error else f"{t('node_restart_failed', context, node_name=node_name)}\n\n<pre><code>{html.escape(error)}</code></pre>"
    keyboard = [[InlineKeyboardButton(t('back_to_restart_list_btn', context), callback_data='go_restart_nodes')]]
    await query.message.edit_text(message_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    return SELECT_NODE_RESTART
# --- End Node Handlers ---

def main() -> None:
    application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).post_init(post_init).build()
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            MAIN_MENU: [CallbackQueryHandler(main_menu_handler, pattern='^go_'), CallbackQueryHandler(start, pattern='^back_to_main$')],
            SELECTING_LANGUAGE: [CallbackQueryHandler(set_lang_callback, pattern='^set_lang_'), CallbackQueryHandler(start, pattern='^back_to_main$')],
            # User Management
            AWAITING_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, show_user_card), CallbackQueryHandler(start, pattern='^back_to_main$')],
            USER_MENU: [CallbackQueryHandler(user_menu_handler)],
            QR_VIEW: [CallbackQueryHandler(back_to_user_info_handler, pattern='^back_to_user_info$')],
            AWAITING_LIMIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_new_value), CallbackQueryHandler(cancel_edit_handler, pattern='^cancel_edit$')],
            AWAITING_EXPIRE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_new_value), CallbackQueryHandler(cancel_edit_handler, pattern='^cancel_edit$')],
            CONFIRM_DELETE: [CallbackQueryHandler(delete_user_confirmation_handler)],
            # Add User
            AWAITING_NEW_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_user_get_username), CallbackQueryHandler(start, pattern='^back_to_main$')],
            AWAITING_NEW_LIMIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_user_get_limit), CallbackQueryHandler(start, pattern='^back_to_main$')],
            AWAITING_NEW_EXPIRE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_user_get_expire), CallbackQueryHandler(start, pattern='^back_to_main$')],
            AWAITING_HWID_CHOICE: [CallbackQueryHandler(add_user_get_hwid_choice, pattern='^hwid_'), CallbackQueryHandler(start, pattern='^back_to_main$')],
            AWAITING_HWID_LIMIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_user_get_hwid_limit), CallbackQueryHandler(start, pattern='^back_to_main$')],
            SELECTING_SQUADS: [CallbackQueryHandler(add_user_toggle_squad, pattern='^squad_(?!done)'), CallbackQueryHandler(add_user_create, pattern='^squad_done$'), CallbackQueryHandler(start, pattern='^back_to_main$')],
            # Nodes
            NODE_LIST: [CallbackQueryHandler(logs_node_handler, pattern='^lognode_'), CallbackQueryHandler(start, pattern='^back_to_main$')],
            VIEWING_LOGS: [CallbackQueryHandler(logs_node_handler, pattern='^lognode_'), CallbackQueryHandler(main_menu_handler, pattern='^go_view_logs$')],
            SELECT_NODE_RESTART: [CallbackQueryHandler(restart_node_handler, pattern='^restartnode_'), CallbackQueryHandler(main_menu_handler, pattern='^go_restart_nodes$'), CallbackQueryHandler(start, pattern='^back_to_main$')],
        },
        fallbacks=[CommandHandler('start', start), CallbackQueryHandler(start, pattern='^back_to_main$')], allow_reentry=True
    )
    application.add_handler(conv_handler)
    logger.info("Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()
