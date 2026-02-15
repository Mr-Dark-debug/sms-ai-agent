"""
Textual Application - Main TUI application
========================================

This module implements the main Textual TUI application for
SMS AI Agent, providing a rich terminal interface.
"""

import asyncio
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll, Grid
from textual.widgets import (
    Header, Footer, Static, Button, Input, Label,
    DataTable, TabbedContent, TabPane, TextArea, Checkbox, Select,
    Sparkline, ProgressBar
)
from textual.binding import Binding
from textual.screen import Screen
from textual.reactive import reactive
from textual.message import Message
from textual import work

from core.config import Config, load_config
from core.database import Database, init_database
from core.logging import get_logger
from services.sms_handler import SMSHandler
from services.guardrails import GuardrailSystem
from services.ai_responder import AIResponder
from rules.engine import RulesEngine

logger = get_logger("tui.app")


class StatusCard(Static):
    """A professional status card widget."""
    
    def __init__(self, title: str, value: str, status: str = "ok", **kwargs):
        super().__init__(**kwargs)
        self.title = title
        self.value = value
        self.status = status
    
    def compose(self) -> ComposeResult:
        yield Static(self.title, classes="card-title")
        yield Static(self.value, classes="card-value")
        yield Static(self.status, classes="card-status")


class DashboardWidget(Container):
    """Dashboard widget showing system status."""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.update_timer = None
    
    def compose(self) -> ComposeResult:
        yield Static("╔══════════════════════════════════════════════════════════╗", classes="header-line")
        yield Static("║              📱 SMS AI Agent - Dashboard                 ║", classes="header-title")
        yield Static("╚══════════════════════════════════════════════════════════╝", classes="header-line")
        
        with VerticalScroll(id="dashboard-content"):
            with Grid(id="status-grid"):
                yield StatusCard("SMS Status", "Checking...", "termux-api", id="card-sms")
                yield StatusCard("LLM Status", "Connecting...", "ai-model", id="card-llm")
                yield StatusCard("AI Mode", "Enabled", "on/off", id="card-aimode")
                yield StatusCard("Auto Reply", "Enabled", "on/off", id="card-autoreply")
            
            yield Static("", classes="divider")
            yield Static("📊 Statistics", classes="section-title")
            yield Static(id="stats-content", classes="stats-box")
            
            yield Static("", classes="divider")
            yield Static("⚡ Quick Actions", classes="section-title")
            with Horizontal(id="quick-actions"):
                yield Button("🔄 Refresh", id="btn-refresh", variant="default")
                yield Button("🧪 Test", id="btn-test", variant="primary")
                yield Button("⚙️ Settings", id="btn-settings", variant="secondary")
    
    def on_mount(self) -> None:
        """Start update timer."""
        self.update_timer = self.set_interval(5, self.update_status)
        self.update_status()
        
        # Bind button events
        self.query_one("#btn-refresh", Button).focus()
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press."""
        if event.button.id == "btn-refresh":
            self.update_status()
            self.app.notify("Dashboard refreshed!", title="Refresh")
        elif event.button.id == "btn-test":
            self.app.action_test()
        elif event.button.id == "btn-settings":
            self.app.action_settings()
    
    def update_status(self) -> None:
        """Update status display."""
        app = self.app
        
        # Update SMS card
        sms_card = self.query_one("#card-sms")
        if hasattr(app, 'sms_handler'):
            is_available = app.sms_handler.is_available
            sms_card.title = "SMS Status"
            sms_card.value = "✓ Available" if is_available else "✗ Unavailable"
            sms_card.status = "Ready" if is_available else "Setup Required"
        
        # Update LLM card
        llm_card = self.query_one("#card-llm")
        if hasattr(app, 'ai_responder') and app.ai_responder.llm:
            llm_test = app.ai_responder.test_connection()
            is_connected = llm_test.get("connection_ok", False)
            llm_card.title = "LLM Status"
            llm_card.value = "✓ Connected" if is_connected else "✗ Failed"
            llm_card.status = llm_test.get("provider", "N/A")
        else:
            llm_card.title = "LLM Status"
            llm_card.value = "✗ Not Configured"
            llm_card.status = "Setup Required"
        
        # Update AI Mode card
        aimode_card = self.query_one("#card-aimode")
        if hasattr(app, 'config'):
            enabled = app.config.sms.ai_mode_enabled
            aimode_card.title = "AI Mode"
            aimode_card.value = "✓ Enabled" if enabled else "✗ Disabled"
            aimode_card.status = "AI Replies On" if enabled else "Rules Only"
        
        # Update Auto Reply card
        auto_card = self.query_one("#card-autoreply")
        if hasattr(app, 'config'):
            enabled = app.config.sms.auto_reply_enabled
            auto_card.title = "Auto Reply"
            auto_card.value = "✓ Enabled" if enabled else "✗ Disabled"
            auto_card.status = "Active" if enabled else "Paused"
        
        # Update stats
        stats_widget = self.query_one("#stats-content")
        if hasattr(app, 'database'):
            stats = app.database.get_statistics()
            total_msgs = stats.get('messages', {}).get('incoming', 0) + stats.get('messages', {}).get('outgoing', 0)
            stats_text = f"""
