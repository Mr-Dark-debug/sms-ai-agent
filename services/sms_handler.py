"""
SMS Handler - Termux API integration for SMS operations
=======================================================

This module provides SMS functionality using Termux API,
including:
- Sending SMS messages
- Receiving SMS messages
- Message parsing
- Notification handling
"""

import subprocess
import json
import re
from datetime import datetime
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass, field
from pathlib import Path
import threading

from core.exceptions import SMSError
from core.logging import get_logger

logger = get_logger("services.sms")


@dataclass
class SMSMessage:
    """
    Represents an SMS message.
    
    Attributes:
        phone_number (str): Sender/recipient phone number
        message (str): Message content
        timestamp (datetime): Message timestamp
        direction (str): 'incoming' or 'outgoing'
        thread_id (int): Conversation thread ID
        read (bool): Whether message has been read
        metadata (dict): Additional metadata
    """
    phone_number: str
    message: str
    timestamp: datetime = field(default_factory=datetime.now)
    direction: str = "incoming"
    thread_id: Optional[int] = None
    read: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __str__(self) -> str:
        """String representation."""
        return f"[{self.direction}] {self.phone_number}: {self.message[:50]}"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "phone_number": self.phone_number,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "direction": self.direction,
            "thread_id": self.thread_id,
            "read": self.read,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SMSMessage':
        """Create from dictionary."""
        return cls(
            phone_number=data["phone_number"],
            message=data["message"],
            timestamp=datetime.fromisoformat(data["timestamp"]) if "timestamp" in data else datetime.now(),
            direction=data.get("direction", "incoming"),
            thread_id=data.get("thread_id"),
            read=data.get("read", False),
            metadata=data.get("metadata", {}),
        )


