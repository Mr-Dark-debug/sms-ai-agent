"""
SMS Handler - Termux API integration for SMS operations
======================================================

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
import hashlib
import time
import shutil
import httpx
from datetime import datetime
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass, field
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
    
    # Android SMS type values
    SMS_TYPE_MAP = {
        1: "incoming",    # MESSAGE_TYPE_INBOX
        2: "outgoing",    # MESSAGE_TYPE_SENT
        3: "draft",       # MESSAGE_TYPE_DRAFT
        4: "outgoing",    # MESSAGE_TYPE_OUTBOX
        5: "failed",      # MESSAGE_TYPE_FAILED
        6: "outgoing",    # MESSAGE_TYPE_QUEUED
    }
    
    def __init__(
        self,
        termux_api_path: str = "termux-sms-send",
        termux_list_path: str = "termux-sms-list",
        timeout: int = 30,
        webhook_config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize SMS handler.
        
        Args:
            termux_api_path: Path to termux-sms-send command
            termux_list_path: Path to termux-sms-list command
            timeout: Command timeout in seconds
            webhook_config: Configuration for webhooks (enabled, url, headers)
        """
        self.termux_api_path = termux_api_path
        self.termux_list_path = termux_list_path
        self.timeout = timeout
        self.webhook_config = webhook_config or {"enabled": False, "url": "", "headers": {}}
        
        # Track when we started to avoid processing old messages
        self.start_time = datetime.now()
        
        # Callbacks for incoming messages
        self._callbacks: List[Callable[[SMSMessage], None]] = []
        self._listener_thread: Optional[threading.Thread] = None
        self._running = False
        
        # Verify Termux API availability and permissions
        self._available = self._check_availability()
        
        logger.info(
            f"SMS Handler initialized",
            extra={"available": self._available}
        )
    
    def _check_availability(self) -> bool:
        """
        Check if Termux API is available AND SMS permissions are granted.
        
        Returns:
            True if Termux API commands are available and SMS permissions granted
        """
        try:
            # First check if termux-api commands exist using shutil.which
            if not shutil.which("termux-sms-list"):
                logger.error("termux-sms-list command not found")
                return False
            
            # Actually try to list SMS (this tests permissions)
            result = subprocess.run(
                ["termux-sms-list", "-l", "1"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                error = result.stderr.strip() if result.stderr else "Unknown error"
                logger.error(f"SMS list failed: {error}")
                
                # Check for permission-related errors
                if "permission" in error.lower() or "denied" in error.lower():
                    logger.error("SMS permission not granted!")
                    logger.error("Grant permission: Settings → Apps → Termux:API → Permissions → SMS")
                return False
            
            # Also verify we can send (different permission)
            if not shutil.which("termux-sms-send"):
                logger.warning("termux-sms-send not found")
            
            logger.info("SMS permissions verified successfully")
            return True
            
        except subprocess.TimeoutExpired:
            logger.error("Availability check timed out")
            return False
        except Exception as e:
            logger.error(f"Availability check failed: {e}")
            return False
    
    @property
    def is_available(self) -> bool:
        """Check if SMS handler is available."""
        return self._available
    
    def send_sms(
        self,
        phone_number: str,
        message: str,
        sim_slot: Optional[int] = None,
        callback_url: Optional[str] = None
    ) -> bool:
        """
        Send an SMS message.
        
        Args:
            phone_number: Recipient phone number
            message: Message content
            sim_slot: SIM slot to use (0 or 1, optional)
            callback_url: URL to notify of delivery status
            
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
            
            status = "sent" if result.returncode == 0 else "failed"
            error_msg = result.stderr.strip() if result.returncode != 0 else None
            
            if callback_url:
                self._report_delivery_status(callback_url, phone_number, status, error_msg)
            
            if result.returncode != 0:
                raise SMSError(
                    f"Failed to send SMS: {error_msg or 'Unknown error'}",
                    details={"phone": phone_number, "returncode": result.returncode}
                )
            
            logger.info(f"SMS sent successfully to {self._mask_phone(phone_number)}")
            return True
        
        except subprocess.TimeoutExpired:
            if callback_url:
                self._report_delivery_status(callback_url, phone_number, "timeout", "Command timed out")
            raise SMSError(
                "SMS send command timed out",
                details={"timeout": self.timeout}
            )
        
        except FileNotFoundError:
            raise SMSError(
                f"Termux API command not found: {self.termux_api_path}",
                details={"hint": "Install termux-api package: pkg install termux-api"}
            )

    def _report_delivery_status(self, url: str, phone: str, status: str, error: Optional[str] = None) -> None:
        """Report SMS delivery status via callback URL."""
        try:
            payload = {
                "phone_number": phone,
                "status": status,
                "timestamp": datetime.now().isoformat(),
                "error": error
            }
            # Run in background to not block SMS sending
            def send_report():
                try:
                    with httpx.Client(timeout=10.0) as client:
                        client.post(url, json=payload)
                except Exception as e:
                    logger.error(f"Failed to send delivery status report: {e}")
            
            threading.Thread(target=send_report, daemon=True).start()
        except Exception as e:
            logger.error(f"Error initializing delivery status report: {e}")
    
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
                msg_type = msg_data.get("type", 1)
                direction = self.SMS_TYPE_MAP.get(msg_type, "incoming")
                
                msg = SMSMessage(
                    phone_number=msg_data.get("number", msg_data.get("address", "")),
                    message=msg_data.get("body", msg_data.get("text", "")),
                    timestamp=self._parse_timestamp(msg_data.get("received", msg_data.get("date"))),
                    direction=direction,
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
    
    def start_listener(self, poll_interval: int = 3) -> None:
        """
        Start listening for new messages.
        
        Uses polling to check for new messages periodically.
        
        Args:
            poll_interval: Seconds between checks (default 3 seconds)
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
        logger.info(f"Started SMS listener (poll interval: {poll_interval}s)")
    
    def stop_listener(self) -> None:
        """Stop the message listener."""
        self._running = False
        if self._listener_thread:
            self._listener_thread.join(timeout=5)
        logger.info("Stopped SMS listener")
    
    def _listener_loop(self, poll_interval: int) -> None:
        """
        Listener loop for polling messages.
        
        Uses polling since Termux API doesn't support real-time SMS broadcast.
        Improved with better logging and unique ID generation.
        
        Args:
            poll_interval: Seconds between polls
        """
        seen_ids = set()
        first_run = True
        poll_count = 0
        
        logger.info(f"SMS listener loop started (poll interval: {poll_interval}s)")
        
        while self._running:
            poll_count += 1
            try:
                # Get recent messages
                messages = self.list_messages(limit=20)
                logger.debug(f"Poll #{poll_count}: Found {len(messages)} total messages")
                
                new_incoming = []
                
                for msg in messages:
                    # Only process incoming messages (Inbox)
                    if msg.direction != "incoming":
                        continue
                    
                    # Ignore messages received before bot started
                    if msg.timestamp < self.start_time:
                        continue
                    
                    # Create more robust unique ID using message content
                    content_preview = msg.message[:50] if msg.message else ""
                    unique_string = f"{msg.phone_number}|{msg.timestamp.isoformat()}|{content_preview}"
                    msg_id = hashlib.sha256(unique_string.encode()).hexdigest()[:16]
                    
                    if msg_id not in seen_ids:
                        seen_ids.add(msg_id)
                        
                        # Skip processing on first run (just populate seen_ids)
                        if not first_run:
                            new_incoming.append(msg)
                            logger.info(
                                f"NEW SMS DETECTED: From {msg.phone_number} - "
                                f"'{msg.message[:30]}{'...' if len(msg.message) > 30 else ''}'"
                            )
                            # Trigger webhook if enabled
                            if self.webhook_config.get("enabled"):
                                self._trigger_webhook(msg)
                
                # Process new messages through callbacks
                if new_incoming:
                    logger.info(f"Processing {len(new_incoming)} new incoming message(s)")
                    for msg in new_incoming:
                        logger.info(f"Dispatching to {len(self._callbacks)} callback(s)")
                        for callback in self._callbacks:
                            try:
                                callback(msg)
                            except Exception as e:
                                logger.error(f"Callback error: {e}", exc_info=True)
                
                # Mark first run complete
                if first_run:
                    logger.info(f"Initial scan complete. Tracking {len(seen_ids)} existing messages")
                    first_run = False
                    
            except Exception as e:
                logger.error(f"Listener loop error: {e}", exc_info=True)
            
            # Wait before next poll
            time.sleep(poll_interval)

    def _trigger_webhook(self, message: SMSMessage) -> None:
        """Trigger external webhook for incoming message."""
        url = self.webhook_config.get("url")
        if not url:
            return
            
        def send_webhook():
            try:
                headers = self.webhook_config.get("headers", {})
                with httpx.Client(timeout=10.0) as client:
                    client.post(url, json=message.to_dict(), headers=headers)
                logger.info(f"Webhook triggered successfully for message from {message.phone_number}")
            except Exception as e:
                logger.error(f"Webhook trigger failed: {e}")
                
        threading.Thread(target=send_webhook, daemon=True).start()

    def diagnose(self) -> Dict[str, Any]:
        """
        Run diagnostic checks for SMS functionality.
        
        Returns:
            Dictionary with diagnostic results
        """
        results = {
            "termux_api_installed": False,
            "sms_list_works": False,
            "sms_send_available": False,
            "device_info": None,
            "sample_messages": [],
            "errors": []
        }
        
        # Check 1: termux-sms-list exists
        try:
            results["termux_api_installed"] = bool(shutil.which("termux-sms-list"))
        except Exception as e:
            results["errors"].append(f"API check failed: {e}")
        
        # Check 2: Can list SMS
        try:
            result = subprocess.run(
                ["termux-sms-list", "-l", "5"],
                capture_output=True,
                text=True,
                timeout=15
            )
            if result.returncode == 0:
                results["sms_list_works"] = True
                try:
                    messages = json.loads(result.stdout)
                    results["sample_messages"] = [
                        {
                            "number": m.get("number", m.get("address", "unknown")),
                            "preview": m.get("body", m.get("text", ""))[:50],
                            "type": m.get("type", "unknown")
                        }
                        for m in messages[:3]
                    ]
                except json.JSONDecodeError:
                    results["errors"].append("Invalid JSON from termux-sms-list")
            else:
                results["errors"].append(f"SMS list failed: {result.stderr}")
        except Exception as e:
            results["errors"].append(f"SMS list test failed: {e}")
        
        # Check 3: termux-sms-send exists
        try:
            results["sms_send_available"] = bool(shutil.which("termux-sms-send"))
        except Exception as e:
            results["errors"].append(f"Send check failed: {e}")
        
        # Check 4: Device info
        try:
            result = subprocess.run(
                ["termux-telephony-deviceinfo"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                results["device_info"] = json.loads(result.stdout)
        except Exception as e:
            results["errors"].append(f"Device info failed: {e}")
        
        return results
    
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
        Get device telephony information including SIM and network details.
        
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
                info = json.loads(result.stdout)
                # Add extra fields if they are known but missing
                info["available"] = True
                return info
        
        except Exception as e:
            logger.error(f"Failed to get device info: {e}")
        
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
