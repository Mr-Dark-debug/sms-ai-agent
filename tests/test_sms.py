"""
Test SMS Handler Module
======================

Unit tests for SMS handling functionality.
"""

import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock
from pathlib import Path
import sys
import json

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.sms_handler import SMSHandler, SMSMessage
from core.exceptions import SMSError


class TestSMSMessage:
    """Tests for SMSMessage class."""
    
    def test_creation(self):
        """Test creating SMSMessage."""
        msg = SMSMessage(
            phone_number="+1234567890",
            message="Hello",
            direction="incoming"
        )
        assert msg.phone_number == "+1234567890"
        assert msg.message == "Hello"
        assert msg.direction == "incoming"
        assert isinstance(msg.timestamp, datetime)
    
    def test_to_dict(self):
        """Test dictionary serialization."""
        msg = SMSMessage(
            phone_number="+1234567890",
            message="Hello"
        )
        data = msg.to_dict()
        assert data["phone_number"] == "+1234567890"
        assert data["message"] == "Hello"
        assert "timestamp" in data
    
    def test_from_dict(self):
        """Test creation from dictionary."""
        data = {
            "phone_number": "+1234567890",
            "message": "Hello",
            "timestamp": datetime.now().isoformat(),
            "direction": "incoming"
        }
        msg = SMSMessage.from_dict(data)
        assert msg.phone_number == "+1234567890"
        assert msg.message == "Hello"


class TestSMSHandler:
    """Tests for SMSHandler class."""
    
    @pytest.fixture
    def handler(self):
        """Create SMSHandler instance with mocked availability check."""
        with patch.object(SMSHandler, '_check_availability', return_value=True):
            return SMSHandler()
    
    def test_phone_normalization(self, handler):
        """Test phone number normalization."""
        assert handler._normalize_phone_number("+1 (234) 567-8900") == "+12345678900"
        assert handler._normalize_phone_number("1234567890") == "1234567890"
        assert handler._normalize_phone_number("123-456") == "123456"
    
    def test_phone_masking(self, handler):
        """Test phone number masking."""
        assert handler._mask_phone("+1234567890") == "+12****7890"
        assert handler._mask_phone("123") == "****"
    
    def test_sms_type_mapping(self, handler):
        """Test SMS type mapping logic."""
        # Check the map directly
        assert handler.SMS_TYPE_MAP[1] == "incoming"
        assert handler.SMS_TYPE_MAP[2] == "outgoing"
        assert handler.SMS_TYPE_MAP[5] == "failed"
    
    @patch("subprocess.run")
    def test_send_sms(self, mock_run, handler):
        """Test sending SMS."""
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        
        result = handler.send_sms("+1234567890", "Test message")
        assert result is True
        
        # Verify command
        cmd = mock_run.call_args[0][0]
        assert "termux-sms-send" in cmd
        assert "-n" in cmd
        assert "+1234567890" in cmd
    
    @patch("subprocess.run")
    def test_list_messages(self, mock_run, handler):
        """Test listing messages."""
        # Mock response
        mock_data = [
            {
                "address": "+1234567890",
                "body": "Test incoming",
                "type": 1,  # incoming
                "date": "1614556800000",
                "read": 1
            },
            {
                "address": "+0987654321",
                "body": "Test outgoing",
                "type": 2,  # outgoing
                "date": "1614556800000",
                "read": 1
            }
        ]
        
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps(mock_data),
            stderr=""
        )
        
        messages = handler.list_messages()
        
        assert len(messages) == 2
        assert messages[0].direction == "incoming"
        assert messages[0].message == "Test incoming"
        assert messages[1].direction == "outgoing"
        assert messages[1].message == "Test outgoing"
    
    @patch("subprocess.run")
    def test_list_messages_error(self, mock_run, handler):
        """Test listing messages with error."""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Error listing messages"
        )
        
        with pytest.raises(SMSError):
            handler.list_messages()