class SMSHandler:
    """
    Handles SMS operations using Termux API.
    
    Provides methods for sending and receiving SMS messages
    using the termux-sms-send and termux-sms-list commands.
    
    Requirements:
    - Termux app installed
    - Termux:API app installed
    - termux-api package: pkg install termux-api
    - SMS permissions granted
    
    Example:
        handler = SMSHandler()
        
        # Send SMS
        handler.send_sms("+1234567890", "Hello from SMS Agent!")
        
        # List messages
        messages = handler.list_messages(limit=10)
        for msg in messages:
            print(msg)
    """
    
    def __init__(
        self,
        termux_api_path: str = "termux-sms-send",
        termux_list_path: str = "termux-sms-list",
        timeout: int = 30
    ):
        """
        Initialize SMS handler.
        
        Args:
            termux_api_path: Path to termux-sms-send command
            termux_list_path: Path to termux-sms-list command
            timeout: Command timeout in seconds
        """
        self.termux_api_path = termux_api_path
        self.termux_list_path = termux_list_path
        self.timeout = timeout
        
        # Callbacks for incoming messages
        self._callbacks: List[Callable[[SMSMessage], None]] = []
        self._listener_thread: Optional[threading.Thread] = None
        self._running = False
        
        # Verify Termux API availability
        self._available = self._check_availability()
        
        logger.info(
            f"SMS Handler initialized",
            extra={"available": self._available}
        )
    
    def _check_availability(self) -> bool:
        """
        Check if Termux API is available.
        
        Returns:
            True if Termux API commands are available
        """
        try:
            # Try to run termux-telephony-deviceinfo as a test
            result = subprocess.run(
                ["termux-telephony-deviceinfo"],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
    
    @property
    def is_available(self) -> bool:
        """Check if SMS handler is available."""
        return self._available
    
    def send_sms(
        self,
        phone_number: str,
        message: str,
        sim_slot: Optional[int] = None
    ) -> bool:
        """
        Send an SMS message.
        
        Args:
            phone_number: Recipient phone number
            message: Message content
            sim_slot: SIM slot to use (0 or 1, optional)
            
        Returns:
            True if message was sent successfully
            
        Raises:
            SMSError: If sending fails
        """
        if not self._available:
            raise SMSError(
                "Termux API not available",
                details={"hint": "Install Termux:API app and run 'pkg install termux-api'"}
            )
        
        # Validate phone number
        phone_number = self._normalize_phone_number(phone_number)
        
        # Build command
        cmd = [self.termux_api_path]
        
        if sim_slot is not None:
            cmd.extend(["--slot", str(sim_slot)])
        
        cmd.extend(["-n", phone_number])
        
        logger.info(
            f"Sending SMS",
            extra={"phone": self._mask_phone(phone_number), "length": len(message)}
        )
        
        try:
            result = subprocess.run(
                cmd,
                input=message,
                capture_output=True,
                text=True,
                timeout=self.timeout
            )
            
            if result.returncode != 0:
                error_msg = result.stderr.strip() or "Unknown error"
                raise SMSError(
                    f"Failed to send SMS: {error_msg}",
                    details={"phone": phone_number, "returncode": result.returncode}
                )
            
            logger.info(f"SMS sent successfully to {self._mask_phone(phone_number)}")
            return True
        
        except subprocess.TimeoutExpired:
            raise SMSError(
                "SMS send command timed out",
                details={"timeout": self.timeout}
            )
        
        except FileNotFoundError:
            raise SMSError(
                f"Termux API command not found: {self.termux_api_path}",
                details={"hint": "Install termux-api package: pkg install termux-api"}
            )
    
    def list_messages(
        self,
        limit: int = 10,
        offset: int = 0,
        phone_number: Optional[str] = None
    ) -> List[SMSMessage]:
        """
        List SMS messages from device.
        
        Args:
            limit: Maximum number of messages
            offset: Number of messages to skip
            phone_number: Filter by phone number (optional)
            
        Returns:
            List of SMSMessage objects
            
        Raises:
            SMSError: If listing fails
        """
        if not self._available:
            raise SMSError("Termux API not available")
        
        # Build command
        cmd = [self.termux_list_path]
        
        if limit:
            cmd.extend(["-l", str(limit)])
        
        if offset:
            cmd.extend(["-o", str(offset)])
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout
            )
            
            if result.returncode != 0:
                error_msg = result.stderr.strip() or "Unknown error"
                raise SMSError(f"Failed to list SMS: {error_msg}")
            
            # Parse JSON response
            try:
                messages_data = json.loads(result.stdout)
            except json.JSONDecodeError:
                raise SMSError("Failed to parse SMS list response")
            
            # Convert to SMSMessage objects
            messages = []
            for msg_data in messages_data:
                msg = SMSMessage(
                    phone_number=msg_data.get("number", msg_data.get("address", "")),
                    message=msg_data.get("body", msg_data.get("text", "")),
                    timestamp=self._parse_timestamp(msg_data.get("received", msg_data.get("date"))),
                    direction="incoming" if msg_data.get("type", 1) == 1 else "outgoing",
                    thread_id=msg_data.get("thread_id"),
                    read=msg_data.get("read", 1) == 1,
                )
                
                # Filter by phone number if specified
                if phone_number:
                    if self._normalize_phone_number(msg.phone_number) != self._normalize_phone_number(phone_number):
                        continue
                
                messages.append(msg)
            
            return messages
        
        except subprocess.TimeoutExpired:
            raise SMSError("SMS list command timed out")
    
    def get_recent_messages(self, count: int = 10) -> List[SMSMessage]:
        """
        Get most recent messages.
        
        Args:
            count: Number of recent messages
            
        Returns:
            List of recent SMSMessage objects
        """
        return self.list_messages(limit=count)
    
    def get_conversation(self, phone_number: str, limit: int = 50) -> List[SMSMessage]:
        """
        Get conversation with a specific number.
        
        Args:
            phone_number: Phone number to get conversation with
            limit: Maximum number of messages
            
        Returns:
            List of messages in conversation
        """
        return self.list_messages(limit=limit, phone_number=phone_number)
    
    def on_message_received(self, callback: Callable[[SMSMessage], None]) -> None:
        """
        Register a callback for incoming messages.
        
        Args:
            callback: Function to call when message is received
        """
        self._callbacks.append(callback)
    
    def start_listener(self, poll_interval: int = 10) -> None:
        """
        Start listening for new messages.
        
        Uses polling to check for new messages periodically.
        
        Args:
            poll_interval: Seconds between checks
        """
        if self._running:
            return
        
        self._running = True
        self._listener_thread = threading.Thread(
            target=self._listener_loop,
            args=(poll_interval,),
            daemon=True
        )
        self._listener_thread.start()
        logger.info("Started SMS listener")
    
    def stop_listener(self) -> None:
        """Stop the message listener."""
        self._running = False
        if self._listener_thread:
            self._listener_thread.join(timeout=5)
        logger.info("Stopped SMS listener")
    
    def _listener_loop(self, poll_interval: int) -> None:
        """Listener loop for polling messages."""
        seen_ids = set()
        
        while self._running:
            try:
                # Get recent messages
                messages = self.list_messages(limit=10)
                
                for msg in messages:
                    # Create unique ID
                    msg_id = f"{msg.phone_number}_{msg.timestamp.isoformat()}"
                    
                    if msg_id not in seen_ids and msg.direction == "incoming":
                        seen_ids.add(msg_id)
                        
                        # Notify callbacks
                        for callback in self._callbacks:
                            try:
                                callback(msg)
                            except Exception as e:
                                logger.error(f"Callback error: {e}")
                
            except Exception as e:
                logger.error(f"Listener error: {e}")
            
            # Wait before next poll
            import time
            time.sleep(poll_interval)
    
    def _normalize_phone_number(self, phone: str) -> str:
        """
        Normalize phone number format.
        
        Removes non-numeric characters except +.
        
        Args:
            phone: Phone number string
            
        Returns:
            Normalized phone number
        """
        return re.sub(r'[^\d+]', '', phone)
    
    def _mask_phone(self, phone: str) -> str:
        """
        Mask phone number for logging.
        
        Args:
            phone: Phone number
            
        Returns:
            Masked phone number
        """
        if len(phone) > 4:
            return phone[:3] + "****" + phone[-4:]
        return "****"
    
    def _parse_timestamp(self, timestamp_str: Optional[str]) -> datetime:
        """
        Parse timestamp from various formats.
        
        Args:
            timestamp_str: Timestamp string
            
        Returns:
            datetime object
        """
        if not timestamp_str:
            return datetime.now()
        
        # Try ISO format
        try:
            return datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            pass
        
        # Try Unix timestamp
        try:
            return datetime.fromtimestamp(int(timestamp_str) / 1000)
        except (ValueError, TypeError):
            pass
        
        return datetime.now()
    
    def get_device_info(self) -> Dict[str, Any]:
        """
        Get device telephony information.
        
        Returns:
            Dictionary with device info
        """
        if not self._available:
            return {"available": False}
        
        try:
            result = subprocess.run(
                ["termux-telephony-deviceinfo"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                return json.loads(result.stdout)
        
        except Exception:
            pass
        
        return {"available": False}


def test_sms_handler() -> Dict[str, Any]:
    """
    Test SMS handler functionality.
    
    Returns:
        Dictionary with test results
    """
    results = {
        "termux_available": False,
        "sms_list": False,
        "device_info": False,
        "error": None,
    }
    
    try:
        handler = SMSHandler()
        results["termux_available"] = handler.is_available
        
        if handler.is_available:
            # Test device info
            info = handler.get_device_info()
            results["device_info"] = bool(info.get("phone_number"))
            
            # Test message list
            messages = handler.list_messages(limit=1)
            results["sms_list"] = True
    
    except Exception as e:
        results["error"] = str(e)
    
    return results
