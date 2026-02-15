"""
Configuration Management - YAML-based configuration with environment overrides
=============================================================================

This module handles all configuration aspects including:
- Loading from YAML files
- Environment variable overrides
- Default values
- Configuration validation
- Hot-reloading support
"""

import os
import yaml
from pathlib import Path
from typing import Any, Dict, Optional, List
from dataclasses import dataclass, field, asdict
import json

from .exceptions import ConfigError


@dataclass
class LLMConfig:
    """
    LLM provider configuration.
    
    Contains all settings related to AI language model providers,
    including API credentials, model selection, and generation parameters.
    """
    # Provider settings
    provider: str = "groq"  # groq, openrouter, ollama
    model: str = "openai/gpt-oss-120b"
    api_key: str = ""  # Loaded from environment
    api_base: str = "https://api.groq.com/openai/v1"
    
    # Generation parameters
    temperature: float = 0.7
    max_tokens: int = 300
    top_p: float = 0.9
    
    # Ollama-specific settings
    ollama_host: str = "http://localhost:11434"
    
    # Behavior settings
    fallback_to_rules: bool = True
    timeout: int = 30
    
    def validate(self) -> None:
        """Validate LLM configuration parameters."""
        if self.provider not in ["groq", "openrouter", "ollama"]:
            raise ConfigError(f"Invalid LLM provider: {self.provider}")
        
        if not 0 <= self.temperature <= 2:
            raise ConfigError(f"Temperature must be between 0 and 2, got {self.temperature}")
        
        if self.max_tokens < 1 or self.max_tokens > 4096:
            raise ConfigError(f"max_tokens must be between 1 and 4096, got {self.max_tokens}")
        
        if self.provider in ["openrouter", "groq"] and not self.api_key:
            raise ConfigError(f"{self.provider.capitalize()} API key is required")


@dataclass
class SMSConfig:
    """
    SMS handling configuration.
    
    Controls how SMS messages are processed, including automatic
    responses, filtering, and Termux API integration settings.
    """
    # Auto-response settings
    auto_reply_enabled: bool = True
    ai_mode_enabled: bool = True
    
    # SMS constraints
    max_response_length: int = 300  # SMS length limit
    truncate_message: str = "..."
    
    # Filtering
    ignored_numbers: List[str] = field(default_factory=list)
    allowed_numbers: List[str] = field(default_factory=list)  # Empty = all allowed
    
    # Termux API settings
    termux_api_path: str = "termux-sms-send"
    sms_timeout: int = 10
    
    # Webhook settings
    webhook_enabled: bool = False
    webhook_url: str = ""
    webhook_headers: Dict[str, str] = field(default_factory=dict)
    
    def validate(self) -> None:
        """Validate SMS configuration parameters."""
        if self.max_response_length < 1 or self.max_response_length > 1600:
            raise ConfigError(
                f"max_response_length must be between 1 and 1600, got {self.max_response_length}"
            )


@dataclass
class RateLimitConfig:
    """
    Rate limiting configuration.
    
    Defines rate limits to prevent abuse and ensure fair usage
    of the auto-responder system.
    """
    # Global limits (per minute) - set to high value to disable
    max_messages_per_minute: int = 1000
    
    # Per-recipient limits - set to high value to disable
    max_per_recipient_per_hour: int = 100
    max_per_recipient_per_day: int = 1000
    
    # Cooldown between messages (seconds) - set to 0 to disable
    min_interval_seconds: float = 0.0
    
    # Burst settings
    burst_allowance: int = 100
    burst_window_seconds: int = 60
    
    def validate(self) -> None:
        """Validate rate limit configuration."""
        if self.max_messages_per_minute < 1:
            raise ConfigError("max_messages_per_minute must be at least 1")
        
        if self.min_interval_seconds < 0:
            raise ConfigError("min_interval_seconds cannot be negative")


