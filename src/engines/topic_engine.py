"""
TopicEngine — Generación automática de temas para nuevos episodios.

Usa el SDK google.genai (nuevo) para generar ideas de temas coherentes
basándose en la serie y episodios anteriores.
"""

import os
import json
from typing import List, Dict, Any, Optional

from google import genai
from google.genai import types

from src.utils.memory_manager import MemoryManager
from src.utils.prompt_manager import PromptManager
from src.variables import GEMINI_MODEL_NAME


class TopicEngine:
    """Genera ideas de temas para nuevos episodios usando Gemini."""

    def __init__(self, pod_config_path: str):
        self.config = self._load_config(pod_config_path)
        self.pod_dir = os.path.dirname(pod_config_path)
        self.memory_manager = MemoryManager(self.pod_dir)

        # Load prompt manager
        prompts_file = os.path.join(self.pod_dir, "prompts.json")
        self.prompt_manager = PromptManager(prompts_file)

        # Initialize Google GenAI client (new SDK)
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError(
                "GOOGLE_API_KEY no encontrada en .env. "
                "Obtener en: https://aistudio.google.com/apikey"
            )
        self.client = genai.Client(api_key=api_key)

    def _load_config(self, path: str) -> Dict[str, Any]:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def generate_topics(self, count: int = 5) -> List[Dict[str, Any]]:
        """
        Generate topic ideas for new episodes.

        Args:
            count: Number of topics to generate.

        Returns:
            List of topic dicts with title, description, educational_value, etc.
        """
        memory_summary = self.memory_manager.get_all_episodes()
        previous_episodes_text = self._format_previous_episodes(memory_summary)

        system_role = self.prompt_manager.get_system_role("topic_generation")
        output_format = self.prompt_manager.get_output_format("topic_generation")

        user_prompt = self.prompt_manager.render_template(
            "topic_generation",
            num_topics=count,
            series_name=self.config.get("series_name", "La Serie"),
            series_description=self.config.get("series_description", ""),
            target_audience=self.config.get("target_audience", "público general"),
            previous_episodes=previous_episodes_text,
            output_format=json.dumps(output_format, indent=2, ensure_ascii=False),
        )

        full_prompt = f"{system_role}\n\n{user_prompt}"

        try:
            response = self.client.models.generate_content(
                model=GEMINI_MODEL_NAME,
                contents=full_prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                ),
            )

            topics_data = json.loads(response.text)
            return topics_data.get("topics", [])

        except json.JSONDecodeError as e:
            print(f"Error decoding JSON from Gemini: {e}")
            print(f"Raw response: {response.text}")
            return []
        except Exception as e:
            print(f"Error generating topics: {e}")
            return []

    def _format_previous_episodes(self, episodes: List[Dict[str, Any]]) -> str:
        if not episodes:
            return "No hay episodios previos. Esta es la oportunidad de crear los primeros."

        formatted = []
        for idx, ep in enumerate(episodes, 1):
            title = ep.get("title", f"Episodio {idx}")
            summary = ep.get("summary", "Sin resumen")
            formatted.append(f"{idx}. {title}: {summary}")

        return "\n".join(formatted)

    def get_next_topic(self) -> Optional[Dict[str, Any]]:
        """Get a single topic for the next episode."""
        topics = self.generate_topics(count=1)
        return topics[0] if topics else None


if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv()

    pod_path = "pods/kids_story/config.json"

    if os.path.exists(pod_path):
        print("[*] Inicializando Topic Engine...")
        engine = TopicEngine(pod_path)

        num_topics = int(sys.argv[1]) if len(sys.argv) > 1 else 3
        print(f"\n[*] Generando {num_topics} ideas de temas...\n")
        topics = engine.generate_topics(count=num_topics)

        if topics:
            print(f"[OK] {len(topics)} temas generados:\n")
            for idx, topic in enumerate(topics, 1):
                print(f"{'='*60}")
                print(f"TEMA {idx}: {topic.get('title', 'Sin titulo')}")
                print(f"Descripcion: {topic.get('description', 'N/A')}")
                print(f"Valor educativo: {topic.get('educational_value', 'N/A')}")
                print()
        else:
            print("[ERROR] No se pudieron generar temas")
    else:
        print(f"Error: No se encontro {pod_path}")
