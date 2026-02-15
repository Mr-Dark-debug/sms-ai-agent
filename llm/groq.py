"""
Groq Provider - LLM provider for Groq API
=========================================

This module implements the LLM provider interface for Groq,
a high-performance inference engine for LLMs.

Groq supports models like:
- Llama 3
- Mixtral
- Gemma

Reference: https://console.groq.com/docs
"""

import time
import asyncio
from typing import Optional, List, Dict, Any
import json

from .base import BaseLLMProvider, LLMConfig, LLMResponse, Message
from core.exceptions import LLMError
from core.logging import get_logger

logger = get_logger("llm.groq")


class GroqProvider(BaseLLMProvider):
    """
    LLM provider implementation for Groq API.
    
    Uses Groq's OpenAI-compatible API endpoint.
    """
    
    PROVIDER_NAME = "groq"
    API_BASE = "https://api.groq.com/openai/v1"
    
    def __init__(self, config: LLMConfig):
        """
        Initialize Groq provider.
        
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
                "Groq API key is required",
                details={"hint": "Set GROQ_API_KEY environment variable or configure in settings"}
            )
        
        self.api_key = config.api_key
        
        # Initialize HTTP client lazily
        self._client = None
        
        logger.info(
            f"Initialized Groq provider",
            extra={"model": config.model, "api_base": self.api_base}
        )
    
    def _get_client(self):
        """Get or create HTTP client."""
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
        """Build request headers."""
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
    
    def _make_request(
        self,
        endpoint: str,
        data: Dict[str, Any],
        timeout: Optional[int] = None
    ) -> Dict[str, Any]:
        """Make synchronous HTTP request."""
        client = self._get_client()
        url = f"{self.api_base}{endpoint}"
        headers = self._build_headers()
        timeout = timeout or self.config.timeout
        
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
                f"Groq API error: {error_msg}",
                details={"status": e.code, "url": url}
            )
        except Exception as e:
            raise LLMError(f"Unexpected error calling Groq: {e}")

    def chat(
        self,
        messages: List[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> LLMResponse:
        """Generate response from conversation."""
        start_time = time.time()
        params = self._get_generation_params(temperature, max_tokens, **kwargs)
        
        request_data = {
            "model": self.config.model,
            "messages": [m.to_dict() for m in messages],
            "temperature": params["temperature"],
            "max_tokens": params["max_tokens"],
            "top_p": params.get("top_p", self.config.top_p),
        }
        
        if "stop" in kwargs:
            request_data["stop"] = kwargs["stop"]
            
        try:
            response_data = self._make_request("/chat/completions", request_data)
            
            choices = response_data.get("choices", [])
            if not choices:
                raise LLMError("No choices in Groq response")
            
            choice = choices[0]
            content = choice.get("message", {}).get("content", "")
            finish_reason = choice.get("finish_reason", "stop")
            
            usage = response_data.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            total_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens)
            
            latency = int((time.time() - start_time) * 1000)
            
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
        except Exception as e:
            if isinstance(e, LLMError):
                raise
            raise LLMError(f"Failed to generate: {e}")

    def generate(self, prompt: str, **kwargs) -> LLMResponse:
        return self.chat([Message(role="user", content=prompt)], **kwargs)

    async def chat_async(self, messages: List[Message], **kwargs) -> LLMResponse:
        # Simple async fallback
        return await asyncio.get_event_loop().run_in_executor(
            None, lambda: self.chat(messages, **kwargs)
        )

    async def generate_async(self, prompt: str, **kwargs) -> LLMResponse:
        return await self.chat_async([Message(role="user", content=prompt)], **kwargs)

    def is_available(self) -> bool:
        try:
            # Groq doesn't have a simple /models GET endpoint that's public without auth
            # but we can try to list models using the OpenAI compatible endpoint
            self._make_request("/models", {}, timeout=5)
            return True
        except Exception:
            return False

    def get_models(self) -> List[str]:
        try:
            # Groq supports GET /v1/models
            client = self._get_client()
            url = f"{self.api_base}/models"
            headers = self._build_headers()
            req = client["request"].Request(url, headers=headers, method="GET")
            with client["request"].urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
                return [m["id"] for m in data.get("data", [])]
        except Exception:
            return ["openai/gpt-oss-120b", "llama-3.3-70b-versatile", "llama3-8b-8192", "mixtral-8x7b-32768", "gemma-7b-it"]
