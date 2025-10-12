# send_file.py
import sys
import os
import asyncio
from telegram import Bot
from importlib.machinery import SourceFileLoader

CONFIG_PATH = '/opt/remna_bot/config.py'

def load_config():
    """Loads the bot configuration file."""
    if not os.path.exists(CONFIG_PATH):
        print("Error: config.py not found!", file=sys.stderr)
        sys.exit(1)
    return SourceFileLoader("remna_config_module", CONFIG_PATH).load_module()

async def send_document(bot_token, chat_id, file_path, caption):
    """Sends a document to the specified chat ID."""
    bot = Bot(token=bot_token)
    try:
        # خط زیر اصلاح شده و پارامتر 'timeout' حذف گردیده است
        with open(file_path, 'rb') as f:
            await bot.send_document(chat_id=chat_id, document=f, caption=caption)
        print("File sent successfully to Telegram.")
    except Exception as e:
        print(f"Error sending file via Telegram: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python send_file.py <file_path> <caption>", file=sys.stderr)
        sys.exit(1)

    file_path = sys.argv[1]
    caption = sys.argv[2]

    if not os.path.exists(file_path):
        print(f"Error: File not found at {file_path}", file=sys.stderr)
        sys.exit(1)

    config = load_config()
    BOT_TOKEN = getattr(config, 'TELEGRAM_BOT_TOKEN', None)
    ADMIN_ID = getattr(config, 'ADMIN_USER_ID', None)

    if not BOT_TOKEN or not ADMIN_ID:
        print("Error: TELEGRAM_BOT_TOKEN or ADMIN_USER_ID not found in config.py", file=sys.stderr)
        sys.exit(1)

    asyncio.run(send_document(BOT_TOKEN, ADMIN_ID, file_path, caption))
