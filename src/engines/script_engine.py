import os
import json
import google.generativeai as genai
from dotenv import load_dotenv
from src.utils.memory_manager import MemoryManager
from src.utils.prompt_manager import PromptManager

from src.variables import GEMINI_MODEL_NAME

# Load environment variables
load_dotenv()

class ScriptGenerator:
    def __init__(self, pod_config_path: str):
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

    def _load_config(self, path: str) -> dict:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def generate_script(self, topic: str) -> dict:
        """
        Generates a script for a new episode based on a topic and previous context.
        Uses template-based prompts from prompts.json.
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
        
        # Format characters for prompt
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
            memory_context=memory_context if memory_context else "Este es el primer episodio de la serie.",
            characters=characters_text,
            duration_seconds=duration_seconds,
            min_scenes=min_scenes,
            max_scenes=max_scenes,
            art_style=art_style,
            num_interactive_questions=interactive_questions if interactivity_enabled else 0,
            output_format=json.dumps(output_format, indent=2, ensure_ascii=False)
        )
        
        # Combine system role and user prompt
        full_prompt = f"{system_role}\n\n{user_prompt}"
        
        # Generate content with Gemini
        try:
            response = self.model.generate_content(
                full_prompt,
                generation_config={"response_mime_type": "application/json"}
            )
            
            script_data = json.loads(response.text)
            
            # Post-process: ensure interactive questions have pause if enabled
            if interactivity_enabled and "scenes" in script_data:
                for scene in script_data["scenes"]:
                    if scene.get("is_interactive_question", False) and scene.get("pause_for_answer", 0) == 0:
                        scene["pause_for_answer"] = 3  # Default 3 seconds pause
            
            return script_data
            
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON from Gemini response: {e}")
            print(f"Raw response: {response.text[:500]}...")
            return None
        except Exception as e:
            print(f"Error generating script: {e}")
            return None

    def _format_characters(self, characters: list) -> str:
        """Format characters list for prompt"""
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
        """Save episode data to memory for continuity"""
        if script_data:
            self.memory_manager.add_episode({
                "title": script_data.get("title"),
                "summary": script_data.get("summary"),
                "moral": script_data.get("moral", "")
            })

if __name__ == "__main__":
    # Test execution
    try:
        generator = ScriptGenerator("pods/kids_story/config.json")
        
        print("🎬 Generando guion de prueba...")
        script = generator.generate_script("Tico aprende sobre la paciencia")
        
        if script:
            print("\n--- Script Generado ---\n")
            print(f"Título: {script.get('title')}")
            print(f"Moraleja: {script.get('moral')}")
            print(f"Número de escenas: {len(script.get('scenes', []))}")
            
            print("\n--- Primeras 3 escenas ---")
            for scene in script.get('scenes', [])[:3]:
                print(f"\nEscena {scene.get('scene_number')}: {scene.get('narrative_phase')}")
                print(f"Audio: {scene.get('audio_text')[:100]}...")
                if scene.get('is_interactive_question'):
                    print(f"⏸️  PREGUNTA INTERACTIVA (pausa: {scene.get('pause_for_answer')}s)")
            
            print(f"\n--- Script completo (JSON) ---")
            print(json.dumps(script, indent=2, ensure_ascii=False))
            
            # Uncomment to save to memory
            # generator.save_episode_to_memory(script)
        else:
            print("❌ Error: No se pudo generar el guion")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

