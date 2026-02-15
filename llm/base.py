"""
Base LLM Provider - Abstract base class for LLM providers
=========================================================

This module defines the abstract interface that all LLM providers
must implement, ensuring consistent behavior across different backends.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, AsyncIterator
from datetime import datetime
import time


@dataclass
class LLMConfig:
    """
    Configuration for an LLM provider instance.
    
    Contains all parameters needed to configure and use an LLM provider,
    including model selection, generation parameters, and API settings.
    
    Attributes:
        model (str): Model identifier to use
        api_key (str): API key for authentication (if required)
        api_base (str): Base URL for API requests
        temperature (float): Sampling temperature (0-2)
        max_tokens (int): Maximum tokens in response
        top_p (float): Top-p sampling parameter
        timeout (int): Request timeout in seconds
    """
    model: str = "meta-llama/llama-3.3-70b-instruct:free"
    api_key: str = ""
    api_base: str = "https://openrouter.ai/api/v1"
    temperature: float = 0.7
    max_tokens: int = 150
    top_p: float = 0.9
    timeout: int = 30
    
    # Additional provider-specific options
    extra_params: Dict[str, Any] = field(default_factory=dict)
    
    def validate(self) -> None:
        """
        Validate configuration parameters.
        
        Raises:
            ValueError: If any parameter is invalid
        """
        if not 0 <= self.temperature <= 2:
            raise ValueError(f"temperature must be between 0 and 2, got {self.temperature}")
        
        if self.max_tokens < 1:
            raise ValueError(f"max_tokens must be positive, got {self.max_tokens}")
        
        if not 0 < self.top_p <= 1:
            raise ValueError(f"top_p must be between 0 and 1, got {self.top_p}")
        
        if self.timeout < 1:
            raise ValueError(f"timeout must be positive, got {self.timeout}")


@dataclass
class LLMResponse:
    """
    Response from an LLM provider.
    
    Contains the generated text along with metadata about the generation,
    including token usage, timing information, and model details.
    
    Attributes:
        content (str): Generated text content
        model (str): Model that generated the response
        provider (str): Provider name
        tokens_used (int): Total tokens used (prompt + completion)
        prompt_tokens (int): Tokens in the prompt
        completion_tokens (int): Tokens in the completion
        latency_ms (int): Response latency in milliseconds
        finish_reason (str): Reason for completion
        timestamp (datetime): When the response was generated
        metadata (dict): Additional provider-specific metadata
    """
    content: str
    model: str
    provider: str
    tokens_used: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    finish_reason: str = "stop"
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def is_complete(self) -> bool:
        """Check if response completed normally."""
        return self.finish_reason == "stop"
    
    @property
    def was_truncated(self) -> bool:
        """Check if response was truncated due to length."""
        return self.finish_reason == "length"


@dataclass
class Message:
    """
    Chat message structure.
    
    Represents a single message in a conversation, following the
    OpenAI chat message format.
    
    Attributes:
        role (str): Message role (system, user, or assistant)
        content (str): Message content
        name (str): Optional name for the message sender
    """
    role: str  # system, user, assistant
    content: str
    name: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary format for API requests."""
        result = {"role": self.role, "content": self.content}
        if self.name:
            result["name"] = self.name
        return result


class BaseLLMProvider(ABC):
    """
    Abstract base class for LLM providers.
    
    Defines the interface that all LLM providers must implement.
    This ensures consistent behavior regardless of the underlying
    provider (OpenRouter, Ollama, etc.).
    
    Subclasses must implement:
    - generate(): Generate text from a prompt
    - chat(): Generate response from conversation
    - is_available(): Check if provider is available
    - get_models(): List available models
    
    Example:
        class MyProvider(BaseLLMProvider):
            def generate(self, prompt: str) -> LLMResponse:
                # Implementation
                pass
    """
    
    def __init__(self, config: LLMConfig):
        """
        Initialize the provider.
        
        Args:
            config: Provider configuration
        """
        self.config = config
        self.config.validate()
    
    @abstractmethod
    def generate(
        self,
        prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> LLMResponse:
        """
        Generate text from a prompt.
        
        Args:
            prompt: Input prompt text
            temperature: Override config temperature
            max_tokens: Override config max_tokens
            **kwargs: Additional provider-specific parameters
            
        Returns:
            LLMResponse with generated text and metadata
        """
        pass
    
    @abstractmethod
    def chat(
        self,
        messages: List[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> LLMResponse:
        """
        Generate response from a conversation.
        
        Args:
            messages: List of conversation messages
            temperature: Override config temperature
            max_tokens: Override config max_tokens
            **kwargs: Additional provider-specific parameters
            
        Returns:
            LLMResponse with generated text and metadata
        """
        pass
    
    @abstractmethod
    async def generate_async(
        self,
        prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> LLMResponse:
        """
        Asynchronously generate text from a prompt.
        
        Args:
            prompt: Input prompt text
            temperature: Override config temperature
            max_tokens: Override config max_tokens
            **kwargs: Additional provider-specific parameters
            
        Returns:
            LLMResponse with generated text and metadata
        """
        pass
    
    @abstractmethod
    async def chat_async(
        self,
        messages: List[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> LLMResponse:
        """
        Asynchronously generate response from a conversation.
        
        Args:
            messages: List of conversation messages
            temperature: Override config temperature
            max_tokens: Override config max_tokens
            **kwargs: Additional provider-specific parameters
            
        Returns:
            LLMResponse with generated text and metadata
        """
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if the provider is available.
        
        Returns:
            True if provider can be used
        """
        pass
    
    @abstractmethod
    def get_models(self) -> List[str]:
        """
        Get list of available models.
        
        Returns:
            List of model identifiers
        """
        pass
    
    def count_tokens(self, text: str) -> int:
        """
        Estimate token count for text.
        
        Provides a rough estimate of token count. Actual count
        may vary by model and tokenizer.
        
        Args:
            text: Text to count tokens for
            
        Returns:
            Estimated token count
        """
        # Rough estimation: ~4 characters per token for English
        return len(text) // 4
    
    def _get_generation_params(
        self,
        temperature: Optional[float],
        max_tokens: Optional[int],
        **kwargs
    ) -> Dict[str, Any]:
        """
        Build generation parameters dictionary.
        
        Combines config defaults with any overrides.
        
        Args:
            temperature: Temperature override
            max_tokens: Max tokens override
            **kwargs: Additional parameters
            
        Returns:
            Dictionary of generation parameters
        """
        params = {
            "temperature": temperature if temperature is not None else self.config.temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.config.max_tokens,
            "top_p": self.config.top_p,
        }
        params.update(kwargs)
        return params
    
    @staticmethod
    def _measure_latency(start_time: float) -> int:
        """
        Calculate latency in milliseconds.
        
        Args:
            start_time: Start time from time.time()
            
        Returns:
            Latency in milliseconds
        """
        return int((time.time() - start_time) * 1000)
