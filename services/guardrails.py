"""
Guardrail System - Safety checks for AI-generated responses
==========================================================

This module provides comprehensive safety checks for AI-generated
responses including:
- Content length validation
- PII detection and redaction
- Unsafe content filtering
- Response quality checks
"""

import re
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import json

from core.exceptions import GuardrailError
from core.logging import get_logger
from core.security import SecurityManager

logger = get_logger("services.guardrails")


class ViolationType(Enum):
    """Types of guardrail violations."""
    LENGTH_EXCEEDED = "length_exceeded"
    PHONE_NUMBER = "phone_number"
    EMAIL_ADDRESS = "email_address"
    URL = "url"
    PII = "pii"
    UNSAFE_CONTENT = "unsafe_content"
    PERSONAL_INFO = "personal_info"
    CREDIT_CARD = "credit_card"
    PROFANITY = "profanity"
    CUSTOM = "custom"


class ActionType(Enum):
    """Actions to take for violations."""
    BLOCK = "block"           # Block the response entirely
    REDACT = "redact"         # Redact the problematic content
    MODIFY = "modify"         # Modify the response
    WARN = "warn"             # Allow but log warning
    TRUNCATE = "truncate"     # Truncate to acceptable length


@dataclass
class GuardrailResult:
    """
    Result of guardrail validation.
    
    Attributes:
        passed (bool): Whether response passed all checks
        original (str): Original response text
        modified (str): Modified response (if applicable)
        violations (list): List of violations detected
        actions (list): Actions taken
    """
    passed: bool
    original: str
    modified: str = ""
    violations: List[Dict[str, Any]] = field(default_factory=list)
    actions: List[str] = field(default_factory=list)
    
    @property
    def safe_response(self) -> str:
        """Get the safe response (modified or original)."""
        return self.modified if self.modified else self.original
    
    @property
    def was_modified(self) -> bool:
        """Check if response was modified."""
        return bool(self.modified) and self.modified != self.original


