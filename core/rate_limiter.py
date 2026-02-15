"""
Rate Limiter Module - Rate limiting and abuse prevention
========================================================

This module provides rate limiting functionality including:
- Token bucket algorithm
- Sliding window rate limiting
- Per-recipient limits
- Global rate limits
- Burst handling
"""

import time
import threading
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from dataclasses import dataclass, field

from .exceptions import RateLimitError
from .logging import get_logger

logger = get_logger("rate_limiter")


@dataclass
class RateLimitResult:
    """
    Result of a rate limit check.
    
    Attributes:
        allowed (bool): Whether the request is allowed
        remaining (int): Number of requests remaining in window
        reset_at (float): Unix timestamp when limit resets
        retry_after (float): Seconds to wait before retry (if blocked)
    """
    allowed: bool
    remaining: int
    reset_at: float
    retry_after: float = 0.0


class TokenBucket:
    """
    Token bucket rate limiter implementation.
    
    Provides smooth rate limiting with burst support using the
    token bucket algorithm. Tokens are added at a fixed rate
    up to a maximum capacity.
    
    Attributes:
        capacity (int): Maximum number of tokens
        refill_rate (float): Tokens added per second
        tokens (float): Current number of tokens
        last_refill (float): Last refill timestamp
    """
    
    def __init__(self, capacity: int, refill_rate: float):
        """
        Initialize token bucket.
        
        Args:
            capacity: Maximum number of tokens (burst size)
            refill_rate: Tokens added per second
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = float(capacity)
        self.last_refill = time.time()
        self.lock = threading.Lock()
    
    def consume(self, tokens: int = 1) -> Tuple[bool, float]:
        """
        Try to consume tokens from the bucket.
        
        Args:
            tokens: Number of tokens to consume
            
        Returns:
            Tuple of (success, wait_time) where wait_time is
            seconds to wait if unsuccessful
        """
        with self.lock:
            self._refill()
            
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True, 0.0
            else:
                # Calculate wait time
                needed = tokens - self.tokens
                wait_time = needed / self.refill_rate
                return False, wait_time
    
    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_refill
        self.tokens = min(
            self.capacity,
            self.tokens + elapsed * self.refill_rate
        )
        self.last_refill = now
    
    def get_state(self) -> Tuple[float, float]:
        """
        Get current bucket state.
        
        Returns:
            Tuple of (current_tokens, last_refill_time)
        """
        with self.lock:
            self._refill()
            return self.tokens, self.last_refill


class SlidingWindowCounter:
    """
    Sliding window rate limiter implementation.
    
    Tracks requests within a sliding time window for accurate
    rate limiting without burst effects.
    
    Attributes:
        window_seconds (int): Window duration in seconds
        max_requests (int): Maximum requests per window
    """
    
    def __init__(self, window_seconds: int, max_requests: int):
        """
        Initialize sliding window counter.
        
        Args:
            window_seconds: Window duration in seconds
            max_requests: Maximum requests allowed per window
        """
        self.window_seconds = window_seconds
        self.max_requests = max_requests
        self.requests: Dict[float, int] = {}
        self.lock = threading.Lock()
    
    def record(self, count: int = 1) -> Tuple[int, float]:
        """
        Record a request and get current count.
        
        Args:
            count: Number of requests to record
            
        Returns:
            Tuple of (current_count, window_reset_time)
        """
        with self.lock:
            now = time.time()
            window_start = now - self.window_seconds
            
            # Clean old entries
            self.requests = {
                ts: cnt for ts, cnt in self.requests.items()
                if ts > window_start
            }
            
            # Add new request
            self.requests[now] = self.requests.get(now, 0) + count
            
            # Calculate total
            total = sum(self.requests.values())
            
            # Calculate reset time
            oldest = min(self.requests.keys()) if self.requests else now
            reset_at = oldest + self.window_seconds
            
            return total, reset_at
    
    def get_count(self) -> int:
        """
        Get current request count without recording.
        
        Returns:
            Current number of requests in window
        """
        with self.lock:
            now = time.time()
            window_start = now - self.window_seconds
            
            # Clean old entries
            self.requests = {
                ts: cnt for ts, cnt in self.requests.items()
                if ts > window_start
            }
            
            return sum(self.requests.values())


@dataclass
class RecipientLimits:
    """
    Rate limits for a single recipient.
    
    Tracks multiple rate limit windows per recipient including
    hourly, daily, and burst limits.
    """
    phone_number: str
    hourly: SlidingWindowCounter = field(default=None)
    daily: SlidingWindowCounter = field(default=None)
    burst: TokenBucket = field(default=None)
    last_message_time: float = 0.0
    
    def __post_init__(self):
        """Initialize rate limiters with defaults."""
        if self.hourly is None:
            self.hourly = SlidingWindowCounter(3600, 5)
        if self.daily is None:
            self.daily = SlidingWindowCounter(86400, 20)
        if self.burst is None:
            self.burst = TokenBucket(3, 0.05)  # 3 bursts, 1 per 20 seconds


class RateLimiter:
    """
    Comprehensive rate limiter for SMS AI Agent.
    
    Provides multiple layers of rate limiting:
    - Global rate limit (total messages per minute)
    - Per-recipient limits (hourly, daily)
    - Burst protection
    - Minimum interval between messages
    
    Thread-safe and suitable for production use.
    
    Example:
        limiter = RateLimiter(
            max_per_minute=10,
            max_per_recipient_per_hour=5,
            min_interval_seconds=5.0
        )
        
        if limiter.check("phone_number"):
            limiter.record("phone_number")
            # Send message
        else:
            # Handle rate limit
    """
    
    def __init__(
        self,
        max_per_minute: int = 10,
        max_per_recipient_per_hour: int = 5,
        max_per_recipient_per_day: int = 20,
        min_interval_seconds: float = 5.0,
        burst_allowance: int = 3,
        burst_window_seconds: int = 60
    ):
        """
        Initialize rate limiter.
        
        Args:
            max_per_minute: Global messages per minute limit
            max_per_recipient_per_hour: Per-recipient hourly limit
            max_per_recipient_per_day: Per-recipient daily limit
            min_interval_seconds: Minimum seconds between messages
            burst_allowance: Number of burst messages allowed
            burst_window_seconds: Burst window duration
        """
        self.max_per_minute = max_per_minute
        self.max_per_recipient_per_hour = max_per_recipient_per_hour
        self.max_per_recipient_per_day = max_per_recipient_per_day
        self.min_interval_seconds = min_interval_seconds
        
        # Global rate limiter
        self.global_limiter = TokenBucket(
            capacity=max_per_minute,
            refill_rate=max_per_minute / 60.0
        )
        
        # Per-recipient limiters
        self.recipient_limiters: Dict[str, RecipientLimits] = {}
        self.recipients_lock = threading.Lock()
        
        # Last message times (for minimum interval)
        self.last_message_times: Dict[str, float] = {}
        self.last_message_lock = threading.Lock()
        
        logger.info(
            "Rate limiter initialized",
            extra={
                "max_per_minute": max_per_minute,
                "max_per_recipient_per_hour": max_per_recipient_per_hour,
                "min_interval": min_interval_seconds
            }
        )
    
    def check(self, phone_number: str) -> RateLimitResult:
        """
        Check if a message can be sent to a phone number.
        
        Performs all rate limit checks without recording the message.
        
        Args:
            phone_number: Recipient phone number
            
        Returns:
            RateLimitResult with check outcome
        """
        # Check minimum interval
        with self.last_message_lock:
            last_time = self.last_message_times.get(phone_number, 0)
            time_since_last = time.time() - last_time
            
            if time_since_last < self.min_interval_seconds:
                retry_after = self.min_interval_seconds - time_since_last
                logger.debug(
                    f"Minimum interval not met for {phone_number}",
                    extra={"retry_after": retry_after}
                )
                return RateLimitResult(
                    allowed=False,
                    remaining=0,
                    reset_at=time.time() + retry_after,
                    retry_after=retry_after
                )
        
        # Check global rate limit
        global_ok, global_wait = self.global_limiter.consume(0)  # Just check
        if not global_ok:
            logger.warning(f"Global rate limit exceeded, wait {global_wait:.1f}s")
            return RateLimitResult(
                allowed=False,
                remaining=0,
                reset_at=time.time() + global_wait,
                retry_after=global_wait
            )
        
        # Check per-recipient limits
        with self.recipients_lock:
            if phone_number not in self.recipient_limiters:
                self.recipient_limiters[phone_number] = RecipientLimits(phone_number)
            
            limits = self.recipient_limiters[phone_number]
        
        # Check hourly limit
        hourly_count, hourly_reset = limits.hourly.record(0)  # Just check
        if hourly_count >= self.max_per_recipient_per_hour:
            retry_after = hourly_reset - time.time()
            logger.warning(
                f"Hourly limit exceeded for {phone_number}",
                extra={"count": hourly_count, "limit": self.max_per_recipient_per_hour}
            )
            return RateLimitResult(
                allowed=False,
                remaining=0,
                reset_at=hourly_reset,
                retry_after=max(0, retry_after)
            )
        
        # Check daily limit
        daily_count, daily_reset = limits.daily.record(0)  # Just check
        if daily_count >= self.max_per_recipient_per_day:
            retry_after = daily_reset - time.time()
            logger.warning(
                f"Daily limit exceeded for {phone_number}",
                extra={"count": daily_count, "limit": self.max_per_recipient_per_day}
            )
            return RateLimitResult(
                allowed=False,
                remaining=0,
                reset_at=daily_reset,
                retry_after=max(0, retry_after)
            )
        
        # Check burst limit
        burst_ok, burst_wait = limits.burst.consume(0)  # Just check
        if not burst_ok:
            logger.debug(f"Burst limit hit for {phone_number}")
            return RateLimitResult(
                allowed=False,
                remaining=0,
                reset_at=time.time() + burst_wait,
                retry_after=burst_wait
            )
        
        # Calculate remaining
        remaining = min(
            self.max_per_minute - int(self.global_limiter.get_state()[0]),
            self.max_per_recipient_per_hour - hourly_count,
            self.max_per_recipient_per_day - daily_count
        )
        
        return RateLimitResult(
            allowed=True,
            remaining=max(0, remaining),
            reset_at=time.time() + 60  # Approximate reset
        )
    
    def record(self, phone_number: str) -> None:
        """
        Record that a message was sent to a phone number.
        
        Should be called after a message is successfully sent.
        
        Args:
            phone_number: Recipient phone number
        """
        now = time.time()
        
        # Record in global limiter
        self.global_limiter.consume(1)
        
        # Record in recipient limiters
        with self.recipients_lock:
            if phone_number not in self.recipient_limiters:
                self.recipient_limiters[phone_number] = RecipientLimits(phone_number)
            
            limits = self.recipient_limiters[phone_number]
            limits.hourly.record(1)
            limits.daily.record(1)
            limits.burst.consume(1)
            limits.last_message_time = now
        
        # Update last message time
        with self.last_message_lock:
            self.last_message_times[phone_number] = now
        
        logger.debug(f"Recorded message to {phone_number}")
    
    def check_and_record(self, phone_number: str) -> RateLimitResult:
        """
        Check rate limit and record if allowed.
        
        Convenience method that combines check and record.
        
        Args:
            phone_number: Recipient phone number
            
        Returns:
            RateLimitResult with check outcome
        """
        result = self.check(phone_number)
        
        if result.allowed:
            self.record(phone_number)
        
        return result
    
    def wait_if_needed(self, phone_number: str, timeout: float = 60.0) -> bool:
        """
        Wait if rate limited, up to timeout seconds.
        
        Args:
            phone_number: Recipient phone number
            timeout: Maximum seconds to wait
            
        Returns:
            True if can proceed, False if timed out
        """
        start = time.time()
        
        while True:
            result = self.check(phone_number)
            
            if result.allowed:
                return True
            
            if time.time() - start >= timeout:
                return False
            
            if result.retry_after > 0:
                wait_time = min(result.retry_after, timeout - (time.time() - start))
                time.sleep(wait_time)
    
    def get_status(self, phone_number: str) -> Dict:
        """
        Get rate limit status for a phone number.
        
        Args:
            phone_number: Recipient phone number
            
        Returns:
            Dictionary with rate limit status information
        """
        with self.recipients_lock:
            if phone_number in self.recipient_limiters:
                limits = self.recipient_limiters[phone_number]
                hourly_count = limits.hourly.get_count()
                daily_count = limits.daily.get_count()
                tokens, _ = limits.burst.get_state()
            else:
                hourly_count = 0
                daily_count = 0
                tokens = 3
        
        global_tokens, _ = self.global_limiter.get_state()
        
        return {
            "phone_number": phone_number,
            "global_remaining": int(global_tokens),
            "hourly_count": hourly_count,
            "hourly_limit": self.max_per_recipient_per_hour,
            "daily_count": daily_count,
            "daily_limit": self.max_per_recipient_per_day,
            "burst_tokens": int(tokens),
            "burst_limit": 3,
        }
    
    def reset(self, phone_number: Optional[str] = None) -> None:
        """
        Reset rate limits for a phone number or all.
        
        Args:
            phone_number: Specific phone number, or None for all
        """
        if phone_number:
            with self.recipients_lock:
                if phone_number in self.recipient_limiters:
                    del self.recipient_limiters[phone_number]
            
            with self.last_message_lock:
                if phone_number in self.last_message_times:
                    del self.last_message_times[phone_number]
            
            logger.info(f"Reset rate limits for {phone_number}")
        else:
            with self.recipients_lock:
                self.recipient_limiters.clear()
            
            with self.last_message_lock:
                self.last_message_times.clear()
            
            self.global_limiter.tokens = float(self.global_limiter.capacity)
            
            logger.info("Reset all rate limits")
    
    def cleanup_old_recipients(self, max_age_hours: int = 24) -> int:
        """
        Remove old recipient entries to free memory.
        
        Args:
            max_age_hours: Maximum age in hours
            
        Returns:
            Number of entries removed
        """
        cutoff = time.time() - max_age_hours * 3600
        removed = 0
        
        with self.recipients_lock:
            to_remove = [
                phone for phone, limits in self.recipient_limiters.items()
                if limits.last_message_time < cutoff
            ]
            
            for phone in to_remove:
                del self.recipient_limiters[phone]
                removed += 1
        
        if removed > 0:
            logger.info(f"Cleaned up {removed} old recipient entries")
        
        return removed
