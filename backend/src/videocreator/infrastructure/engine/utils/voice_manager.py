import os
import json
import time
import platform
import subprocess
import requests
from dotenv import load_dotenv
from videocreator.infrastructure.engine.utils.api_key_manager import get_api_key_manager
from videocreator.infrastructure.engine.variables import GEMINI_MODEL_NAME
from videocreator.infrastructure.engine.providers.elevenlabs_provider import ElevenLabsProvider

load_dotenv()

class VoiceManager:
    def __init__(self, pod_config_path: str):
        self.pod_config_path = pod_config_path
        self.api_key = os.getenv("ELEVENLABS_API_KEY")
        
        # We also need Gemini to parse the natural language query
        key_mgr = get_api_key_manager()
        self.gemini_client = key_mgr.get_client()
        self.gemini_model_name = GEMINI_MODEL_NAME
        
        self.temp_voice_ids = []  # Track added voices for cleanup

    def _play_audio(self, file_path: str):
        """Play audio cross-platform."""
        sys_name = platform.system()
        try:
            if sys_name == 'Darwin':
                subprocess.run(['afplay', file_path])
            else:
                # ffplay is required for VeoProvider, so we assume it exists
                subprocess.run(
                    ['ffplay', '-nodisp', '-autoexit', file_path], 
                    stdout=subprocess.DEVNULL, 
                    stderr=subprocess.DEVNULL
                )
        except Exception as e:
            print(f"⚠️ No se pudo reproducir el audio: {e}")

    def _get_config(self):
        with open(self.pod_config_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_config(self, config):
        with open(self.pod_config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)

    def test_current_voice(self, character_name: str, voice_id: str):
        """Generate and play a test line for the current voice."""
        provider = ElevenLabsProvider(self.pod_config_path)
        
        text = f"Esto es una prueba de voz para el personaje {character_name}."
        out_path = os.path.join(os.path.dirname(self.pod_config_path), f"test_{character_name}.mp3")
        
        print(f"🎙️ Generando audio de prueba para {character_name}...")
        res = provider.generate_dialogue(text, character_name, out_path)
        if res and os.path.exists(res):
            print("🔊 Reproduciendo...")
            self._play_audio(res)
            os.remove(res)
        else:
            print("❌ Error al generar audio de prueba.")

    def add_shared_voice(self, public_owner_id: str, voice_id: str, name: str) -> str:
        """Add a shared voice to the user's ElevenLabs account."""
        url = f"https://api.elevenlabs.io/v1/voices/add/{public_owner_id}/{voice_id}"
        headers = {"xi-api-key": self.api_key, "Content-Type": "application/json"}
        data = {"new_name": f"AI-Video_{name}"}
        
        res = requests.post(url, headers=headers, json=data)
        if res.status_code == 200:
            new_voice_id = res.json().get("voice_id")
            self.temp_voice_ids.append(new_voice_id)
            return new_voice_id
        else:
            print(f"⚠️ No se pudo añadir la voz a tu cuenta (Límite de voces?): {res.text}")
            return None

    def delete_voice(self, voice_id: str):
        """Cleanup temporary voices."""
        url = f"https://api.elevenlabs.io/v1/voices/{voice_id}"
        headers = {"xi-api-key": self.api_key}
        requests.delete(url, headers=headers)

    def search_voices_with_ai(self, character_name: str, user_prompt: str) -> list:
        """Use Gemini to map natural language to ElevenLabs API parameters and search."""
        sys_prompt = '''Actúa como un Experto en Búsqueda de Voces para la API de ElevenLabs.
        El usuario describirá una voz en lenguaje natural. Tu objetivo es convertir esa descripción en los parámetros óptimos JSON para la API /v1/shared-voices.
        
        IMPORTANTE: Solo debes incluir estas llaves exactas y valores:
        - "gender": estrictamente "male" o "female" (omítelo si no está claro).
        - "age": estrictamente "young", "middle_aged", o "old" (omítelo si no está claro).
        - "search_term": ¡CRÍTICO! Mejora la petición abstraiéndola en 1 o 2 (MÁXIMO) palabras clave generales en INGLÉS (ej. "energetic", "pirate", "spanish boy"). NO sobre-especifiques o el buscador no devolverá nada.
        
        NUNCA inventes otras llaves (NI category, NI language, etc.).
        Solo devuelve el JSON sin formato markdown extra.
        '''
        
        print("🧠 Analizando tu petición con IA...")
        try:
            response = self.gemini_client.models.generate_content(
                model=self.gemini_model_name,
                contents=f"{sys_prompt}\n\nPetición: {user_prompt}"
            )
            raw_text = response.text.strip().replace("```json", "").replace("```", "")
            search_params = json.loads(raw_text)
        except Exception as e:
            print(f"⚠️ Error de IA parseando la descripción ({e}). Buscando de forma genérica.")
            search_params = {"search_term": user_prompt[:20]}
            
        print(f"🔍 Buscando en ElevenLabs con: {search_params}")
        
        # Query ElevenLabs Shared Voices API
        url = "https://api.elevenlabs.io/v1/shared-voices"
        headers = {"xi-api-key": self.api_key}
        params = {"page_size": 20}
        
        if "gender" in search_params: params["gender"] = search_params["gender"]
        if "age" in search_params: params["age"] = search_params["age"]
        if "search_term" in search_params: params["search"] = search_params["search_term"]
        
        # Dejamos que la comunidad busque por "spanish" en el search_term si lo dice, 
        # en lugar de forzar el parámetro 'language' que es demasiado estricto.
        
        res = requests.get(url, headers=headers, params=params)
        if res.status_code != 200:
            print(f"❌ Error buscando voces: {res.text}")
            return []
            
        voices = res.json().get("voices", [])
        return voices[:5] # Top 5 results

    def interactive_voice_editor(self):
        """Main flow for the CLI interactive menu to edit character voices."""
        config = self._get_config()
        characters = config.get("characters", [])
        
        if not characters:
            print("❌ No hay personajes en este pod.")
            return

        print("\n👥 Personajes disponibles:")
        for idx, char in enumerate(characters, 1):
            v_id = char.get("elevenlabs_voice_id", "NO ASIGNADA")
            print(f"  {idx}. {char['name']} (Voice ID actual: {v_id})")
            
        try:
            sel = int(input("\nElige un personaje (número): ")) - 1
            if sel < 0 or sel >= len(characters):
                print("❌ Selección inválida.")
                return
        except ValueError:
            return
            
        char = characters[sel]
        char_name = char["name"]
        curr_id = char.get("elevenlabs_voice_id")
        
        if curr_id:
            ans = input(f"¿Quieres escuchar la voz actual de {char_name}? (s/n): ").lower()
            if ans == 's':
                self.test_current_voice(char_name, curr_id)
                
        ans = input(f"\n¿Quieres buscar una NUEVA voz para {char_name}? (s/n): ").lower()
        if ans != 's':
            return
            
        print("\nDescribe cómo quieres que suene la voz. Ejemplos:")
        print("- 'Una voz grave y rasposa de abuelo'")
        print("- 'Una niña dulce y energética'")
        print("- 'Voz de narrador épico profundo'")
        desc = input("> ")
        
        voices = self.search_voices_with_ai(char_name, desc)
        if not voices:
            print("❌ No se encontraron voces con esa descripción.")
            return
            
        print("\n🎯 Resultados encontrados:")
        for idx, v in enumerate(voices, 1):
            rate = v.get("rate", 0)
            desc = v.get("description", "Sin descripción")[:50]
            print(f"  {idx}. {v['name']} (Likes: {rate}) - {desc}...")
            
        print("  0. Cancelar")
        
        while True:
            try:
                pick = int(input(f"\nElige una voz para probar (1-{len(voices)}, 0 para salir): "))
                if pick == 0:
                    break
                if 1 <= pick <= len(voices):
                    selected_voice = voices[pick-1]
                    print(f"🔄 Preparando demostración para: {selected_voice['name']}")
                    
                    # Try to add it to the user's account to generate a custom phrase
                    pub_id = selected_voice.get("public_owner_id")
                    v_id = selected_voice.get("voice_id")
                    
                    added_id = self.add_shared_voice(pub_id, v_id, selected_voice['name'])
                    if added_id:
                        # Test with custom phrase
                        provider = ElevenLabsProvider(self.pod_config_path)
                        text = f"Esto es una prueba de voz para el personaje {char_name}."
                        out_path = os.path.join(os.path.dirname(self.pod_config_path), "temp_preview.mp3")
                        
                        # Use the new ID for the TTS call explicitly
                        # We bypass the provider's voice mapping by calling the API directly for the preview
                        url = f"https://api.elevenlabs.io/v1/text-to-speech/{added_id}"
                        headers = {"xi-api-key": self.api_key, "Content-Type": "application/json", "Accept": "audio/mpeg"}
                        data = {"text": text, "model_id": "eleven_multilingual_v2"}
                        res = requests.post(url, json=data, headers=headers)
                        
                        if res.status_code == 200:
                            with open(out_path, "wb") as f:
                                f.write(res.content)
                            print("🔊 Reproduciendo...")
                            self._play_audio(out_path)
                            os.remove(out_path)
                        else:
                            print("❌ Error al generar TTS de prueba.")
                    else:
                        print("⚠️ No se pudo añadir a tu cuenta. Reproduciendo preview pre-grabada...")
                        # Fallback to preview_url
                        prev_url = selected_voice.get("preview_url")
                        if prev_url:
                            res = requests.get(prev_url)
                            out_path = os.path.join(os.path.dirname(self.pod_config_path), "temp_preview.mp3")
                            with open(out_path, "wb") as f:
                                f.write(res.content)
                            self._play_audio(out_path)
                            os.remove(out_path)
                        else:
                            print("❌ No hay audio de previsualización disponible.")
                            
                    # Ask if they want to keep it
                    keep = input(f"\n¿Asignar esta voz a {char_name}? (s/n): ").lower()
                    if keep == 's':
                        config["characters"][sel]["elevenlabs_voice_id"] = v_id
                        self._save_config(config)
                        # Ensure we don't clean it up if we *did* manage to add it temporarily
                        if added_id and added_id in self.temp_voice_ids:
                            self.temp_voice_ids.remove(added_id)
                        print(f"✅ ¡Voz guardada correctamente para {char_name}! (Voice ID Comunitario: {v_id})")
                        break
                else:
                    print("Selección inválida.")
            except ValueError:
                print("Por favor, introduce un número.")
                
        # Cleanup temporary voices we tested but didn't keep
        print("🧹 Limpiando voces temporales de prueba...")
        for vid in self.temp_voice_ids:
            self.delete_voice(vid)
        self.temp_voice_ids.clear()
