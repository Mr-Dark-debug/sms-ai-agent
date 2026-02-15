"""
OpenRouter Provider - LLM provider for OpenRouter API
=====================================================

This module implements the LLM provider interface for OpenRouter,
a unified API gateway that provides access to multiple LLM providers
through a single API endpoint.

OpenRouter supports models from:
- OpenAI (GPT-4, GPT-3.5)
- Anthropic (Claude)
- Meta (Llama)
- Google (Gemini)
- Mistral AI
- And many more

Reference: https://openrouter.ai/docs
"""

import time
import asyncio
from typing import Optional, List, Dict, Any
import json

from .base import BaseLLMProvider, LLMConfig, LLMResponse, Message
from core.exceptions import LLMError
from core.logging import get_logger

logger = get_logger("llm.openrouter")


class OpenRouterProvider(BaseLLMProvider):
    """
    LLM provider implementation for OpenRouter API.
    
    OpenRouter provides a unified API to access multiple LLM providers.
    This implementation uses HTTP requests (via urllib or requests) to
    communicate with the OpenRouter API.
    
    Features:
    - Access to 100+ models through single API
    - Automatic failover between providers
    - Cost optimization
    - Streaming support
    - Proper error handling
    
    Example:
        config = LLMConfig(
            model="meta-llama/llama-3.3-70b-instruct:free",
            api_key="sk-or-...",
            temperature=0.7,
            max_tokens=150
        )
        
        provider = OpenRouterProvider(config)
        
        response = provider.generate("Hello, how are you?")
        print(response.content)
    """
    
    PROVIDER_NAME = "openrouter"
    API_BASE = "https://openrouter.ai/api/v1"
    
    # Default headers for OpenRouter API
    DEFAULT_HEADERS = {
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/sms-ai-agent",  # For rankings
        "X-Title": "SMS AI Agent",  # For rankings
    }
    
    def __init__(self, config: LLMConfig):
        """
        Initialize OpenRouter provider.
        
        Args:
            config: Provider configuration
            
        Raises:
            LLMError: If API key is not provided
        """
        super().__init__(config)
        
        # Set API base URL
        self.api_base = config.api_base or self.API_BASE
        
        # Validate API key
        if not config.api_key:
            raise LLMError(
                "OpenRouter API key is required",
                details={"hint": "Set SMS_AGENT_LLM_API_KEY environment variable or configure in settings"}
            )
        
        self.api_key = config.api_key
        
        # Initialize HTTP client lazily
        self._client = None
        
        logger.info(
            f"Initialized OpenRouter provider",
            extra={"model": config.model, "api_base": self.api_base}
        )
    
    def _get_client(self):
        """
        Get or create HTTP client.
        
        Uses urllib for Termux compatibility (no dependency on requests).
        
        Returns:
            HTTP client module
        """
        if self._client is None:
            try:
                import urllib.request
                import urllib.error
                self._client = {
                    "request": urllib.request,
                    "error": urllib.error
                }
            except ImportError as e:
                raise LLMError(f"Failed to import urllib: {e}")
        return self._client
    
    def _build_headers(self) -> Dict[str, str]:
        """
        Build request headers with authorization.
        
        Returns:
            Dictionary of headers
        """
        headers = self.DEFAULT_HEADERS.copy()
        headers["Authorization"] = f"Bearer {self.api_key}"
        return headers
    
    def _make_request(
        self,
        endpoint: str,
        data: Dict[str, Any],
        timeout: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Make synchronous HTTP request to OpenRouter API.
        
        Args:
            endpoint: API endpoint (e.g., "/chat/completions")
            data: Request body as dictionary
            timeout: Request timeout in seconds
            
        Returns:
            Response data as dictionary
            
        Raises:
            LLMError: If request fails
        """
        client = self._get_client()
        url = f"{self.api_base}{endpoint}"
        headers = self._build_headers()
        timeout = timeout or self.config.timeout
        
        # Prepare request
        body = json.dumps(data).encode("utf-8")
        req = client["request"].Request(
            url,
            data=body,
            headers=headers,
            method="POST"
        )
        
        try:
            with client["request"].urlopen(req, timeout=timeout) as response:
                response_data = response.read().decode("utf-8")
                return json.loads(response_data)
        
        except client["error"].HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            try:
                error_data = json.loads(error_body)
                error_msg = error_data.get("error", {}).get("message", str(e))
            except json.JSONDecodeError:
                error_msg = error_body or str(e)
            
            raise LLMError(
                f"OpenRouter API error: {error_msg}",
                details={"status": e.code, "url": url}
            )
        
        except client["error"].URLError as e:
            raise LLMError(
                f"Failed to connect to OpenRouter: {e.reason}",
                details={"url": url}
            )
        
        except json.JSONDecodeError as e:
            raise LLMError(
                f"Failed to parse OpenRouter response: {e}",
                details={"url": url}
            )
        
        except Exception as e:
            raise LLMError(
                f"Unexpected error calling OpenRouter: {e}",
                details={"url": url}
            )
    
    async def _make_request_async(
        self,
        endpoint: str,
        data: Dict[str, Any],
        timeout: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Make asynchronous HTTP request to OpenRouter API.
        
        Uses aiohttp if available, falls back to asyncio with urllib.
        
        Args:
            endpoint: API endpoint
            data: Request body
            timeout: Request timeout
            
        Returns:
            Response data
        """
        # Try to use aiohttp if available
        try:
            import aiohttp
            
            url = f"{self.api_base}{endpoint}"
            headers = self._build_headers()
            timeout_val = timeout or self.config.timeout
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=data,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=timeout_val)
                ) as response:
                    response_data = await response.json()
                    
                    if response.status != 200:
                        error_msg = response_data.get("error", {}).get("message", "Unknown error")
                        raise LLMError(
                            f"OpenRouter API error: {error_msg}",
                            details={"status": response.status, "url": url}
                        )
                    
                    return response_data
        
        except ImportError:
            # Fall back to running sync in executor
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None,
                lambda: self._make_request(endpoint, data, timeout)
            )
    
    def generate(
        self,
        prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> LLMResponse:
        """
        Generate text from a prompt using OpenRouter.
        
        Args:
            prompt: Input prompt text
            temperature: Sampling temperature (0-2)
            max_tokens: Maximum tokens to generate
            **kwargs: Additional parameters (e.g., top_p, stop)
            
        Returns:
            LLMResponse with generated text
            
        Raises:
            LLMError: If generation fails
        """
        # Convert prompt to chat format for better compatibility
        messages = [Message(role="user", content=prompt)]
        return self.chat(messages, temperature, max_tokens, **kwargs)
    
    def chat(
        self,
        messages: List[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> LLMResponse:
        """
        Generate response from conversation using OpenRouter.
        
        Args:
            messages: List of conversation messages
            temperature: Sampling temperature
            max_tokens: Maximum tokens
            **kwargs: Additional parameters
            
        Returns:
            LLMResponse with generated text
            
        Raises:
            LLMError: If generation fails
        """
        start_time = time.time()
        
        # Build request
        params = self._get_generation_params(temperature, max_tokens, **kwargs)
        
        request_data = {
            "model": self.config.model,
            "messages": [m.to_dict() for m in messages],
            "temperature": params["temperature"],
            "max_tokens": params["max_tokens"],
            "top_p": params.get("top_p", self.config.top_p),
        }
        
        # Add optional parameters
        if "stop" in kwargs:
            request_data["stop"] = kwargs["stop"]
        
        logger.debug(
            f"Sending chat request to OpenRouter",
            extra={
                "model": self.config.model,
                "message_count": len(messages),
                "max_tokens": request_data["max_tokens"]
            }
        )
        
        try:
            response_data = self._make_request("/chat/completions", request_data)
            
            # Parse response
            choices = response_data.get("choices", [])
            if not choices:
                raise LLMError("No choices in OpenRouter response")
            
            choice = choices[0]
            content = choice.get("message", {}).get("content", "")
            finish_reason = choice.get("finish_reason", "stop")
            
            # Parse usage
            usage = response_data.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            total_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens)
            
            latency = self._measure_latency(start_time)
            
            logger.info(
                f"OpenRouter generation complete",
                extra={
                    "model": self.config.model,
                    "tokens": total_tokens,
                    "latency_ms": latency
                }
            )
            
            return LLMResponse(
                content=content,
                model=response_data.get("model", self.config.model),
                provider=self.PROVIDER_NAME,
                tokens_used=total_tokens,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency,
                finish_reason=finish_reason,
                metadata={"raw_response": response_data}
            )
        
        except LLMError:
            raise
        except Exception as e:
            raise LLMError(f"Failed to generate: {e}")
    
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
            prompt: Input prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens
            **kwargs: Additional parameters
            
        Returns:
            LLMResponse with generated text
        """
        messages = [Message(role="user", content=prompt)]
        return await self.chat_async(messages, temperature, max_tokens, **kwargs)
    
    async def chat_async(
        self,
        messages: List[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> LLMResponse:
        """
        Asynchronously generate response from conversation.
        
        Args:
            messages: Conversation messages
            temperature: Sampling temperature
            max_tokens: Maximum tokens
            **kwargs: Additional parameters
            
        Returns:
            LLMResponse with generated text
        """
        start_time = time.time()
        
        params = self._get_generation_params(temperature, max_tokens, **kwargs)
        
        request_data = {
            "model": self.config.model,
            "messages": [m.to_dict() for m in messages],
            "temperature": params["temperature"],
            "max_tokens": params["max_tokens"],
            "top_p": params.get("top_p", self.config.top_p),
        }
        
        try:
            response_data = await self._make_request_async("/chat/completions", request_data)
            
            choices = response_data.get("choices", [])
            if not choices:
                raise LLMError("No choices in OpenRouter response")
            
            choice = choices[0]
            content = choice.get("message", {}).get("content", "")
            finish_reason = choice.get("finish_reason", "stop")
            
            usage = response_data.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            total_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens)
            
            latency = self._measure_latency(start_time)
            
            return LLMResponse(
                content=content,
                model=response_data.get("model", self.config.model),
                provider=self.PROVIDER_NAME,
                tokens_used=total_tokens,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency,
                finish_reason=finish_reason,
                metadata={"raw_response": response_data}
            )
        
        except LLMError:
            raise
        except Exception as e:
            raise LLMError(f"Failed to generate async: {e}")
    
    def is_available(self) -> bool:
        """
        Check if OpenRouter API is available.
        
        Makes a simple request to verify connectivity and authentication.
        
        Returns:
            True if API is accessible and key is valid
        """
        try:
            # Try a minimal request
            response = self._make_request(
                "/models",
                {},
                timeout=5
            )
            return True
        except Exception as e:
            logger.warning(f"OpenRouter availability check failed: {e}")
            return False
    
    def get_models(self) -> List[str]:
        """
        Get list of available models from OpenRouter.
        
        Returns:
            List of model identifiers
        """
        try:
            response = self._make_request("/models", {}, timeout=10)
            models = response.get("data", [])
            return [m.get("id") for m in models if m.get("id")]
        except Exception as e:
            logger.warning(f"Failed to get models: {e}")
            # Return common models as fallback
            return [
                "meta-llama/llama-3.3-70b-instruct:free",
                "openai/gpt-4o-mini",
                "anthropic/claude-3.5-sonnet",
                "google/gemini-pro",
            ]
