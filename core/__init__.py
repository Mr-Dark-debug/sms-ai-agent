"""
Core Module - Foundation components for SMS AI Agent
=====================================================

This module provides the foundational components including:
- Configuration management
- Database operations
- Logging setup
- Exception handling
- Rate limiting
- Security utilities
"""

from .config import Config, load_config, save_config
from .database import Database, init_database
from .exceptions import (
    SMSAgentError,
    ConfigError,
    DatabaseError,
    LLMError,
    SMSError,
    RateLimitError,
    GuardrailError,
)
from .logging import setup_logging, get_logger
from .rate_limiter import RateLimiter
from .security import SecurityManager

__all__ = [
    "Config",
    "load_config",
    "save_config",
    "Database",
    "init_database",
    "SMSAgentError",
    "ConfigError",
    "DatabaseError",
    "LLMError",
    "SMSError",
    "RateLimitError",
    "GuardrailError",
    "setup_logging",
    "get_logger",
    "RateLimiter",
    "SecurityManager",
]
