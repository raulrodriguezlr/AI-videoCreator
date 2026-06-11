"""Test rapido: generar video con Veo 3.0 GA (modelo que SI existe)."""
import os, sys, time
sys.stdout.reconfigure(encoding='utf-8')
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "backend", ".env"))
from google import genai
from google.genai import types

client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

MODEL = "veo-3.0-generate-001"
PROMPT = "A fluffy orange cat sitting on a windowsill, watching raindrops on the glass. Warm indoor lighting, cozy atmosphere. Medium shot, static camera."

print(f"[MODEL] {MODEL}")
print(f"[PROMPT] {PROMPT[:80]}...")
print("[STATUS] Enviando peticion a Veo...")

try:
    operation = client.models.generate_videos(
        model=MODEL,
        prompt=PROMPT,
        config=types.GenerateVideosConfig(
            aspect_ratio="16:9",
            resolution="720p",
            number_of_videos=1,
        ),
    )
    print(f"[OK] Operacion creada")

    elapsed = 0
    while not operation.done:
        if elapsed >= 360:
            print("[TIMEOUT]")
            break
        print(f"   Polling... {elapsed}s")
        time.sleep(10)
        elapsed += 10
        operation = client.operations.get(operation=operation)

    print(f"\n[DONE] operation.done = {operation.done}")

    if hasattr(operation, "error") and operation.error:
        print(f"[ERROR] {operation.error}")
        sys.exit(1)

    if not hasattr(operation, "response") or not operation.response:
        print("[ERROR] Respuesta vacia")
        sys.exit(1)

    response = operation.response
    print(f"[INFO] Response type: {type(response).__name__}")

    has_gv = hasattr(response, "generated_videos")
    gv = response.generated_videos if has_gv else None

    if gv:
        video = gv[0]
        out_path = os.path.join(os.path.dirname(__file__), "test_output.mp4")
        client.files.download(file=video.video)
        video.video.save(out_path)
        sz = os.path.getsize(out_path)
        print(f"[SUCCESS] Video guardado: {out_path} ({sz/1024/1024:.1f} MB)")
    else:
        print(f"[FAIL] No generated_videos")
        rai = getattr(response, "rai_media_filtered_count", None)
        print(f"[RAI] filtered: {rai}")
        print(f"[RESP] {repr(response)[:500]}")

except Exception as e:
    print(f"[EXCEPTION] {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