┌────────────────────────────────────────┐
│  Total Messages:  {total_msgs:<20}│
│  Incoming:       {stats.get('messages', {}).get('incoming', 0):<20}│
│  Outgoing:       {stats.get('messages', {}).get('outgoing', 0):<20}│
│  Conversations:  {stats.get('conversations', 0):<20}│
│  LLM Requests:  {sum(stats.get('llm_requests', {}).values()):<20}│
│  Guardrail Block:{stats.get('guardrail_violations', 0):<20}│
└────────────────────────────────────────┘
            """
            stats_widget.update(stats_text)


class MessagesWidget(Container):
    """Widget to display message history."""
    
    def __init__(self, database: Database, **kwargs):
        super().__init__(**kwargs)
        self.database = database
    
    def compose(self) -> ComposeResult:
        yield Static("📬 Messages", classes="title")
        
        with Horizontal(classes="toolbar"):
            yield Button("🔄 Refresh", id="btn-refresh-msgs", variant="default")
            yield Button("➕ New Test", id="btn-new-test", variant="primary")
        
        yield DataTable(id="messages-table")
    
    def on_mount(self) -> None:
        """Initialize table."""
        table = self.query_one(DataTable)
        table.add_columns("Time", "Dir", "Phone Number", "Message", "Status")
        table.cursor_type = "row"
        self.load_messages()
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-refresh-msgs":
            self.load_messages()
            self.app.notify("Messages refreshed!")
        elif event.button.id == "btn-new-test":
            self.app.action_test()
    
    def load_messages(self, limit: int = 50) -> None:
        """Load messages into table."""
        table = self.query_one(DataTable)
        table.clear()
        
        messages = self.database.get_messages(limit=limit)
        
        for msg in messages:
            direction = "↓ In" if msg["direction"] == "incoming" else "↑ Out"
            phone = msg["phone_number"][:15] + "..." if len(msg["phone_number"]) > 15 else msg["phone_number"]
            message = msg["message"][:35] + "..." if len(msg["message"]) > 35 else msg["message"]
            table.add_row(
                msg["timestamp"][:16] if msg.get("timestamp") else "",
                direction,
                phone,
                message,
                msg["status"] or "—"
            )


class TestWidget(Container):
    """Widget for testing message responses."""
    
    def __init__(self, ai_responder: AIResponder, **kwargs):
        super().__init__(**kwargs)
        self.ai_responder = ai_responder
    
    def compose(self) -> ComposeResult:
        yield Static("🧪 Test Message Response", classes="title")
        
        yield Label("Enter a test message:", classes="input-label")
        yield Input(placeholder="Type your message here...", id="test-input", classes="test-input")
        
        with Horizontal(classes="button-row"):
            yield Button("📋 Test Rules", id="test-rules-btn", variant="primary")
            yield Button("🤖 Test AI", id="test-ai-btn", variant="success")
        
        yield Label("Response:", classes="input-label")
        yield Static(id="test-response", classes="response-box")
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "test-rules-btn":
            self.run_test(use_ai=False)
        elif event.button.id == "test-ai-btn":
            self.run_test(use_ai=True)
    
    @work(exclusive=True)
    async def run_test(self, use_ai: bool = False) -> None:
        input_widget = self.query_one("#test-input", Input)
        message = input_widget.value.strip()
        
        if not message:
            self.app.notify("Please enter a message!", severity="warning")
            return
        
        response_widget = self.query_one("#test-response")
        response_widget.update("⏳ Generating response...")
        
        original_mode = self.ai_responder.config.sms.ai_mode_enabled
        self.ai_responder.config.sms.ai_mode_enabled = use_ai
        
        try:
            result = self.ai_responder.respond(message, "+1234567890")
            
            response_text = f"""
