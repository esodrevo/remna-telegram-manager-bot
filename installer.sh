#!/bin/bash

#================================================================================#
#                         remna_bot manager                                      #
#                           by esodrevo                                          #
#                                                                                #
#  A script to install and manage the Remna Telegram Bot on Debian/Ubuntu.       #
#================================================================================#

RAW_GITHUB_URL="https://raw.githubusercontent.com/esodrevo/remna-telegram-manager-bot/main"
INSTALL_DIR="/opt/remna_bot"
LOG_SERVER_DIR="/opt/remna_log_server"
BOT_SERVICE_NAME="remna_bot"
LOG_SERVICE_NAME="remna_log_server"
BOT_SERVICE_FILE="/etc/systemd/system/${BOT_SERVICE_NAME}.service"
LOG_SERVICE_FILE="/etc/systemd/system/${LOG_SERVICE_NAME}.service"
CONFIG_FILE="$INSTALL_DIR/config.py"
MANAGER_SCRIPT_PATH="$INSTALL_DIR/remna_bot_manager.sh"
EXECUTABLE_PATH="/usr/local/bin/remna_bot"
PYTHON_VENV_EXEC="$INSTALL_DIR/venv/bin/python"
BACKUP_DIR="$INSTALL_DIR/backups"
PANEL_COMPOSE_DIR="" # This will be set dynamically

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

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

find_panel_path() {
    if [ -n "$PANEL_COMPOSE_DIR" ]; then
        return
    fi
    
    if [ -f "/opt/remnawave/docker-compose.yml" ]; then
        PANEL_COMPOSE_DIR="/opt/remnawave"
        return
    fi

    echo "Default panel path not found. Trying to detect automatically..."
    local detected_path
    if docker inspect remnawave &> /dev/null; then
        detected_path=$(docker inspect remnawave | grep '"com.docker.compose.project.working_dir":' | sed -n 's/.*"com.docker.compose.project.working_dir": "\(.*\)",/\1/p')
    fi
    
    if [ -n "$detected_path" ] && [ -d "$detected_path" ]; then
        PANEL_COMPOSE_DIR="$detected_path"
        echo -e "${GREEN}Panel directory detected at: $PANEL_COMPOSE_DIR${NC}"
    else
        echo -e "${RED}Error: Could not automatically detect the RemnaWave panel directory.${NC}"
        echo -e "${YELLOW}The backup/restore functionality may not work.${NC}"
        PANEL_COMPOSE_DIR="/opt/remnawave"
    fi
}

get_db_details() {
    find_panel_path

    if [ -f "$PANEL_COMPOSE_DIR/.env" ]; then
        DB_USER=$(grep -oP 'POSTGRES_USER=\K.*' "$PANEL_COMPOSE_DIR/.env")
        DB_NAME=$(grep -oP 'POSTGRES_DB=\K.*' "$PANEL_COMPOSE_DIR/.env")
    else
        echo -e "${RED}Warning: Could not find .env file in $PANEL_COMPOSE_DIR. Using default DB credentials.${NC}"
    fi
    DB_USER=${DB_USER:-postgres}
    DB_NAME=${DB_NAME:-remnawave-db}
}

run_backup() {
    mkdir -p "$BACKUP_DIR"
    get_db_details
    
    local backup_type="$1"
    local filename="${backup_type}_backup_$(date +%Y-%m-%d_%H-%M-%S).sql.gz"
    local filepath="$BACKUP_DIR/$filename"
    
    echo "Creating database backup..."
    docker exec remnawave-db pg_dump -U "$DB_USER" -d "$DB_NAME" | gzip > "$filepath"
    
    if [ $? -eq 0 ] && [ -s "$filepath" ]; then
        echo -e "${GREEN}Backup created successfully at $filepath.${NC}"
        echo "Sending backup to Telegram..."
        local caption
        if [ "$backup_type" == "instant" ]; then
            caption="✅ Instant backup created on $(date +"%Y-%m-%d %H:%M:%S")"
        else
            caption="🗓 Automatic backup created on $(date +"%Y-%m-%d %H:%M:%S")"
        fi
        
        "$PYTHON_VENV_EXEC" "$INSTALL_DIR/send_file.py" "$filepath" "$caption"
        
        if [ "$backup_type" == "instant" ]; then
            read -p "Do you want to delete the local backup file after sending? (y/N): " choice
            if [[ "$choice" =~ ^[Yy]$ ]]; then
                rm "$filepath"
                echo "Local backup file deleted."
            fi
        else
            rm "$filepath"
            find "$BACKUP_DIR" -name "auto_backup_*.sql.gz" -mtime +7 -delete > /dev/null 2>&1
        fi
        
        return 0
    else
        echo -e "${RED}Backup creation failed.${NC}"
        rm -f "$filepath"
        return 1
    fi
}

