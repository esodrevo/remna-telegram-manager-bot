#!/bin/bash

#================================================================================#
#                         remna_bot manager                                      #
#                           by esodrevo                                          #
#                                                                                #
#  A script to install and manage the Remna Telegram Bot on Debian/Ubuntu.       #
#================================================================================#

# --- Global Variables & Configuration ---
# !!! AFTER UPLOADING TO GITHUB, REPLACE THIS URL WITH YOUR OWN REPOSITORY'S RAW URL !!!
RAW_GITHUB_URL="https://raw.githubusercontent.com/esodrevo/remna-telegram-manager-bot/main"

INSTALL_DIR="/opt/remna_bot"
LOG_SERVER_DIR="/opt/remna_log_server"
BOT_SERVICE_NAME="remna_bot"
LOG_SERVICE_NAME="remna_log_server"
WEBHOOK_SERVICE_NAME="remna_webhook"
BOT_SERVICE_FILE="/etc/systemd/system/${BOT_SERVICE_NAME}.service"
LOG_SERVICE_FILE="/etc/systemd/system/${LOG_SERVICE_NAME}.service"
WEBHOOK_SERVICE_FILE="/etc/systemd/system/${WEBHOOK_SERVICE_NAME}.service"
CONFIG_FILE="$INSTALL_DIR/config.py"
MANAGER_SCRIPT_PATH="$INSTALL_DIR/remna_bot_manager.sh"
EXECUTABLE_PATH="/usr/local/bin/remna_bot"
PYTHON_VENV_EXEC="$INSTALL_DIR/venv/bin/python"

# --- Colors for output ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# --- Helper Functions ---
check_root() {
    if [ "$(id -u)" -ne 0 ]; then
        echo -e "${RED}Error: This script must be run as root. Please use sudo.${NC}"
        exit 1
    fi
}

pause() {
    read -p "Press [Enter] to continue..."
}

show_banner() {
    echo -e "${CYAN}"
    echo "  ██████╗ ███████╗███╗   ███╗███╗   ██╗ █████╗     ██████╗  ██████╗ ████████╗"
    echo "  ██╔══██╗██╔════╝████╗ ████║████╗  ██║██╔══██╗    ██╔══██╗██╔════██╗╚═██╔══╝"
    echo "  ██████╔╝█████╗  ██╔████╔██║██╔██╗ ██║███████║    ██████╔╝██║    ██║  ██║   "
    echo "  ██╔══██╗██╔══╝  ██║╚██╔╝██║██║╚██╗██║██╔══██║    ██╔══██╗██║    ██║  ██║   "
    echo "  ██║  ██║███████╗██║ ╚═╝ ██║██║ ╚████║██║  ██║    ██████╔╝╚██████╔═╝  ██║   "
    echo "  ╚═╝  ╚═╝╚══════╝╚═╝     ╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝    ╚═════╝  ╚═════╝    ╚═╝   "
    echo -e "____________________________________________________________________"
    echo -e "${YELLOW}                        remna_bot manager${NC}"
    echo -e "${NC}                              by esodrevo"
    echo
}