@dataclass
class GuardrailConfig:
    """
    Guardrail configuration for safe AI responses.
    
    Defines safety rules and content filtering to ensure
    generated responses are appropriate and safe.
    """
    # Content filtering
    block_personal_info: bool = True
    block_links: bool = False
    block_phone_numbers: bool = True
    block_email_addresses: bool = True
    
    # Length constraints
    max_response_length: int = 300
    enforce_length_limit: bool = True
    
    # Content patterns to block (regex patterns)
    blocked_patterns: List[str] = field(default_factory=lambda: [
        r"password",
        r"credit card",
        r"social security",
        r"bank account",
    ])
    
    # Allowed response patterns
    require_polite_tone: bool = True
    
    def validate(self) -> None:
        """Validate guardrail configuration."""
        if self.max_response_length < 1:
            raise ConfigError("max_response_length must be at least 1")


@dataclass
class UIConfig:
    """
    User interface configuration.
    
    Controls settings for both the terminal UI (TUI) and web UI,
    including server settings and display preferences.
    """
    # Web UI settings
    web_enabled: bool = True
    web_host: str = "127.0.0.1"
    web_port: int = 8080
    web_debug: bool = False
    
    # Terminal UI settings
    tui_enabled: bool = True
    tui_theme: str = "dark"
    tui_refresh_rate: int = 1  # seconds
    
    # Display settings
    log_lines: int = 100
    show_timestamps: bool = True
    
    def validate(self) -> None:
        """Validate UI configuration."""
        if self.web_port < 1 or self.web_port > 65535:
            raise ConfigError(f"Invalid web port: {self.web_port}")


@dataclass
class Config:
    """
    Main configuration container.
    
    Aggregates all configuration sections into a single object
    and provides methods for loading, saving, and validating.
    """
    # Application settings
    app_name: str = "SMS AI Agent"
    version: str = "1.0.0"
    debug: bool = False
    
    # Configuration sections
    llm: LLMConfig = field(default_factory=LLMConfig)
    sms: SMSConfig = field(default_factory=SMSConfig)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    guardrail: GuardrailConfig = field(default_factory=GuardrailConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    
    # Paths (set at runtime)
    config_dir: str = ""
    data_dir: str = ""
    log_dir: str = ""
    
    def validate(self) -> None:
        """
        Validate all configuration sections.
        
        Raises:
            ConfigError: If any configuration section is invalid
        """
        self.llm.validate()
        self.sms.validate()
        self.rate_limit.validate()
        self.guardrail.validate()
        self.ui.validate()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            "app_name": self.app_name,
            "version": self.version,
            "debug": self.debug,
            "llm": asdict(self.llm),
            "sms": asdict(self.sms),
            "rate_limit": asdict(self.rate_limit),
            "guardrail": asdict(self.guardrail),
            "ui": asdict(self.ui),
        }


def get_default_config_dir() -> Path:
    """
    Get the default configuration directory path.
    
    Returns:
        Path to the configuration directory
    """
    # Check environment variable first
    if "SMS_AGENT_CONFIG_DIR" in os.environ:
        return Path(os.environ["SMS_AGENT_CONFIG_DIR"])
    
    # Check for XDG config home
    if "XDG_CONFIG_HOME" in os.environ:
        return Path(os.environ["XDG_CONFIG_HOME"]) / "sms-ai-agent"
    
    # Default to ~/.config/sms-ai-agent or ~/.sms-ai-agent
    home = Path.home()
    config_home = home / ".config"
    
    if config_home.exists():
        return config_home / "sms-ai-agent"
    
    return home / ".sms-ai-agent"


def get_default_data_dir() -> Path:
    """
    Get the default data directory path.
    
    Returns:
        Path to the data directory
    """
    # Check environment variable first
    if "SMS_AGENT_DATA_DIR" in os.environ:
        return Path(os.environ["SMS_AGENT_DATA_DIR"])
    
    # Check for XDG data home
    if "XDG_DATA_HOME" in os.environ:
        return Path(os.environ["XDG_DATA_HOME"]) / "sms-ai-agent"
    
    # Default to ~/.local/share/sms-ai-agent
    home = Path.home()
    data_home = home / ".local" / "share"
    
    return data_home / "sms-ai-agent"


