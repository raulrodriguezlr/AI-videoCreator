"""
Topic Engine - Automatic topic generation for video series

This module uses LLM to generate unique, coherent topics for new episodes
based on the series concept and previous episodes.
"""

import os
import json
import google.generativeai as genai
from dotenv import load_dotenv
from typing import List, Dict, Any, Optional

from src.utils.memory_manager import MemoryManager
from src.utils.prompt_manager import PromptManager
from src.variables import GEMINI_MODEL_NAME

load_dotenv()


class TopicEngine:
    """Generates topic ideas for new episodes using LLM"""
    
    def __init__(self, pod_config_path: str):
        """
        Initialize TopicEngine with pod configuration.
        
        Args:
            pod_config_path: Path to pod's config.json file
        """
        self.config = self._load_config(pod_config_path)
        self.pod_dir = os.path.dirname(pod_config_path)
        self.memory_manager = MemoryManager(self.pod_dir)
        
        # Load prompt manager
        prompts_file = os.path.join(self.pod_dir, "prompts.json")
        self.prompt_manager = PromptManager(prompts_file)
        
        # Configure Gemini
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY not found in .env")
        
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(GEMINI_MODEL_NAME)
    
    def _load_config(self, path: str) -> Dict[str, Any]:
        """Load pod configuration"""
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def generate_topics(self, count: int = 5) -> List[Dict[str, Any]]:
        """
        Generate topic ideas for new episodes.
        
        Args:
            count: Number of topics to generate
            
        Returns:
            List of topic dictionaries with title, description, educational_value, etc.
        """
        # Get previous episodes from memory
        memory_summary = self.memory_manager.get_all_episodes()
        previous_episodes_text = self._format_previous_episodes(memory_summary)
        
        # Render prompt template
        system_role = self.prompt_manager.get_system_role("topic_generation")
        output_format = self.prompt_manager.get_output_format("topic_generation")
        
        user_prompt = self.prompt_manager.render_template(
            "topic_generation",
            num_topics=count,
            series_name=self.config.get("series_name", "La Serie"),
            series_description=self.config.get("series_description", ""),
            target_audience=self.config.get("target_audience", "público general"),
            previous_episodes=previous_episodes_text,
            output_format=json.dumps(output_format, indent=2, ensure_ascii=False)
        )
        
        # Generate topics with Gemini
        full_prompt = f"{system_role}\n\n{user_prompt}"
        
        try:
            response = self.model.generate_content(
                full_prompt,
                generation_config={"response_mime_type": "application/json"}
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
        """Format previous episodes for prompt context"""
        if not episodes:
            return "No hay episodios previos aún. Esta es la oportunidad de crear los primeros episodios de la serie."
        
        formatted = []
        for idx, ep in enumerate(episodes, 1):
            title = ep.get("title", f"Episodio {idx}")
            summary = ep.get("summary", "Sin resumen")
            formatted.append(f"{idx}. {title}: {summary}")
        
        return "\n".join(formatted)
    
    def get_next_topic(self) -> Optional[Dict[str, Any]]:
        """
        Get a single topic for the next episode.
        Convenience method that generates 1 topic.
        
        Returns:
            Topic dictionary or None if generation failed
        """
        topics = self.generate_topics(count=1)
        return topics[0] if topics else None


# Example usage
if __name__ == "__main__":
    import sys
    
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
                print(f"{'='*60}")
                print(f"Descripcion: {topic.get('description', 'N/A')}")
                print(f"Valor educativo: {topic.get('educational_value', 'N/A')}")
                print(f"Emocion objetivo: {topic.get('target_emotion', 'N/A')}")
                
                if topic.get('references_episode'):
                    print(f"Referencia a: {topic['references_episode']}")
                print()
        else:
            print("[ERROR] No se pudieron generar temas")
    else:
        print(f"Error: No se encontro {pod_path}")
        print("Ejecutar desde la raiz del proyecto")
