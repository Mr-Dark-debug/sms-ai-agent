"""
Security Module - Security utilities and safe content handling
=============================================================

This module provides security-related functionality including:
- API key management
- Content sanitization
- PII detection and redaction
- Safe fallback responses
- Security validation
"""

import os
import re
import hashlib
import secrets
from typing import Optional, List, Tuple, Dict, Any
from pathlib import Path
import json

from .exceptions import GuardrailError
from .logging import get_logger

logger = get_logger("security")


class SecurityManager:
    """
    Centralized security management for SMS AI Agent.
    
    Handles all security-related operations including:
    - API key storage and validation
    - Content sanitization
    - PII detection and redaction
    - Security logging
    - Safe fallback responses
    
    Example:
        security = SecurityManager(config_dir="/path/to/config")
        
        # Validate API key
        if security.validate_api_key("openrouter", key):
            security.store_api_key("openrouter", key)
        
        # Sanitize message
        safe_msg = security.sanitize_content(user_message)
    """
    
    # Patterns for detecting sensitive information
    PII_PATTERNS = {
        "phone_number": [
            r'\+?1?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',  # US phone
            r'\+\d{1,3}[-.\s]?\d{4,14}',  # International
        ],
        "email": [
            r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
        ],
        "credit_card": [
            r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b',  # Credit card
            r'\b\d{13,19}\b',  # Potential card number
        ],
        "ssn": [
            r'\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b',  # SSN
        ],
        "address": [
            r'\d+\s+[A-Za-z]+\s+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Way|Court|Ct)\b',
        ],
        "ip_address": [
            r'\b(?:\d{1,3}\.){3}\d{1,3}\b',  # IPv4
            r'\b(?:[A-Fa-f0-9]{1,4}:){7}[A-Fa-f0-9]{1,4}\b',  # IPv6
        ],
    }
    
    # Patterns for unsafe content
    UNSAFE_PATTERNS = [
        r'password\s*[=:]\s*\S+',
        r'api[_-]?key\s*[=:]\s*\S+',
        r'secret\s*[=:]\s*\S+',
        r'token\s*[=:]\s*\S+',
        r'private[_-]?key',
        r'credit[_-]?card',
        r'social[_-]?security',
        r'bank[_-]?account',
    ]
    
    # Safe fallback responses for various scenarios
    FALLBACK_RESPONSES = [
        "I received your message but cannot respond right now. Please try again later.",
        "Thanks for reaching out! I'll get back to you as soon as possible.",
        "I'm currently unavailable. Your message has been noted.",
        "Thanks for your message! I'll respond when I'm able to.",
        "Message received. I'll reply when available.",
    ]
    
    def __init__(self, config_dir: str, data_dir: str):
        """
        Initialize security manager.
        
        Args:
            config_dir: Directory for configuration files
            data_dir: Directory for data files
        """
        self.config_dir = Path(config_dir)
        self.data_dir = Path(data_dir)
        self.env_file = self.config_dir / ".env"
        
        # Ensure directories exist
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Load environment from .env file
        self._load_env_file()
        
        logger.info("Security manager initialized")
    
    def _load_env_file(self) -> None:
        """
        Load environment variables from .env file.
        
        Does not override existing environment variables.
        """
        if not self.env_file.exists():
            return
        
        try:
            with open(self.env_file, "r") as f:
                for line in f:
                    line = line.strip()
                    
                    # Skip comments and empty lines
                    if not line or line.startswith("#"):
                        continue
                    
                    # Parse key=value
                    if "=" in line:
                        key, value = line.split("=", 1)
                        key = key.strip()
                        value = value.strip()
                        
                        # Remove quotes if present
                        if value.startswith('"') and value.endswith('"'):
                            value = value[1:-1]
                        elif value.startswith("'") and value.endswith("'"):
                            value = value[1:-1]
                        
                        # Set if not already in environment
                        if key not in os.environ:
                            os.environ[key] = value
            
            logger.debug("Loaded environment from .env file")
        except Exception as e:
            logger.warning(f"Failed to load .env file: {e}")
    
    def get_api_key(self, provider: str) -> Optional[str]:
        """
        Get API key for a provider.
        
        Checks environment variables and .env file.
        
        Args:
            provider: Provider name (e.g., "openrouter", "ollama")
            
        Returns:
            API key if found, None otherwise
        """
        # Map provider to environment variable name
        env_mappings = {
            "openrouter": ["OPENROUTER_API_KEY", "SMS_AGENT_LLM_API_KEY"],
            "ollama": ["OLLAMA_API_KEY"],
        }
        
        keys_to_check = env_mappings.get(provider, [f"{provider.upper()}_API_KEY"])
        
        for key in keys_to_check:
            value = os.environ.get(key)
            if value and value.strip():
                return value.strip()
        
        return None
    
    def store_api_key(self, provider: str, api_key: str) -> None:
        """
        Store API key in .env file.
        
        Args:
            provider: Provider name
            api_key: API key to store
        """
        # Determine environment variable name
        env_mappings = {
            "openrouter": "OPENROUTER_API_KEY",
            "ollama": "OLLAMA_API_KEY",
        }
        
        var_name = env_mappings.get(provider, f"{provider.upper()}_API_KEY")
        
        # Read existing .env content
        existing = {}
        if self.env_file.exists():
            with open(self.env_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        existing[key.strip()] = value.strip()
        
        # Update with new key
        existing[var_name] = api_key
        
        # Write back to .env file
        with open(self.env_file, "w") as f:
            f.write("# SMS AI Agent Environment Variables\n")
            f.write("# This file contains sensitive information - DO NOT SHARE\n\n")
            
            for key, value in sorted(existing.items()):
                f.write(f"{key}={value}\n")
        
        # Set in current environment
        os.environ[var_name] = api_key
        
        # Set restrictive permissions
        try:
            os.chmod(self.env_file, 0o600)
        except Exception:
            pass
        
        logger.info(f"Stored API key for {provider}")
    
    def validate_api_key(self, provider: str, api_key: str) -> bool:
        """
        Validate an API key format.
        
        Args:
            provider: Provider name
            api_key: API key to validate
            
        Returns:
            True if key appears valid
        """
        if not api_key or not api_key.strip():
            return False
        
        # Provider-specific validation
        if provider == "openrouter":
            # OpenRouter keys typically start with "sk-or-"
            return len(api_key) >= 20 and (api_key.startswith("sk-or-") or api_key.startswith("sk-"))
        
        elif provider == "ollama":
            # Ollama doesn't require API keys by default
            return True
        
        # Generic validation
        return len(api_key) >= 10
    
    def has_api_key(self, provider: str) -> bool:
        """
        Check if an API key is configured for a provider.
        
        Args:
            provider: Provider name
            
        Returns:
            True if API key is configured
        """
        return self.get_api_key(provider) is not None
    
    def sanitize_content(self, content: str) -> str:
        """
        Sanitize content for safe display or logging.
        
        Removes or masks potential PII and sensitive information.
        
        Args:
            content: Content to sanitize
            
        Returns:
            Sanitized content
        """
        sanitized = content
        
        # Mask phone numbers (keep last 4 digits)
        for pattern in self.PII_PATTERNS.get("phone_number", []):
            sanitized = re.sub(
                pattern,
                lambda m: "***-***-" + m.group()[-4:] if len(m.group()) >= 4 else "***",
                sanitized
            )
        
        # Mask email addresses
        for pattern in self.PII_PATTERNS.get("email", []):
            sanitized = re.sub(
                pattern,
                lambda m: m.group()[0] + "***@" + m.group().split("@")[1] if "@" in m.group() else "***",
                sanitized
            )
        
        # Mask credit card numbers
        for pattern in self.PII_PATTERNS.get("credit_card", []):
            sanitized = re.sub(pattern, "****-****-****-****", sanitized)
        
        # Mask SSN
        for pattern in self.PII_PATTERNS.get("ssn", []):
            sanitized = re.sub(pattern, "***-**-****", sanitized)
        
        return sanitized
    
    def detect_pii(self, content: str) -> List[Dict[str, Any]]:
        """
        Detect potential PII in content.
        
        Args:
            content: Content to analyze
            
        Returns:
            List of detected PII types and locations
        """
        detected = []
        
        for pii_type, patterns in self.PII_PATTERNS.items():
            for pattern in patterns:
                for match in re.finditer(pattern, content):
                    detected.append({
                        "type": pii_type,
                        "value": match.group(),
                        "start": match.start(),
                        "end": match.end(),
                    })
        
        return detected
    
    def check_unsafe_content(self, content: str) -> List[Dict[str, Any]]:
        """
        Check for potentially unsafe content patterns.
        
        Args:
            content: Content to check
            
        Returns:
            List of detected unsafe patterns
        """
        detected = []
        
        for pattern in self.UNSAFE_PATTERNS:
            for match in re.finditer(pattern, content, re.IGNORECASE):
                detected.append({
                    "pattern": pattern,
                    "match": match.group(),
                    "start": match.start(),
                    "end": match.end(),
                })
        
        return detected
    
    def redact_pii(self, content: str, redactor: str = "[REDACTED]") -> str:
        """
        Redact PII from content.
        
        Args:
            content: Content to redact
            redactor: String to replace PII with
            
        Returns:
            Content with PII redacted
        """
        redacted = content
        
        for pii_type, patterns in self.PII_PATTERNS.items():
            for pattern in patterns:
                redacted = re.sub(pattern, redactor, redacted)
        
        return redacted
    
    def validate_response(
        self,
        response: str,
        max_length: int = 300,
        block_links: bool = False,
        block_phone_numbers: bool = True,
        block_emails: bool = True
    ) -> Tuple[bool, List[str]]:
        """
        Validate an AI-generated response.
        
        Checks for various safety and policy violations.
        
        Args:
            response: Response to validate
            max_length: Maximum allowed length
            block_links: Whether to block URLs
            block_phone_numbers: Whether to block phone numbers
            block_emails: Whether to block email addresses
            
        Returns:
            Tuple of (is_valid, list_of_violations)
        """
        violations = []
        
        # Check length
        if len(response) > max_length:
            violations.append(f"Response too long: {len(response)} > {max_length}")
        
        # Check for links
        if block_links:
            url_pattern = r'https?://[^\s]+|www\.[^\s]+'
            if re.search(url_pattern, response):
                violations.append("Response contains URL")
        
        # Check for phone numbers
        if block_phone_numbers:
            for pattern in self.PII_PATTERNS.get("phone_number", []):
                if re.search(pattern, response):
                    violations.append("Response contains phone number")
                    break
        
        # Check for emails
        if block_emails:
            for pattern in self.PII_PATTERNS.get("email", []):
                if re.search(pattern, response):
                    violations.append("Response contains email address")
                    break
        
        # Check for unsafe patterns
        unsafe = self.check_unsafe_content(response)
        if unsafe:
            violations.append(f"Response contains unsafe patterns: {len(unsafe)} found")
        
        return len(violations) == 0, violations
    
    def get_fallback_response(self, context: Optional[str] = None) -> str:
        """
        Get a safe fallback response.
        
        Returns a randomized fallback response for use when
        AI generation fails or is inappropriate.
        
        Args:
            context: Optional context for selecting response
            
        Returns:
            Safe fallback response string
        """
        import random
        return random.choice(self.FALLBACK_RESPONSES)
    
    def generate_secure_token(self, length: int = 32) -> str:
        """
        Generate a cryptographically secure random token.
        
        Args:
            length: Token length in bytes (output will be hex encoded)
            
        Returns:
            Hex-encoded secure token
        """
        return secrets.token_hex(length)
    
    def hash_sensitive(self, value: str) -> str:
        """
        Create a secure hash of a sensitive value.
        
        Useful for logging or storing references to sensitive
        data without exposing the actual value.
        
        Args:
            value: Value to hash
            
        Returns:
            SHA256 hash of the value
        """
        return hashlib.sha256(value.encode()).hexdigest()[:16]
    
    def create_data_wipe_script(self) -> Path:
        """
        Create a script for wiping all user data.
        
        Generates a shell script that can be run to securely
        delete all SMS AI Agent data.
        
        Returns:
            Path to the generated script
        """
        script_path = self.config_dir / "wipe_data.sh"
        
        script_content = f'''#!/bin/bash
# SMS AI Agent Data Wipe Script
# This script will permanently delete all SMS AI Agent data

echo "WARNING: This will permanently delete all SMS AI Agent data!"
echo "Including: messages, logs, settings, and API keys"
echo ""
read -p "Are you sure? Type 'DELETE' to confirm: " confirm

if [ "$confirm" != "DELETE" ]; then
    echo "Cancelled."
    exit 0
fi

# Delete data directories
rm -rf "{self.data_dir}"
rm -rf "{self.config_dir}/logs"

# Delete database
rm -f "{self.data_dir}/sms_agent.db"

# Delete environment file
rm -f "{self.env_file}"

# Delete config
rm -f "{self.config_dir}/config.yaml"

echo "All SMS AI Agent data has been deleted."
'''
        
        with open(script_path, "w") as f:
            f.write(script_content)
        
        os.chmod(script_path, 0o700)
        
        logger.info(f"Created data wipe script at {script_path}")
        return script_path
    
    def export_security_report(self) -> Dict[str, Any]:
        """
        Generate a security status report.
        
        Returns:
            Dictionary with security status information
        """
        return {
            "api_keys_configured": {
                "openrouter": self.has_api_key("openrouter"),
                "ollama": self.has_api_key("ollama"),
            },
            "env_file_exists": self.env_file.exists(),
            "env_file_permissions": oct(self.env_file.stat().st_mode)[-3:] if self.env_file.exists() else None,
            "config_dir_permissions": oct(self.config_dir.stat().st_mode)[-3:],
            "data_dir_permissions": oct(self.data_dir.stat().st_mode)[-3:],
        }
