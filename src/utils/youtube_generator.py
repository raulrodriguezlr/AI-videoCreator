import os
import json
from google import genai
from google.genai import types

from src.utils.api_key_manager import get_api_key_manager
from src.variables import GEMINI_MODEL_NAME


class YoutubeMetadataGenerator:
    """
    Genera metadatos listos para YouTube (título y descripción) a partir 
    del contexto del episodio.
    """

    def __init__(self):
        self.key_manager = get_api_key_manager()
        self.client = self.key_manager.get_client()

    def generate_metadata(self, title: str, summary: str, moral: str) -> dict:
        """
        Llama a Gemini para generar un título SEO y una descripción atractiva para YouTube.
        Devuelve un diccionario con el resultado.
        """
        print(f"\n[YouTube] 🎬 Generando metadatos para YouTube con Gemini...")

        system_instruction = (
            "Eres un experto creador de contenido para YouTube, especializado en canales infantiles. "
            "Tu objetivo es crear títulos súper atractivos y descripciones divertidas, "
            "usando emojis, llamadas a la acción y resaltando la moraleja de la historia."
        )

        user_prompt = f"""
        A partir del siguiente episodio de nuestra serie de cuentos infantiles generados con IA, 
        crea un título para YouTube y una descripción.
        
        Título original: {title}
        Resumen: {summary}
        Moraleja: {moral}
        
        Sigue estas reglas:
        - El título debe ser atractivo (ej: ¡Aventuras Mágicas! ✨ | Tico la ardilla en...)
        - La descripción debe empezar con un saludo animado.
        - Cuenta un poco de qué va sin hacer mucho spoiler.
        - Haz una pregunta a los niños para que dejen comentarios.
        - Recuerda pedir que se suscriban y le den a Me Gusta.
        - Añade algunos hashtags relevantes al final.
        - Devuelve EXCLUSIVAMENTE un objeto JSON válido con las claves "titulo_youtube" y "descripcion_youtube".
        """

        try:
            response = self.client.models.generate_content(
                model=GEMINI_MODEL_NAME,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                ),
            )

            data = json.loads(response.text)
            print("[YouTube] ✅ Metadatos generados con éxito.")
            return data

        except Exception as e:
            print(f"[YouTube] ❌ Error generando metadatos: {e}")
            return {}

    def generate_and_save(self, script_data: dict, output_dir: str):
        """
        Extrae la información del script, genera los metadatos y los guarda en un JSON.
        """
        title = script_data.get("title", "")
        summary = script_data.get("summary", "")
        moral = script_data.get("moral", "")

        metadata = self.generate_metadata(title, summary, moral)

        if metadata:
            output_path = os.path.join(output_dir, "youtube_metadata.json")
            try:
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(metadata, f, indent=2, ensure_ascii=False)
                print(f"[YouTube] 💾 Metadatos guardados en: {output_path}")
            except OSError as e:
                print(f"[YouTube] ⚠️ No se pudo guardar el archivo: {e}")
