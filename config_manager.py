import sys
import os
from importlib.machinery import SourceFileLoader

CONFIG_PATH = '/opt/remna_bot/config.py'

def format_value(value):
    if isinstance(value, str):
        return f"'{value}'"
    if value is None:
        return "None"
    return value

def load_config():
    if not os.path.exists(CONFIG_PATH):
        print("Error: config.py not found!", file=sys.stderr)
        sys.exit(1)
    return SourceFileLoader("remna_config_module", CONFIG_PATH).load_module()

def rewrite_config(config_module):
    content = f"""# config.py

# botfather API token:
TELEGRAM_BOT_TOKEN = {format_value(getattr(config_module, 'TELEGRAM_BOT_TOKEN', ''))}

# panel url
PANEL_URL = {format_value(getattr(config_module, 'PANEL_URL', ''))}

# remnawave API token
PANEL_API_TOKEN = {format_value(getattr(config_module, 'PANEL_API_TOKEN', ''))}

# telegram user ID
ADMIN_USER_ID = {getattr(config_module, 'ADMIN_USER_ID', 0)}

# node list
NODES = {getattr(config_module, 'NODES', {})}
"""
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        f.write(content)
    os.chmod(CONFIG_PATH, 0o660)

def list_nodes():
    config = load_config()
    nodes = getattr(config, 'NODES', {})
    if not nodes:
        print("No nodes are currently configured.")
        return
    print("Configured nodes:")
    for name in nodes.keys():
        print(f"- {name} ({nodes[name].get('type', 'unknown')})")

def add_local_node(name):
    config = load_config()
    nodes = getattr(config, 'NODES', {})
    if name in nodes:
        print(f"Error: Node '{name}' already exists.", file=sys.stderr)
        return
    nodes[name] = {"type": "local"}
    config.NODES = nodes
    rewrite_config(config)
    print(f"Successfully added local node '{name}'.")

def add_remote_node(name, ip, token):
    config = load_config()
    nodes = getattr(config, 'NODES', {})
    if name in nodes:
        print(f"Error: Node '{name}' already exists.", file=sys.stderr)
        return
    url = f"http://{ip}:5555/logs"
    nodes[name] = {"type": "remote", "url": url, "token": token}
    config.NODES = nodes
    rewrite_config(config)
    print(f"Successfully added remote node '{name}'.")

def remove_node(name):
    config = load_config()
    nodes = getattr(config, 'NODES', {})
    if name not in nodes:
        print(f"Error: Node '{name}' not found.", file=sys.stderr)
        return
    del nodes[name]
    config.NODES = nodes
    rewrite_config(config)
    print(f"Successfully removed node '{name}'.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python config_manager.py [list|add_local|add_remote|remove] [args...]", file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]

    if command == 'list':
        list_nodes()
    elif command == 'add_local' and len(sys.argv) == 3:
        add_local_node(sys.argv[2])
    elif command == 'add_remote' and len(sys.argv) == 5:
        add_remote_node(sys.argv[2], sys.argv[3], sys.argv[4])
    elif command == 'remove' and len(sys.argv) == 3:
        remove_node(sys.argv[2])
    else:
        print(f"Invalid command or arguments for '{command}'.", file=sys.stderr)
        sys.exit(1)
