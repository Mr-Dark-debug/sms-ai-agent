"""
LLM Factory - Factory for creating LLM provider instances
=========================================================

This module provides a factory pattern for creating and managing
LLM provider instances, making it easy to switch between providers.
"""

from typing import Optional, Type, Dict, Any

from .base import BaseLLMProvider, LLMConfig
from .openrouter import OpenRouterProvider
from .ollama import OllamaProvider
from .groq import GroqProvider
from core.exceptions import LLMError, ConfigError
from core.logging import get_logger

logger = get_logger("llm.factory")


# Registry of available providers
PROVIDERS: Dict[str, Type[BaseLLMProvider]] = {
    "openrouter": OpenRouterProvider,
    "ollama": OllamaProvider,
    "groq": GroqProvider,
}


class LLMFactory:
    """
    Factory for creating LLM provider instances.
    
    Provides a centralized way to create and configure LLM providers,
    with support for dynamic provider registration and configuration
    validation.
    
    Example:
        # Create provider from config
        provider = LLMFactory.create_from_config(config)
        
        # Create provider directly
        provider = LLMFactory.create("openrouter", llm_config)
        
        # Register custom provider
        LLMFactory.register("my_provider", MyProvider)
    """
    
    @staticmethod
    def create(
        provider_name: str,
        config: LLMConfig,
        **kwargs
    ) -> BaseLLMProvider:
        """
        Create an LLM provider instance.
        
        Args:
            provider_name: Name of the provider (e.g., "openrouter", "ollama")
            config: Provider configuration
            **kwargs: Additional provider-specific arguments
            
        Returns:
            Configured provider instance
            
        Raises:
            ConfigError: If provider is not registered
            LLMError: If provider initialization fails
        """
        provider_name = provider_name.lower()
        
        if provider_name not in PROVIDERS:
            available = ", ".join(PROVIDERS.keys())
            raise ConfigError(
                f"Unknown LLM provider: {provider_name}",
                details={"available_providers": available}
            )
        
        provider_class = PROVIDERS[provider_name]
        
        try:
            logger.info(f"Creating {provider_name} provider")
            return provider_class(config, **kwargs)
        except Exception as e:
            raise LLMError(
                f"Failed to create {provider_name} provider: {e}",
                details={"provider": provider_name}
            )
    
    @staticmethod
    def create_from_config(config) -> BaseLLMProvider:
        """
        Create provider from application config.
        
        Convenience method that extracts LLM configuration from
        the main application configuration.
        
        Args:
            config: Main application Config object
            
        Returns:
            Configured provider instance
        """
        llm_config = LLMConfig(
            model=config.llm.model,
            api_key=config.llm.api_key,
            api_base=config.llm.api_base,
            temperature=config.llm.temperature,
            max_tokens=config.llm.max_tokens,
            top_p=config.llm.top_p,
            timeout=config.llm.timeout,
            extra_params={
                "ollama_host": config.llm.ollama_host,
            }
        )
        
        return LLMFactory.create(config.llm.provider, llm_config)
    
    @staticmethod
    def register(name: str, provider_class: Type[BaseLLMProvider]) -> None:
        """
        Register a new provider class.
        
        Allows adding custom providers at runtime.
        
        Args:
            name: Provider name
            provider_class: Provider class (must inherit from BaseLLMProvider)
            
        Raises:
            ConfigError: If provider class is invalid
        """
        if not issubclass(provider_class, BaseLLMProvider):
            raise ConfigError(
                f"Provider class must inherit from BaseLLMProvider",
                details={"class": str(provider_class)}
            )
        
        PROVIDERS[name.lower()] = provider_class
        logger.info(f"Registered LLM provider: {name}")
    
    @staticmethod
    def list_providers() -> Dict[str, str]:
        """
        Get list of available providers.
        
        Returns:
            Dictionary mapping provider names to descriptions
        """
        return {
            "groq": "Groq - High-performance LLM inference",
            "openrouter": "OpenRouter - Multi-provider LLM gateway",
            "ollama": "Ollama - Local LLM runtime",
        }
    
    @staticmethod
    def get_recommended_model(provider: str) -> str:
        """
        Get recommended model for a provider.
        
        Args:
            provider: Provider name
            
        Returns:
            Recommended model identifier
        """
        recommendations = {
            "groq": "openai/gpt-oss-120b",
            "openrouter": "meta-llama/llama-3.3-70b-instruct:free",
            "ollama": "llama3",
        }
        return recommendations.get(provider.lower(), "")


def create_llm_provider(
    provider: Optional[str] = None,
    config: Optional[Any] = None,
    **kwargs
) -> BaseLLMProvider:
    """
    Convenience function to create an LLM provider.
    
    This is the main entry point for creating LLM providers.
    It handles configuration loading and provider initialization.
    
    Args:
        provider: Provider name (optional if config is provided)
        config: Application config (optional)
        **kwargs: Additional arguments
        
    Returns:
        Configured LLM provider
        
    Example:
        # Create with app config
        provider = create_llm_provider(config=app_config)
        
        # Create with specific provider
        provider = create_llm_provider(
            provider="openrouter",
            model="gpt-4",
            api_key="sk-...",
            temperature=0.7
        )
    """
    if config is not None:
        # Use application config
        return LLMFactory.create_from_config(config)
    
    if provider is None:
        provider = "openrouter"  # Default provider
    
    # Build LLMConfig from kwargs
    llm_config = LLMConfig(
        model=kwargs.get("model", LLMFactory.get_recommended_model(provider)),
        api_key=kwargs.get("api_key", ""),
        api_base=kwargs.get("api_base", ""),
        temperature=kwargs.get("temperature", 0.7),
        max_tokens=kwargs.get("max_tokens", 150),
        top_p=kwargs.get("top_p", 0.9),
        timeout=kwargs.get("timeout", 30),
    )
    
    return LLMFactory.create(provider, llm_config)
