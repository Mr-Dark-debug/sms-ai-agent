"""
Logging Module - Centralized logging configuration
=================================================

This module provides logging setup and utilities including:
- Structured JSON logging
- File and console handlers
- Log rotation
- Context-aware logging
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
import json
import threading


class JSONFormatter(logging.Formatter):
    """
    JSON log formatter for structured logging.
    
    Outputs log records as JSON objects for easy parsing and
    integration with log aggregation systems.
    """
    
    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record as JSON.
        
        Args:
            record: Log record to format
            
        Returns:
            JSON-formatted log string
        """
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        # Add extra fields
        if hasattr(record, "extra_data"):
            log_data["data"] = record.extra_data
        
        return json.dumps(log_data)


class ColoredFormatter(logging.Formatter):
    """
    Colored console formatter for readable terminal output.
    
    Uses ANSI color codes to highlight different log levels.
    """
    
    # ANSI color codes
    COLORS = {
        "DEBUG": "\033[36m",     # Cyan
        "INFO": "\033[32m",      # Green
        "WARNING": "\033[33m",   # Yellow
        "ERROR": "\033[31m",     # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"
    BOLD = "\033[1m"
    
    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record with colors.
        
        Args:
            record: Log record to format
            
        Returns:
            Colored log string
        """
        # Get color for level
        color = self.COLORS.get(record.levelname, "")
        
        # Format timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Build formatted message
        formatted = (
            f"{color}{self.BOLD}[{record.levelname}]{self.RESET} "
            f"{timestamp} | {record.name}:{record.lineno} | "
            f"{record.getMessage()}"
        )
        
        # Add exception info if present
        if record.exc_info:
            formatted += f"\n{self.formatException(record.exc_info)}"
        
        return formatted


class ContextFilter(logging.Filter):
    """
    Logging filter that adds context information to records.
    
    Adds thread-local context data to each log record.
    """
    
    _context = threading.local()
    
    @classmethod
    def set_context(cls, **kwargs) -> None:
        """
        Set context values for current thread.
        
        Args:
            **kwargs: Context key-value pairs
        """
        if not hasattr(cls._context, "data"):
            cls._context.data = {}
        cls._context.data.update(kwargs)
    
    @classmethod
    def clear_context(cls) -> None:
        """Clear context for current thread."""
        cls._context.data = {}
    
    def filter(self, record: logging.LogRecord) -> bool:
        """
        Add context to log record.
        
        Args:
            record: Log record to modify
            
        Returns:
            Always True (allows all records)
        """
        if hasattr(self._context, "data"):
            record.extra_data = self._context.data.copy()
        return True


class LoggerAdapter(logging.LoggerAdapter):
    """
    Custom logger adapter with extra context support.
    
    Allows passing extra context data that will be included
    in structured log output.
    """
    
    def process(self, msg: str, kwargs: Dict[str, Any]) -> tuple:
        """
        Process the logging call to add extra context.
        
        Args:
            msg: Log message
            kwargs: Keyword arguments
            
        Returns:
            Tuple of (message, kwargs)
        """
        extra = kwargs.get("extra", {})
        extra.update(self.extra)
        kwargs["extra"] = extra
        return msg, kwargs


# Global logger registry
_loggers: Dict[str, logging.Logger] = {}
_configured = False


def setup_logging(
    log_dir: Optional[str] = None,
    log_level: str = "INFO",
    json_format: bool = False,
    console_output: bool = True
) -> None:
    """
    Set up logging configuration for the application.
    
    This should be called once at application startup.
    
    Args:
        log_dir: Directory for log files (optional)
        log_level: Minimum log level to capture
        json_format: Use JSON format for file logs
        console_output: Also output to console
        
    Example:
        setup_logging(
            log_dir="/var/log/sms-agent",
            log_level="DEBUG",
            json_format=True
        )
    """
    global _configured
    
    if _configured:
        return
    
    # Get root logger
    root_logger = logging.getLogger("sms_agent")
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    
    # Clear existing handlers
    root_logger.handlers.clear()
    
    # Add context filter
    context_filter = ContextFilter()
    root_logger.addFilter(context_filter)
    
    # Console handler
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(ColoredFormatter())
        root_logger.addHandler(console_handler)
    
    # File handler
    if log_dir:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        
        log_file = log_path / "sms-agent.log"
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        
        if json_format:
            file_handler.setFormatter(JSONFormatter())
        else:
            file_handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s"
                )
            )
        root_logger.addHandler(file_handler)
        
        # Error log file
        error_file = log_path / "errors.log"
        error_handler = logging.FileHandler(error_file, encoding="utf-8")
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(JSONFormatter())
        root_logger.addHandler(error_handler)
    
    _configured = True


def get_logger(name: str, **extra) -> LoggerAdapter:
    """
    Get a logger instance for a module.
    
    Returns a logger adapter that can include extra context
    in log messages.
    
    Args:
        name: Logger name (usually __name__)
        **extra: Extra context to include in all log messages
        
    Returns:
        LoggerAdapter instance
        
    Example:
        logger = get_logger(__name__, component="sms_handler")
        logger.info("Message received", extra={"phone": "+1234567890"})
    """
    full_name = f"sms_agent.{name}" if not name.startswith("sms_agent") else name
    
    if full_name not in _loggers:
        logger = logging.getLogger(full_name)
        _loggers[full_name] = logger
    
    return LoggerAdapter(_loggers[full_name], extra)


def set_log_context(**kwargs) -> None:
    """
    Set thread-local logging context.
    
    Context values will be included in all subsequent log messages
    in the current thread.
    
    Args:
        **kwargs: Context key-value pairs
        
    Example:
        set_log_context(request_id="abc123", user="john")
        logger.info("Processing request")  # Will include context
    """
    ContextFilter.set_context(**kwargs)


def clear_log_context() -> None:
    """Clear thread-local logging context."""
    ContextFilter.clear_context()
