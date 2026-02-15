"""
AI Responder - LLM-powered SMS response generation
==================================================

This module provides the AI responder that uses LLMs to generate
contextual responses to SMS messages, with fallback to rules.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from dataclasses import dataclass
import json

from llm.base import Message, LLMResponse
from llm.factory import create_llm_provider
from rules.engine import RulesEngine, RuleMatch
from core.config import Config
from core.database import Database
from core.exceptions import LLMError
from core.logging import get_logger
from .guardrails import GuardrailSystem, GuardrailResult
from .sms_handler import SMSMessage

logger = get_logger("services.ai_responder")


@dataclass
class ResponderResult:
    """
    Result of AI responder processing.
    
    Attributes:
        response (str): Generated response text
        source (str): Source of response ('ai', 'rules', 'fallback')
        model (str): Model used (if AI)
        tokens_used (int): Tokens consumed (if AI)
        latency_ms (int): Response latency
        guardrail_result: Guardrail validation result
        metadata (dict): Additional metadata
    """
    response: str
    source: str  # 'ai', 'rules', 'fallback'
    model: str = ""
    tokens_used: int = 0
    latency_ms: int = 0
    guardrail_result: Optional[GuardrailResult] = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class AIResponder:
    """
    AI-powered SMS response generator.
    
    Combines LLM generation with rule-based fallbacks and guardrails
    to produce safe, contextual responses.
    
    Features:
    - Context-aware responses using conversation history
    - Personality-based writing style
    - Automatic fallback to rules when AI fails
    - Comprehensive guardrails
    - Rate limiting awareness
    
    Example:
        responder = AIResponder(config, db, guardrails, rules_engine)
        
        result = responder.respond(
            incoming_message="Hello, how are you?",
            phone_number="+1234567890"
        )
        
        if result.response:
            send_sms(result.response)
    """
    
    def __init__(
        self,
        config: Config,
        database: Database,
        guardrails: GuardrailSystem,
        rules_engine: Optional[RulesEngine] = None,
        personality_path: Optional[str] = None,
        agent_path: Optional[str] = None
    ):
        """
        Initialize AI responder.
        
        Args:
            config: Application configuration
            database: Database instance for conversation history
            guardrails: Guardrail system for response validation
            rules_engine: Optional rules engine for fallbacks
            personality_path: Path to personality.md file
            agent_path: Path to agent.md file
        """
        self.config = config
        self.database = database
        self.guardrails = guardrails
        self.rules_engine = rules_engine
        
        # Load personality and agent instructions
        self.personality = self._load_instructions(personality_path, "personality")
        self.agent_rules = self._load_instructions(agent_path, "agent")
        
        # Initialize LLM provider
        self.llm = None
        if config.llm.api_key:
            try:
                self.llm = create_llm_provider(config=config)
                logger.info(f"LLM provider initialized: {config.llm.provider}")
            except Exception as e:
                logger.warning(f"Failed to initialize LLM: {e}")
        
        # Response history for context
        self.max_context_messages = 10
    
    def _load_instructions(self, path: Optional[str], default_name: str) -> str:
        """
        Load instruction file content.
        
        Args:
            path: Path to instruction file
            default_name: Default filename to look for
            
        Returns:
            Instruction content
        """
        if path:
            try:
                with open(path, "r") as f:
                    return f.read().strip()
            except Exception as e:
                logger.warning(f"Failed to load {default_name}: {e}")
        
        # Try default location
        default_path = f"{self.config.config_dir}/{default_name}.md"
        try:
            with open(default_path, "r") as f:
                return f.read().strip()
        except Exception:
            pass
        
        # Return default instructions
        if default_name == "personality":
            return self._get_default_personality()
        else:
            return self._get_default_agent_rules()
    
    def _get_default_personality(self) -> str:
        """Get default personality instructions."""
        return """You are a friendly and helpful SMS assistant. Your responses should be:
