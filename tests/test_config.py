"""
Test Configuration Module
========================

Unit tests for configuration loading and validation.
"""

import os
import pytest
from pathlib import Path

# Add parent directory to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import (
    Config, LLMConfig, SMSConfig, RateLimitConfig, 
    GuardrailConfig, UIConfig, load_config, save_config
)
from core.exceptions import ConfigError


class TestLLMConfig:
    """Tests for LLMConfig."""
    
    def test_default_values(self):
        """Test default configuration values."""
        config = LLMConfig()
        assert config.provider == "openrouter"
        assert config.temperature == 0.7
        assert config.max_tokens == 150
    
    def test_validation_valid(self):
        """Test valid configuration passes validation."""
        config = LLMConfig(provider="ollama")
        config.validate()  # Should not raise
    
    def test_validation_invalid_temperature(self):
        """Test invalid temperature raises error."""
        config = LLMConfig(temperature=3.0)
        with pytest.raises(ConfigError):
            config.validate()
    
    def test_validation_invalid_max_tokens(self):
        """Test invalid max_tokens raises error."""
        config = LLMConfig(max_tokens=0)
        with pytest.raises(ConfigError):
            config.validate()


class TestSMSConfig:
    """Tests for SMSConfig."""
    
    def test_default_values(self):
        """Test default configuration values."""
        config = SMSConfig()
        assert config.auto_reply_enabled is True
        assert config.max_response_length == 300
    
    def test_validation(self):
        """Test configuration validation."""
        config = SMSConfig()
        config.validate()  # Should not raise


class TestConfig:
    """Tests for main Config class."""
    
    def test_default_values(self):
        """Test default configuration values."""
        config = Config()
        assert config.app_name == "SMS AI Agent"
        assert config.llm is not None
        assert config.sms is not None
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        config = Config()
        d = config.to_dict()
        assert "app_name" in d
        assert "llm" in d
        assert "sms" in d


# Integration tests would go here
# These require actual configuration files
