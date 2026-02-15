"""
Rules Module - Template-based response engine
=============================================

This module provides a rule-based response system that can operate
independently of the LLM, offering:
- Keyword-based matching
- Pattern matching with regex
- Time-based rules
- Context-aware responses
- Template variables
"""

from .engine import RulesEngine, Rule, RuleMatch
from .templates import TemplateManager, Template

__all__ = [
    "RulesEngine",
    "Rule",
    "RuleMatch",
    "TemplateManager",
    "Template",
]
