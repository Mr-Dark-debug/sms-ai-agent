#!/usr/bin/env python3
"""
SMS AI Agent - Main Entry Point
===============================

This is the main entry point for the SMS AI Agent system.
It provides a command-line interface for running the agent
in various modes.

Usage:
    python main.py --web          # Start web UI
    python main.py --tui          # Start terminal UI
    python main.py --daemon       # Run as background service
    python main.py --status       # Check system status
    python main.py --test         # Test message handling
    python main.py --help         # Show help
"""

import os
import sys
import argparse
import asyncio
import signal
from pathlib import Path
from typing import Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from core.config import load_config, create_default_config, Config
from core.database import init_database
from core.logging import setup_logging, get_logger
from core.exceptions import SMSAgentError

logger = get_logger("main")


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="SMS AI Agent - Termux-based SMS Auto-Responder",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --web              Start web UI on default port
  python main.py --web --port 9000  Start web UI on port 9000
  python main.py --tui              Start terminal UI
  python main.py --daemon           Run as background service
  python main.py --test "Hello"     Test message handling
  python main.py --status           Check system status
  python main.py --setup            Run initial setup

For more information, visit: https://github.com/sms-ai-agent
        """
    )
    
    # Mode selection (mutually exclusive)
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--web",
        action="store_true",
        help="Start web UI server"
    )
    mode_group.add_argument(
        "--tui",
        action="store_true",
        help="Start terminal UI"
    )
    mode_group.add_argument(
        "--daemon",
        action="store_true",
        help="Run as background daemon (SMS listener only)"
    )
    mode_group.add_argument(
        "--status",
        action="store_true",
        help="Check system status"
    )
    mode_group.add_argument(
        "--test",
        nargs="+",
        metavar=("MESSAGE", "SENDER"),
        help="Test message handling (usage: --test 'Hello' [SENDER_NUMBER])"
    )
    mode_group.add_argument(
        "--send-sms",
        nargs=2,
        metavar=("NUMBER", "MESSAGE"),
        help="Send an SMS message (usage: --send-sms +1234567890 'Hello')"
    )
    mode_group.add_argument(
        "--setup",
        action="store_true",
        help="Run initial setup wizard"
    )
    mode_group.add_argument(
        "--api-key",
        type=str,
        metavar="KEY",
        help="Set API key for LLM provider"
    )
    mode_group.add_argument(
        "--diagnose",
        action="store_true",
        help="Run diagnostic checks for SMS functionality"
    )
    
    # Optional arguments
    parser.add_argument(
        "--config",
        type=str,
        metavar="PATH",
        help="Path to configuration file"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port for web UI (default: 8080)"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host for web UI (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode"
    )
    parser.add_argument(
        "--provider",
        type=str,
        choices=["openrouter", "ollama"],
        help="LLM provider to use"
    )
    parser.add_argument(
        "--model",
        type=str,
        help="Model to use"
    )
    
    return parser.parse_args()


def check_dependencies() -> bool:
    """
    Check if all required dependencies are installed.
    
    Returns:
        True if all dependencies are available
    """
    missing = []
    
    try:
        import yaml  # noqa: F401
    except ImportError:
        missing.append("pyyaml")
    
    try:
        import fastapi  # noqa: F401
    except ImportError:
        missing.append("fastapi")
    
    try:
        import uvicorn  # noqa: F401
    except ImportError:
        missing.append("uvicorn")
    
    try:
        import jinja2  # noqa: F401
    except ImportError:
        missing.append("jinja2")
    
    if missing:
        print(f"Missing dependencies: {', '.join(missing)}")
        print("Install with: pip install " + " ".join(missing))
        return False
    
    return True


def run_setup_wizard() -> None:
    """Run interactive setup wizard."""
    print("\n" + "=" * 50)
    print("SMS AI Agent Setup Wizard")
    print("=" * 50 + "\n")
    
    # Check/create config directory
    config_dir = os.environ.get("SMS_AGENT_CONFIG_DIR")
    if not config_dir:
        if os.environ.get("XDG_CONFIG_HOME"):
            config_dir = os.path.join(os.environ["XDG_CONFIG_HOME"], "sms-ai-agent")
        elif os.path.exists(os.path.expanduser("~/.config")):
            config_dir = os.path.expanduser("~/.config/sms-ai-agent")
        else:
            config_dir = os.path.expanduser("~/.sms-ai-agent")
    
    print(f"Configuration directory: {config_dir}")
    
    # Create default configuration
    config = create_default_config(config_dir)
    print("✓ Created default configuration")
    
    # Ask for API key
    print("\nLLM Provider Configuration")
    print("-" * 30)
    
    provider = input("Provider [openrouter/ollama] (default: openrouter): ").strip()
    if provider not in ["openrouter", "ollama"]:
        provider = "openrouter"
    
    config.llm.provider = provider
    
    if provider == "openrouter":
        print("\nTo use OpenRouter, you need an API key.")
        print("Get one at: https://openrouter.ai/keys")
        api_key = input("Enter your OpenRouter API key (or press Enter to skip): ").strip()
        
        if api_key:
            config.llm.api_key = api_key
            # Save to .env file
            env_file = Path(config_dir) / ".env"
            with open(env_file, "a") as f:
                f.write(f"\nOPENROUTER_API_KEY={api_key}\n")
            print("✓ API key saved")
    else:
        print("\nOllama runs locally. Make sure Ollama is installed.")
        print("Visit: https://ollama.ai")
    
    # Save configuration
    from core.config import save_config
    save_config(config)
    print("\n✓ Configuration saved")
    
    # Ask about auto-start
    print("\nAuto-Start Configuration")
    print("-" * 30)
    
    boot = input("Setup auto-start on device boot? [y/N]: ").strip().lower()
    if boot == "y":
        boot_dir = Path.home() / ".termux" / "boot"
        boot_dir.mkdir(parents=True, exist_ok=True)
        
        boot_script = boot_dir / "sms-ai-agent.sh"
        with open(boot_script, "w") as f:
            f.write(f"""#!/bin/bash