# --- Core Logic Functions ---
install_bot() {
    check_root
    if [ -d "$INSTALL_DIR" ]; then
        echo -e "${YELLOW}Existing installation found. Updating bot files...${NC}"
    else
        echo -e "${GREEN}Starting Remna Bot installation...${NC}"
        apt-get update >/dev/null 2>&1
        apt-get install -y python3 python3-venv python3-pip curl >/dev/null 2>&1
        echo "Dependencies installed."
        mkdir -p "$INSTALL_DIR"
        python3 -m venv "$INSTALL_DIR/venv"
        echo "Virtual environment created at $INSTALL_DIR/venv."
        "$INSTALL_DIR/venv/bin/pip" install "python-telegram-bot[ext]" requests "qrcode[pil]" flask "urllib3" >/dev/null 2>&1
        echo "Python packages installed."
        echo -e "${YELLOW}Please provide your bot configuration:${NC}"
        read -p "Enter your BotFather API Token: " bot_token
        read -p "Enter your admin Telegram User ID: " admin_id
        read -p "Enter your Remna panel URL (e.g., https://panel.domain.com): " panel_url
        read -p "Enter your Remna panel API Token: " panel_api_token
        cat << EOF > "$CONFIG_FILE"
# config.py
TELEGRAM_BOT_TOKEN = '$bot_token'
PANEL_URL = '$panel_url'
PANEL_API_TOKEN = '$panel_api_token'
ADMIN_USER_ID = $admin_id
NODES = {}
EOF
        chmod 660 "$CONFIG_FILE"
        echo "Configuration file created."
    fi

    echo "Downloading bot files from GitHub..."
    curl -sL "${RAW_GITHUB_URL}/bot.py" -o "$INSTALL_DIR/bot.py"
    curl -sL "${RAW_GITHUB_URL}/locales.json" -o "$INSTALL_DIR/locales.json"
    curl -sL "${RAW_GITHUB_URL}/config_manager.py" -o "$INSTALL_DIR/config_manager.py"
    curl -sL "${RAW_GITHUB_URL}/notifier.py" -o "$INSTALL_DIR/notifier.py"
    curl -sL "${RAW_GITHUB_URL}/webhook_listener.py" -o "$INSTALL_DIR/webhook_listener.py"
    curl -sL "${RAW_GITHUB_URL}/cache_manager.py" -o "$INSTALL_DIR/cache_manager.py"
    
    cat << 'EOF' > "$INSTALL_DIR/settings.json"
{"language": "fa"}
EOF

    if [ ! -f "$BOT_SERVICE_FILE" ]; then
        cat << EOF > "$BOT_SERVICE_FILE"
[Unit]
Description=Remna Telegram Bot
After=network.target
[Service]
User=root
Group=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$PYTHON_VENV_EXEC $INSTALL_DIR/bot.py
Restart=always
RestartSec=10
[Install]
WantedBy=multi-user.target
EOF
        echo "Bot systemd service file created."
    fi

    if [ ! -f "$WEBHOOK_SERVICE_FILE" ]; then
        cat << EOF > "$WEBHOOK_SERVICE_FILE"
[Unit]
Description=Remna Bot Webhook Listener
After=network.target
[Service]
User=root
Group=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$PYTHON_VENV_EXEC $INSTALL_DIR/webhook_listener.py
Restart=always
RestartSec=10
[Install]
WantedBy=multi-user.target
EOF
        echo "Webhook listener systemd service file created."
    fi

    echo "Reloading, enabling and restarting services..."
    systemctl daemon-reload
    systemctl enable "$BOT_SERVICE_NAME" >/dev/null 2>&1
    systemctl restart "$BOT_SERVICE_NAME"
    systemctl enable "$WEBHOOK_SERVICE_NAME" >/dev/null 2>&1
    systemctl restart "$WEBHOOK_SERVICE_NAME"

    if [ ! -f "$EXECUTABLE_PATH" ] || [ ! -L "$EXECUTABLE_PATH" ]; then
        cp "$0" "$MANAGER_SCRIPT_PATH"
        chmod +x "$MANAGER_SCRIPT_PATH"
        ln -s "$MANAGER_SCRIPT_PATH" "$EXECUTABLE_PATH"
        echo "Command 'remna_bot' created."
    fi

    echo -e "${GREEN}Installation/Update complete! The bot is now running with the latest features.${NC}"
    pause
}

restart_bot() {
    check_root
    if ! systemctl is-active --quiet "$BOT_SERVICE_NAME"; then
        echo -e "${YELLOW}Bot service is not running. Starting it...${NC}"
        systemctl start "$BOT_SERVICE_NAME"
    else
        echo "Restarting the bot service..."
        systemctl restart "$BOT_SERVICE_NAME"
    fi
    echo -e "${GREEN}Operation completed.${NC}"
    pause
}

populate_cache_menu() {
    check_root
    echo -e "${YELLOW}Populating user cache from Remna panel...${NC}"
    echo "This may take a moment depending on the number of users."
    "$PYTHON_VENV_EXEC" "$INSTALL_DIR/cache_manager.py" populate
    echo -e "${GREEN}Cache population process finished.${NC}"
    pause
}

