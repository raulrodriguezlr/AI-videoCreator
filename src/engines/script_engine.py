import os
import json
import google.generativeai as genai
from dotenv import load_dotenv
from src.utils.memory_manager import MemoryManager

from src.variables import GEMINI_MODEL_NAME

# Load environment variables
load_dotenv()

class ScriptGenerator:
    def __init__(self, pod_config_path: str):
        self.config = self._load_config(pod_config_path)
        self.memory_manager = MemoryManager(os.path.dirname(pod_config_path))
        
        # Configure Gemini
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY not found in .env")
        
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(GEMINI_MODEL_NAME) 

    def _load_config(self, path: str) -> dict:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def generate_script(self, topic: str) -> dict:
        """
        Generates a script for a new episode based on a topic and previous context.
        """
        context = self.memory_manager.get_context_summary()
        pod_settings = self.config
        
        prompt = f"""
        ACT AS: {pod_settings['system_prompt']}
        
        CONTEXTO ACTUAL (Memoria):
        {context}
        
        TAREA:
        Escribe un guion para un video de Youtube Shorts ({pod_settings['video_duration_seconds']} segundos).
        Tema del episodio: "{topic}"
        
        PERSONAJES:
        {json.dumps(pod_settings['characters'], ensure_ascii=False)}
        
        FORMATO DE SALIDA (JSON estrictamente):
        {{
            "title": "Título del episodio",
            "summary": "Resumen de 1 frase de lo que pasa (para la memoria)",
            "scenes": [
                {{
                    "visual_prompt": "Descripción detallada de la imagen para IA (incluyendo estilo {pod_settings['consistency']['art_style_lora']})",
                    "audio_text": "Texto que dirá el narrador o personaje",
                    "character": "Nombre del personaje que habla o 'Narrador'",
                    "duration_est": 5
                }}
            ]
        }}
        """

        response = self.model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        
        try:
            script_data = json.loads(response.text)
            return script_data
        except json.JSONDecodeError:
            # Fallback or retry logic could go here
            print("Error decoding JSON from Gemini response")
            return None

    def save_episode_to_memory(self, script_data: dict):
        if script_data:
            self.memory_manager.add_episode({
                "title": script_data.get("title"),
                "summary": script_data.get("summary")
            })

if __name__ == "__main__":
    # Test execution
    try:
        generator = ScriptGenerator("pods/kids_story/config.json")
        script = generator.generate_script("Tico encuentra una nuez mágica brillante")
        print("\n--- Script Generado ---\n")
        print(json.dumps(script, indent=2, ensure_ascii=False))
        
        # Uncomment to save to memory
        # generator.save_episode_to_memory(script)
        
    except Exception as e:
        print(f"Error: {e}")
