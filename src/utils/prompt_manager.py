"""
Prompt Manager - Template-based prompt rendering system

This module handles loading and rendering prompt templates with variable substitution.
Prompts are stored in JSON files per pod, allowing easy customization without code changes.
"""

import json
import os
from typing import Dict, Any, Optional
from string import Formatter


class PromptManager:
    """Manages prompt templates and variable substitution"""
    
    def __init__(self, prompts_file_path: str):
        """
        Initialize PromptManager with a prompts configuration file.
        
        Args:
            prompts_file_path: Absolute path to prompts.json file
        """
        self.prompts_file_path = prompts_file_path
        self.prompts = self._load_prompts()
        
    def _load_prompts(self) -> Dict[str, Any]:
        """Load prompts from JSON file"""
        if not os.path.exists(self.prompts_file_path):
            raise FileNotFoundError(f"Prompts file not found: {self.prompts_file_path}")
        
        with open(self.prompts_file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def get_template(self, section: str, key: str = "user_template") -> str:
        """
        Get a specific prompt template.
        
        Args:
            section: Section name (e.g., 'script_generation', 'topic_generation')
            key: Key within the section (default: 'user_template')
            
        Returns:
            Template string with placeholders
        """
        if section not in self.prompts:
            raise KeyError(f"Section '{section}' not found in prompts file")
        
        if key not in self.prompts[section]:
            raise KeyError(f"Key '{key}' not found in section '{section}'")
        
        return self.prompts[section][key]
    
    def render_template(self, section: str, key: str = "user_template", **variables) -> str:
        """
        Render a template by substituting variables.
        
        Args:
            section: Section name (e.g., 'script_generation')
            key: Key within the section (default: 'user_template')
            **variables: Variables to substitute (e.g., topic="...", duration_seconds=180)
            
        Returns:
            Rendered prompt string
            
        Raises:
            KeyError: If template not found or required variable missing
        """
        template = self.get_template(section, key)
        
        # Extract required fields from template
        required_fields = [field_name for _, field_name, _, _ in Formatter().parse(template) if field_name]
        
        # Check for missing required fields
        missing_fields = [field for field in required_fields if field not in variables]
        if missing_fields:
            raise KeyError(f"Missing required variables for template '{section}.{key}': {missing_fields}")
        
        # Render template
        return template.format(**variables)
    
    def get_system_role(self, section: str) -> str:
        """
        Get system role prompt for a section.
        
        Args:
            section: Section name
            
        Returns:
            System role string
        """
        return self.get_template(section, "system_role")
    
    def get_output_format(self, section: str) -> Dict[str, Any]:
        """
        Get expected output format for a section.
        
        Args:
            section: Section name
            
        Returns:
            Output format dictionary
        """
        if section not in self.prompts:
            raise KeyError(f"Section '{section}' not found in prompts file")
        
        if "output_format" not in self.prompts[section]:
            raise KeyError(f"'output_format' not found in section '{section}'")
        
        return self.prompts[section]["output_format"]


# Example usage
if __name__ == "__main__":
    # Test with kids_story pod
    prompts_path = "pods/kids_story/prompts.json"
    
    if os.path.exists(prompts_path):
        pm = PromptManager(prompts_path)
        
        # Test rendering script generation template
        rendered = pm.render_template(
            "script_generation",
            topic="Tico aprende a compartir",
            target_audience="niños de 3 a 7 años",
            series_context="Serie educativa sobre valores",
            memory_context="Episodio 1: Tico conoce a nuevos amigos",
            characters="Tico (ardilla curiosa), Narrador",
            duration_seconds=180,
            art_style="3D Disney/Pixar",
            num_interactive_questions=2,
            output_format=json.dumps(pm.get_output_format("script_generation"), indent=2)
        )
        
        print("=== RENDERED PROMPT ===")
        print(rendered)
        
        print("\n=== SYSTEM ROLE ===")
        print(pm.get_system_role("script_generation"))
    else:
        print(f"Prompts file not found: {prompts_path}")
        print("Run from project root directory")