toggle_notifications_menu() {
    check_root
    "$PYTHON_VENV_EXEC" "$INSTALL_DIR/config_manager.py" toggle_notifications
    echo "Restarting services to apply changes..."
    systemctl restart "$BOT_SERVICE_NAME"
    systemctl restart "$WEBHOOK_SERVICE_NAME"
    pause
}

add_node_menu() {
    while true; do
        clear
        show_banner
        echo -e "${YELLOW}--- Add Node Menu ---${NC}"
        echo "Please choose the type of node to add:"
        echo
        echo -e "  ${CYAN}1)${NC} Add Local Node"
        echo "     (The node is on the same server as this panel)"
        echo
        echo -e "  ${CYAN}2)${NC} Add Remote Node"
        echo "     (The node is on a different, separate server)"
        echo
        echo -e "  ${CYAN}0)${NC} Back to Main Menu"
        echo
        read -p "Enter your choice [1-2, 0]: " choice

        case $choice in
            1) add_local_node ;;
            2) add_remote_node_menu ;;
            0) break ;;
            *) echo -e "${RED}Invalid option. Please try again.${NC}"; pause ;;
        esac
    done
}

add_local_node() {
    echo -e "${YELLOW}--- Add Local Node ---${NC}"
    read -p "Enter a name for this local node (e.g., germany-1): " node_name
    if [ -z "$node_name" ]; then
        echo -e "${RED}Node name cannot be empty.${NC}"
        pause
        return
    fi
    "$PYTHON_VENV_EXEC" "$INSTALL_DIR/config_manager.py" add_local "$node_name"
    echo "Restarting bot to apply changes..."
    systemctl restart "$BOT_SERVICE_NAME"
    pause
}

add_remote_node_menu() {
    while true; do
        clear
        show_banner
        echo -e "${YELLOW}--- Add Remote Node Menu ---${NC}"
        echo -e "${RED}IMPORTANT:${NC} To add a remote node, you must first run this script on the ${YELLOW}REMOTE NODE's server${NC}."
        echo "On the node's server, choose option '1. Configure remote server' below."
        echo "It will give you a secret token. Copy it."
        echo "Then, come back to this server (the main panel server) and choose option '2. Add remote node to bot'."
        echo
        echo -e "  ${CYAN}1)${NC} Configure remote server (Run this on the NODE server)"
        echo -e "  ${CYAN}2)${NC} Add remote node to bot (Run this on the PANEL server)"
        echo
        echo -e "  ${CYAN}0)${NC} Back to Add Node Menu"
        echo
        read -p "Enter your choice [1-2, 0]: " choice

        case $choice in
            1) configure_remote_server ;;
            2) add_remote_to_config ;;
            0) break ;;
            *) echo -e "${RED}Invalid option. Please try again.${NC}"; pause ;;
        esac
    done
}

