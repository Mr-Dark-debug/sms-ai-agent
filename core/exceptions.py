"""
Exception Definitions - Custom exceptions for SMS AI Agent
==========================================================

This module defines all custom exceptions used throughout the application,
providing clear error handling and meaningful error messages.
"""


class SMSAgentError(Exception):
    """
    Base exception for all SMS Agent errors.
    
    All custom exceptions in this application inherit from this base class,
    allowing for easy catching of all application-specific errors.
    
    Attributes:
        message (str): Human-readable error description
        details (dict): Additional error details for debugging
    """
    
    def __init__(self, message: str, details: dict = None):
        """
        Initialize the exception.
        
        Args:
            message: Human-readable error description
            details: Optional dictionary with additional error context
        """
        self.message = message
        self.details = details or {}
        super().__init__(self.message)
    
    def __str__(self) -> str:
        """Return formatted error message with details if present."""
        if self.details:
            return f"{self.message} | Details: {self.details}"
        return self.message


class ConfigError(SMSAgentError):
    """
    Configuration-related errors.
    
    Raised when there are issues with:
    - Missing configuration files
    - Invalid configuration values
    - Environment variable issues
    - Configuration parsing errors
    """
    pass


class DatabaseError(SMSAgentError):
    """
    Database operation errors.
    
    Raised when there are issues with:
    - Database connection failures
    - Query execution errors
    - Data integrity violations
    - Migration failures
    """
    pass


class LLMError(SMSAgentError):
    """
    LLM provider errors.
    
    Raised when there are issues with:
    - API connection failures
    - Authentication errors
    - Rate limiting from provider
    - Invalid responses
    - Timeout errors
    """
    pass


class SMSError(SMSAgentError):
    """
    SMS handling errors.
    
    Raised when there are issues with:
    - Termux API failures
    - SMS sending failures
    - SMS parsing errors
    - Permission issues
    """
    pass


class RateLimitError(SMSAgentError):
    """
    Rate limiting errors.
    
    Raised when rate limits are exceeded:
    - Too many messages per timeframe
    - Recipient rate limit exceeded
    - Global rate limit reached
    
    Attributes:
        retry_after (float): Seconds until rate limit resets
    """
    
    def __init__(self, message: str, retry_after: float = 0, details: dict = None):
        """
        Initialize rate limit error with retry information.
        
        Args:
            message: Human-readable error description
            retry_after: Seconds until rate limit resets
            details: Optional dictionary with additional error context
        """
        self.retry_after = retry_after
        super().__init__(message, details)
    
    def __str__(self) -> str:
        """Return formatted error message with retry time."""
        base = super().__str__()
        return f"{base} | Retry after: {self.retry_after:.1f}s"


class GuardrailError(SMSAgentError):
    """
    Guardrail violation errors.
    
    Raised when generated content violates safety rules:
    - Unsafe content detected
    - Personal information leakage
    - Inappropriate content
    - Length constraints violated
    """
    pass


class UIError(SMSAgentError):
    """
    User interface errors.
    
    Raised when there are issues with:
    - Terminal UI rendering
    - Web UI template errors
    - User input validation
    """
    pass
