import os
import sys
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from google import genai

load_dotenv()
api_key = os.getenv("GOOGLE_API_KEY")

client = genai.Client(api_key=api_key)

print("Available models:")
try:
    models = list(client.models.list())
    for model in models:
        print(model.name)
except Exception as e:
    print(f"Error: {e}")