configure_remote_server() {
    check_root
    echo -e "${YELLOW}--- Configuring this server as a Remote Log/Restart Node ---${NC}"
    apt-get update >/dev/null 2>&1
    apt-get install -y python3 python3-venv python3-pip openssl >/dev/null 2>&1
    mkdir -p "$LOG_SERVER_DIR"
    python3 -m venv "$LOG_SERVER_DIR/venv"
    "$LOG_SERVER_DIR/venv/bin/pip" install flask >/dev/null 2>&1
    echo "Environment created."
    if [ -f "$LOG_SERVER_DIR/config.json" ]; then
        SECRET_TOKEN=$(grep -oP '"SECRET_TOKEN": "\K[^"]+' "$LOG_SERVER_DIR/config.json")
    else
        SECRET_TOKEN=$(openssl rand -hex 16)
        echo "{\"SECRET_TOKEN\": \"$SECRET_TOKEN\"}" > "$LOG_SERVER_DIR/config.json"
    fi
    cat << EOF > "$LOG_SERVER_DIR/log_server.py"
from flask import Flask, request, jsonify
import subprocess, json
app = Flask(__name__)
with open('config.json', 'r') as f:
    config = json.load(f)
SECRET_TOKEN = config['SECRET_TOKEN']
DOCKER_CONTAINER_NAME = "remnanode"
LOG_PATH_IN_CONTAINER = "/var/log/supervisor/xray.out.log"
LOG_LINES_TO_FETCH = 30
NODE_DIR = "/opt/remnanode"
def check_auth():
    auth_header = request.headers.get('Authorization')
    if not auth_header or auth_header != f"Bearer {SECRET_TOKEN}":
        return False
    return True
@app.route('/logs', methods=['GET'])
def get_xray_logs():
    if not check_auth(): return jsonify({"error": "Unauthorized"}), 401
    command = [ "docker", "exec", DOCKER_CONTAINER_NAME, "tail", f"-n{LOG_LINES_TO_FETCH}", LOG_PATH_IN_CONTAINER ]
    try:
        result = subprocess.run( command, capture_output=True, text=True, check=True, encoding='utf-8' )
        return jsonify({"logs": result.stdout.strip()})
    except Exception as e:
        return jsonify({"error": "Failed to get logs from container.", "details": str(e)}), 500
@app.route('/restart', methods=['POST'])
def restart_node():
    if not check_auth(): return jsonify({"error": "Unauthorized"}), 401
    command = f"cd {NODE_DIR} && docker compose down && docker compose up -d && sleep 5 && docker compose logs --tail=20"
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, check=True, encoding='utf-8')
        return jsonify({"status": "success", "logs": result.stdout.strip()})
    except subprocess.CalledProcessError as e:
        return jsonify({"status": "error", "details": e.stderr.strip()}), 500
    except Exception as e:
        return jsonify({"status": "error", "details": str(e)}), 500
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5555)
EOF
    echo "Log server script created/updated."
    cat << EOF > "$LOG_SERVICE_FILE"
[Unit]
Description=Remna Bot Remote Log/Restart Server
After=network.target docker.service
Requires=docker.service
[Service]
User=root
Group=root
WorkingDirectory=$LOG_SERVER_DIR
ExecStart=$LOG_SERVER_DIR/venv/bin/python $LOG_SERVER_DIR/log_server.py
Restart=always
RestartSec=10
[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable "$LOG_SERVICE_NAME" >/dev/null 2>&1
    systemctl restart "$LOG_SERVICE_NAME"
    echo -e "${GREEN}Configuration complete! The log/restart server is now running.${NC}"
    echo -e "Please copy the following information and use it on your main panel server:"
    echo "------------------------------------------------------------------"
    echo -e "  Remote Node IP:  ${YELLOW}$(curl -s ifconfig.me)${NC}"
    echo -e "  Secret Token:    ${YELLOW}$SECRET_TOKEN${NC}"
    echo "------------------------------------------------------------------"
    echo "Ensure that port 5555 is open in your firewall."
    pause
}

add_remote_to_config() {
    echo -e "${YELLOW}--- Add Remote Node to Bot Config ---${NC}"
    read -p "Enter a name for this remote node (e.g., france-1): " node_name
    read -p "Enter the IP address of the remote node: " node_ip
    read -p "Enter the Secret Token from the remote node: " node_token
    if [ -z "$node_name" ] || [ -z "$node_ip" ] || [ -z "$node_token" ]; then
        echo -e "${RED}All fields are required.${NC}"
        pause
        return
    fi
    "$PYTHON_VENV_EXEC" "$INSTALL_DIR/config_manager.py" add_remote "$node_name" "$node_ip" "$node_token"
    echo "Restarting bot to apply changes..."
    systemctl restart "$BOT_SERVICE_NAME"
    pause
}

remove_node() {
    check_root
    echo -e "${YELLOW}--- Remove a Node ---${NC}"
    "$PYTHON_VENV_EXEC" "$INSTALL_DIR/config_manager.py" list
    echo
    read -p "Enter the exact name of the node you want to remove: " node_to_remove
    if [ -z "$node_to_remove" ]; then
        echo -e "${RED}No node name entered. Operation cancelled.${NC}"
        pause
        return
    fi
    "$PYTHON_VENV_EXEC" "$INSTALL_DIR/config_manager.py" remove "$node_to_remove"
    echo "Restarting bot to apply changes..."
    systemctl restart "$BOT_SERVICE_NAME"
    pause
}

