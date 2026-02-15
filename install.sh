#!/bin/bash
#
# SMS AI Agent Installation Script
# =================================
# This script installs all dependencies and sets up the SMS AI Agent
# for use in Termux on Android devices.
#
# Usage:
#   chmod +x install.sh
#   ./install.sh
#
# For first-time installation, run:
#   ./install.sh --first-run
#

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print colored message
print_msg() {
    echo -e "${2}${1}${NC}"
}

print_success() {
    print_msg "✓ $1" "$GREEN"
}

print_error() {
    print_msg "✗ $1" "$RED"
}

print_info() {
    print_msg "ℹ $1" "$BLUE"
}

print_warning() {
    print_msg "⚠ $1" "$YELLOW"
}

# Check if running in Termux
check_termux() {
    if [ -n "$TERMUX_VERSION" ] || [ -d "/data/data/com.termux" ]; then
        print_success "Running in Termux environment"
        return 0
    else
        print_warning "Not running in Termux. Some features may not work."
        return 1
    fi
}

# Check Android version
check_android_version() {
    if [ -f "/system/build.prop" ]; then
        ANDROID_VERSION=$(grep "ro.build.version.release" /system/build.prop | cut -d'=' -f2)
        print_info "Android version: $ANDROID_VERSION"
        
        # Android 10+ has some restrictions
        if [ "${ANDROID_VERSION%%.*}" -ge 10 ]; then
            print_warning "Android 10+ detected. Some SMS features may be restricted."
            print_info "Make sure to grant all necessary permissions."
        fi
    fi
}

# Install Termux packages
install_termux_packages() {
    print_info "Installing Termux packages..."
    
    # Update packages
    pkg update -y || true
    pkg upgrade -y || true
    
    # Install required packages
    local packages=(
        "python"
        "python-pip"
        "termux-api"
        "git"
        "cronie"
        "nano"
    )
    
    for pkg in "${packages[@]}"; do
        if ! pkg list-installed | grep -q "^$pkg/"; then
            print_info "Installing $pkg..."
            pkg install -y "$pkg" || print_warning "Failed to install $pkg"
        else
            print_success "$pkg already installed"
        fi
    done
    
    print_success "Termux packages installed"
}

# Install Python dependencies
install_python_deps() {
    print_info "Installing Python dependencies..."
    
    # Upgrade pip
    pip install --upgrade pip || true
    
    # Install requirements
    if [ -f "requirements.txt" ]; then
        pip install -r requirements.txt || {
            print_error "Failed to install some dependencies"
            print_info "Trying to install core dependencies individually..."
            
            # Install core dependencies individually
            pip install pyyaml || true
            pip install fastapi || true
            pip install uvicorn || true
            pip install jinja2 || true
            pip install textual || true
            pip install python-multipart || true
        }
        print_success "Python dependencies installed"
    else
        print_warning "requirements.txt not found, installing core dependencies..."
        pip install pyyaml fastapi uvicorn jinja2 textual python-multipart
    fi
}

