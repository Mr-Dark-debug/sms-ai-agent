"""
Web UI Module - FastAPI-based web interface
===========================================

This module provides a web-based user interface for managing
the SMS AI Agent, including:
- Dashboard with statistics
- Settings management
- Message log viewer
- Rule editor
- Test message simulator
"""

from .app import create_app, run_app
from .routes import router

__all__ = [
    "create_app",
    "run_app",
    "router",
]
