import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()
try:
    genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
    for m in genai.list_models():
        if "generateContent" in m.supported_generation_methods or "generateImage" in m.supported_generation_methods:
             print(f"Name: {m.name}")
             print(f"Methods: {m.supported_generation_methods}")
             print("-" * 20)
except Exception as e:
    print(e)

print(f"Library Version: {genai.__version__}")