# SMS AI Agent auto-start script
sleep 30
cd "{Path(__file__).parent}"
python main.py --daemon &
""")
        os.chmod(boot_script, 0o755)
        print("✓ Auto-start configured")
        print("  Note: Requires Termux:Boot app from F-Droid")
    
    print("\n" + "=" * 50)
    print("Setup Complete!")
    print("=" * 50)
    print("\nTo start the agent:")
    print("  Web UI:    python main.py --web")
    print("  Terminal:  python main.py --tui")
    print("  Help:      python main.py --help")


def run_status_check(config: Config) -> None:
    """Check and display system status."""
    from core.security import SecurityManager
    from services.sms_handler import SMSHandler
    from services.ai_responder import AIResponder
    from llm.factory import create_llm_provider
    
    print("\n" + "=" * 50)
    print("SMS AI Agent - System Status")
    print("=" * 50 + "\n")
    
    # Initialize database
    db_path = os.path.join(config.data_dir, "sms_agent.db")
    database = init_database(db_path)
    
    # Check SMS
    print("SMS Handler")
    print("-" * 30)
    sms_handler = SMSHandler(
        webhook_config={
            "enabled": config.sms.webhook_enabled,
            "url": config.sms.webhook_url,
            "headers": config.sms.webhook_headers
        }
    )
    if sms_handler.is_available:
        print("  Status: ✓ Available")
        info = sms_handler.get_device_info()
        if info.get("phone_number"):
            print(f"  Phone: {info['phone_number']}")
    else:
        print("  Status: ✗ Unavailable")
        print("  Note: Install Termux:API and grant SMS permission")
    
    # Check Security
    print("\nSecurity")
    print("-" * 30)
    security = SecurityManager(config.config_dir, config.data_dir)
    report = security.export_security_report()
    
    for provider, configured in report["api_keys_configured"].items():
        status = "✓ Configured" if configured else "✗ Not Set"
        print(f"  {provider.title()}: {status}")
    
    # Check LLM
    print("\nLLM Provider")
    print("-" * 30)
    print(f"  Provider: {config.llm.provider}")
    print(f"  Model: {config.llm.model}")
    print(f"  Temperature: {config.llm.temperature}")
    print(f"  Max Tokens: {config.llm.max_tokens}")
    
    if config.llm.api_key:
        print("  API Key: ✓ Set")
        
        # Test connection
        print("\n  Testing connection...")
        try:
            llm = create_llm_provider(config=config)
            if llm.is_available():
                print("  Connection: ✓ Successful")
            else:
                print("  Connection: ✗ Failed")
        except Exception as e:
            print(f"  Connection: ✗ Error: {e}")
    else:
        print("  API Key: ✗ Not Set")
    
    # Database stats
    print("\nDatabase")
    print("-" * 30)
    stats = database.get_statistics()
    print(f"  Messages: {sum(stats.get('messages', {}).values())}")
    print(f"  Conversations: {stats.get('conversations', 0)}")
    print(f"  LLM Requests: {sum(stats.get('llm_requests', {}).values())}")
    print(f"  Guardrail Blocks: {stats.get('guardrail_violations', 0)}")
    
    # Configuration
    print("\nConfiguration")
    print("-" * 30)
    print(f"  Auto Reply: {'Enabled' if config.sms.auto_reply_enabled else 'Disabled'}")
    print(f"  AI Mode: {'Enabled' if config.sms.ai_mode_enabled else 'Disabled'}")
    print(f"  Rate Limit: {config.rate_limit.max_messages_per_minute}/min")
    
    print("\n" + "=" * 50 + "\n")


def run_send_sms(config: Config, phone_number: str, message: str) -> None:
    """Send an SMS message."""
    from services.sms_handler import SMSHandler
    
    print(f"\nSending SMS to {phone_number}...")
    print(f"Message: {message}")
    print("-" * 50)
    
    sms_handler = SMSHandler(
        timeout=config.sms.sms_timeout,
        webhook_config={
            "enabled": config.sms.webhook_enabled,
            "url": config.sms.webhook_url,
            "headers": config.sms.webhook_headers
        }
    )
    
    if not sms_handler.is_available:
        print("✗ SMS handler not available!")
        print("  Check Termux API installation and permissions.")
        return
    
    try:
        sms_handler.send_sms(phone_number, message)
        print("✓ Message sent successfully")
    except Exception as e:
        print(f"✗ Failed to send message: {e}")


def run_diagnosis() -> None:
    """Run diagnostic checks for SMS functionality."""

    from services.sms_handler import SMSHandler
    
    print("\n" + "=" * 50)
    print("SMS AI Agent - Diagnostic Mode")
    print("=" * 50 + "\n")
    
    handler = SMSHandler()
    results = handler.diagnose()
    
    print("1. Termux API Installation")
    print("-" * 30)
    if results["termux_api_installed"]:
        print("   ✓ termux-sms-list is installed")
    else:
        print("   ✗ termux-sms-list NOT found")
        print("   → Run: pkg install termux-api")
    
    print("\n2. SMS List Capability")
    print("-" * 30)
    if results["sms_list_works"]:
        print("   ✓ Can read SMS messages")
        if results["sample_messages"]:
            print(f"   Found {len(results['sample_messages'])} recent messages:")
            for m in results["sample_messages"]:
                print(f"     - {m['number']}: '{m['preview']}...' (type={m['type']})")
    else:
        print("   ✗ Cannot read SMS - permission issue likely")
        print("   → Settings → Apps → Termux:API → Permissions")
        print("   → Enable: SMS, Storage, Phone")
    
    print("\n3. SMS Send Capability")
    print("-" * 30)
    if results["sms_send_available"]:
        print("   ✓ termux-sms-send is available")
    else:
        print("   ✗ termux-sms-send NOT found")
    
    print("\n4. Device Info")
    print("-" * 30)
    if results["device_info"]:
        print(f"   Phone: {results['device_info'].get('phone_number', 'Unknown')}")
        print(f"   Network: {results['device_info'].get('network_operator_name', 'Unknown')}")
    else:
        print("   ⚠ Could not get device info")
    
    if results["errors"]:
        print("\n5. Errors Found")
        print("-" * 30)
        for err in results["errors"]:
            print(f"   • {err}")
    
    print("\n" + "=" * 50)
    
    if not results["sms_list_works"]:
        print("\n⚠ SMS PERMISSION REQUIRED!")
        print("1. Go to: Settings → Apps → Termux:API → Permissions")
        print("2. Enable: SMS")
        print("3. Also check: Settings → Apps → Termux → Permissions")
        print("4. Run this diagnosis again to verify")
    
    print()


def run_test_message(config: Config, message: str, phone_number: str = "+1234567890") -> None:
    """Test message handling."""
    from core.security import SecurityManager
    from services.guardrails import GuardrailSystem
    from services.ai_responder import AIResponder
    from rules.engine import RulesEngine
    
    print(f"\nTest Message: {message}")
    print(f"From: {phone_number}")
    print("-" * 50)
    
    # Initialize components
    db_path = os.path.join(config.data_dir, "sms_agent.db")
    database = init_database(db_path)
    
    security = SecurityManager(config.config_dir, config.data_dir)
    guardrails = GuardrailSystem(max_length=config.guardrail.max_response_length)
    rules_engine = RulesEngine(config_dir=config.config_dir)
    
    ai_responder = AIResponder(
        config=config,
        database=database,
        guardrails=guardrails,
        rules_engine=rules_engine,
        personality_path=os.path.join(config.config_dir, "personality.md"),
        agent_path=os.path.join(config.config_dir, "agent.md")
    )
    
    # Generate response
    print("\nGenerating response...")
    result = ai_responder.respond(message, phone_number)
    
    print(f"\nResponse:")
    print(f"  Source: {result.source}")
    print(f"  Message: {result.response}")
    print(f"  Length: {len(result.response)} chars")
    print(f"  Latency: {result.latency_ms}ms")
    
    if result.model:
        print(f"  Model: {result.model}")
    if result.tokens_used:
        print(f"  Tokens: {result.tokens_used}")
    
    if result.guardrail_result and result.guardrail_result.violations:
        print(f"\n  Guardrail Violations:")
        for v in result.guardrail_result.violations:
            print(f"    - {v['type']}: {v['action']}")


def set_api_key(config: Config, api_key: str, provider: str = "openrouter") -> None:
    """Set API key for a provider."""
    from core.security import SecurityManager
    
    security = SecurityManager(config.config_dir, config.data_dir)
    
    if not security.validate_api_key(provider, api_key):
        print(f"Error: Invalid API key format for {provider}")
        sys.exit(1)
    
    security.store_api_key(provider, api_key)
    print(f"✓ API key stored for {provider}")
    print(f"  Stored in: {config.config_dir}/.env")


def run_web_ui(config: Config, host: str, port: int, debug: bool) -> None:
    """Run the web UI server."""
    from ui.web.app import run_app
    
    print(f"\nStarting Web UI on http://{host}:{port}")
    print("Press Ctrl+C to stop\n")
    
    run_app(host=host, port=port, debug=debug, config=config)


def run_terminal_ui(config: Config) -> None:
    """Run the terminal UI."""
    from ui.terminal.app import run_tui
    
    print("\nStarting Terminal UI...")
    print("Press Ctrl+C or 'q' to exit\n")
    
    run_tui(config=config)


def run_daemon(config: Config) -> None:
    """Run as background daemon."""
    from core.security import SecurityManager
    from services.sms_handler import SMSHandler
    from services.guardrails import GuardrailSystem
    from services.ai_responder import AIResponder
    from rules.engine import RulesEngine
    from core.rate_limiter import RateLimiter
    
    print("\nStarting SMS AI Agent daemon...")
    print("Press Ctrl+C to stop\n")
    
    # Initialize components
    db_path = os.path.join(config.data_dir, "sms_agent.db")
    database = init_database(db_path)
    
    security = SecurityManager(config.config_dir, config.data_dir)
    guardrails = GuardrailSystem(max_length=config.guardrail.max_response_length)
    rules_engine = RulesEngine(config_dir=config.config_dir)
    rate_limiter = RateLimiter(
        max_per_minute=config.rate_limit.max_messages_per_minute,
        max_per_recipient_per_hour=config.rate_limit.max_per_recipient_per_hour,
        max_per_recipient_per_day=config.rate_limit.max_per_recipient_per_day
    )
    
    sms_handler = SMSHandler(
        timeout=config.sms.sms_timeout,
        webhook_config={
            "enabled": config.sms.webhook_enabled,
            "url": config.sms.webhook_url,
            "headers": config.sms.webhook_headers
        }
    )
    ai_responder = AIResponder(
        config=config,
        database=database,
        guardrails=guardrails,
        rules_engine=rules_engine,
        personality_path=os.path.join(config.config_dir, "personality.md"),
        agent_path=os.path.join(config.config_dir, "agent.md")
    )
    
    # Verify permissions before starting
    print("\nVerifying SMS permissions...")
    if not sms_handler.is_available:
        print("✗ SMS handler not available!")
        print("\nPossible causes:")
        print("1. Termux:API app not installed")
        print("2. termux-api package not installed (run: pkg install termux-api)")
        print("3. SMS permission not granted")
        print("\nRun: python main.py --diagnose")
        return
    
    # Run diagnosis to confirm everything works
    diag = sms_handler.diagnose()
    if not diag["sms_list_works"]:
        print("✗ Cannot read SMS messages - permission issue!")
        print("Grant permission: Settings → Apps → Termux:API → Permissions → SMS")
        print("\nRun: python main.py --diagnose")
        return
    
    print("✓ SMS permissions verified")
    
    # Message handler callback
    def handle_message(msg):
        logger.info(f"Received message from {msg.phone_number}: {msg.message[:50]}")
        
        # Check rate limit
        result = rate_limiter.check_and_record(msg.phone_number)
        if not result.allowed:
            logger.warning(f"Rate limited: {msg.phone_number}")
            return
        
        # Check if auto-reply is enabled
        if not config.sms.auto_reply_enabled:
            return
        
        # Store incoming message
        database.add_message(
            direction="incoming",
            phone_number=msg.phone_number,
            message=msg.message
        )
        
        # Generate response
        response = ai_responder.respond(msg.message, msg.phone_number)
        
        if response.response:
            logger.info(f"Daemon: AI generated response for {msg.phone_number}: '{response.response[:30]}...'")
            # Send response
            try:
                logger.info(f"Daemon: Attempting to send SMS to {msg.phone_number}")
                sms_handler.send_sms(msg.phone_number, response.response)
                database.add_message(
                    direction="outgoing",
                    phone_number=msg.phone_number,
                    message=response.response,
                    status="sent"
                )
                logger.info(f"Daemon: Successfully sent response to {msg.phone_number}")
            except Exception as e:
                logger.error(f"Daemon: Failed to send response to {msg.phone_number}: {e}", exc_info=True)
        else:
            logger.warning(f"Daemon: AI produced empty response for {msg.phone_number}")
    
    # Register callback and start listener
    sms_handler.on_message_received(handle_message)
    
    # Handle shutdown
    def shutdown(signum, frame):
        logger.info("Shutting down...")
        sms_handler.stop_listener()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    
    # Start listener
    logger.info("SMS listener started")
    sms_handler.start_listener(poll_interval=3)
    
    # Keep running
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown(None, None)


def main() -> int:
    """Main entry point."""
    args = parse_args()
    
    # Check dependencies
    if not check_dependencies():
        return 1
    
    # Auto-detect config directory if not set
    if "XDG_CONFIG_HOME" not in os.environ:
        # Check common config locations (user config first, then project default)
        # Also check Termux-specific locations
        termux_home = os.environ.get("TERMUX_HOME", "/data/data/com.termux/files/home")
        possible_config_dirs = [
            Path.home() / ".config" / "sms-ai-agent",
            Path.home() / ".sms-ai-agent",
            Path(termux_home) / ".config" / "sms-ai-agent" if termux_home != str(Path.home()) else None,
            Path("/data/data/com.termux/files/home") / ".config" / "sms-ai-agent",
        ]
        possible_config_dirs = [d for d in possible_config_dirs if d]
        
        # Also check if there's a config in the data directory
        data_home = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
        possible_config_dirs.append(Path(data_home) / "sms-ai-agent")
        
        found_config = False
        for config_dir in possible_config_dirs:
            if (config_dir / "config.yaml").exists():
                os.environ["XDG_CONFIG_HOME"] = str(config_dir.parent)
                found_config = True
                break
        
        # If no user config found, create default config directory
        if not found_config:
            user_config = Path.home() / ".config" / "sms-ai-agent"
            user_config.mkdir(parents=True, exist_ok=True)
    
    # Load or create configuration
    try:
        if args.setup:
            run_setup_wizard()
            return 0
        
        config = load_config(args.config)
        
        # Apply command-line overrides
        if args.provider:
            config.llm.provider = args.provider
        if args.model:
            config.llm.model = args.model
        if args.debug:
            config.debug = True
        
        # Setup logging
        setup_logging(
            log_dir=config.log_dir,
            log_level="DEBUG" if args.debug else "INFO",
            console_output=True
        )
        
        # Route to appropriate mode
        if args.web:
            run_web_ui(config, args.host, args.port, args.debug)
        elif args.tui:
            run_terminal_ui(config)
        elif args.daemon:
            run_daemon(config)
        elif args.diagnose:
            run_diagnosis()
        elif args.status:
            run_status_check(config)
        elif args.test:
            message = args.test[0]
            sender = args.test[1] if len(args.test) > 1 else "+1234567890"
            run_test_message(config, message, sender)
        elif args.send_sms:
            run_send_sms(config, args.send_sms[0], args.send_sms[1])
        elif args.api_key:
            set_api_key(config, args.api_key, args.provider or "openrouter")
        else:
            # Default: show help
            run_status_check(config)
            print("\nNo mode specified. Use --web, --tui, --daemon, or --help")
            print("\nQuick start:")
            print("  python main.py --web    # Start web UI")
            print("  python main.py --tui    # Start terminal UI")
        
        return 0
    
    except SMSAgentError as e:
        print(f"\nError: {e}")
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted")
        return 0
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