╔══════════════════════════════════════════════════════════╗
║  Source: {result.source.upper():<46}║
╠══════════════════════════════════════════════════════════╣
║  Response:                                              ║
║  {result.response[:50]:<50}║
║  {result.response[50:100] if len(result.response) > 50 else '':<50}║
╠══════════════════════════════════════════════════════════╣
║  Length: {len(result.response)} chars  |  Latency: {result.latency_ms}ms         ║
║  Model:  {result.model[:40] if result.model else 'N/A':<40}             ║
╚══════════════════════════════════════════════════════════╝
"""
            response_widget.update(response_text)
            
        except Exception as e:
            response_widget.update(f"❌ Error: {str(e)}")
        
        finally:
            self.ai_responder.config.sms.ai_mode_enabled = original_mode


class SettingsWidget(Container):
    """Widget for managing settings."""
    
    def __init__(self, config: Config, database: Database, **kwargs):
        super().__init__(**kwargs)
        self.config = config
        self.database = database
    
    def compose(self) -> ComposeResult:
        yield Static("⚙️ Settings", classes="title")
        
        with VerticalScroll(classes="settings-scroll"):
            yield Static("🤖 LLM Configuration", classes="section-title")
            
            yield Label("Provider")
            yield Select(
                [("OpenRouter (Cloud)", "openrouter"), ("Ollama (Local)", "ollama")],
                id="llm-provider",
                value=self.config.llm.provider
            )
            
            yield Label("Model")
            yield Input(value=self.config.llm.model, id="llm-model", placeholder="e.g., openrouter/free")
            
            yield Label("Temperature (0.0 - 2.0)")
            yield Input(value=str(self.config.llm.temperature), id="llm-temp")
            
            yield Label("Max Tokens")
            yield Input(value=str(self.config.llm.max_tokens), id="llm-tokens")
            
            yield Static("", classes="divider")
            yield Static("📱 SMS Configuration", classes="section-title")
            
            yield Checkbox("Auto Reply Enabled", value=self.config.sms.auto_reply_enabled, id="auto-reply")
            yield Checkbox("AI Mode Enabled", value=self.config.sms.ai_mode_enabled, id="ai-mode")
            
            yield Static("", classes="divider")
            yield Button("💾 Save Settings", id="save-settings", variant="success", classes="save-button")
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-settings":
            self.save_settings()
    
    def save_settings(self) -> None:
        try:
            provider = self.query_one("#llm-provider", Select).value
            model = self.query_one("#llm-model", Input).value
            temp = float(self.query_one("#llm-temp", Input).value)
            tokens = int(self.query_one("#llm-tokens", Input).value)
            auto_reply = self.query_one("#auto-reply", Checkbox).value
            ai_mode = self.query_one("#ai-mode", Checkbox).value
            
            self.config.llm.provider = provider
            self.config.llm.model = model
            self.config.llm.temperature = temp
            self.config.llm.max_tokens = tokens
            self.config.sms.auto_reply_enabled = auto_reply
            self.config.sms.ai_mode_enabled = ai_mode
            
            self.database.set_setting("llm_provider", provider)
            self.database.set_setting("llm_model", model)
            self.database.set_setting("llm_temperature", temp)
            self.database.set_setting("llm_max_tokens", tokens)
            self.database.set_setting("sms_auto_reply", auto_reply)
            self.database.set_setting("sms_ai_mode", ai_mode)
            
            self.app.notify("✅ Settings saved successfully!", title="Success")
        except Exception as e:
            self.app.notify(f"❌ Error: {str(e)}", severity="error")


class LogsWidget(Container):
    """Widget for viewing logs."""
    
    def __init__(self, database: Database, **kwargs):
        super().__init__(**kwargs)
        self.database = database
    
    def compose(self) -> ComposeResult:
        yield Static("📜 LLM Request Logs", classes="title")
        
        with Horizontal(classes="toolbar"):
            yield Button("🔄 Refresh", id="btn-refresh-logs", variant="default")
        
        yield DataTable(id="logs-table")
    
    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Time", "Provider", "Model", "Tokens", "Latency", "Status")
        table.cursor_type = "row"
        self.load_logs()
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-refresh-logs":
            self.load_logs()
            self.app.notify("Logs refreshed!")
    
    def load_logs(self) -> None:
        table = self.query_one(DataTable)
        table.clear()
        
        logs = self.database.get_llm_logs(limit=100)
        
        for log in logs:
            model_name = log.get("model", "N/A")[:25] + "..." if len(log.get("model", "")) > 25 else log.get("model", "N/A")
            table.add_row(
                log.get("timestamp", "")[:16] if log.get("timestamp") else "",
                log.get("provider", "N/A"),
                model_name,
                str(log.get("tokens_used", 0)),
                f"{log.get('latency_ms', 0)}ms",
                log.get("status", "unknown")
            )


class MainScreen(Screen):
    """Main application screen."""
    
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("t", "test", "Test"),
        Binding("s", "settings", "Settings"),
        Binding("m", "messages", "Messages"),
        Binding("l", "logs", "Logs"),
        Binding("?", "help", "Help"),
    ]
    
    def __init__(self, config: Config, database: Database, **kwargs):
        super().__init__(**kwargs)
        self.config = config
        self.database = database
    
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        
        with TabbedContent(id="main-tabs"):
            with TabPane("📊 Dashboard", id="dashboard"):
                yield DashboardWidget()
            
            with TabPane("📬 Messages", id="messages"):
                yield MessagesWidget(self.database)
            
            with TabPane("🧪 Test", id="test"):
                yield TestWidget(self.app.ai_responder)
            
            with TabPane("⚙️ Settings", id="settings"):
                yield SettingsWidget(self.config, self.database)
            
            with TabPane("📜 Logs", id="logs"):
                yield LogsWidget(self.database)
        
        yield Footer()
    
    def action_refresh(self) -> None:
        try:
            for widget in [DashboardWidget, MessagesWidget, LogsWidget]:
                w = self.query(widget).first()
                if hasattr(w, 'update_status'):
                    w.update_status()
                elif hasattr(w, 'load_messages'):
                    w.load_messages()
                elif hasattr(w, 'load_logs'):
                    w.load_logs()
            self.app.notify("🔄 All data refreshed!")
        except Exception:
            self.app.notify("Error refreshing data", severity="warning")
    
    def action_test(self) -> None:
        tabs = self.query_one(TabbedContent)
        tabs.active = "test"
    
    def action_settings(self) -> None:
        tabs = self.query_one(TabbedContent)
        tabs.active = "settings"
    
    def action_messages(self) -> None:
        tabs = self.query_one(TabbedContent)
        tabs.active = "messages"
    
    def action_logs(self) -> None:
        tabs = self.query_one(TabbedContent)
        tabs.active = "logs"
    
    def action_help(self) -> None:
        self.app.notify(
            "Keyboard Shortcuts:\n"
            "  q - Quit\n"
            "  r - Refresh\n"
            "  t - Test\n"
            "  s - Settings\n"
            "  m - Messages\n"
            "  l - Logs\n"
            "  ? - Help",
            title="Keyboard Shortcuts"
        )


class SMSAgentApp(App):
    """
    SMS AI Agent Terminal UI Application.
    
    A rich terminal interface for managing the SMS AI Agent,
    built with Textual framework.
    """
    
    CSS = """
    Screen {
        background: $surface;
    }
    
    .header-line {
        text-align: center;
        color: $primary;
        text-style: bold;
    }
    
    .header-title {
        text-align: center;
        color: $primary;
        text-style: bold;
    }
    
    .title {
        text-style: bold;
        color: $accent;
        margin: 1 0;
    }
    
    .section-title {
        text-style: bold;
        color: $primary;
        margin: 1 0;
    }
    
    .divider {
        color: $border;
        margin: 1 0;
    }
    
    .card-title {
        color: $text-muted;
        padding: 0 1;
    }
    
    .card-value {
        color: $text;
        text-style: bold;
        padding: 0 1;
    }
    
    .card-status {
        color: $success;
        padding: 0 1;
    }
    
    #status-grid {
        grid-size: 2;
        grid-gutter: 1 2;
        padding: 1;
    }
    
    .stats-box {
        background: $panel;
        border: solid $border;
        padding: 1;
        color: $text;
    }
    
    .toolbar {
        height: auto;
        margin-bottom: 1;
    }
    
    .button-row {
        height: auto;
        margin: 1 0;
    }
    
    .input-label {
        color: $text-muted;
        margin: 1 0 0 0;
    }
    
    .test-input {
        margin: 0 0 1 0;
    }
    
    .response-box {
        background: $panel;
        border: solid $primary;
        padding: 1;
        margin: 1 0;
        color: $text;
        min-height: 8;
    }
    
    .settings-scroll {
        height: 100%;
    }
    
    .save-button {
        width: 100%;
        margin: 2 0;
    }
    
    DataTable {
        height: 100%;
        margin: 1 0;
    }
    
    TabbedContent {
        height: 100%;
    }
    
    TabPane {
        padding: 1;
    }
    
    Button {
        margin: 0 1;
    }
    
    Input, Select {
        margin: 0 0 1 0;
        width: 100%;
    }
    
    Label {
        color: $text-muted;
        margin: 1 0 0 0;
    }
    
    Checkbox {
        margin: 0 0 1 0;
    }
    """
    
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit"),
    ]
    
    def __init__(
        self,
        config: Optional[Config] = None,
        database: Optional[Database] = None
    ):
        super().__init__()
        
        self.config = config or load_config()
        
        import os
        if "XDG_CONFIG_HOME" not in os.environ:
            termux_home = os.environ.get("TERMUX_HOME", "/data/data/com.termux/files/home")
            possible_dirs = [
                Path.home() / ".config" / "sms-ai-agent",
                Path(termux_home) / ".config" / "sms-ai-agent",
            ]
            for d in possible_dirs:
                if (d / "config.yaml").exists():
                    os.environ["XDG_CONFIG_HOME"] = str(d.parent)
                    break
        
        db_path = os.path.join(self.config.data_dir, "sms_agent.db")
        self.database = database or init_database(db_path)
        
        from core.security import SecurityManager
        from services.guardrails import GuardrailSystem
        
        self.security = SecurityManager(
            config_dir=self.config.config_dir,
            data_dir=self.config.data_dir
        )
        
        self.guardrails = GuardrailSystem(
            max_length=self.config.guardrail.max_response_length
        )
        
        self.rules_engine = RulesEngine(config_dir=self.config.config_dir)
        
        self.sms_handler = SMSHandler()
        
        self.ai_responder = AIResponder(
            config=self.config,
            database=self.database,
            guardrails=self.guardrails,
            rules_engine=self.rules_engine
        )
        
        self.install_screen(MainScreen(self.config, self.database), name="main")
    
    def on_mount(self) -> None:
        self.push_screen("main")
    
    def action_quit(self) -> None:
        self.exit()


def run_tui(config: Optional[Config] = None) -> None:
    app = SMSAgentApp(config=config)
    app.run()


if __name__ == "__main__":
    run_tui()
