"""
ReviewerEngine - Capa de revisión y perfeccionamiento de guiones.

Toma el JSON de un guion generado por el ScriptEngine y lo pasa a una segunda
instancia de Gemini que actúa como Director Supervisor. Esta instancia se
encarga de corregir fallos técnicos (uso indebido de transiciones, duración),
así como de mejorar el storytelling y la coherencia general antes de enviarlo
a producción de vídeo.
"""

import os
import json
from typing import Optional

from google import genai
from google.genai import types

from src.utils.api_key_manager import get_api_key_manager
from src.utils.prompt_manager import PromptManager
from src.variables import GEMINI_MODEL_NAME


class ReviewerEngine:
    def __init__(self, pod_config_path: str):
        self.pod_dir = os.path.dirname(pod_config_path)
        
        # Load prompt manager
        prompts_file = os.path.join(self.pod_dir, "prompts.json")
        self.prompt_manager = PromptManager(prompts_file)
        
        # Initialize Google GenAI client via ApiKeyManager
        self.key_manager = get_api_key_manager()
        self.client = self.key_manager.get_client()

    def review_script(self, draft_script: dict) -> Optional[dict]:
        """
        Pasa el guion borrador por un prompt supervisor para corregirlo.
        """
        print("[ReviewerEngine] 🧐 Evaluando guion como Director/Supervisor...")
        
        try:
            # Check if prompt exists, fallback gracefully if it doesn't
            try:
                system_role = self.prompt_manager.get_system_role("script_review")
                output_format = self.prompt_manager.get_output_format("script_review")
            except KeyError:
                print("[ReviewerEngine] ⚠️ Prompt 'script_review' no encontrado en prompts.json. Saltando revisión.")
                return draft_script

            pods_dir = os.path.dirname(self.pod_dir)
            video_rules_text = PromptManager.load_video_rules(pods_dir)
            
            draft_json_str = json.dumps(draft_script, indent=2, ensure_ascii=False)
            output_format_str = json.dumps(output_format, indent=2, ensure_ascii=False)

            user_prompt = self.prompt_manager.render_template(
                "script_review",
                draft_script=draft_json_str,
                video_rules=video_rules_text,
                output_format=output_format_str
            )

            full_prompt = f"{system_role}\n\n{user_prompt}"

            response = self.client.models.generate_content(
                model=GEMINI_MODEL_NAME,
                contents=full_prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                ),
            )

            refined_data = json.loads(response.text)

            # Gemini sometimes wraps the response in a list
            if isinstance(refined_data, list) and len(refined_data) > 0:
                refined_data = refined_data[0]

            print("[ReviewerEngine] ✅ Guion purgado y mejorado exitosamente.")
            return refined_data

        except json.JSONDecodeError as e:
            print(f"[ReviewerEngine] ❌ Error decodificando respuesta JSON del supervisor: {e}")
            print(f"Raw response: {response.text[:500]}...")
            return draft_script  # Retorna el original si falla
        except Exception as e:
            print(f"[ReviewerEngine] ❌ Error general durante la revisión: {e}")
            return draft_script
