import os
import time
from dotenv import load_dotenv
from google import genai
from google.genai import types
import base64

load_dotenv('backend/.env', override=True)
client = genai.Client(api_key=os.getenv('GOOGLE_API_KEY'))

models = ['veo-3.1-generate-preview']

# Un pixel rojo 1x1 png valido
b64_img = b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
real_img = base64.b64decode(b64_img)

test_img = types.VideoGenerationReferenceImage(
    image=types.Image(image_bytes=real_img, mime_type='image/png'),
    reference_type="asset",
)

for m in models:
    try:
        print(f'Testing {m}...')
        result = client.models.generate_videos(
            model=m,
            prompt='A simple test',
            config=types.GenerateVideosConfig(
                reference_images=[test_img]
            )
        )
        print(f'   [+] {m} SUPPORTS reference_images!')
    except Exception as e:
        print(f'   [-] {m} FAILED: {e}')
    time.sleep(1)
