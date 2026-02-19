import requests
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("ELEVENLABS_API_KEY")
URL = "https://api.elevenlabs.io/v1/voices"

headers = {
  "Accept": "application/json",
  "xi-api-key": API_KEY
}

response = requests.get(URL, headers=headers)

if response.status_code == 200:
    voices = response.json().get('voices', [])
    print(f"Encontradas {len(voices)} voces:\n")
    for voice in voices:
        print(f"Nombre: {voice['name']}")
        print(f"ID: {voice['voice_id']}")
        print(f"Categoría: {voice.get('category', 'N/A')}")
        print("-" * 30)
else:
    print(f"Error: {response.status_code} - {response.text}")
