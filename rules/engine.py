"""
Rules Engine - Pattern matching and template-based responses
============================================================

This module implements the core rules engine that matches incoming
messages against patterns and generates appropriate responses.
"""

import re
import yaml
import json
from pathlib import Path
from datetime import datetime, time as dt_time
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
import random


class RulePriority(Enum):
    """Priority levels for rules."""
    LOWEST = 0
    LOW = 25
    NORMAL = 50
    HIGH = 75
    HIGHEST = 100


class MatchType(Enum):
    """Types of pattern matching."""
    EXACT = "exact"           # Exact string match
    CONTAINS = "contains"     # Contains substring
    STARTSWITH = "startswith" # Starts with
    ENDSWITH = "endswith"     # Ends with
    REGEX = "regex"           # Regular expression
    KEYWORDS = "keywords"     # Contains any keywords
    ALL_KEYWORDS = "all_keywords"  # Contains all keywords


@dataclass
class RuleMatch:
    """
    Result of a rule matching a message.
    
    Contains information about which rule matched and any
    captured groups or extracted variables.
    
    Attributes:
        rule (Rule): The matching rule
        message (str): The matched message
        groups (dict): Captured groups from regex
        variables (dict): Extracted variables
        confidence (float): Match confidence (0-1)
    """
    rule: 'Rule'
    message: str
    groups: Dict[str, str] = field(default_factory=dict)
    variables: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    
    def get_response(self) -> str:
        """Generate response from the matched rule."""
        return self.rule.generate_response(self)


