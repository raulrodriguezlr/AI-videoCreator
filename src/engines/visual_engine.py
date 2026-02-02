import os
import json
import time
import requests
from typing import List, Dict

from src.variables import MOCK_VISUALS_ENABLED

class VisualGenerator:
    def __init__(self, pod_config_path: str):
        self.config = self._load_config(pod_config_path)
        self.api_key = os.getenv("SJINN_API_KEY")
        # Use centralized config override OR missing key
        self.mock_mode = MOCK_VISUALS_ENABLED or (not self.api_key or self.api_key == "your_sjinn_api_key_here")
        
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
        print(f"--- Iniciando Generación Visual ({'ODO MOCK' if self.mock_mode else 'MODO API REAL'}) ---")

        for i, scene in enumerate(script['scenes']):
            prompt = scene['visual_prompt']
            character = scene.get('character', 'Environment')
            
            output_filename = f"scene_{i+1:03d}_{character}.png" # In real mode might be .mp4
            output_path = os.path.join(self.assets_dir, output_filename)
            
            if self.mock_mode:
                self._generate_mock_asset(prompt, output_path, i)
            else:
                self._generate_real_asset(prompt, output_path)
            
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
        Uses REST API to call Imagen 3 (or 2) since capabilities check was ambiguous.
        """
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise Exception("No Google API Key")
            
        # Try Imagen 2 endpoint (widely available in v1beta)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-001:predict?key={api_key}"
        
        headers = {'Content-Type': 'application/json'}
        data = {
            "instances": [
                {"prompt": f"Cartoon style, 3d pixar style. {prompt}"}
            ],
            "parameters": {
                "sampleCount": 1,
                "aspectRatio": "16:9"
            }
        }
        
        response = requests.post(url, headers=headers, json=data)
        
        if response.status_code != 200:
            # Try fallback to 'gemini-pro-vision'? No, that's input.
            # Try fallback to 'imagen-2'
            raise Exception(f"API Error {response.status_code}: {response.text}")
            
        # Parse response (It returns base64 string usually)
        results = response.json().get('predictions')
        if not results:
             raise Exception("No predictions in response")
             
        import base64
        # Depends on exact response format (bytesBase64Encoded or mimeType/bytes)
        b64_data = results[0].get('bytesBase64Encoded')
        
        if b64_data:
            with open(path, "wb") as f:
                f.write(base64.b64decode(b64_data))
            print(f"[MOCK-GEMINI] Imagen generada: {path}")
        else:
            raise Exception("No image data found in response")

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