def load_config(config_path: Optional[str] = None, load_env: bool = True) -> Config:
    """
    Load configuration from YAML file with environment variable overrides.
    
    This function loads configuration in the following order:
    1. Default values from dataclass
    2. Values from YAML file
    3. Environment variable overrides
    
    Args:
        config_path: Path to configuration file (optional)
        load_env: Whether to load environment variable overrides
        
    Returns:
        Config object with loaded values
        
    Raises:
        ConfigError: If configuration is invalid or cannot be loaded
    """
    config = Config()
    
    # Set default paths
    config.config_dir = str(get_default_config_dir())
    config.data_dir = str(get_default_data_dir())
    config.log_dir = str(Path(config.data_dir) / "logs")
    
    # Load .env file from config directory if it exists
    if load_env:
        env_file = Path(config.config_dir) / ".env"
        if env_file.exists():
            try:
                with open(env_file, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, value = line.split("=", 1)
                            if key and value and key not in os.environ:
                                os.environ[key] = value
            except Exception:
                pass
    
    # Determine config file path
    if config_path:
        yaml_path = Path(config_path)
    else:
        yaml_path = Path(config.config_dir) / "config.yaml"
    
    # Load from YAML file if it exists
    if yaml_path.exists():
        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                yaml_config = yaml.safe_load(f) or {}
            
            # Apply YAML values to config
            _apply_yaml_config(config, yaml_config)
        except yaml.YAMLError as e:
            raise ConfigError(f"Failed to parse config file: {e}", {"path": str(yaml_path)})
        except IOError as e:
            raise ConfigError(f"Failed to read config file: {e}", {"path": str(yaml_path)})
    
    # Load environment variable overrides
    if load_env:
        _apply_env_overrides(config)
    
    # Validate configuration
    config.validate()
    
    return config


def _apply_yaml_config(config: Config, yaml_config: Dict[str, Any]) -> None:
    """
    Apply YAML configuration values to Config object.
    
    Args:
        config: Config object to update
        yaml_config: Dictionary of configuration values from YAML
    """
    # Top-level settings
    if "app_name" in yaml_config:
        config.app_name = yaml_config["app_name"]
    if "version" in yaml_config:
        config.version = yaml_config["version"]
    if "debug" in yaml_config:
        config.debug = yaml_config["debug"]
    
    # LLM configuration
    if "llm" in yaml_config:
        llm_cfg = yaml_config["llm"]
        for key, value in llm_cfg.items():
            if hasattr(config.llm, key):
                setattr(config.llm, key, value)
    
    # SMS configuration
    if "sms" in yaml_config:
        sms_cfg = yaml_config["sms"]
        for key, value in sms_cfg.items():
            if hasattr(config.sms, key):
                setattr(config.sms, key, value)
    
    # Rate limit configuration
    if "rate_limit" in yaml_config:
        rate_cfg = yaml_config["rate_limit"]
        for key, value in rate_cfg.items():
            if hasattr(config.rate_limit, key):
                setattr(config.rate_limit, key, value)
    
    # Guardrail configuration
    if "guardrail" in yaml_config:
        guard_cfg = yaml_config["guardrail"]
        for key, value in guard_cfg.items():
            if hasattr(config.guardrail, key):
                setattr(config.guardrail, key, value)
    
    # UI configuration
    if "ui" in yaml_config:
        ui_cfg = yaml_config["ui"]
        for key, value in ui_cfg.items():
            if hasattr(config.ui, key):
                setattr(config.ui, key, value)


def _apply_env_overrides(config: Config) -> None:
    """
    Apply environment variable overrides to Config object.
    
    Environment variables follow the pattern: SMS_AGENT_SECTION_KEY
    For example: SMS_AGENT_LLM_API_KEY, SMS_AGENT_SMS_AUTO_REPLY_ENABLED
    
    Args:
        config: Config object to update
    """
    env_mappings = {
        # LLM settings
        "SMS_AGENT_LLM_PROVIDER": ("llm", "provider"),
        "SMS_AGENT_LLM_MODEL": ("llm", "model"),
        "SMS_AGENT_LLM_API_KEY": ("llm", "api_key"),
        "SMS_AGENT_LLM_API_BASE": ("llm", "api_base"),
        "SMS_AGENT_LLM_TEMPERATURE": ("llm", "temperature", float),
        "SMS_AGENT_LLM_MAX_TOKENS": ("llm", "max_tokens", int),
        "SMS_AGENT_LLM_OLLAMA_HOST": ("llm", "ollama_host"),
        # Legacy API key env vars
        "OPENROUTER_API_KEY": ("llm", "api_key"),
        "GROQ_API_KEY": ("llm", "api_key"),
        
        # SMS settings
        "SMS_AGENT_SMS_AUTO_REPLY_ENABLED": ("sms", "auto_reply_enabled", bool),
        "SMS_AGENT_SMS_AI_MODE_ENABLED": ("sms", "ai_mode_enabled", bool),
        "SMS_AGENT_SMS_WEBHOOK_ENABLED": ("sms", "webhook_enabled", bool),
        "SMS_AGENT_SMS_WEBHOOK_URL": ("sms", "webhook_url"),
        
        # UI settings
        "SMS_AGENT_UI_WEB_HOST": ("ui", "web_host"),
        "SMS_AGENT_UI_WEB_PORT": ("ui", "web_port", int),
        "SMS_AGENT_UI_WEB_DEBUG": ("ui", "web_debug", bool),
        
        # Rate limit settings
        "SMS_AGENT_RATE_LIMIT_MAX_MESSAGES_PER_MINUTE": (
            "rate_limit", "max_messages_per_minute", int
        ),
    }
    
    for env_var, mapping in env_mappings.items():
        value = os.environ.get(env_var)
        if value is not None:
            section = mapping[0]
            key = mapping[1]
            converter = mapping[2] if len(mapping) > 2 else str
            
            # Get the section object
            section_obj = getattr(config, section)
            
            # Convert value if needed
            if converter == bool:
                converted = value.lower() in ("true", "1", "yes", "on")
            else:
                converted = converter(value)
            
            setattr(section_obj, key, converted)


def save_config(config: Config, config_path: Optional[str] = None) -> None:
    """
    Save configuration to YAML file.
    
    Args:
        config: Config object to save
        config_path: Path to save configuration (optional)
        
    Raises:
        ConfigError: If configuration cannot be saved
    """
    # Determine config file path
    if config_path:
        yaml_path = Path(config_path)
    else:
        yaml_path = Path(config.config_dir) / "config.yaml"
    
    # Ensure directory exists
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        # Convert to dictionary and save
        config_dict = config.to_dict()
        
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(config_dict, f, default_flow_style=False, sort_keys=False)
    except IOError as e:
        raise ConfigError(f"Failed to save config file: {e}", {"path": str(yaml_path)})


def create_default_config(config_dir: Optional[str] = None) -> Config:
    """
    Create a default configuration file with sensible defaults.
    
    This function creates the configuration directory structure and
    writes a default config.yaml file that can be customized.
    
    Args:
        config_dir: Directory to create configuration in (optional)
        
    Returns:
        Config object with default values
    """
    config = Config()
    
    if config_dir:
        config.config_dir = config_dir
        config.data_dir = str(Path(config_dir) / "data")
        config.log_dir = str(Path(config_dir) / "logs")
    
    # Create directories
    Path(config.config_dir).mkdir(parents=True, exist_ok=True)
    Path(config.data_dir).mkdir(parents=True, exist_ok=True)
    Path(config.log_dir).mkdir(parents=True, exist_ok=True)
    
    # Save default configuration
    save_config(config)
    
    return config
