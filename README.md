# Remna Panel Telegram Bot

A easy-to-use Telegram bot designed to manage your Remnawave directly from Telegram. This bot provides a convenient interface for administrators to perform common user and server management tasks without needing to log into a web panel.

The entire project is managed through a single installer script, making setup and configuration straightforward.

## ✨ Features

The bot comes packed with features to make panel administration seamless:

#### 👤 User Management
- Get Detailed User Info: Instantly fetch a user's status, data usage, and expiration date and subscription link by their username.
- Modify Data Limit: Easily increase or change a user's traffic limit.
- Modify Expiration Date: Add more days to a user's subscription.
- Enable / Disable Users: Activate or deactivate users with a single tap. The bot intelligently shows the relevant action (e.g., shows "Disable" for an active user).
- QR Code Generation: Display the user's subscription link as a scannable QR code.

#### 🖥️ Node (Server) Management
- View Live Logs: Securely stream the latest logs from any of your configured nodes, whether they are local or remote.
- Restart Nodes: Restart your nodes directly from the bot to apply changes or troubleshoot issues.

#### 🤖 Bot & Interface
- Secure: Access is restricted to a single, predefined Telegram Admin ID.
- Multi-Language Support: The interface is available in English, Persian (فارسی), and Russian (Русский).
- Clean & Intuitive: The bot features a clean, conversational flow, automatically deleting old messages to prevent clutter.
- Easy Management: The bot itself can be managed (updated, configured, uninstalled) via a simple command (remna_bot) in the server terminal.

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

## 🛠️ Usage

- Initial Setup: After running the installation command, select 1) Install / Update Bot from the menu.
- Bot Interaction: Open a chat with your bot in Telegram and send the /start command to bring up the main administrative menu.
- Server-Side Management: To add or remove nodes, restart the bot service, or uninstall, simply run the remna_bot command in your server's terminal at any time.

## 🤝 Contributing

Contributions, issues, and feature requests are welcome! Feel free to check the [issues page](https://github.com/esodrevo/remna-telegram-manager-bot/issues).

## 📄 License

This project is licensed under the MIT License.
