"""
Template Manager - Variable substitution and template processing
==============================================================

This module provides template processing for responses including
variable substitution, conditional blocks, and formatting.
"""

import re
from datetime import datetime
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
import random


@dataclass
class Template:
    """
    A response template with variable substitution support.
    
    Templates support various placeholder types:
    - Simple: {variable}
    - Default: {variable:default}
    - Format: {variable:%Y-%m-%d} for dates
    - Random: {random:option1|option2|option3}
    
    Attributes:
        content (str): Template content with placeholders
        name (str): Optional template name
    """
    content: str
    name: str = ""
    
    def render(self, context: Optional[Dict[str, Any]] = None) -> str:
        """
        Render the template with context variables.
        
        Args:
            context: Dictionary of variable values
            
        Returns:
            Rendered string
        """
        context = context or {}
        result = self.content
        
        # Process simple substitutions
        result = self._process_simple_vars(result, context)
        
        # Process default values
        result = self._process_defaults(result, context)
        
        # Process date formatting
        result = self._process_dates(result, context)
        
        # Process random selections
        result = self._process_random(result)
        
        # Process conditionals
        result = self._process_conditionals(result, context)
        
        # Process built-in variables
        result = self._process_builtins(result)
        
        return result
    
    def _process_simple_vars(self, text: str, context: Dict) -> str:
        """Process simple {variable} substitutions."""
        def replace(match):
            var_name = match.group(1)
            if var_name in context:
                return str(context[var_name])
            return match.group(0)  # Keep placeholder if not found
        
        return re.sub(r'\{(\w+)\}', replace, text)
    
    def _process_defaults(self, text: str, context: Dict) -> str:
        """Process {variable:default} substitutions."""
        def replace(match):
            var_name = match.group(1)
            default = match.group(2)
            if var_name in context:
                return str(context[var_name])
            return default
        
        return re.sub(r'\{(\w+):([^}]+)\}', replace, text)
    
    def _process_dates(self, text: str, context: Dict) -> str:
        """Process date formatting {date:%Y-%m-%d}."""
        def replace(match):
            var_name = match.group(1)
            fmt = match.group(2)
            
            if var_name == "date":
                return datetime.now().strftime(fmt)
            elif var_name == "time":
                return datetime.now().strftime(fmt)
            elif var_name in context:
                value = context[var_name]
                if isinstance(value, datetime):
                    return value.strftime(fmt)
                elif isinstance(value, str):
                    try:
                        dt = datetime.fromisoformat(value)
                        return dt.strftime(fmt)
                    except ValueError:
                        pass
            
            return match.group(0)
        
        return re.sub(r'\{(date|time|\w+):(%[^}]+)\}', replace, text)
    
    def _process_random(self, text: str) -> str:
        """Process {random:opt1|opt2|opt3} selections."""
        def replace(match):
            options = match.group(1).split("|")
            return random.choice(options)
        
        return re.sub(r'\{random:([^}]+)\}', replace, text)
    
    def _process_conditionals(self, text: str, context: Dict) -> str:
        """
        Process conditional blocks.
        
        Syntax: {if:variable}content{endif}
        Syntax: {if:variable}yes{else}no{endif}
        """
        # Process if-else blocks
        pattern = r'\{if:(\w+)\}([^{]*)\{else\}([^{]*)\{endif\}'
        
        def replace_if_else(match):
            var_name = match.group(1)
            yes_content = match.group(2)
            no_content = match.group(3)
            
            if var_name in context and context[var_name]:
                return yes_content
            return no_content
        
        text = re.sub(pattern, replace_if_else, text)
        
        # Process if-only blocks
        pattern = r'\{if:(\w+)\}([^{]*)\{endif\}'
        
        def replace_if(match):
            var_name = match.group(1)
            content = match.group(2)
            
            if var_name in context and context[var_name]:
                return content
            return ""
        
        return re.sub(pattern, replace_if, text)
    
    def _process_builtins(self, text: str) -> str:
        """Process built-in variables."""
        now = datetime.now()
        
        builtins = {
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M"),
            "datetime": now.strftime("%Y-%m-%d %H:%M"),
            "year": str(now.year),
            "month": str(now.month),
            "day": str(now.day),
            "weekday": now.strftime("%A"),
            "hour": str(now.hour),
            "minute": str(now.minute),
        }
        
        for name, value in builtins.items():
            text = text.replace(f"{{{name}}}", value)
        
        return text
    
    def extract_variables(self) -> List[str]:
        """
        Extract all variable names from template.
        
        Returns:
            List of variable names
        """
        variables = set()
        
        # Simple variables
        for match in re.finditer(r'\{(\w+)\}', self.content):
            variables.add(match.group(1))
        
        # Variables with defaults
        for match in re.finditer(r'\{(\w+):[^}]+\}', self.content):
            variables.add(match.group(1))
        
        # Remove built-ins
        builtins = {"date", "time", "datetime", "year", "month", "day", 
                   "weekday", "hour", "minute", "random"}
        variables -= builtins
        
        return list(variables)


class TemplateManager:
    """
    Manager for multiple templates.
    
    Provides template storage, retrieval, and rendering.
    
    Example:
        manager = TemplateManager()
        
        # Add template
        manager.add_template("greeting", "Hello {name}! Today is {weekday}.")
        
        # Render template
        message = manager.render("greeting", {"name": "Alice"})
        print(message)  # Hello Alice! Today is Monday.
    """
    
    def __init__(self):
        """Initialize template manager."""
        self.templates: Dict[str, Template] = {}
    
    def add_template(self, name: str, content: str) -> None:
        """
        Add a named template.
        
        Args:
            name: Template name
            content: Template content
        """
        self.templates[name] = Template(content=content, name=name)
    
    def get_template(self, name: str) -> Optional[Template]:
        """
        Get a template by name.
        
        Args:
            name: Template name
            
        Returns:
            Template if found, None otherwise
        """
        return self.templates.get(name)
    
    def render(self, name: str, context: Optional[Dict] = None) -> Optional[str]:
        """
        Render a template by name.
        
        Args:
            name: Template name
            context: Variable context
            
        Returns:
            Rendered string or None if template not found
        """
        template = self.get_template(name)
        if template:
            return template.render(context)
        return None
    
    def has_template(self, name: str) -> bool:
        """Check if template exists."""
        return name in self.templates
    
    def remove_template(self, name: str) -> bool:
        """Remove a template."""
        if name in self.templates:
            del self.templates[name]
            return True
        return False
    
    def list_templates(self) -> List[str]:
        """Get list of template names."""
        return list(self.templates.keys())
    
    def load_from_dict(self, data: Dict[str, str]) -> None:
        """
        Load templates from dictionary.
        
        Args:
            data: Dictionary mapping names to content
        """
        for name, content in data.items():
            self.add_template(name, content)
    
    def to_dict(self) -> Dict[str, str]:
        """Export templates to dictionary."""
        return {name: t.content for name, t in self.templates.items()}