instant_backup() {
    check_root
    echo -e "${YELLOW}--- Instant Backup ---${NC}"
    run_backup "instant"
    pause
}

auto_backup_menu() {
    check_root
    local CRON_CMD="$MANAGER_SCRIPT_PATH auto_backup_run"
    
    clear
    show_banner
    echo -e "${YELLOW}--- Auto Backup Settings ---${NC}"
    echo "Select the backup frequency. A cron job will be created to automatically"
    echo "back up the database and send it to your Telegram bot."
    echo
    echo "  1) Every 1 Hour"
    echo "  2) Every 2 Hours"
    echo "  3) Every 6 Hours"
    echo "  4) Every 12 Hours"
    echo "  5) Every 24 Hours"
    echo "  6) Disable Auto Backup"
    echo
    echo "  0) Back to Backup Menu"
    echo
    read -p "Enter your choice: " choice
    
    crontab -l 2>/dev/null | grep -v "$CRON_CMD" | crontab -
    
    local cron_schedule=""
    case $choice in
        1) cron_schedule="0 */1 * * *" ;;
        2) cron_schedule="0 */2 * * *" ;;
        3) cron_schedule="0 */6 * * *" ;;
        4) cron_schedule="0 */12 * * *" ;;
        5) cron_schedule="0 0 * * *" ;;
        6) 
            echo -e "${GREEN}Auto backup has been disabled.${NC}"
            pause
            return
            ;;
        0) return ;;
        *) 
            echo -e "${RED}Invalid option.${NC}"
            pause
            return
            ;;
    esac
    
    (crontab -l 2>/dev/null; echo "$cron_schedule $CRON_CMD") | crontab -
    echo -e "${GREEN}Auto backup scheduled successfully!${NC}"
    echo "Taking an initial backup now..."
    run_backup "auto"
    pause
}

restore_backup() {
    check_root
    clear
    show_banner
    echo -e "${YELLOW}--- Restore Database from Backup ---${NC}"
    echo -e "${RED}WARNING: This action will completely overwrite your current database.${NC}"
    echo -e "${RED}It is STRONGLY recommended to take an 'Instant Backup' before proceeding.${NC}"
    echo
    read -p "Please enter the full path to the backup file (e.g., /path/to/backup.sql.gz): " backup_file
    
    if [ ! -f "$backup_file" ]; then
        echo -e "${RED}Error: File not found at the specified path.${NC}"
        pause
        return
    fi
    
    read -p "Are you absolutely sure you want to restore? This cannot be undone. (y/N): " choice
    if [[ ! "$choice" =~ ^[Yy]$ ]]; then
        echo "Restore operation cancelled."
        pause
        return
    fi
    
    get_db_details
    
    echo "Stopping the panel to prevent data conflicts..."
    docker stop remnawave >/dev/null 2>&1
    
    echo "Dropping the existing database..."
    docker exec remnawave-db dropdb -U "$DB_USER" --if-exists "$DB_NAME"
    
    echo "Creating a new empty database..."
    docker exec remnawave-db createdb -U "$DB_USER" "$DB_NAME"
    
    echo "Restoring database... This may take a moment."
    gunzip < "$backup_file" | docker exec -i remnawave-db psql -U "$DB_USER" -d "$DB_NAME"
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}Database restored successfully.${NC}"
    else
        echo -e "${RED}An error occurred during the restore process.${NC}"
    fi
    
    echo "Starting the panel..."
    docker start remnawave >/dev/null 2>&1
    
    pause
}

