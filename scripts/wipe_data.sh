#!/bin/bash
# SMS AI Agent Data Wipe Script
# ==============================
# This script permanently deletes all SMS AI Agent data.
# USE WITH CAUTION - This cannot be undone!

CONFIG_DIR="${SMS_AGENT_CONFIG_DIR:-$HOME/.config/sms-ai-agent}"
DATA_DIR="${SMS_AGENT_DATA_DIR:-$HOME/.local/share/sms-ai-agent}"

echo "=========================================="
echo "    SMS AI Agent Data Wipe Script"
echo "=========================================="
echo ""
echo "This will permanently delete:"
echo "  - Configuration files"
echo "  - Database (messages, logs)"
echo "  - API keys"
echo "  - Personality settings"
echo ""
echo "Directories to be deleted:"
echo "  - $CONFIG_DIR"
echo "  - $DATA_DIR"
echo ""

read -p "Are you sure? Type 'DELETE' to confirm: " confirm

if [ "$confirm" != "DELETE" ]; then
    echo "Cancelled."
    exit 0
fi

echo ""
echo "Deleting data..."

# Stop any running instances
pkill -f "python.*main.py" 2>/dev/null || true
sleep 1

# Delete configuration directory
if [ -d "$CONFIG_DIR" ]; then
    rm -rf "$CONFIG_DIR"
    echo "✓ Deleted: $CONFIG_DIR"
fi

# Delete data directory
if [ -d "$DATA_DIR" ]; then
    rm -rf "$DATA_DIR"
    echo "✓ Deleted: $DATA_DIR"
fi

# Delete boot script
if [ -f "$HOME/.termux/boot/sms-ai-agent.sh" ]; then
    rm -f "$HOME/.termux/boot/sms-ai-agent.sh"
    echo "✓ Deleted: boot script"
fi

# Delete shortcuts
rm -f "$HOME/.termux/shortcuts/SMS Agent Web UI" 2>/dev/null
rm -f "$HOME/.termux/shortcuts/SMS Agent TUI" 2>/dev/null
rm -f "$HOME/.termux/shortcuts/SMS Agent Status" 2>/dev/null
echo "✓ Deleted: shortcuts"

echo ""
echo "=========================================="
echo "All SMS AI Agent data has been deleted."
echo "Reinstall with: ./install.sh --first-run"
echo "=========================================="