- Concise and to the point (under 300 characters)
- Friendly and conversational
- Helpful and informative
- Professional but approachable

Avoid:
- Long explanations
- Unnecessary details
- Technical jargon
- Sensitive personal information"""
    
    def _get_default_agent_rules(self) -> str:
        """Get default agent rules."""
        return """As an SMS assistant, you must:
1. Never share personal information about yourself or others
2. Never generate harmful or inappropriate content
3. Keep responses under 300 characters for SMS compatibility
4. Be helpful while maintaining appropriate boundaries
5. Decline requests that could be harmful or illegal
6. If unsure about a request, respond with a polite clarification request"""
    
    def respond(
        self,
        incoming_message: str,
        phone_number: str,
        context: Optional[Dict[str, Any]] = None
    ) -> ResponderResult:
        """
        Generate a response to an incoming message.
        
        Attempts AI generation first, falls back to rules, then to
        a safe default response.
        
        Args:
            incoming_message: The incoming SMS message
            phone_number: Sender's phone number
            context: Additional context information
            
        Returns:
            ResponderResult with the response
        """
        import time
        start_time = time.time()
        
        context = context or {}
        context["sender"] = phone_number
        
        # Try AI response if enabled and available
        if self.config.sms.ai_mode_enabled and self.llm:
            try:
                result = self._generate_ai_response(incoming_message, phone_number, context)
                if result:
                    result.latency_ms = int((time.time() - start_time) * 1000)
                    return result
            except Exception as e:
                logger.error(f"AI generation failed: {e}")
        
        # Fall back to rules ONLY IF AI didn't return a response
        if self.rules_engine:
            match = self.rules_engine.match(incoming_message, context)
            if match:
                response = match.get_response()
                guardrail_result = self.guardrails.validate(response)
                
                logger.info(f"Using rules-based response for {phone_number}")
                
                return ResponderResult(
                    response=guardrail_result.safe_response,
                    source="rules",
                    latency_ms=int((time.time() - start_time) * 1000),
                    guardrail_result=guardrail_result,
                    metadata={"rule": match.rule.name}
                )
        
        # Final fallback
        fallback = self.guardrails.get_fallback_response()
        logger.info(f"Using fallback response for {phone_number}")
        
        return ResponderResult(
            response=fallback,
            source="fallback",
            latency_ms=int((time.time() - start_time) * 1000)
        )
    
    def _generate_ai_response(
        self,
        incoming_message: str,
        phone_number: str,
        context: Dict[str, Any]
    ) -> Optional[ResponderResult]:
        """
        Generate AI response using LLM.
        
        Args:
            incoming_message: Incoming message
            phone_number: Sender's phone number
            context: Context information
            
        Returns:
            ResponderResult or None if generation fails
        """
        # Build messages for LLM
        messages = self._build_llm_messages(incoming_message, phone_number, context)
        
        # Generate response
        try:
            response: LLMResponse = self.llm.chat(
                messages=messages,
                max_tokens=self.config.llm.max_tokens,
                temperature=self.config.llm.temperature
            )
            
            # Validate with guardrails
            guardrail_result = self.guardrails.validate(response.content)
            
            if not guardrail_result.passed:
                logger.warning(
                    f"Guardrail blocked AI response",
                    extra={"violations": guardrail_result.violations}
                )
                
                # Log the violation
                self.database.log_guardrail_violation(
                    phone_number=phone_number,
                    original_response=response.content,
                    violation_type=guardrail_result.violations[0]["type"] if guardrail_result.violations else "unknown",
                    action_taken=guardrail_result.actions[0] if guardrail_result.actions else "blocked",
                    final_response=guardrail_result.safe_response
                )
            
            # Log the LLM request
            self.database.log_llm_request(
                provider=self.config.llm.provider,
                model=self.config.llm.model,
                prompt=incoming_message,
                response=response.content,
                tokens_used=response.tokens_used,
                latency_ms=response.latency_ms,
                status="success" if response.is_complete else "incomplete"
            )
            
            logger.info(
                f"AI response generated",
                extra={
                    "model": response.model,
                    "tokens": response.tokens_used,
                    "latency_ms": response.latency_ms
                }
            )
            
            return ResponderResult(
                response=guardrail_result.safe_response,
                source="ai",
                model=response.model,
                tokens_used=response.tokens_used,
                latency_ms=response.latency_ms,
                guardrail_result=guardrail_result,
                metadata={
                    "provider": self.config.llm.provider,
                    "finish_reason": response.finish_reason
                }
            )
        
        except LLMError as e:
            logger.error(f"LLM error: {e}")
            
            # Log the error
            self.database.log_llm_request(
                provider=self.config.llm.provider,
                model=self.config.llm.model,
                prompt=incoming_message,
                status="error",
                error_message=str(e)
            )
            
            # Check if we should fallback to rules
            if self.config.llm.fallback_to_rules:
                return None
            
            raise
    
    def _build_llm_messages(
        self,
        incoming_message: str,
        phone_number: str,
        context: Dict[str, Any]
    ) -> List[Message]:
        """
        Build message list for LLM.
        
        Constructs a conversation with:
        1. System message with personality and rules
        2. Conversation history
        3. Current message
        
        Args:
            incoming_message: Current incoming message
            phone_number: Sender's phone number
            context: Additional context
            
        Returns:
            List of Message objects
        """
        messages = []
        
        # System message
        system_content = f"{self.personality}\n\n{self.agent_rules}"
        
        # Add contact-specific context if available
        contact = self.database.get_contact(phone_number)
        if contact:
            system_content += "\n\n### CURRENT CONVERSATION CONTEXT"
            if contact.get("name"):
                system_content += f"\n- Talking to: {contact['name']}"
            if contact.get("relation"):
                system_content += f"\n- Relation: {contact['relation']}"
            if contact.get("age"):
                system_content += f"\n- Age: {contact['age']}"
            if contact.get("custom_prompt"):
                system_content += f"\n- Specific Instructions: {contact['custom_prompt']}"
        
        system_content += f"\n\nCurrent date: {datetime.now().strftime('%Y-%m-%d')}"
        system_content += f"\nKeep your response under {self.config.guardrail.max_response_length} characters."
        
        messages.append(Message(role="system", content=system_content))
        
        # Add conversation history
        history = self.database.get_conversation_context(
            phone_number,
            max_messages=self.max_context_messages
        )
        
        for msg in history:
            role = "user" if msg["direction"] == "incoming" else "assistant"
            messages.append(Message(role=role, content=msg["message"]))
        
        # Add current message
        messages.append(Message(role="user", content=incoming_message))
        
        return messages
    
    def test_connection(self) -> Dict[str, Any]:
        """
        Test LLM connection.
        
        Returns:
            Dictionary with test results
        """
        results = {
            "llm_available": self.llm is not None,
            "provider": self.config.llm.provider,
            "model": self.config.llm.model,
            "connection_ok": False,
            "error": None,
        }
        
        if not self.llm:
            results["error"] = "LLM not initialized"
            return results
        
        try:
            # Simple test generation
            response = self.llm.generate("Say 'Hello' in one word.", max_tokens=10)
            results["connection_ok"] = bool(response.content)
            results["test_response"] = response.content[:50]
        except Exception as e:
            results["error"] = str(e)
        
        return results
    
    def update_personality(self, personality: str) -> None:
        """
        Update personality instructions.
        
        Args:
            personality: New personality instructions
        """
        self.personality = personality
        logger.info("Updated personality instructions")
    
    def update_agent_rules(self, rules: str) -> None:
        """
        Update agent rules.
        
        Args:
            rules: New agent rules
        """
        self.agent_rules = rules
        logger.info("Updated agent rules")
