"""
SceneContextManager — Mantiene el contexto visual entre escenas para consistencia.

Trackea localización, props activos y estado del personaje a lo largo del episodio.
Inyecta contexto textual en los prompts de escenas consecutivas para reforzar
la consistencia visual, complementando el seed de último frame (Fase 2).

Inspirado en el sistema de "Ingredients" de Google Flow.

All extraction keywords are loaded from the pod's config.json under "scene_context",
making this system pod-agnostic.
"""

import os
import json
import re
from typing import Optional, Dict, List


class SceneContextManager:
    """
    Tracks visual context across scenes to reinforce consistency.
    
    Works alongside the last-frame seeding (Phase 2) by providing
    textual context about the current environment, props, and character state.
    This gives Veo redundant consistency signals: visual (last frame) + textual (this).
    
    All extraction keywords come from pod config.json["scene_context"].
    If no config is provided, falls back to generic regex patterns only.
    """

    def __init__(self, episode_dir: str, pod_config: Optional[Dict] = None):
        self.episode_dir = episode_dir
        self.context_file = os.path.join(episode_dir, "scene_context.json")
        
        # Load pod-specific keywords from config
        ctx_config = (pod_config or {}).get("scene_context", {})
        self.location_keywords: Dict[str, str] = ctx_config.get("location_keywords", {})
        self.known_props: Dict[str, str] = ctx_config.get("known_props", {})
        self.permanent_props: List[str] = ctx_config.get("permanent_props", [])
        
        states_config = ctx_config.get("character_states", {})
        self.physical_states: Dict[str, str] = states_config.get("physical", {})
        self.emotional_states: Dict[str, str] = states_config.get("emotional", {})
        
        # Current state
        self.current_location: Optional[str] = None
        self.active_props: List[str] = []
        self.character_state: Optional[str] = None
        self.scene_history: List[Dict] = []
        
        # Try to load existing context (for resume support)
        self._load_context()

    def _load_context(self):
        """Load context from disk if resuming an episode."""
        if os.path.exists(self.context_file):
            try:
                with open(self.context_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.current_location = data.get("current_location")
                self.active_props = data.get("active_props", [])
                self.character_state = data.get("character_state")
                self.scene_history = data.get("scene_history", [])
            except (json.JSONDecodeError, OSError):
                pass

    def _save_context(self):
        """Persist context to disk for resume safety."""
        data = {
            "current_location": self.current_location,
            "active_props": self.active_props,
            "character_state": self.character_state,
            "scene_history": self.scene_history,
        }
        try:
            with open(self.context_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except OSError:
            pass

    def update_after_scene(self, scene_index: int, scene: dict, transition_to_next: str):
        """
        Update context after a scene has been generated.
        Extracts location, props, and character state from the visual_prompt.
        
        Args:
            scene_index: Index of the scene that was just generated
            scene: The scene dict from the script
            transition_to_next: The transition type to the next scene
        """
        visual_prompt = scene.get("visual_prompt", "")
        
        # Extract location from visual prompt
        location = self._extract_location(visual_prompt)
        if location:
            self.current_location = location
        
        # Extract props
        props = self._extract_props(visual_prompt)
        if props:
            self.active_props = props
        
        # Extract character state
        state = self._extract_character_state(visual_prompt)
        if state:
            self.character_state = state
        
        # If scene_change, reset location context (new place)
        if transition_to_next == "scene_change":
            self.current_location = None
            self.character_state = None
        
        # Store in history
        self.scene_history.append({
            "scene_index": scene_index,
            "location": self.current_location,
            "props": self.active_props,
            "character_state": self.character_state,
        })
        
        self._save_context()

    def get_continuity_context(self, incoming_transition: str) -> Optional[str]:
        """
        Build a continuity context string to inject into the next scene's prompt.
        
        Only returns context for 'continue' and 'cut' transitions (same location).
        Returns None for 'scene_change' (new location, no context needed).
        
        Args:
            incoming_transition: The transition type leading INTO this scene
            
        Returns:
            Context string or None
        """
        if incoming_transition == "scene_change" or not self.scene_history:
            return None
        
        parts = []
        
        if self.current_location:
            parts.append(f"Current location: {self.current_location}")
        
        if self.active_props:
            parts.append(f"Props present: {', '.join(self.active_props)}")
        
        if self.character_state:
            parts.append(f"Character state: {self.character_state}")
        
        if not parts:
            return None
        
        return "CONTINUITY CONTEXT from previous scene — " + ". ".join(parts)

    def _extract_location(self, visual_prompt: str) -> Optional[str]:
        """
        Extract location description from visual_prompt.
        Uses generic regex patterns + pod-specific keywords from config.
        """
        prompt_lower = visual_prompt.lower()
        
        # Generic regex: catches "in a forest clearing", "by the river", etc.
        generic_pattern = (
            r"(?:inside|in|at|near|by|beside|on)\s+"
            r"(?:a\s+|the\s+)?"
            r"([\w\s]+(?:cave|river|lake|pond|stream|waterfall|bridge|house|tree|"
            r"path|clearing|meadow|hill|mountain|cliff|beach|shore|garden|forest|"
            r"woods|burrow|nest|den|stump|rock|boulder|log|village|town|room|"
            r"kitchen|field|desert|ocean|island|swamp|valley|canyon))"
        )
        match = re.search(generic_pattern, prompt_lower)
        if match:
            return match.group(0).strip()
        
        # Pod-specific keyword fallback from config
        for keyword, description in self.location_keywords.items():
            if keyword in prompt_lower:
                return description
        
        return None

    def _extract_props(self, visual_prompt: str) -> List[str]:
        """
        Extract notable props/objects from the visual_prompt.
        Uses generic interaction patterns + pod-specific known props from config.
        """
        props = []
        prompt_lower = visual_prompt.lower()
        
        # Generic patterns: "holding a golden leaf", "carrying a basket", etc.
        interaction_patterns = [
            r"holding\s+(?:a\s+|the\s+)?([\w\s]+?)(?:\.|,|\s+in\s|\s+with\s|\s+and\s)",
            r"carrying\s+(?:a\s+|the\s+)?([\w\s]+?)(?:\.|,|\s+in\s|\s+with\s|\s+and\s)",
            r"grabbing\s+(?:a\s+|the\s+)?([\w\s]+?)(?:\.|,|\s+in\s|\s+with\s|\s+and\s)",
            r"picking up\s+(?:a\s+|the\s+)?([\w\s]+?)(?:\.|,|\s+and\s)",
            r"showing\s+(?:a\s+|the\s+)?([\w\s]+?)(?:\.|,|\s+to\s)",
        ]
        
        for pattern in interaction_patterns:
            matches = re.findall(pattern, prompt_lower)
            props.extend([m.strip() for m in matches if len(m.strip()) > 2])
        
        # Pod-specific known props from config (skip permanent ones like backpack)
        for keyword, prop_name in self.known_props.items():
            if keyword in prompt_lower and prop_name not in props:
                # Skip permanent props (always in character description, not actively used)
                if keyword not in self.permanent_props:
                    props.append(prop_name)
        
        return props

    def _extract_character_state(self, visual_prompt: str) -> Optional[str]:
        """
        Extract character physical/emotional state from visual_prompt.
        Uses pod-specific states from config.
        """
        prompt_lower = visual_prompt.lower()
        states = []
        
        # Physical states from config
        for keyword, state in self.physical_states.items():
            if keyword in prompt_lower:
                states.append(state)
        
        # Emotional states from config
        for keyword, state in self.emotional_states.items():
            if keyword in prompt_lower:
                states.append(state)
        
        return ", ".join(states) if states else None