# Setup configuration directory
setup_config_dir() {
    print_info "Setting up configuration directory..."
    
    # Determine config directory
    if [ -n "$XDG_CONFIG_HOME" ]; then
        CONFIG_DIR="$XDG_CONFIG_HOME/sms-ai-agent"
    elif [ -d "$HOME/.config" ]; then
        CONFIG_DIR="$HOME/.config/sms-ai-agent"
    else
        CONFIG_DIR="$HOME/.sms-ai-agent"
    fi
    
    # Determine data directory
    if [ -n "$XDG_DATA_HOME" ]; then
        DATA_DIR="$XDG_DATA_HOME/sms-ai-agent"
    else
        DATA_DIR="$HOME/.local/share/sms-ai-agent"
    fi
    
    # Create directories
    mkdir -p "$CONFIG_DIR"
    mkdir -p "$DATA_DIR"
    mkdir -p "$DATA_DIR/logs"
    
    print_success "Config directory: $CONFIG_DIR"
    print_success "Data directory: $DATA_DIR"
    
    # Copy default configuration if not exists
    if [ ! -f "$CONFIG_DIR/config.yaml" ]; then
        if [ -f "config/config.yaml" ]; then
            cp "config/config.yaml" "$CONFIG_DIR/"
            print_success "Default configuration copied"
        fi
    else
        print_info "Configuration already exists, preserving"
    fi
    
    # Copy personality and agent files
    if [ ! -f "$CONFIG_DIR/personality.md" ]; then
        if [ -f "config/personality.md" ]; then
            cp "config/personality.md" "$CONFIG_DIR/"
            print_success "Personality configuration copied"
        fi
    fi
    
    if [ ! -f "$CONFIG_DIR/agent.md" ]; then
        if [ -f "config/agent.md" ]; then
            cp "config/agent.md" "$CONFIG_DIR/"
            print_success "Agent rules copied"
        fi
    fi
    
    # Copy .env.example if .env doesn't exist
    if [ ! -f "$CONFIG_DIR/.env" ]; then
        if [ -f "config/.env.example" ]; then
            cp "config/.env.example" "$CONFIG_DIR/.env"
            print_success "Environment template created"
            print_warning "Edit $CONFIG_DIR/.env to add your API keys!"
        fi
    fi
    
    # Export for later use
    export SMS_AGENT_CONFIG_DIR="$CONFIG_DIR"
    export SMS_AGENT_DATA_DIR="$DATA_DIR"
}

# Setup Termux:Boot for auto-start
setup_termux_boot() {
    print_info "Setting up Termux:Boot service..."
    
    BOOT_DIR="$HOME/.termux/boot"
    mkdir -p "$BOOT_DIR"
    
    BOOT_SCRIPT="$BOOT_DIR/sms-ai-agent.sh"
    
    cat > "$BOOT_SCRIPT" << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash
# SMS AI Agent Boot Script
# This script runs when the device boots (requires Termux:Boot app)

# Wait for device to fully boot
sleep 30

# Change to script directory
cd "$HOME/sms-ai-agent" 2>/dev/null || cd "$(dirname "$0")/../sms-ai-agent" 2>/dev/null || exit 0

# Start the SMS AI Agent
python main.py --daemon &

# Log the start
echo "$(date): SMS AI Agent started" >> "$HOME/.sms-ai-agent/boot.log"
EOF
    
    chmod +x "$BOOT_SCRIPT"
    print_success "Boot script created at $BOOT_SCRIPT"
    print_info "Install Termux:Boot app from F-Droid for auto-start on boot"
}

# Setup Termux:Widget shortcuts
setup_termux_widget() {
    print_info "Setting up Termux:Widget shortcuts..."
    
    SHORTCUTS_DIR="$HOME/.termux/shortcuts"
    mkdir -p "$SHORTCUTS_DIR"
    
    # Start Web UI shortcut
    cat > "$SHORTCUTS_DIR/SMS Agent Web UI" << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash
cd "$HOME/sms-ai-agent" 2>/dev/null || exit 1
python main.py --web
EOF
    chmod +x "$SHORTCUTS_DIR/SMS Agent Web UI"
    
    # Start TUI shortcut
    cat > "$SHORTCUTS_DIR/SMS Agent TUI" << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash
cd "$HOME/sms-ai-agent" 2>/dev/null || exit 1
python main.py --tui
EOF
    chmod +x "$SHORTCUTS_DIR/SMS Agent TUI"
    
    # Status shortcut
    cat > "$SHORTCUTS_DIR/SMS Agent Status" << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash
cd "$HOME/sms-ai-agent" 2>/dev/null || exit 1
python main.py --status
EOF
    chmod +x "$SHORTCUTS_DIR/SMS Agent Status"
    
    print_success "Widget shortcuts created in $SHORTCUTS_DIR"
    print_info "Install Termux:Widget app from F-Droid for home screen shortcuts"
}

