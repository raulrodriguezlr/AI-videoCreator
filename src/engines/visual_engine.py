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
        Creates a dummy image with text using Pillow purely for testing pipeline flow.
        """
        print(f"[MOCK] Generando asset para escena {index+1}: {prompt[:30]}...")
        try:
            from PIL import Image, ImageDraw
            # Create a colored image based on index to differentiate scenes
            color = ((index * 50) % 255, (index * 80) % 255, (index * 110) % 255)
            img = Image.new('RGB', (1280, 720), color=color)
            d = ImageDraw.Draw(img)
            d.text((10, 10), f"ESCENA {index+1}\n{prompt[:50]}...", fill=(255, 255, 255))
            img.save(path)
        except ImportError:
            # Fallback if Pillow is missing (though it's in requirements)
            with open(path, 'w') as f:
                f.write("Mock Image Content")

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
