import os
import json
import time
import requests
from typing import List, Dict

from src.variables import MOCK_VISUALS_ENABLED, IMAGE_GENERATION_PROVIDER

class VisualGenerator:
    def __init__(self, pod_config_path: str):
        self.config = self._load_config(pod_config_path)
        
        # Determine which API to use
        self.provider = IMAGE_GENERATION_PROVIDER
        self.huggingface_key = os.getenv("HUGGINGFACE_API_KEY")
        self.sjinn_key = os.getenv("SJINN_API_KEY")
        
        # Use centralized config override OR missing key
        self.mock_mode = MOCK_VISUALS_ENABLED or (
            self.provider == "huggingface" and (not self.huggingface_key or self.huggingface_key == "your_huggingface_token_here")
        ) or (
            self.provider == "sjinn" and (not self.sjinn_key or self.sjinn_key == "your_sjinn_api_key_here")
        )
        
        # Ensure assets directory exists
        self.assets_dir = os.path.join(os.path.dirname(pod_config_path), "assets")
        os.makedirs(self.assets_dir, exist_ok=True)

    def _load_config(self, path: str) -> dict:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def generate_visuals(self, script: Dict) -> List[str]:
        """
        Generates images/videos for each scene in the script.
        Returns a list of local file paths to the generated assets.
        """
        generated_paths = []
        mode_label = "MODO MOCK" if self.mock_mode else f"MODO {self.provider.upper()}"
        print(f"--- Iniciando Generacion Visual ({mode_label}) ---")

        for i, scene in enumerate(script['scenes']):
            prompt = scene['visual_prompt']
            character = scene.get('character', 'Environment')
            
            output_filename = f"scene_{i+1:03d}_{character}.png"
            output_path = os.path.join(self.assets_dir, output_filename)
            
            if self.mock_mode:
                self._generate_mock_asset(prompt, output_path, i)
            elif self.provider == "huggingface":
                self._generate_huggingface_image(prompt, output_path, i)
            elif self.provider == "sjinn":
                self._generate_real_asset(prompt, output_path)
            else:
                # Fallback to mock
                print(f"[WARN] Provider desconocido: {self.provider}. Usando mock.")
                self._generate_mock_asset(prompt, output_path, i)
            
            generated_paths.append(output_path)
        
        return generated_paths

    def _generate_mock_asset(self, prompt: str, path: str, index: int):
        """
        Creates a dummy image. If GEMINI_MOCK_IMAGES is True, attempts to use Google Imagen API.
        Otherwise uses Pillow.
        """
        from src.variables import GEMINI_MOCK_IMAGES, GEMINI_MODEL_NAME
        
        if GEMINI_MOCK_IMAGES:
            try:
                print(f"[MOCK-GEMINI] Intentando generar imagen con API de Google para escena {index+1}...")
                self._generate_google_image(prompt, path)
                return
            except Exception as e:
                print(f"[WARN] Falló generación con Google ({e}). Usando Pillow.")

        # ... Fallback to Pillow logic ...
        print(f"[MOCK] Generando asset para escena {index+1}: {prompt[:30]}...")
        try:
            from PIL import Image, ImageDraw, ImageFont
            # Create a colored image based on index to differentiate scenes
            color = ((index * 50) % 255, (index * 80) % 255, (index * 110) % 255)
            img = Image.new('RGB', (1280, 720), color=color)
            d = ImageDraw.Draw(img)
            # Try to load a font, otherwise default
            try:
                # MacOS standard font
                font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 40)
            except:
                font = None
                
            d.text((50, 300), f"ESCENA {index+1}\n{prompt[:60]}...", fill=(255, 255, 255), font=font)
            img.save(path)
        except ImportError:
            with open(path, 'w') as f:
                f.write("Mock Image Content")

    def _generate_google_image(self, prompt: str, path: str):
        """
        Uses Gemini Image Models to enhance the prompt, then generates the actual image.
        Models like gemini-2.5-flash-image and gemini-3-pro-image-preview are for
        GENERATING prompts/descriptions, not images directly.
        
        For now, we'll use them to enhance the prompt and fall back to Pillow.
        TODO: Integrate with actual Imagen API when available.
        """
        from src.variables import GEMINI_IMAGE_MODELS
        import google.generativeai as genai
        
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise Exception("No Google API Key")
        
        genai.configure(api_key=api_key)
        
        # Try to use Gemini to enhance the prompt for better image generation
        enhanced_prompt = prompt
        try:
            model_name = GEMINI_IMAGE_MODELS[0] if GEMINI_IMAGE_MODELS else "gemini-2.5-flash"
            model = genai.GenerativeModel(model_name)
            
            enhancement_request = f"""Given this scene description: "{prompt}"
            
Create an enhanced, detailed image generation prompt optimized for DALL-E or Imagen.
Include: art style (3D Pixar/Disney), lighting, colors, mood, composition, camera angle.
Keep it suitable for children (ages 3-7).

Return ONLY the enhanced prompt, nothing else."""
            
            response = model.generate_content(enhancement_request)
            if hasattr(response, 'text') and response.text:
                enhanced_prompt = response.text.strip()
                print(f"[GEMINI] Prompt mejorado: {enhanced_prompt[:80]}...")
            
        except Exception as e:
            print(f"[INFO] No se pudo mejorar el prompt con Gemini: {str(e)[:100]}")
            # Continue with original prompt
        
        # For now, we don't have access to Imagen API directly
        # So we'll use Pillow with the enhanced prompt
        raise Exception(f"Gemini image models solo mejoran prompts. Usando Pillow mock.")

    def _generate_huggingface_image(self, prompt: str, path: str, index: int):
        """
        Generates image using Hugging Face Inference API with Stable Diffusion.
        100% FREE! Just need a Hugging Face token.
        Get yours at: https://huggingface.co/settings/tokens
        """
        from src.variables import (
            HUGGINGFACE_IMAGE_MODEL, 
            HUGGINGFACE_NUM_INFERENCE_STEPS,
            HUGGINGFACE_GUIDANCE_SCALE
        )
        
        api_key = self.huggingface_key
        if not api_key or api_key == "your_huggingface_token_here":
            raise Exception("No Hugging Face API Key. Get FREE token at https://huggingface.co/settings/tokens")
        
        # Enhance prompt for better Stable Diffusion results
        enhanced_prompt = f"3D Pixar style, Disney animation, vibrant colors, child-friendly, detailed textures, cinematic lighting. {prompt}"
        
        # Hugging Face Inference API endpoint
        api_url = f"https://router.huggingface.co/models/{HUGGINGFACE_IMAGE_MODEL}"
        
        headers = {"Authorization": f"Bearer {api_key}"}
        payload = {
            "inputs": enhanced_prompt,
            "parameters": {
                "num_inference_steps": HUGGINGFACE_NUM_INFERENCE_STEPS,
                "guidance_scale": HUGGINGFACE_GUIDANCE_SCALE,
            }
        }
        
        print(f"[HUGGINGFACE] Generando imagen {index+1} con {HUGGINGFACE_IMAGE_MODEL}...")
        print(f"[PROMPT] {enhanced_prompt[:100]}...")
        
        try:
            response = requests.post(api_url, headers=headers, json=payload, timeout=60)
            
            if response.status_code == 200:
                # Save the image
                with open(path, 'wb') as f:
                    f.write(response.content)
                print(f"[OK] Imagen generada: {path}")
            elif response.status_code == 503:
               # Model is loading, wait and retry
                print(f"[INFO] Modelo cargando... Reintentando en 20s...")
                time.sleep(20)
                response = requests.post(api_url, headers=headers, json=payload, timeout=60)
                if response.status_code == 200:
                    with open(path, 'wb') as f:
                        f.write(response.content)
                    print(f"[OK] Imagen generada: {path}")
                else:
                    raise Exception(f"Error {response.status_code}: {response.text}")
            else:
                raise Exception(f"Error {response.status_code}: {response.text}")
                
        except Exception as e:
            print(f"[ERROR] Fallo Hugging Face: {str(e)}")
            # Fallback to mock
            print(f"[FALLBACK] Usando Pillow mock...")
            self._generate_mock_asset(prompt, path, index)

    def _generate_real_asset(self, prompt: str, path: str):
        """
        Calls SJinn API to generate the asset.
        """
        # TODO: Implement actual SJinn API call format once documentation is verified
        # This is a placeholder structure based on typical Agent APIs
        print(f"[API] Solicitando a SJinn: {prompt[:30]}...")
        
        # Pseudo-code for API call
        # response = requests.post("https://api.sjinn.ai/v1/generate", json={...}, headers={...})
        # if response.status_code == 200:
        #     with open(path, 'wb') as f:
        #         f.write(response.content)
        # else:
        #     raise Exception(f"SJinn API Error: {response.text}")
        
        # For now, since we track the task ID but don't have the polling endpoint docs, 
        # we will fallback to Mock to let the user see the rest of the pipeline working (Audio/Script).
        print(f"[WARN] SJinn API Key detectada, pero falta documentación del endpoint de 'polling'. Usando MOCK por ahora.")
        self._generate_mock_asset(prompt, path, 999)
        # raise NotImplementedError("La implementación del cliente API real se hará cuando confirmes la API Key.")

if __name__ == "__main__":
    # Test execution
    from dotenv import load_dotenv
    load_dotenv()
    
    generator = VisualGenerator("pods/kids_story/config.json")
    
    # Dummy script for testing
    dummy_script = {
        "title": "Test Episode",
        "scenes": [
            {"visual_prompt": "Ardilla Tico saltando en un árbol", "character": "Tico"},
            {"visual_prompt": "Un bosque soleado", "character": "Narrador"}
        ]
    }
    
    paths = generator.generate_visuals(dummy_script)
    print(f"Assets generados en: {paths}")
