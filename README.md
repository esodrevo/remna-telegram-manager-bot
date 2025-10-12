# Remna Panel Telegram Bot

A powerful and easy-to-use Telegram bot designed to manage your RemnaWave panel directly from Telegram. This bot provides a comprehensive interface for administrators to perform common user, server, and backup management tasks without needing to log into a web panel.

The entire project is managed through a single, smart installer script, making setup, configuration, and updates straightforward.

## 🚀 Installation

Connect to your server via SSH and run the following single-line command. The script is interactive and will guide you through the setup process.

```bash
curl -sL https://raw.githubusercontent.com/esodrevo/remna-telegram-manager-bot/main/installer.sh -o installer.sh && sudo bash installer.sh
```

During the installation, you will be prompted to enter the following:
1.  Your Telegram Bot Token (from @BotFather)
2.  Your numeric Telegram User ID (from @userinfobot)
3.  Your Panel's URL
4.  Your Panel's API Token

## ✨ Features

The bot comes packed with features to make panel administration seamless:

#### 👤 User Management
- Add New User: Quickly create new users with custom data limits, expiration dates, and HWID (device limit) settings.

- Get Detailed User Info: Instantly fetch a user's status, data usage, remaining volume, expiration date, and subscription link by their username.

- Modify Data Limit & Expiration Date: Easily increase or change a user's traffic limit or change their subscription time.

- Reset Usage: Reset a user's data consumption to zero with a single tap.

- Enable / Disable / Delete Users: Activate, deactivate, or completely remove users from the system.

Get Subscription Link & QR Code: Retrieve subscription and Happ links, along with scannable QR codes.
#### 👤 Bulk User Management
- Bulk Edit Volume: Increase or decrease the data limit for all users at once (e.g., +10 or -5 GB for everyone).

- Bulk Edit Expiration Date: Extend or shorten the subscription for all users at once (e.g., +30 or -7 days for everyone).

- Bulk Set HWID: Enable, disable, or set a specific device limit for all users simultaneously.
#### 📊 Reporting
- User Activity Report: Get a detailed report of which users have recently updated their subscription (active) and which have not (inactive).
#### 🖥️ Node (Server) Management
- View Live Logs: Securely stream the latest logs from any of your configured nodes, whether they are local or remote.
- Restart Nodes: Restart your nodes directly from the bot to apply changes or troubleshoot issues.
#### 🛠️ Advanced CLI Management (Server Terminal)
🗄️ Advanced Backup & Restore System:

- Instant Backup: Create an on-demand database backup and receive it instantly in your Telegram chat.

- Auto Backup: Schedule automatic backups at regular intervals (every 1, 2, 6, 12, or 24 hours).

- Restore from Backup: Easily restore your panel's database from a backup file. The script handles dropping the old database to prevent conflicts.
#### 🤖 Bot & Interface
- Secure: Access is restricted to a single, predefined Telegram Admin ID.
- Multi-Language Support: The interface is available in English, Persian (فارسی), and Russian (Русский).
- Clean & Intuitive: The bot features a clean, conversational flow, automatically deleting old messages to prevent clutter.

## 🛠️ Usage

- Initial Setup: After running the installation command, select 1) Install / Update Bot from the menu.
- Bot Interaction: Open a chat with your bot in Telegram and send the /start command to bring up the main administrative menu.
- Server-Side Management: To add or remove nodes(to check node's xray logs), restart the bot service, or uninstall, simply run the remna_bot command in your server's terminal at any time.

## 📄 License

This project is licensed under the MIT License.
