"""
Database Module - SQLite-based storage for messages, logs, and settings
=======================================================================

This module provides database operations including:
- Message history storage
- Conversation context management
- Settings persistence
- Log storage
- Rate limit tracking
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from contextlib import contextmanager
import threading

from .exceptions import DatabaseError
from .logging import get_logger

logger = get_logger("core.database")


class Database:
    """
    SQLite database manager for SMS AI Agent.
    
    Provides thread-safe database operations with connection pooling
    and automatic schema migration.
    
    Attributes:
        db_path (str): Path to SQLite database file
        lock (threading.Lock): Thread lock for concurrent access
    """
    
    def __init__(self, db_path: str):
        """
        Initialize database connection.
        
        Args:
            db_path: Path to SQLite database file
            
        Raises:
            DatabaseError: If database cannot be initialized
        """
        self.db_path = db_path
        self.lock = threading.Lock()
        self._local = threading.local()
        
        # Ensure database directory exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize schema
        self._init_schema()
    
    def _get_connection(self) -> sqlite3.Connection:
        """
        Get thread-local database connection.
        
        Returns:
            sqlite3.Connection: Database connection for current thread
        """
        if not hasattr(self._local, "connection") or self._local.connection is None:
            self._local.connection = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                timeout=30.0
            )
            self._local.connection.row_factory = sqlite3.Row
            # Enable foreign keys
            self._local.connection.execute("PRAGMA foreign_keys = ON")
            # Enable WAL mode for better concurrent access
            self._local.connection.execute("PRAGMA journal_mode = WAL")
        return self._local.connection
    
    @contextmanager
    def transaction(self):
        """
        Context manager for database transactions.
        
        Provides automatic commit on success and rollback on error.
        
        Yields:
            sqlite3.Connection: Database connection
            
        Example:
            with db.transaction() as conn:
                conn.execute("INSERT INTO messages ...")
        """
        conn = self._get_connection()
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise DatabaseError(f"Transaction failed: {e}")
    
    def _init_schema(self) -> None:
        """
        Initialize database schema.
        
        Creates all necessary tables if they don't exist.
        
        Raises:
            DatabaseError: If schema creation fails
        """
        schema_sql = """
        -- Messages table: stores all incoming and outgoing SMS messages
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            direction TEXT NOT NULL CHECK (direction IN ('incoming', 'outgoing')),
            phone_number TEXT NOT NULL,
            message TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'sent', 'failed', 'delivered')),
            responded INTEGER DEFAULT 0, -- 0 for false, 1 for true
            response_to INTEGER,
            metadata TEXT,
            FOREIGN KEY (response_to) REFERENCES messages(id) ON DELETE SET NULL
        );
        
        -- Conversations table: groups messages by contact
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone_number TEXT NOT NULL UNIQUE,
            last_message_at DATETIME,
            message_count INTEGER DEFAULT 0,
            is_blocked INTEGER DEFAULT 0,
            notes TEXT
        );
        
        -- Rate limits table: tracks rate limit counters
        CREATE TABLE IF NOT EXISTS rate_limits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone_number TEXT NOT NULL,
            window_start DATETIME NOT NULL,
            window_type TEXT NOT NULL CHECK (window_type IN ('minute', 'hour', 'day', 'burst')),
            count INTEGER DEFAULT 1,
            last_message_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(phone_number, window_type, window_start)
        );
        
        -- LLM logs table: stores LLM request/response logs
        CREATE TABLE IF NOT EXISTS llm_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id TEXT,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt TEXT NOT NULL,
            response TEXT,
            tokens_used INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            latency_ms INTEGER,
            status TEXT DEFAULT 'success',
            error_message TEXT,
            metadata TEXT
        );
        
        -- Settings table: stores application settings
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        
        -- Contacts table: stores per-number personality and instructions
        CREATE TABLE IF NOT EXISTS contacts (
            phone_number TEXT PRIMARY KEY,
            name TEXT,
            relation TEXT,
            age INTEGER,
            custom_prompt TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        
        -- Guardrail logs table: stores guardrail violations
        CREATE TABLE IF NOT EXISTS guardrail_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone_number TEXT,
            original_response TEXT NOT NULL,
            violation_type TEXT NOT NULL,
            action_taken TEXT NOT NULL,
            final_response TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        
        -- Indexes for common queries
        CREATE INDEX IF NOT EXISTS idx_messages_phone ON messages(phone_number);
        CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);
        CREATE INDEX IF NOT EXISTS idx_messages_direction ON messages(direction);
        CREATE INDEX IF NOT EXISTS idx_conversations_phone ON conversations(phone_number);
        CREATE INDEX IF NOT EXISTS idx_rate_limits_window ON rate_limits(phone_number, window_type, window_start);
        CREATE INDEX IF NOT EXISTS idx_llm_logs_timestamp ON llm_logs(timestamp);
        """
        
        try:
            with self.transaction() as conn:
                conn.executescript(schema_sql)
            # Run migrations for existing databases
            self._run_migrations()
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to initialize database schema: {e}")
            
    def _run_migrations(self) -> None:
        """Run database migrations to ensure schema is up to date."""
        try:
            with self.transaction() as conn:
                # Check if 'responded' column exists in 'messages' table
                cursor = conn.execute("PRAGMA table_info(messages)")
                columns = [row["name"] for row in cursor.fetchall()]
                
                if "responded" not in columns:
                    logger.info("Migrating: Adding 'responded' column to messages table")
                    conn.execute("ALTER TABLE messages ADD COLUMN responded INTEGER DEFAULT 0")
                
                # Check for other potential missing columns or tables
                # Contacts table is already in schema_sql so CREATE TABLE IF NOT EXISTS handles it,
                # but if we added columns to it later we'd check here.
        except Exception as e:
            logger.error(f"Migration failed: {e}")
    
    # === Message Operations ===
    
    def add_message(
        self,
        direction: str,
        phone_number: str,
        message: str,
        status: str = "pending",
        response_to: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        Add a new message to the database.
        
        Args:
            direction: 'incoming' or 'outgoing'
            phone_number: Sender/recipient phone number
            message: Message content
            status: Message status
            response_to: ID of message this is responding to
            metadata: Optional metadata dictionary
            
        Returns:
            int: ID of inserted message
            
        Raises:
            DatabaseError: If insertion fails
        """
        try:
            with self.transaction() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO messages (direction, phone_number, message, status, response_to, metadata)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        direction,
                        phone_number,
                        message,
                        status,
                        response_to,
                        json.dumps(metadata) if metadata else None
                    )
                )
                
                message_id = cursor.lastrowid
                
                # If this is an outgoing response, mark the original message as responded
                if direction == "outgoing" and response_to:
                    conn.execute(
                        "UPDATE messages SET responded = 1 WHERE id = ?",
                        (response_to,)
                    )
                
                # Update conversation stats
                conn.execute(
                    """
                    INSERT INTO conversations (phone_number, last_message_at, message_count)
                    VALUES (?, CURRENT_TIMESTAMP, 1)
                    ON CONFLICT(phone_number) DO UPDATE SET
                        last_message_at = CURRENT_TIMESTAMP,
                        message_count = message_count + 1
                    """,
                    (phone_number,)
                )
                
                return message_id
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to add message: {e}")
    
    def get_messages(
        self,
        phone_number: Optional[str] = None,
        direction: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        order_desc: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Retrieve messages from the database.
        
        Args:
            phone_number: Filter by phone number (optional)
            direction: Filter by direction (optional)
            limit: Maximum number of messages to return
            offset: Number of messages to skip
            order_desc: Order by timestamp descending if True
            
        Returns:
            List of message dictionaries
        """
        query = "SELECT * FROM messages WHERE 1=1"
        params = []
        
        if phone_number:
            query += " AND phone_number = ?"
            params.append(phone_number)
        
        if direction:
            query += " AND direction = ?"
            params.append(direction)
        
        order = "DESC" if order_desc else "ASC"
        query += f" ORDER BY timestamp {order} LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        try:
            with self.transaction() as conn:
                cursor = conn.execute(query, params)
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to get messages: {e}")
    
    def get_conversation_context(
        self,
        phone_number: str,
        max_messages: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Get conversation context for a phone number.
        
        Retrieves recent messages for building conversation context
        in LLM prompts.
        
        Args:
            phone_number: Phone number to get context for
            max_messages: Maximum number of messages to return
            
        Returns:
            List of message dictionaries ordered chronologically
        """
        try:
            with self.transaction() as conn:
                cursor = conn.execute(
                    """
                    SELECT direction, message, timestamp
                    FROM messages
                    WHERE phone_number = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (phone_number, max_messages)
                )
                rows = cursor.fetchall()
                # Return in chronological order
                return [dict(row) for row in reversed(rows)]
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to get conversation context: {e}")
    
    def update_message_status(self, message_id: int, status: str) -> None:
        """
        Update the status of a message.
        
        Args:
            message_id: ID of message to update
            status: New status value
            
        Raises:
            DatabaseError: If update fails
        """
        try:
            with self.transaction() as conn:
                conn.execute(
                    "UPDATE messages SET status = ? WHERE id = ?",
                    (status, message_id)
                )
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to update message status: {e}")
            
    def was_message_responded(self, phone_number: str, message_content: str) -> bool:
        """
        Check if a specific message from a number has already been responded to.
        Used for idempotency during polling.
        """
        try:
            with self.transaction() as conn:
                cursor = conn.execute(
                    """
                    SELECT id FROM messages 
                    WHERE phone_number = ? AND message = ? AND responded = 1
                    LIMIT 1
                    """,
                    (phone_number, message_content)
                )
                return cursor.fetchone() is not None
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to check response status: {e}")
    
    def _update_conversation(self, conn: sqlite3.Connection, phone_number: str) -> None:
        """
        Update conversation statistics for a phone number.
        
        Args:
            conn: Database connection
            phone_number: Phone number to update
        """
        conn.execute(
            """
            INSERT INTO conversations (phone_number, last_message_at, message_count)
            VALUES (?, CURRENT_TIMESTAMP, 1)
            ON CONFLICT(phone_number) DO UPDATE SET
                last_message_at = CURRENT_TIMESTAMP,
                message_count = message_count + 1
            """,
            (phone_number,)
        )
    
    def get_conversations(self) -> List[Dict[str, Any]]:
        """
        Get all conversations ordered by last message.
        
        Returns:
            List of conversation dictionaries
        """
        try:
            with self.transaction() as conn:
                cursor = conn.execute(
                    """
                    SELECT c.*, 
                           (SELECT message FROM messages WHERE phone_number = c.phone_number ORDER BY timestamp DESC LIMIT 1) as last_message,
                           (SELECT direction FROM messages WHERE phone_number = c.phone_number ORDER BY timestamp DESC LIMIT 1) as last_direction
                    FROM conversations c
                    ORDER BY last_message_at DESC
                    """
                )
                return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to get conversations: {e}")
    
    # === Rate Limit Operations ===
    
    def check_rate_limit(
        self,
        phone_number: str,
        window_type: str,
        limit: int,
        window_seconds: int
    ) -> tuple[bool, int]:
        """
        Check if rate limit is exceeded for a phone number.
        
        Args:
            phone_number: Phone number to check
            window_type: Type of rate limit window
            limit: Maximum allowed messages
            window_seconds: Window duration in seconds
            
        Returns:
            Tuple of (is_allowed, current_count)
        """
        try:
            with self.transaction() as conn:
                # Clean up old entries
                conn.execute(
                    """
                    DELETE FROM rate_limits
                    WHERE phone_number = ?
                    AND window_type = ?
                    AND datetime(window_start) < datetime('now', ? || ' seconds')
                    """,
                    (phone_number, window_type, f"-{window_seconds}")
                )
                
                # Get current count
                cursor = conn.execute(
                    """
                    SELECT COALESCE(SUM(count), 0) as total
                    FROM rate_limits
                    WHERE phone_number = ? AND window_type = ?
                    """,
                    (phone_number, window_type)
                )
                row = cursor.fetchone()
                current_count = row["total"] if row else 0
                
                return current_count < limit, current_count
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to check rate limit: {e}")
    
    def increment_rate_limit(self, phone_number: str, window_type: str) -> None:
        """
        Increment rate limit counter for a phone number.
        
        Args:
            phone_number: Phone number to increment
            window_type: Type of rate limit window
        """
        try:
            with self.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO rate_limits (phone_number, window_type, window_start, count)
                    VALUES (?, ?, datetime('now'), 1)
                    ON CONFLICT(phone_number, window_type, window_start) DO UPDATE SET
                        count = count + 1,
                        last_message_at = CURRENT_TIMESTAMP
                    """,
                    (phone_number, window_type)
                )
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to increment rate limit: {e}")
    
    # === LLM Log Operations ===
    
    def log_llm_request(
        self,
        provider: str,
        model: str,
        prompt: str,
        response: Optional[str] = None,
        tokens_used: Optional[int] = None,
        latency_ms: Optional[int] = None,
        status: str = "success",
        error_message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        Log an LLM request and response.
        
        Args:
            provider: LLM provider name
            model: Model identifier
            prompt: Input prompt
            response: Generated response
            tokens_used: Number of tokens used
            latency_ms: Request latency in milliseconds
            status: Request status
            error_message: Error message if failed
            metadata: Additional metadata
            
        Returns:
            int: Log entry ID
        """
        try:
            with self.transaction() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO llm_logs (
                        provider, model, prompt, response, tokens_used,
                        latency_ms, status, error_message, metadata
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        provider,
                        model,
                        prompt,
                        response,
                        tokens_used,
                        latency_ms,
                        status,
                        error_message,
                        json.dumps(metadata) if metadata else None
                    )
                )
                return cursor.lastrowid
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to log LLM request: {e}")
    
    def get_llm_logs(
        self,
        limit: int = 100,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieve LLM logs.
        
        Args:
            limit: Maximum number of logs to return
            status: Filter by status (optional)
            
        Returns:
            List of log entries
        """
        query = "SELECT * FROM llm_logs WHERE 1=1"
        params = []
        
        if status:
            query += " AND status = ?"
            params.append(status)
        
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        try:
            with self.transaction() as conn:
                cursor = conn.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to get LLM logs: {e}")
    
    # === Settings Operations ===
    
    def get_setting(self, key: str, default: Any = None) -> Any:
        """
        Get a setting value.
        
        Args:
            key: Setting key
            default: Default value if not found
            
        Returns:
            Setting value or default
        """
        try:
            with self.transaction() as conn:
                cursor = conn.execute(
                    "SELECT value FROM settings WHERE key = ?",
                    (key,)
                )
                row = cursor.fetchone()
                if row:
                    try:
                        return json.loads(row["value"])
                    except json.JSONDecodeError:
                        return row["value"]
                return default
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to get setting: {e}")
    
    def set_setting(self, key: str, value: Any) -> None:
        """
        Set a setting value.
        
        Args:
            key: Setting key
            value: Setting value (will be JSON-serialized if not a string)
        """
        try:
            with self.transaction() as conn:
                serialized = json.dumps(value) if not isinstance(value, str) else value
                conn.execute(
                    """
                    INSERT INTO settings (key, value, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (key, serialized)
                )
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to set setting: {e}")
    
    # === Contact Operations ===
    
    def upsert_contact(
        self,
        phone_number: str,
        name: Optional[str] = None,
        relation: Optional[str] = None,
        age: Optional[int] = None,
        custom_prompt: Optional[str] = None
    ) -> None:
        """
        Add or update contact information.
        """
        try:
            with self.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO contacts (phone_number, name, relation, age, custom_prompt, updated_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(phone_number) DO UPDATE SET
                        name = COALESCE(excluded.name, name),
                        relation = COALESCE(excluded.relation, relation),
                        age = COALESCE(excluded.age, age),
                        custom_prompt = COALESCE(excluded.custom_prompt, custom_prompt),
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (phone_number, name, relation, age, custom_prompt)
                )
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to upsert contact: {e}")
            
    def get_contact(self, phone_number: str) -> Optional[Dict[str, Any]]:
        """Get contact info for a phone number."""
        try:
            with self.transaction() as conn:
                cursor = conn.execute(
                    "SELECT * FROM contacts WHERE phone_number = ?",
                    (phone_number,)
                )
                row = cursor.fetchone()
                return dict(row) if row else None
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to get contact: {e}")
    
    # === Guardrail Log Operations ===
    
    def log_guardrail_violation(
        self,
        phone_number: str,
        original_response: str,
        violation_type: str,
        action_taken: str,
        final_response: Optional[str] = None
    ) -> int:
        """
        Log a guardrail violation.
        
        Args:
            phone_number: Phone number that triggered violation
            original_response: Original AI response
            violation_type: Type of violation detected
            action_taken: Action taken (blocked, modified, etc.)
            final_response: Final response after action
            
        Returns:
            int: Log entry ID
        """
        try:
            with self.transaction() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO guardrail_logs (
                        phone_number, original_response, violation_type,
                        action_taken, final_response
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (phone_number, original_response, violation_type, action_taken, final_response)
                )
                return cursor.lastrowid
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to log guardrail violation: {e}")
    
    def get_guardrail_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Retrieve guardrail violation logs.
        
        Args:
            limit: Maximum number of logs to return
            
        Returns:
            List of violation logs
        """
        try:
            with self.transaction() as conn:
                cursor = conn.execute(
                    "SELECT * FROM guardrail_logs ORDER BY timestamp DESC LIMIT ?",
                    (limit,)
                )
                return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to get guardrail logs: {e}")
    
    # === Statistics ===
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get database statistics.
        
        Returns:
            Dictionary with various statistics
        """
        try:
            with self.transaction() as conn:
                stats = {}
                
                # Message counts
                cursor = conn.execute(
                    "SELECT direction, COUNT(*) as count FROM messages GROUP BY direction"
                )
                stats["messages"] = {row["direction"]: row["count"] for row in cursor.fetchall()}
                
                # Conversation count
                cursor = conn.execute("SELECT COUNT(*) as count FROM conversations")
                stats["conversations"] = cursor.fetchone()["count"]
                
                # LLM request stats
                cursor = conn.execute(
                    """
                    SELECT status, COUNT(*) as count
                    FROM llm_logs
                    GROUP BY status
                    """
                )
                stats["llm_requests"] = {row["status"]: row["count"] for row in cursor.fetchall()}
                
                # Guardrail violations
                cursor = conn.execute("SELECT COUNT(*) as count FROM guardrail_logs")
                stats["guardrail_violations"] = cursor.fetchone()["count"]
                
                return stats
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to get statistics: {e}")
    
    def close(self) -> None:
        """Close database connection for current thread."""
        if hasattr(self._local, "connection") and self._local.connection:
            self._local.connection.close()
            self._local.connection = None
    
    def vacuum(self) -> None:
        """Run VACUUM to optimize database and reclaim space."""
        try:
            conn = self._get_connection()
            conn.execute("VACUUM")
        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to vacuum database: {e}")


def init_database(db_path: str) -> Database:
    """
    Initialize and return a database instance.
    
    This is the preferred way to create a database instance.
    
    Args:
        db_path: Path to SQLite database file
        
    Returns:
        Database instance
    """
    return Database(db_path)
