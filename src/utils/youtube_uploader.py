import os
import json
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError


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
            print(f"\n❌ Error: No se encontró 'client_secret.json'.")
            print("Para subir vídeos, debes descargar las credenciales OAuth 2.0 desde Google Cloud Console")
            print("y colocarlas como 'client_secret.json' en la raíz del proyecto o en el directorio del pod.")
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
                    print(f"⚠️ No se pudo refrescar el token ({e}). Solicitando nuevo...")
                    creds = None
            
            if not creds:
                print(f"\n🔐 Solicitando acceso para el canal del Pod '{self.pod_name}'...")
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
            print(f"❌ Error construyendo el cliente de YouTube: {e}")
            return False

    def upload_video(self, video_path: str, ep_dir: str):
        """
        Lee los metadatos y sube el vídeo seleccionado a YouTube.
        """
        metadata_path = os.path.join(ep_dir, "youtube_metadata.json")
        
        if not os.path.exists(metadata_path):
            print(f"❌ Error: No se encontraron metadatos en {metadata_path}.")
            print("Asegúrate de que el episodio tenga el archivo youtube_metadata.json.")
            return
            
        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
            
        title = metadata.get("titulo_youtube")
        description = metadata.get("descripcion_youtube")
        
        if not title or not description:
            print("❌ Error: youtube_metadata.json no tiene el formato correcto (titulo_youtube, descripcion_youtube).")
            return
            
        print(f"\n📤 Subiendo a YouTube...")
        print(f"   Título: {title}")
        print(f"   Vídeo: {os.path.basename(video_path)}")
        
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

            print("⏳ Subiendo vídeo (esto puede tardar varios minutos dependiendo de tu conexión)...")
            response = request.execute()

            print(f"\n✅ ¡Vídeo subido con éxito a YouTube!")
            print(f"🔗 Enlace privado: https://youtu.be/{response['id']}")
            print("ℹ️ Se ha subido como PRIVADO. Deberás entrar a YouTube Studio para publicarlo.")

        except HttpError as e:
            print(f"\n❌ Error de la API de YouTube: {e.resp.status}")
            print(e.content.decode('utf-8'))
        except Exception as e:
            print(f"\n❌ Error inesperado al subir el vídeo: {e}")
