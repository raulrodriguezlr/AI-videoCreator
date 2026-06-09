import os
import json

import structlog
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

log = structlog.get_logger(__name__)


class YoutubeUploader:
    """
    Gestiona la subida manual de vídeos a YouTube usando la API oficial v3.
    Maneja el flujo OAuth y asocia cada Pod con su propio token.
    """

    SCOPES = ['https://www.googleapis.com/auth/youtube.upload']

    def __init__(self, pod_name: str, pod_dir: str):
        self.pod_name = pod_name
        self.pod_dir = pod_dir
        self.youtube = None

    def _authenticate(self):
        """Maneja el flujo de autenticación OAuth 2.0 y guarda el token en el Pod."""
        token_path = os.path.join(self.pod_dir, "youtube_token.json")

        # Buscar el archivo de secretos en el Pod primero, y si no, en la raíz
        secrets_path = os.path.join(self.pod_dir, "client_secret.json")
        if not os.path.exists(secrets_path):
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            secrets_path = os.path.join(project_root, "client_secret.json")

        if not os.path.exists(secrets_path):
            log.error(
                "youtube_upload_missing_credentials",
                hint="Download OAuth 2.0 credentials from Google Cloud Console and save as client_secret.json",
            )
            return False

        creds = None
        if os.path.exists(token_path):
            try:
                creds = Credentials.from_authorized_user_file(token_path, self.SCOPES)
            except Exception:
                pass

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:
                    log.warning("youtube_token_refresh_failed", error=str(e))
                    creds = None

            if not creds:
                log.info("youtube_requesting_oauth", pod=self.pod_name)
                flow = InstalledAppFlow.from_client_secrets_file(secrets_path, self.SCOPES)
                # Abrimos puerto fijo o dejamos que elija uno
                creds = flow.run_local_server(port=0)

            # Guardar el token para la próxima vez
            with open(token_path, 'w') as token_file:
                token_file.write(creds.to_json())

        try:
            self.youtube = build('youtube', 'v3', credentials=creds)
            return True
        except Exception as e:
            log.error("youtube_client_build_failed", error=str(e))
            return False

    def upload_video(self, video_path: str, ep_dir: str):
        """
        Lee los metadatos y sube el vídeo seleccionado a YouTube.
        """
        metadata_path = os.path.join(ep_dir, "youtube_metadata.json")

        if not os.path.exists(metadata_path):
            log.error("youtube_upload_missing_metadata", path=metadata_path)
            return

        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        title = metadata.get("titulo_youtube")
        description = metadata.get("descripcion_youtube")

        if not title or not description:
            log.error("youtube_metadata_invalid_format", path=metadata_path)
            return

        log.info("youtube_uploading", title=title, video=os.path.basename(video_path))

        if not self._authenticate():
            return

        try:
            request_body = {
                'snippet': {
                    'title': title[:100],  # YouTube tiene un límite de 100 caracteres en el título
                    'description': description,
                    'tags': ['kids story', 'ai story', 'animation'],
                    'categoryId': '1'  # Film & Animation
                },
                'status': {
                    'privacyStatus': 'private', # Por seguridad, se sube en privado por defecto
                    'selfDeclaredMadeForKids': True
                }
            }

            media_file = MediaFileUpload(video_path, chunksize=-1, resumable=True)

            request = self.youtube.videos().insert(
                part="snippet,status",
                body=request_body,
                media_body=media_file
            )

            log.info("youtube_upload_in_progress", video=os.path.basename(video_path))
            response = request.execute()

            log.info(
                "youtube_upload_done",
                video_id=response['id'],
                url=f"https://youtu.be/{response['id']}",
                privacy="private",
            )

        except HttpError as e:
            log.error("youtube_api_error", status=e.resp.status, detail=e.content.decode('utf-8'))
        except Exception as e:
            log.error("youtube_upload_unexpected_error", error=str(e))
