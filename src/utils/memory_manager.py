import json
import os
from typing import List, Dict, Any

class MemoryManager:
    def __init__(self, pod_path: str):
        self.memory_file = os.path.join(pod_path, "universe_memory.json")
        self._ensure_memory_exists()

    def _ensure_memory_exists(self):
        if not os.path.exists(self.memory_file):
            initial_state = {
                "episodes": [],
                "current_state": {
                    "characters": {}
                }
            }
            self.save_memory(initial_state)

    def load_memory(self) -> Dict[str, Any]:
        with open(self.memory_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def save_memory(self, data: Dict[str, Any]):
        with open(self.memory_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    def add_episode(self, episode_summary: Dict[str, Any]):
        memory = self.load_memory()
        memory["episodes"].append(episode_summary)
        # Keep only last 10 episodes in full detail to save context window if needed, 
        # though Gemini 3 Pro has a huge window.
        self.save_memory(memory)

    def get_context_summary(self) -> str:
        memory = self.load_memory()
        episodes = memory.get("episodes", [])
        if not episodes:
            return "Este es el primer episodio. No hay historia previa."
        
        context = "Resumen de episodios anteriores:\n"
        for i, ep in enumerate(episodes[-5:]): # Last 5 episodes context
            context += f"- Episodio {i+1}: {ep.get('summary', 'Sin resumen')}\n"
        
        return context
