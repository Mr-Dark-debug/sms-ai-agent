"""
Terminal UI Module - Textual-based TUI
=====================================

This module provides a terminal-based user interface using Textual,
offering a rich, interactive experience in the terminal.
"""

from .app import SMSAgentApp, run_tui

__all__ = [
    "SMSAgentApp",
    "run_tui",
]