# Request necessary permissions
request_permissions() {
    print_info "Requesting permissions..."
    
    if command -v termux-sms-send &> /dev/null; then
        print_info "SMS permission required. Grant when prompted..."
        # This will request SMS permission
        termux-sms-send -n "0000000000" "Permission test" 2>/dev/null || true
        print_success "SMS permission should now be granted"
    else
        print_warning "termux-sms-send not found. Install termux-api package."
    fi
    
    print_info ""
    print_info "Required permissions:"
    print_info "  1. SMS: For sending and receiving messages"
    print_info "  2. Storage: For accessing configuration files"
    print_info "  3. Background: For running as a service"
    print_info ""
    print_info "Grant these in: Settings > Apps > Termux > Permissions"
}

# Create run scripts
create_run_scripts() {
    print_info "Creating run scripts..."
    
    # Start script
    cat > "start.sh" << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
python main.py "$@"
EOF
    chmod +x "start.sh"
    
    # Stop script
    cat > "stop.sh" << 'EOF'
#!/bin/bash
pkill -f "python main.py" 2>/dev/null || true
echo "SMS AI Agent stopped"
EOF
    chmod +x "stop.sh"
    
    # Web UI script
    cat > "run_web.sh" << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
python main.py --web "$@"
EOF
    chmod +x "run_web.sh"
    
    # TUI script
    cat > "run_tui.sh" << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
python main.py --tui "$@"
EOF
    chmod +x "run_tui.sh"
    
    print_success "Run scripts created"
}

# First run setup
first_run_setup() {
    print_info "Performing first-run setup..."
    
    # Check if OpenRouter API key is set
    if [ -f "$CONFIG_DIR/.env" ]; then
        if grep -q "sk-or-your-api-key-here" "$CONFIG_DIR/.env"; then
            print_warning ""
            print_warning "=========================================="
            print_warning "IMPORTANT: Configure your API key!"
            print_warning "=========================================="
            print_warning ""
            print_info "1. Get an API key from: https://openrouter.ai/keys"
            print_info "2. Edit: $CONFIG_DIR/.env"
            print_info "3. Set: OPENROUTER_API_KEY=your-key-here"
            print_info "4. Restart the service"
            print_info ""
        fi
    fi
    
    # Ask to launch Web UI
    print_info ""
    print_info "Setup complete! Launch options:"
    print_info "  Web UI:    python main.py --web"
    print_info "  Terminal:  python main.py --tui"
    print_info "  Help:      python main.py --help"
    print_info ""
    
    read -p "Launch Web UI now? [Y/n] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Nn]$ ]]; then
        print_info "Starting Web UI..."
        python main.py --web
    fi
}

# Print banner
print_banner() {
    echo ""
    echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║      SMS AI Agent - Installer         ║${NC}"
    echo -e "${BLUE}║     Termux-based SMS Auto-Responder   ║${NC}"
    echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
    echo ""
}

# Main installation
main() {
    print_banner
    
    # Check environment
    check_termux
    check_android_version
    
    # Install dependencies
    install_termux_packages
    install_python_deps
    
    # Setup configuration
    setup_config_dir
    create_run_scripts
    
    # Optional: Setup boot and widgets
    if [ "$1" == "--first-run" ] || [ "$1" == "--full" ]; then
        setup_termux_boot
        setup_termux_widget
        request_permissions
        first_run_setup
    fi
    
    print_success ""
    print_success "Installation complete!"
    print_success ""
    
    if [ "$1" != "--first-run" ] && [ "$1" != "--full" ]; then
        print_info "For full setup including auto-start, run:"
        print_info "  ./install.sh --first-run"
        print_info ""
    fi
    
    print_info "Quick start:"
    print_info "  ./run_web.sh    # Start Web UI"
    print_info "  ./run_tui.sh    # Start Terminal UI"
    print_info "  python main.py --help  # Show all options"
}

# Run main
main "$@"
