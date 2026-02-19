"""
Test rapido de generacion de imagenes con Hugging Face
"""

import os
from dotenv import load_dotenv

load_dotenv()

from src.engines.visual_engine import VisualGenerator

# Script de prueba simple (solo 2 escenas para ser rapido)
test_script = {
    "title": "Test de Imagenes con Hugging Face",
    "scenes": [
        {
            "scene_number": 1,
            "visual_prompt": "Una ardilla naranja llamada Tico con mochila verde en un bosque magico",
            "character": "Tico"
        },
        {
            "scene_number": 2,
            "visual_prompt": "Bosque encantado con arboles coloridos y luces brillantes",
            "character": "Environment"
        }
    ]
}

print("=" * 70)
print("TEST: Generacion de Imagenes Reales con Hugging Face (GRATIS)")
print("=" * 70)
print("\n[INFO] Esto puede tardar 30-60 segundos por imagen...")
print("[INFO] La primera vez el modelo puede tardar mas (se esta cargando)\n")

# Crear generador
gen = VisualGenerator("pods/kids_story/config.json")

# Generar visuales
try:
    paths = gen.generate_visuals(test_script)
    
    print("\n" + "=" * 70)
    print("[RESULTADO] Imagenes generadas:")
    print("=" * 70)
    
    for i, path in enumerate(paths, 1):
        if os.path.exists(path):
            size_kb = os.path.getsize(path) / 1024
            print(f"  {i}. [OK] {path}")
            print(f"      Tamano: {size_kb:.1f} KB")
        else:
            print(f"  {i}. [ERROR] No se genero: {path}")
    
    print("\n" + "=" * 70)
    print("[INFO] Revisa las imagenes en: pods/kids_story/assets/")
    print("=" * 70)
    
except Exception as e:
    print(f"\n[ERROR] {str(e)}")
    import traceback
    traceback.print_exc()
