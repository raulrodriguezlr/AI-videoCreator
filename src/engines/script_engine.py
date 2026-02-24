"""
ScriptEngine — Generación de guiones cinematográficos con Gemini.

Usa el SDK google.genai (nuevo) para generar scripts con metadatos de cámara,
iluminación, mood y transiciones. Produce un JSON estructurado que el
VideoEngine/Providers puede consumir directamente.
"""

import os
import json
from typing import Optional, Dict, Any

from google import genai
from google.genai import types

from src.utils.api_key_manager import get_api_key_manager
from src.utils.memory_manager import MemoryManager
from src.utils.prompt_manager import PromptManager
from src.variables import GEMINI_MODEL_NAME


class ScriptGenerator:
    def __init__(self, pod_config_path: str):
        self.config = self._load_config(pod_config_path)
        self.pod_dir = os.path.dirname(pod_config_path)
        self.memory_manager = MemoryManager(self.pod_dir)

        # Load prompt manager
        prompts_file = os.path.join(self.pod_dir, "prompts.json")
        self.prompt_manager = PromptManager(prompts_file)

        # Initialize Google GenAI client via ApiKeyManager
        self.key_manager = get_api_key_manager()
        self.client = self.key_manager.get_client()

    def _load_config(self, path: str) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def generate_script(self, topic: str) -> Optional[dict]:
        """
        Generates a cinematographic script for a new episode.
        Output includes camera metadata for each scene.

        Returns:
            Script dict with title, scenes (with camera, mood, lighting,
            visual_prompt, audio_text, transition_to_next), or None on error.
        """
        # Get context from memory
        memory_context = self.memory_manager.get_context_summary()

        # Extract config values
        video_settings = self.config.get("video_settings", {})
        duration_seconds = video_settings.get("duration_seconds", 180)
        min_scenes = video_settings.get("min_scenes", 12)
        max_scenes = video_settings.get("max_scenes", 20)
        interactive_questions = video_settings.get("interactive_questions", 2)
        interactivity_enabled = video_settings.get("interactivity_enabled", False)

        consistency = self.config.get("consistency", {})
        art_style = consistency.get("art_style", "3D animated style")

        series_context = self.config.get("series_description", "")
        target_audience = self.config.get("target_audience", "público general")

        # Format characters
        characters_list = self.config.get("characters", [])
        characters_text = self._format_characters(characters_list)

        # Get output format from prompts
        output_format = self.prompt_manager.get_output_format("script_generation")

        # Render user prompt template
        system_role = self.prompt_manager.get_system_role("script_generation")
        user_prompt = self.prompt_manager.render_template(
            "script_generation",
            topic=topic,
            target_audience=target_audience,
            series_context=series_context,
            memory_context=memory_context
            if memory_context
            else "Este es el primer episodio de la serie.",
            characters=characters_text,
            duration_seconds=duration_seconds,
            min_scenes=min_scenes,
            max_scenes=max_scenes,
            art_style=art_style,
            num_interactive_questions=interactive_questions
            if interactivity_enabled
            else 0,
            output_format=json.dumps(output_format, indent=2, ensure_ascii=False),
        )

        full_prompt = f"{system_role}\n\n{user_prompt}"

        # Generate with Gemini (new SDK)
        try:
            response = self.client.models.generate_content(
                model=GEMINI_MODEL_NAME,
                contents=full_prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                ),
            )

            script_data = json.loads(response.text)

            # Gemini sometimes wraps the response in a list
            if isinstance(script_data, list) and len(script_data) > 0:
                script_data = script_data[0]

            # Post-process: ensure interactive questions have pause
            if interactivity_enabled and "scenes" in script_data:
                for scene in script_data["scenes"]:
                    if (
                        scene.get("is_interactive_question", False)
                        and scene.get("pause_for_answer", 0) == 0
                    ):
                        scene["pause_for_answer"] = 3

            return script_data

        except json.JSONDecodeError as e:
            print(f"Error decoding JSON from Gemini: {e}")
            print(f"Raw response: {response.text[:500]}...")
            return None
        except Exception as e:
            print(f"Error generating script: {e}")
            return None

    def _format_characters(self, characters: list) -> str:
        """Format characters list for prompt."""
        formatted = []
        for char in characters:
            name = char.get("name", "Unknown")
            role = char.get("role", "")
            personality = char.get("personality", "")
            visual = char.get("visual_description", "")

            char_text = f"- {name}"
            if role:
                char_text += f" ({role})"
            if personality:
                char_text += f": {personality}"
            if visual:
                char_text += f"\n  Visual: {visual}"

            formatted.append(char_text)

        return "\n".join(formatted)

    def save_episode_to_memory(self, script_data: dict):
        """Save episode data to memory for continuity."""
        if script_data:
            self.memory_manager.add_episode(
                {
                    "title": script_data.get("title"),
                    "summary": script_data.get("summary"),
                    "moral": script_data.get("moral", ""),
                }
            )


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    try:
        generator = ScriptGenerator("pods/kids_story/config.json")

        print("🎬 Generando guion de prueba...")
        script = generator.generate_script("Tico aprende sobre la paciencia")

        if script:
            print(f"\nTítulo: {script.get('title')}")
            print(f"Moraleja: {script.get('moral')}")
            print(f"Escenas: {len(script.get('scenes', []))}")
            print(json.dumps(script, indent=2, ensure_ascii=False))
        else:
            print("❌ Error generando guion")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
