from src.engines.visual_engine import VisualGenerator
import os
from dotenv import load_dotenv

load_dotenv()

# Force enable for this test
os.environ["GEMINI_MOCK_IMAGES"] = "True"

print("--- Test Inicio ---")
gen = VisualGenerator("pods/kids_story/config.json")

# Force the flag in the instance if needed, though variable import handles it.
# Actually variables.py is imported in visual_engine. 
# We rely on variables.py having GEMINI_MOCK_IMAGES = True (which I set).

try:
    path = "test_gemini_image.png"
    prompt = "A cute Squirrel holding a nut, 3d pixar style"
    print(f"Generando imagen para: {prompt}")
    gen._generate_mock_asset(prompt, path, 1)
    print(f"Generación finalizada. Chequea {path}")
except Exception as e:
    print(f"Error: {e}")