uninstall_bot() {
    check_root
    echo -e "${RED}--- Uninstall Remna Bot ---${NC}"
    read -p "Are you sure you want to completely uninstall the bot and all its data? (y/N): " choice
    if [[ ! "$choice" =~ ^[Yy]$ ]]; then
        echo "Uninstallation cancelled."
        return
    fi
    systemctl stop "$BOT_SERVICE_NAME" >/dev/null 2>&1
    systemctl disable "$BOT_SERVICE_NAME" >/dev/null 2>&1
    systemctl stop "$LOG_SERVICE_NAME" >/dev/null 2>&1
    systemctl disable "$LOG_SERVICE_NAME" >/dev/null 2>&1
    systemctl stop "$WEBHOOK_SERVICE_NAME" >/dev/null 2>&1
    systemctl disable "$WEBHOOK_SERVICE_NAME" >/dev/null 2>&1
    rm -f "$BOT_SERVICE_FILE"
    rm -f "$LOG_SERVICE_FILE"
    rm -f "$WEBHOOK_SERVICE_FILE"
    rm -rf "$INSTALL_DIR"
    rm -rf "$LOG_SERVER_DIR"
    rm -f "$EXECUTABLE_PATH"
    systemctl daemon-reload
    echo -e "${GREEN}Uninstallation complete.${NC}"
    if [[ "$0" == "$MANAGER_SCRIPT_PATH" ]]; then
       exit 0
    fi
    pause
}

show_menu() {
    while true; do
        clear
        show_banner
        if [ -f "$BOT_SERVICE_FILE" ]; then
            if systemctl is-active --quiet "$BOT_SERVICE_NAME"; then
                BOT_STATUS="[ ${GREEN}Running${NC} ]"
            else
                BOT_STATUS="[ ${RED}Stopped${NC} ]"
            fi
        else
            BOT_STATUS="[ ${YELLOW}Not Installed${NC} ]"
        fi
        
        if [ -f "$CONFIG_FILE" ] && grep -q "NOTIFICATIONS_ENABLED = True" "$CONFIG_FILE"; then
            NOTIF_STATUS="[ ${GREEN}Enabled${NC} ]"
        else
            NOTIF_STATUS="[ ${RED}Disabled${NC} ]"
        fi
        echo -e "Bot Status: $BOT_STATUS"
        echo -e "Notifications: $NOTIF_STATUS"
        echo "----------------------------------------"
        echo "Select an option:"
        echo "  1) Install / Update Bot"
        echo "  2) Restart Bot Service"
        echo "  3) Add Nodes"
        echo "  4) Remove Nodes"
        echo "  5) Enable/Disable Notifications"
        echo "  6) Populate User Cache (Run once after install)"
        echo "  7) Uninstall Bot"
        echo "  0) Exit"
        echo "----------------------------------------"
        read -p "Enter your choice [1-7, 0]: " choice
        case $choice in
            1) install_bot ;;
            2) restart_bot ;;
            3) add_node_menu ;;
            4) remove_node ;;
            5) toggle_notifications_menu ;;
            6) populate_cache_menu ;;
            7) uninstall_bot ;;
            0) break ;;
            *) echo -e "${RED}Invalid option. Please try again.${NC}"; pause ;;
        esac
    done
    echo "Exiting."
}

# --- Script Execution Starts Here ---
if [ -t 0 ]; then
  show_menu
else
  echo -e "${RED}Error: Direct execution via pipe is not supported as this script requires user input.${NC}"
  echo -e "${YELLOW}Please use the recommended two-step installation method:${NC}"
  echo
  echo -e "   ${CYAN}1. Download the installer:${NC}"
  echo "   curl -sL ${RAW_GITHUB_URL}/installer.sh -o installer.sh"
  echo
  echo -e "   ${CYAN}2. Run the installer:${NC}"
  echo "   sudo bash installer.sh"
  echo
  exit 1
fi