backup_menu() {
    while true; do
        clear
        show_banner
        echo -e "${YELLOW}--- Backup Management ---${NC}"
        echo "  1) Instant Backup (Create and send a backup now)"
        echo "  2) Configure Auto Backup (Schedule periodic backups)"
        echo "  3) Restore from Backup (Overwrite DB with a backup file)"
        echo
        echo "  0) Back to Main Menu"
        echo "----------------------------------------"
        read -p "Enter your choice: " choice
        case $choice in
            1) instant_backup ;;
            2) auto_backup_menu ;;
            3) restore_backup ;;
            0) break ;;
            *) echo -e "${RED}Invalid option. Please try again.${NC}"; pause ;;
        esac
    done
}

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
    curl -sL "${RAW_GITHUB_URL}/send_file.py" -o "$INSTALL_DIR/send_file.py"
    
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
        echo "Systemd service file created."
    fi

    echo "Reloading, enabling and restarting the bot service..."
    systemctl daemon-reload
    systemctl enable "$BOT_SERVICE_NAME" >/dev/null 2>&1
    systemctl restart "$BOT_SERVICE_NAME"

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
    rm -f "$BOT_SERVICE_FILE"
    rm -f "$LOG_SERVICE_FILE"
    rm -rf "$INSTALL_DIR"
    rm -rf "$LOG_SERVER_DIR"
    rm -f "$EXECUTABLE_PATH"
    crontab -l 2>/dev/null | grep -v "$MANAGER_SCRIPT_PATH auto_backup_run" | crontab -
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

        CRON_CMD_SEARCH="/opt/remna_bot/remna_bot_manager.sh auto_backup_run"
        CRON_JOB_ENTRY=$(crontab -l 2>/dev/null | grep "$CRON_CMD_SEARCH")

        if [ -n "$CRON_JOB_ENTRY" ]; then
            SCHEDULE=$(echo "$CRON_JOB_ENTRY" | awk '{print $1,$2,$3,$4,$5}')
            case "$SCHEDULE" in
                "0 */1 * * *") FREQUENCY="Every 1 Hour" ;;
                "0 */2 * * *") FREQUENCY="Every 2 Hours" ;;
                "0 */6 * * *") FREQUENCY="Every 6 Hours" ;;
                "0 */12 * * *") FREQUENCY="Every 12 Hours" ;;
                "0 0 * * *") FREQUENCY="Every 24 Hours" ;;
                *) FREQUENCY="Custom Schedule" ;;
            esac
            BACKUP_STATUS="[ ${GREEN}Active - ${FREQUENCY}${NC} ]"
        else
            BACKUP_STATUS="[ ${YELLOW}Disabled${NC} ]"
        fi

        echo -e "Bot Status:         $BOT_STATUS"
        echo -e "Auto Backup Status: $BACKUP_STATUS"
        echo "----------------------------------------"
        echo "Select an option:"
        echo "  1) Install / Update Bot"
        echo "  2) Restart Bot Service"
        echo "  3) Add Nodes"
        echo "  4) Remove Nodes"
        echo "  5) Backup Management"
        echo "  6) Uninstall Bot"
        echo "  0) Exit"
        echo "----------------------------------------"
        read -p "Enter your choice: " choice
        case $choice in
            1) install_bot ;;
            2) restart_bot ;;
            3) add_node_menu ;;
            4) remove_node ;;
            5) backup_menu ;;
            6) uninstall_bot ;;
            0) break ;;
            *) echo -e "${RED}Invalid option. Please try again.${NC}"; pause ;;
        esac
    done
    echo "Exiting."
}

if [[ $# -gt 0 ]]; then
    case "$1" in
        auto_backup_run)
            check_root
            run_backup "auto"
            exit 0
            ;;
        *)
            echo "Unknown command: $1"
            exit 1
            ;;
    esac
fi

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
