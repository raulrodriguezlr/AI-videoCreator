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
import structlog
from videocreator.infrastructure.engine.providers import get_provider
from videocreator.infrastructure.engine.variables import VIDEO_PROVIDER

log = structlog.get_logger(__name__)


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
        log.info("video_engine.provider_ready", provider=VIDEO_PROVIDER)

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

        # Ambient background music (Lyria) was deliberately dropped: the ~22s
        # loop added nothing and distracted from the dialogue.
        return final_video_path

    def check_provider(self) -> bool:
        """Verifica que el provider está disponible."""
        return self.provider.check_availability()