class GuardrailSystem:
    """
    Comprehensive guardrail system for AI responses.
    
    Provides multiple layers of safety checks:
    1. Length constraints (SMS limit)
    2. PII detection and redaction
    3. Unsafe content filtering
    4. Quality checks
    
    Example:
        guardrails = GuardrailSystem(
            max_length=300,
            block_phone_numbers=True,
            block_urls=False
        )
        
        result = guardrails.validate(response_text)
        if result.passed:
            send(result.safe_response)
        else:
            handle_violations(result.violations)
    """
    
    # Default patterns for various content types
    DEFAULT_PATTERNS = {
        "phone_number": [
            r'\+?1?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',
            r'\+\d{1,3}[-.\s]?\d{4,14}',
        ],
        "email": [
            r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
        ],
        "url": [
            r'https?://[^\s<>"]+|www\.[^\s<>"]+',
        ],
        "credit_card": [
            r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b',
            r'\b\d{13,19}\b',
        ],
        "ssn": [
            r'\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b',
        ],
    }
    
    # Profanity patterns (basic set)
    PROFANITY_PATTERNS = [
        r'\b(damn|hell|crap)\b',  # Add more as needed
    ]
    
    # Default fallback responses
    FALLBACK_RESPONSES = [
        "I received your message but cannot provide a specific response right now.",
        "Thanks for reaching out! I'll get back to you soon.",
        "Message received. I'll respond when available.",
        "Thanks for your message! I'm currently unavailable.",
    ]
    
    def __init__(
        self,
        max_length: int = 300,
        block_phone_numbers: bool = True,
        block_emails: bool = True,
        block_urls: bool = False,
        block_credit_cards: bool = True,
        block_ssn: bool = True,
        block_profanity: bool = True,
        custom_patterns: Optional[List[str]] = None,
        security_manager: Optional[SecurityManager] = None
    ):
        """
        Initialize guardrail system.
        
        Args:
            max_length: Maximum response length (SMS limit)
            block_phone_numbers: Block phone numbers in responses
            block_emails: Block email addresses
            block_urls: Block URLs
            block_credit_cards: Block credit card numbers
            block_ssn: Block SSN
            block_profanity: Block profanity
            custom_patterns: Additional patterns to block
            security_manager: Optional security manager instance
        """
        self.max_length = max_length
        self.block_phone_numbers = block_phone_numbers
        self.block_emails = block_emails
        self.block_urls = block_urls
        self.block_credit_cards = block_credit_cards
        self.block_ssn = block_ssn
        self.block_profanity = block_profanity
        self.security_manager = security_manager
        
        # Compile patterns
        self._compile_patterns()
        
        # Add custom patterns
        self.custom_patterns = []
        if custom_patterns:
            for pattern in custom_patterns:
                try:
                    self.custom_patterns.append(re.compile(pattern, re.IGNORECASE))
                except re.error:
                    logger.warning(f"Invalid custom pattern: {pattern}")
        
        logger.info(
            "Guardrail system initialized",
            extra={
                "max_length": max_length,
                "block_phone": block_phone_numbers,
                "block_email": block_emails,
            }
        )
    
    def _compile_patterns(self) -> None:
        """Compile regex patterns for efficiency."""
        self.compiled_patterns = {}
        
        for pattern_type, patterns in self.DEFAULT_PATTERNS.items():
            self.compiled_patterns[pattern_type] = [
                re.compile(p, re.IGNORECASE) for p in patterns
            ]
        
        self.compiled_profanity = [
            re.compile(p, re.IGNORECASE) for p in self.PROFANITY_PATTERNS
        ]
    
    def validate(
        self,
        response: str,
        context: Optional[Dict[str, Any]] = None
    ) -> GuardrailResult:
        """
        Validate a response against all guardrails.
        
        Args:
            response: Response text to validate
            context: Optional context (sender, conversation, etc.)
            
        Returns:
            GuardrailResult with validation outcome
        """
        violations = []
        actions = []
        modified = response
        
        # 1. Check length
        length_violation = self._check_length(modified)
        if length_violation:
            violations.append(length_violation)
            if length_violation["action"] == ActionType.TRUNCATE.value:
                modified = self._truncate(modified)
                actions.append("truncated")
        
        # 2. Check for blocked content
        content_checks = [
            ("phone_number", self.block_phone_numbers),
            ("email", self.block_emails),
            ("url", self.block_urls),
            ("credit_card", self.block_credit_cards),
            ("ssn", self.block_ssn),
        ]
        
        for content_type, should_block in content_checks:
            if should_block:
                violation = self._check_content_type(modified, content_type)
                if violation:
                    violations.append(violation)
                    modified = self._redact(modified, content_type)
                    actions.append(f"redacted_{content_type}")
        
        # 3. Check profanity
        if self.block_profanity:
            profanity_violation = self._check_profanity(modified)
            if profanity_violation:
                violations.append(profanity_violation)
                modified = self._redact_profanity(modified)
                actions.append("redacted_profanity")
        
        # 4. Check custom patterns
        custom_violation = self._check_custom_patterns(modified)
        if custom_violation:
            violations.append(custom_violation)
            modified = self._redact_custom(modified)
            actions.append("redacted_custom")
        
        # 5. Check for PII using security manager
        if self.security_manager:
            pii_violation = self._check_pii(modified)
            if pii_violation:
                violations.append(pii_violation)
                modified = self.security_manager.redact_pii(modified)
                actions.append("redacted_pii")
        
        # Determine if passed
        # Failed if any violation requires blocking
        blocked = any(
            v.get("action") == ActionType.BLOCK.value
            for v in violations
        )
        
        passed = len(violations) == 0 or not blocked
        
        # Final length check after modifications
        if len(modified) > self.max_length:
            modified = self._truncate(modified)
            actions.append("final_truncated")
        
        return GuardrailResult(
            passed=passed,
            original=response,
            modified=modified,
            violations=violations,
            actions=actions
        )
    
    def _check_length(self, text: str) -> Optional[Dict[str, Any]]:
        """Check if text exceeds maximum length."""
        if len(text) > self.max_length:
            return {
                "type": ViolationType.LENGTH_EXCEEDED.value,
                "length": len(text),
                "max_length": self.max_length,
                "action": ActionType.TRUNCATE.value,
            }
        return None
    
    def _check_content_type(self, text: str, content_type: str) -> Optional[Dict[str, Any]]:
        """Check for specific content type in text."""
        patterns = self.compiled_patterns.get(content_type, [])
        
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                return {
                    "type": content_type,
                    "match": match.group(),
                    "action": ActionType.REDACT.value,
                }
        return None
    
    def _check_profanity(self, text: str) -> Optional[Dict[str, Any]]:
        """Check for profanity in text."""
        for pattern in self.compiled_profanity:
            match = pattern.search(text)
            if match:
                return {
                    "type": ViolationType.PROFANITY.value,
                    "match": match.group(),
                    "action": ActionType.REDACT.value,
                }
        return None
    
    def _check_custom_patterns(self, text: str) -> Optional[Dict[str, Any]]:
        """Check for custom pattern matches."""
        for pattern in self.custom_patterns:
            match = pattern.search(text)
            if match:
                return {
                    "type": ViolationType.CUSTOM.value,
                    "match": match.group(),
                    "action": ActionType.REDACT.value,
                }
        return None
    
    def _check_pii(self, text: str) -> Optional[Dict[str, Any]]:
        """Check for PII using security manager."""
        if self.security_manager:
            pii = self.security_manager.detect_pii(text)
            if pii:
                return {
                    "type": ViolationType.PII.value,
                    "count": len(pii),
                    "types": list(set(p["type"] for p in pii)),
                    "action": ActionType.REDACT.value,
                }
        return None
    
    def _truncate(self, text: str) -> str:
        """Truncate text to maximum length."""
        if len(text) <= self.max_length:
            return text
        
        # Try to truncate at word boundary
        truncated = text[:self.max_length - 3]
        last_space = truncated.rfind(" ")
        
        if last_space > self.max_length // 2:
            truncated = truncated[:last_space]
        
        return truncated + "..."
    
    def _redact(self, text: str, content_type: str) -> str:
        """Redact specific content type from text."""
        patterns = self.compiled_patterns.get(content_type, [])
        redacted = text
        
        for pattern in patterns:
            redacted = pattern.sub("[REDACTED]", redacted)
        
        return redacted
    
    def _redact_profanity(self, text: str) -> str:
        """Redact profanity from text."""
        redacted = text
        
        for pattern in self.compiled_profanity:
            redacted = pattern.sub("****", redacted)
        
        return redacted
    
    def _redact_custom(self, text: str) -> str:
        """Redact custom pattern matches."""
        redacted = text
        
        for pattern in self.custom_patterns:
            redacted = pattern.sub("[REDACTED]", redacted)
        
        return redacted
    
    def get_fallback_response(self) -> str:
        """
        Get a safe fallback response.
        
        Returns:
            Safe response to use when validation fails
        """
        import random
        return random.choice(self.FALLBACK_RESPONSES)
    
    def add_custom_pattern(self, pattern: str) -> bool:
        """
        Add a custom pattern to block.
        
        Args:
            pattern: Regex pattern string
            
        Returns:
            True if pattern was added successfully
        """
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
            self.custom_patterns.append(compiled)
            logger.info(f"Added custom guardrail pattern: {pattern}")
            return True
        except re.error as e:
            logger.warning(f"Invalid custom pattern: {pattern} - {e}")
            return False
    
    def remove_custom_pattern(self, pattern: str) -> bool:
        """
        Remove a custom pattern.
        
        Args:
            pattern: Pattern string to remove
            
        Returns:
            True if pattern was removed
        """
        for i, compiled in enumerate(self.custom_patterns):
            if compiled.pattern == pattern:
                del self.custom_patterns[i]
                return True
        return False
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get guardrail system status.
        
        Returns:
            Dictionary with configuration and statistics
        """
        return {
            "max_length": self.max_length,
            "blocks": {
                "phone_numbers": self.block_phone_numbers,
                "emails": self.block_emails,
                "urls": self.block_urls,
                "credit_cards": self.block_credit_cards,
                "ssn": self.block_ssn,
                "profanity": self.block_profanity,
            },
            "custom_patterns_count": len(self.custom_patterns),
        }
