"""
LLM Module - Abstraction layer for LLM providers
=================================================

This module provides a unified interface for interacting with
multiple LLM providers including:
- OpenRouter (multi-provider gateway)
- Ollama (local LLM runtime)

The module implements a provider abstraction pattern allowing
easy switching between different LLM backends.
"""

from .base import BaseLLMProvider, LLMResponse, LLMConfig
from .openrouter import OpenRouterProvider
from .ollama import OllamaProvider
from .factory import LLMFactory, create_llm_provider

__all__ = [
    "BaseLLMProvider",
    "LLMResponse",
    "LLMConfig",
    "OpenRouterProvider",
    "OllamaProvider",
    "LLMFactory",
    "create_llm_provider",
]