@dataclass
class Rule:
    """
    A single rule for matching and responding to messages.
    
    Rules define patterns to match and templates for responses.
    They support multiple match types and can include conditions
    like time-based activation.
    
    Attributes:
        name (str): Unique rule name
        patterns (list): Patterns to match
        match_type (MatchType): How to match patterns
        responses (list): Possible responses
        priority (int): Rule priority (higher = more important)
        enabled (bool): Whether rule is active
        conditions (dict): Additional conditions
    """
    name: str
    patterns: List[str]
    match_type: MatchType = MatchType.CONTAINS
    responses: List[str] = field(default_factory=list)
    priority: int = RulePriority.NORMAL.value
    enabled: bool = True
    conditions: Dict[str, Any] = field(default_factory=dict)
    
    # Optional callback for custom matching
    custom_matcher: Optional[Callable[[str], bool]] = None
    
    def matches(self, message: str, context: Optional[Dict] = None) -> Optional[RuleMatch]:
        """
        Check if this rule matches a message.
        
        Args:
            message: Message to check
            context: Optional context (time, sender, etc.)
            
        Returns:
            RuleMatch if matched, None otherwise
        """
        if not self.enabled:
            return None
        
        # Check conditions
        if not self._check_conditions(context):
            return None
        
        # Try each pattern
        for pattern in self.patterns:
            match = self._match_pattern(pattern, message)
            if match:
                return match
        
        # Try custom matcher
        if self.custom_matcher and self.custom_matcher(message):
            return RuleMatch(rule=self, message=message)
        
        return None
    
    def _match_pattern(self, pattern: str, message: str) -> Optional[RuleMatch]:
        """
        Match a single pattern against a message.
        
        Args:
            pattern: Pattern to match
            message: Message to check
            
        Returns:
            RuleMatch if matched, None otherwise
        """
        message_lower = message.lower()
        pattern_lower = pattern.lower()
        
        if self.match_type == MatchType.EXACT:
            if message_lower == pattern_lower:
                return RuleMatch(rule=self, message=message)
        
        elif self.match_type == MatchType.CONTAINS:
            if pattern_lower in message_lower:
                return RuleMatch(rule=self, message=message)
        
        elif self.match_type == MatchType.STARTSWITH:
            if message_lower.startswith(pattern_lower):
                return RuleMatch(rule=self, message=message)
        
        elif self.match_type == MatchType.ENDSWITH:
            if message_lower.endswith(pattern_lower):
                return RuleMatch(rule=self, message=message)
        
        elif self.match_type == MatchType.REGEX:
            try:
                regex = re.compile(pattern, re.IGNORECASE)
                match = regex.search(message)
                if match:
                    groups = match.groupdict() if match.groupdict() else {}
                    return RuleMatch(
                        rule=self,
                        message=message,
                        groups=groups
                    )
            except re.error:
                pass
        
        elif self.match_type == MatchType.KEYWORDS:
            keywords = [k.lower() for k in pattern.split()]
            if any(kw in message_lower for kw in keywords):
                return RuleMatch(rule=self, message=message)
        
        elif self.match_type == MatchType.ALL_KEYWORDS:
            keywords = [k.lower() for k in pattern.split()]
            if all(kw in message_lower for kw in keywords):
                return RuleMatch(rule=self, message=message)
        
        return None
    
    def _check_conditions(self, context: Optional[Dict]) -> bool:
        """
        Check rule conditions.
        
        Args:
            context: Context dictionary with time, sender, etc.
            
        Returns:
            True if all conditions are satisfied
        """
        if not self.conditions:
            return True
        
        # Time-based conditions
        if "time_start" in self.conditions or "time_end" in self.conditions:
            now = datetime.now().time()
            
            if "time_start" in self.conditions:
                start = self._parse_time(self.conditions["time_start"])
                if start and now < start:
                    return False
            
            if "time_end" in self.conditions:
                end = self._parse_time(self.conditions["time_end"])
                if end and now > end:
                    return False
        
        # Day of week conditions
        if "days" in self.conditions:
            today = datetime.now().strftime("%A").lower()
            allowed_days = [d.lower() for d in self.conditions["days"]]
            if today not in allowed_days:
                return False
        
        # Sender conditions
        if context and "allowed_senders" in self.conditions:
            sender = context.get("sender", "")
            if sender not in self.conditions["allowed_senders"]:
                return False
        
        return True
    
    def _parse_time(self, time_str: str) -> Optional[dt_time]:
        """Parse time string (HH:MM format)."""
        try:
            parts = time_str.split(":")
            return dt_time(int(parts[0]), int(parts[1]))
        except (ValueError, IndexError):
            return None
    
    def generate_response(self, match: RuleMatch) -> str:
        """
        Generate a response for a match.
        
        Args:
            match: The rule match
            
        Returns:
            Generated response string
        """
        if not self.responses:
            return ""
        
        # Select random response
        response = random.choice(self.responses)
        
        # Substitute variables
        response = self._substitute_variables(response, match)
        
        return response
    
    def _substitute_variables(self, template: str, match: RuleMatch) -> str:
        """
        Substitute variables in template.
        
        Supports:
        - {captured_group} - Regex captured groups
        - {date} - Current date
        - {time} - Current time
        - {message} - Original message
        """
        result = template
        
        # Substitute captured groups
        for name, value in match.groups.items():
            result = result.replace(f"{{{name}}}", value)
        
        # Substitute built-in variables
        result = result.replace("{date}", datetime.now().strftime("%Y-%m-%d"))
        result = result.replace("{time}", datetime.now().strftime("%H:%M"))
        result = result.replace("{message}", match.message)
        
        return result
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert rule to dictionary."""
        return {
            "name": self.name,
            "patterns": self.patterns,
            "match_type": self.match_type.value,
            "responses": self.responses,
            "priority": self.priority,
            "enabled": self.enabled,
            "conditions": self.conditions,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Rule':
        """Create rule from dictionary."""
        return cls(
            name=data["name"],
            patterns=data.get("patterns", []),
            match_type=MatchType(data.get("match_type", "contains")),
            responses=data.get("responses", []),
            priority=data.get("priority", RulePriority.NORMAL.value),
            enabled=data.get("enabled", True),
            conditions=data.get("conditions", {}),
        )


class RulesEngine:
    """
    Main rules engine for matching and responding to messages.
    
    Manages a collection of rules and provides methods for
    adding, removing, and evaluating rules.
    
    Example:
        engine = RulesEngine()
        
        # Add a rule
        engine.add_rule(Rule(
            name="greeting",
            patterns=["hello", "hi", "hey"],
            match_type=MatchType.CONTAINS,
            responses=["Hello! How can I help?", "Hi there!"]
        ))
        
        # Match a message
        match = engine.match("Hello there!")
        if match:
            print(match.get_response())
    """
    
    def __init__(self, config_dir: Optional[str] = None):
        """
        Initialize rules engine.
        
        Args:
            config_dir: Directory containing rules configuration
        """
        self.rules: List[Rule] = []
        self.config_dir = Path(config_dir) if config_dir else None
        
        # Load rules from config
        if self.config_dir:
            self._load_rules()
    
    def add_rule(self, rule: Rule) -> None:
        """
        Add a rule to the engine.
        
        Rules are kept sorted by priority (highest first).
        
        Args:
            rule: Rule to add
        """
        self.rules.append(rule)
        self.rules.sort(key=lambda r: r.priority, reverse=True)
    
    def remove_rule(self, name: str) -> bool:
        """
        Remove a rule by name.
        
        Args:
            name: Name of rule to remove
            
        Returns:
            True if rule was removed
        """
        for i, rule in enumerate(self.rules):
            if rule.name == name:
                del self.rules[i]
                return True
        return False
    
    def get_rule(self, name: str) -> Optional[Rule]:
        """
        Get a rule by name.
        
        Args:
            name: Rule name
            
        Returns:
            Rule if found, None otherwise
        """
        for rule in self.rules:
            if rule.name == name:
                return rule
        return None
    
    def match(
        self,
        message: str,
        context: Optional[Dict] = None
    ) -> Optional[RuleMatch]:
        """
        Find the best matching rule for a message.
        
        Iterates through rules in priority order and returns
        the first match found.
        
        Args:
            message: Message to match
            context: Optional context for condition checking
            
        Returns:
            RuleMatch if found, None otherwise
        """
        for rule in self.rules:
            match = rule.matches(message, context)
            if match:
                return match
        return None
    
    def match_all(
        self,
        message: str,
        context: Optional[Dict] = None
    ) -> List[RuleMatch]:
        """
        Find all matching rules for a message.
        
        Args:
            message: Message to match
            context: Optional context
            
        Returns:
            List of all matches
        """
        matches = []
        for rule in self.rules:
            match = rule.matches(message, context)
            if match:
                matches.append(match)
        return matches
    
    def _load_rules(self) -> None:
        """Load rules from configuration directory."""
        rules_file = self.config_dir / "rules.yaml"
        
        if not rules_file.exists():
            self._create_default_rules(rules_file)
            return
        
        try:
            with open(rules_file, "r") as f:
                data = yaml.safe_load(f) or {}
            
            for rule_data in data.get("rules", []):
                rule = Rule.from_dict(rule_data)
                self.add_rule(rule)
        
        except Exception as e:
            print(f"Warning: Failed to load rules: {e}")
    
    def _create_default_rules(self, path: Path) -> None:
        """Create default rules file."""
        default_rules = {
            "rules": [
                {
                    "name": "greeting",
                    "patterns": ["hello", "hi", "hey", "good morning", "good afternoon", "good evening"],
                    "match_type": "contains",
                    "responses": [
                        "Hello! How can I help you today?",
                        "Hi there! What can I do for you?",
                        "Hey! How can I assist you?"
                    ],
                    "priority": 50
                },
                {
                    "name": "thanks",
                    "patterns": ["thank you", "thanks", "thx", "appreciate"],
                    "match_type": "contains",
                    "responses": [
                        "You're welcome!",
                        "Happy to help!",
                        "No problem at all!"
                    ],
                    "priority": 40
                },
                {
                    "name": "goodbye",
                    "patterns": ["bye", "goodbye", "see you", "later", "take care"],
                    "match_type": "contains",
                    "responses": [
                        "Goodbye! Have a great day!",
                        "Take care!",
                        "See you later!"
                    ],
                    "priority": 40
                },
                {
                    "name": "help",
                    "patterns": ["help", "support", "assist"],
                    "match_type": "contains",
                    "responses": [
                        "I'm here to help! What do you need?",
                        "Sure, I'd be happy to assist. What's your question?",
                        "How can I help you today?"
                    ],
                    "priority": 60
                },
                {
                    "name": "status",
                    "patterns": ["status", "how are you", "how's it going"],
                    "match_type": "contains",
                    "responses": [
                        "I'm doing well, thanks for asking!",
                        "All systems running smoothly!",
                        "Everything is working great on my end!"
                    ],
                    "priority": 30
                },
                {
                    "name": "yes",
                    "patterns": ["yes", "yeah", "yep", "sure", "ok", "okay"],
                    "match_type": "exact",
                    "responses": [
                        "Got it!",
                        "Understood!",
                        "Alright!"
                    ],
                    "priority": 20
                },
                {
                    "name": "no",
                    "patterns": ["no", "nope", "nah"],
                    "match_type": "exact",
                    "responses": [
                        "Okay, no problem.",
                        "Understood.",
                        "Got it."
                    ],
                    "priority": 20
                },
                {
                    "name": "question",
                    "patterns": ["\\?$"],
                    "match_type": "regex",
                    "responses": [
                        "That's a good question! Let me think...",
                        "Interesting question! Here's what I think...",
                        "Great question! I'll do my best to help."
                    ],
                    "priority": 10
                }
            ]
        }
        
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, "w") as f:
            yaml.dump(default_rules, f, default_flow_style=False)
        
        # Load the default rules
        for rule_data in default_rules["rules"]:
            self.add_rule(Rule.from_dict(rule_data))
    
    def save_rules(self, path: Optional[Path] = None) -> None:
        """
        Save current rules to file.
        
        Args:
            path: Path to save to (uses config_dir if not specified)
        """
        if path is None:
            path = self.config_dir / "rules.yaml"
        
        data = {
            "rules": [rule.to_dict() for rule in self.rules]
        }
        
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False)
    
    def get_all_rules(self) -> List[Rule]:
        """Get all rules."""
        return self.rules.copy()
    
    def clear_rules(self) -> None:
        """Remove all rules."""
        self.rules.clear()
    
    def enable_rule(self, name: str) -> bool:
        """Enable a rule by name."""
        rule = self.get_rule(name)
        if rule:
            rule.enabled = True
            return True
        return False
    
    def disable_rule(self, name: str) -> bool:
        """Disable a rule by name."""
        rule = self.get_rule(name)
        if rule:
            rule.enabled = False
            return True
        return False
