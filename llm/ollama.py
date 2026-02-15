"""
Ollama Provider - LLM provider for local Ollama runtime
=======================================================

This module implements the LLM provider interface for Ollama,
a local LLM runtime that allows running large language models
directly on your device.

Ollama supports models like:
- Llama 2/3
- Mistral
- Gemma
- Phi
- And many more

Reference: https://ollama.ai
"""

import time
import asyncio
import json
from typing import Optional, List, Dict, Any

from .base import BaseLLMProvider, LLMConfig, LLMResponse, Message
from core.exceptions import LLMError
from core.logging import get_logger

logger = get_logger("llm.ollama")


class OllamaProvider(BaseLLMProvider):
    """
    LLM provider implementation for Ollama local runtime.
    
    Ollama allows running LLMs locally without external API calls,
    providing privacy and no per-token costs. Requires Ollama
    to be installed and running.
    
    Features:
    - Complete privacy (local processing)
    - No API costs
    - Works offline
    - Multiple model support
    - Custom model support
    
    Requirements:
    - Ollama installed: https://ollama.ai
    - Ollama service running: `ollama serve`
    - Model pulled: `ollama pull llama3`
    
    Example:
        config = LLMConfig(
            model="llama3",
            api_base="http://localhost:11434",
            temperature=0.7,
            max_tokens=150
        )
        
        provider = OllamaProvider(config)
        
        if provider.is_available():
            response = provider.generate("Hello!")
            print(response.content)
    """
    
    PROVIDER_NAME = "ollama"
    DEFAULT_HOST = "http://localhost:11434"
    
    def __init__(self, config: LLMConfig):
        """
        Initialize Ollama provider.
        
        Args:
            config: Provider configuration
        """
        super().__init__(config)
        
        # Set Ollama host
        self.host = config.api_base or config.extra_params.get("ollama_host") or self.DEFAULT_HOST
        
        # Remove trailing slash
        self.host = self.host.rstrip("/")
        
        # Initialize HTTP client lazily
        self._client = None
        
        logger.info(
            f"Initialized Ollama provider",
            extra={"model": config.model, "host": self.host}
        )
    
    def _get_client(self):
        """
        Get or create HTTP client.
        
        Returns:
            HTTP client modules
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
    
    def _make_request(
        self,
        endpoint: str,
        data: Dict[str, Any],
        timeout: Optional[int] = None,
        stream: bool = False
    ) -> Dict[str, Any]:
        """
        Make synchronous HTTP request to Ollama API.
        
        Args:
            endpoint: API endpoint (e.g., "/api/generate")
            data: Request body
            timeout: Request timeout
            stream: Whether to stream response
            
        Returns:
            Response data
        """
        client = self._get_client()
        url = f"{self.host}{endpoint}"
        timeout = timeout or self.config.timeout
        
        headers = {"Content-Type": "application/json"}
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
                
                # Ollama may return NDJSON (newline-delimited JSON)
                if stream and "\n" in response_data:
                    # Get last complete JSON object
                    lines = [l for l in response_data.strip().split("\n") if l.strip()]
                    if lines:
                        return json.loads(lines[-1])
                
                return json.loads(response_data)
        
        except client["error"].HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            raise LLMError(
                f"Ollama API error: {error_body}",
                details={"status": e.code, "url": url}
            )
        
        except client["error"].URLError as e:
            raise LLMError(
                f"Failed to connect to Ollama: {e.reason}. Is Ollama running?",
                details={"url": url, "hint": "Run 'ollama serve' to start Ollama"}
            )
        
        except json.JSONDecodeError as e:
            raise LLMError(f"Failed to parse Ollama response: {e}")
        
        except Exception as e:
            raise LLMError(f"Unexpected error calling Ollama: {e}")
    
    async def _make_request_async(
        self,
        endpoint: str,
        data: Dict[str, Any],
        timeout: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Make asynchronous HTTP request to Ollama.
        
        Args:
            endpoint: API endpoint
            data: Request body
            timeout: Request timeout
            
        Returns:
            Response data
        """
        try:
            import aiohttp
            
            url = f"{self.host}{endpoint}"
            timeout_val = timeout or self.config.timeout
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=data,
                    timeout=aiohttp.ClientTimeout(total=timeout_val)
                ) as response:
                    response_data = await response.json()
                    
                    if response.status != 200:
                        raise LLMError(
                            f"Ollama API error: {response_data.get('error', 'Unknown error')}",
                            details={"status": response.status}
                        )
                    
                    return response_data
        
        except ImportError:
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
        Generate text from a prompt using Ollama.
        
        Args:
            prompt: Input prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens (mapped to num_predict)
            **kwargs: Additional Ollama parameters
            
        Returns:
            LLMResponse with generated text
        """
        start_time = time.time()
        
        params = self._get_generation_params(temperature, max_tokens, **kwargs)
        
        request_data = {
            "model": self.config.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": params["temperature"],
                "num_predict": params["max_tokens"],
                "top_p": params.get("top_p", self.config.top_p),
            }
        }
        
        # Add additional Ollama-specific options
        if "num_ctx" in kwargs:
            request_data["options"]["num_ctx"] = kwargs["num_ctx"]
        if "seed" in kwargs:
            request_data["options"]["seed"] = kwargs["seed"]
        
        logger.debug(
            f"Sending generate request to Ollama",
            extra={"model": self.config.model, "prompt_length": len(prompt)}
        )
        
        try:
            response_data = self._make_request("/api/generate", request_data)
            
            content = response_data.get("response", "")
            done = response_data.get("done", True)
            
            # Ollama provides token counts
            prompt_tokens = response_data.get("prompt_eval_count", 0)
            completion_tokens = response_data.get("eval_count", 0)
            total_tokens = prompt_tokens + completion_tokens
            
            latency = self._measure_latency(start_time)
            
            logger.info(
                f"Ollama generation complete",
                extra={
                    "model": self.config.model,
                    "tokens": total_tokens,
                    "latency_ms": latency
                }
            )
            
            return LLMResponse(
                content=content,
                model=self.config.model,
                provider=self.PROVIDER_NAME,
                tokens_used=total_tokens,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency,
                finish_reason="stop" if done else "length",
                metadata=response_data
            )
        
        except LLMError:
            raise
        except Exception as e:
            raise LLMError(f"Failed to generate with Ollama: {e}")
    
    def chat(
        self,
        messages: List[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> LLMResponse:
        """
        Generate response from conversation using Ollama chat API.
        
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
        
        # Convert messages to Ollama format
        ollama_messages = []
        for m in messages:
            ollama_messages.append({
                "role": m.role,
                "content": m.content
            })
        
        request_data = {
            "model": self.config.model,
            "messages": ollama_messages,
            "stream": False,
            "options": {
                "temperature": params["temperature"],
                "num_predict": params["max_tokens"],
                "top_p": params.get("top_p", self.config.top_p),
            }
        }
        
        try:
            response_data = self._make_request("/api/chat", request_data)
            
            message = response_data.get("message", {})
            content = message.get("content", "")
            done = response_data.get("done", True)
            
            prompt_tokens = response_data.get("prompt_eval_count", 0)
            completion_tokens = response_data.get("eval_count", 0)
            total_tokens = prompt_tokens + completion_tokens
            
            latency = self._measure_latency(start_time)
            
            return LLMResponse(
                content=content,
                model=self.config.model,
                provider=self.PROVIDER_NAME,
                tokens_used=total_tokens,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency,
                finish_reason="stop" if done else "length",
                metadata=response_data
            )
        
        except LLMError:
            raise
        except Exception as e:
            raise LLMError(f"Failed to chat with Ollama: {e}")
    
    async def generate_async(
        self,
        prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> LLMResponse:
        """
        Asynchronously generate text.
        
        Args:
            prompt: Input prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens
            **kwargs: Additional parameters
            
        Returns:
            LLMResponse
        """
        start_time = time.time()
        
        params = self._get_generation_params(temperature, max_tokens, **kwargs)
        
        request_data = {
            "model": self.config.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": params["temperature"],
                "num_predict": params["max_tokens"],
            }
        }
        
        try:
            response_data = await self._make_request_async("/api/generate", request_data)
            
            content = response_data.get("response", "")
            prompt_tokens = response_data.get("prompt_eval_count", 0)
            completion_tokens = response_data.get("eval_count", 0)
            
            latency = self._measure_latency(start_time)
            
            return LLMResponse(
                content=content,
                model=self.config.model,
                provider=self.PROVIDER_NAME,
                tokens_used=prompt_tokens + completion_tokens,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency,
                metadata=response_data
            )
        
        except LLMError:
            raise
        except Exception as e:
            raise LLMError(f"Failed to generate async with Ollama: {e}")
    
    async def chat_async(
        self,
        messages: List[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> LLMResponse:
        """
        Asynchronously generate chat response.
        
        Args:
            messages: Conversation messages
            temperature: Sampling temperature
            max_tokens: Maximum tokens
            **kwargs: Additional parameters
            
        Returns:
            LLMResponse
        """
        start_time = time.time()
        
        params = self._get_generation_params(temperature, max_tokens, **kwargs)
        
        request_data = {
            "model": self.config.model,
            "messages": [m.to_dict() for m in messages],
            "stream": False,
            "options": {
                "temperature": params["temperature"],
                "num_predict": params["max_tokens"],
            }
        }
        
        try:
            response_data = await self._make_request_async("/api/chat", request_data)
            
            content = response_data.get("message", {}).get("content", "")
            prompt_tokens = response_data.get("prompt_eval_count", 0)
            completion_tokens = response_data.get("eval_count", 0)
            
            latency = self._measure_latency(start_time)
            
            return LLMResponse(
                content=content,
                model=self.config.model,
                provider=self.PROVIDER_NAME,
                tokens_used=prompt_tokens + completion_tokens,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency,
                metadata=response_data
            )
        
        except LLMError:
            raise
        except Exception as e:
            raise LLMError(f"Failed to chat async with Ollama: {e}")
    
    def is_available(self) -> bool:
        """
        Check if Ollama is running and accessible.
        
        Returns:
            True if Ollama is running
        """
        try:
            client = self._get_client()
            url = f"{self.host}/api/version"
            
            req = client["request"].Request(url, method="GET")
            
            with client["request"].urlopen(req, timeout=5) as response:
                return response.status == 200
        
        except Exception as e:
            logger.debug(f"Ollama availability check failed: {e}")
            return False
    
    def get_models(self) -> List[str]:
        """
        Get list of locally available Ollama models.
        
        Returns:
            List of model names
        """
        try:
            client = self._get_client()
            url = f"{self.host}/api/tags"
            
            req = client["request"].Request(url, method="GET")
            
            with client["request"].urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
                models = data.get("models", [])
                return [m.get("name") for m in models if m.get("name")]
        
        except Exception as e:
            logger.warning(f"Failed to get Ollama models: {e}")
            return []
    
    def pull_model(self, model_name: str) -> bool:
        """
        Pull (download) a model from Ollama registry.
        
        Args:
            model_name: Name of model to pull
            
        Returns:
            True if successful
        """
        try:
            response = self._make_request(
                "/api/pull",
                {"name": model_name, "stream": False},
                timeout=300  # 5 minutes for large models
            )
            return response.get("status") == "success"
        except Exception as e:
            logger.error(f"Failed to pull model {model_name}: {e}")
            return False
    
    def get_model_info(self, model_name: str) -> Dict[str, Any]:
        """
        Get information about a specific model.
        
        Args:
            model_name: Model name
            
        Returns:
            Model information dictionary
        """
        try:
            return self._make_request(
                "/api/show",
                {"name": model_name},
                timeout=30
            )
        except Exception as e:
            logger.error(f"Failed to get model info: {e}")
            return {}
