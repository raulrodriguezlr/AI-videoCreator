"""
VideoEngine — Router que delega al provider seleccionado en variables.py.

No contiene lógica de generación. Solo es un punto de entrada que:
1. Lee VIDEO_PROVIDER de variables.py
2. Instancia el provider correcto (VeoProvider o OviProvider)
3. Delega la generación de vídeo al provider

Usage:
    engine = VideoEngine("pods/kids_story/config.json")
    engine.generate(script, "pods/kids_story/output/video.mp4")
"""

import os
import json
from src.providers import get_provider
from src.variables import VIDEO_PROVIDER
from src.providers.lyria_provider import LyriaProvider
from src.utils.audio_mixer import AudioMixer


class VideoEngine:
    """Router: selecciona y delega al provider de vídeo configurado."""

    def __init__(self, pod_config_path: str):
        """
        Inicializa el router con la configuración del pod.

        Args:
            pod_config_path: Path al config.json del pod.
        """
        self.pod_config_path = pod_config_path
        self.pod_dir = os.path.dirname(pod_config_path)
        self.output_dir = os.path.join(self.pod_dir, "output")
        os.makedirs(self.output_dir, exist_ok=True)

        # Factory: obtener el provider según variables.py
        self.provider = get_provider(pod_config_path)
        print(f"[VideoEngine] Provider activo: {VIDEO_PROVIDER}")

    def generate(
        self,
        script: dict,
        output_path: str = None,
        episode_dir: str = None,
        resume_from: int = 0,
        progress_manager=None,
    ) -> str:
        """
        Genera el vídeo completo delegando al provider.

        Args:
            script: Script estructurado con escenas.
            output_path: Path de salida (opcional, se genera automáticamente).
            episode_dir: Directory for the episode (clips saved to episode_dir/clips/).
            resume_from: Índice de escena desde donde retomar (0 = desde el inicio).
            progress_manager: ProgressManager para persistencia de estado.

        Returns:
            Path al vídeo final generado.
        """
        if not output_path:
            title = script.get("title", "video").replace(" ", "_")
            output_path = os.path.join(self.output_dir, f"{title}.mp4")

        # 1. Generate full video sequence using Provider (Veo or Ovi)
        final_video_path = self.provider.generate_full_video(
            script,
            output_path,
            episode_dir=episode_dir,
            resume_from=resume_from,
            progress_manager=progress_manager,
        )

        # --- BACKGROUND AUDIO DISABLED ---
        # El usuario ha reportado que la música de fondo (cancioncita de ~22s) no aporta y raya.
        # Se ha deshabilitado la generación y mezcla de audio de fondo.
        """
        # 2. Generate ambient background music using Lyria
        audio_prompt = script.get("ambient_audio_prompt", "").strip()
        
        if audio_prompt and os.path.exists(final_video_path):
            audio_dir = os.path.join(episode_dir, "audio") if episode_dir else self.output_dir
            lyria = LyriaProvider(output_dir=audio_dir)
            
            audio_file = f"bg_{os.path.basename(output_path).replace('.mp4', '.wav')}"
            
            generated_audio_path = lyria.generate_ambient_audio(audio_prompt, audio_file)
            
            # 3. Mix audio and video together
            if generated_audio_path:
                mixed_output = final_video_path.replace(".mp4", "_mixed.mp4")
                mixed_video_path = AudioMixer.mix_background_audio(
                    video_path=final_video_path,
                    audio_path=generated_audio_path,
                    output_path=mixed_output,
                    bg_volume=0.15  # Background volume level
                )
                
                # Replace the original video output with the mixed one
                if os.path.exists(mixed_video_path) and mixed_video_path != final_video_path:
                    try:
                        os.replace(mixed_video_path, final_video_path)
                        print(f"[VideoEngine] 🎵 Audio añadido al vídeo final exitosamente.")
                    except OSError as e:
                        print(f"[VideoEngine] ⚠️  No se pudo renombrar vídeo mezclado: {e}")
        """
        return final_video_path

    def check_provider(self) -> bool:
        """Verifica que el provider está disponible."""
        return self.provider.check_availability()
