"""
Test Rules Engine Module
=======================

Unit tests for the rules engine and pattern matching.
"""

import pytest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from rules.engine import RulesEngine, Rule, RuleMatch, MatchType, RulePriority


class TestRule:
    """Tests for Rule class."""
    
    def test_exact_match(self):
        """Test exact string matching."""
        rule = Rule(
            name="test",
            patterns=["hello"],
            match_type=MatchType.EXACT,
            responses=["Hi!"]
        )
        
        match = rule.matches("hello")
        assert match is not None
        assert match.get_response() == "Hi!"
        
        match = rule.matches("hello world")
        assert match is None
    
    def test_contains_match(self):
        """Test contains matching."""
        rule = Rule(
            name="test",
            patterns=["hello"],
            match_type=MatchType.CONTAINS,
            responses=["Hi!"]
        )
        
        match = rule.matches("hello world")
        assert match is not None
        
        match = rule.matches("say hello please")
        assert match is not None
    
    def test_regex_match(self):
        """Test regex matching."""
        rule = Rule(
            name="test",
            patterns=[r"\d{3}-\d{4}"],
            match_type=MatchType.REGEX,
            responses=["Got a phone pattern!"]
        )
        
        match = rule.matches("Call 555-1234 now")
        assert match is not None
    
    def test_keywords_match(self):
        """Test keywords matching."""
        rule = Rule(
            name="test",
            patterns=["help support assist"],
            match_type=MatchType.KEYWORDS,
            responses=["How can I help?"]
        )
        
        match = rule.matches("I need help")
        assert match is not None
        
        match = rule.matches("support team")
        assert match is not None
    
    def test_disabled_rule(self):
        """Test disabled rules don't match."""
        rule = Rule(
            name="test",
            patterns=["hello"],
            match_type=MatchType.CONTAINS,
            responses=["Hi!"],
            enabled=False
        )
        
        match = rule.matches("hello")
        assert match is None
    
    def test_priority(self):
        """Test rule priority."""
        rule1 = Rule(name="low", patterns=["test"], priority=10, responses=["Low"])
        rule2 = Rule(name="high", patterns=["test"], priority=90, responses=["High"])
        
        assert rule2.priority > rule1.priority


class TestRulesEngine:
    """Tests for RulesEngine class."""
    
    def test_add_rule(self):
        """Test adding rules."""
        engine = RulesEngine()
        rule = Rule(name="test", patterns=["hello"], responses=["Hi!"])
        
        engine.add_rule(rule)
        
        assert len(engine.rules) == 1
        assert engine.get_rule("test") is not None
    
    def test_remove_rule(self):
        """Test removing rules."""
        engine = RulesEngine()
        rule = Rule(name="test", patterns=["hello"], responses=["Hi!"])
        
        engine.add_rule(rule)
        engine.remove_rule("test")
        
        assert len(engine.rules) == 0
    
    def test_match_priority(self):
        """Test that higher priority rules match first."""
        engine = RulesEngine()
        
        engine.add_rule(Rule(name="low", patterns=["test"], priority=10, responses=["Low"]))
        engine.add_rule(Rule(name="high", patterns=["test"], priority=90, responses=["High"]))
        
        match = engine.match("test")
        
        assert match.rule.name == "high"
    
    def test_match_all(self):
        """Test getting all matches."""
        engine = RulesEngine()
        
        engine.add_rule(Rule(name="rule1", patterns=["test"], responses=["1"]))
        engine.add_rule(Rule(name="rule2", patterns=["test"], responses=["2"]))
        
        matches = engine.match_all("test")
        
        assert len(matches) == 2


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
