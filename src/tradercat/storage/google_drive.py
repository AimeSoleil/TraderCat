import os
import logging
from typing import Optional
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

class GoogleDriveStorage:
    SCOPES = ['https://www.googleapis.com/auth/drive.file']
    
    def __init__(self, 
                 client_secret_file: Optional[str] = None, 
                 token_file: Optional[str] = None, 
                 folder_id: Optional[str] = None):
        """
        Initialize the Google Drive Storage handler.
        
        Configuration priority:
        1. Constructor Argument
        2. Environment Variable (GOOGLE_CLIENT_SECRET_FILE, GOOGLE_TOKEN_FILE, GOOGLE_DRIVE_FOLDER_ID)
        3. Default Value ("credentials.json", "token.json")

        :param client_secret_file: Path to the OAuth client secret JSON.
        :param token_file: Path to save/load user credentials.
        :param folder_id: The ID of the Google Drive folder to potential uploads.
        """
        self.client_secret_file = (
            client_secret_file 
            or os.environ.get("GOOGLE_CLIENT_SECRET_FILE") 
            or "credentials.json"
        )
        
        self.token_file = (
            token_file 
            or os.environ.get("GOOGLE_TOKEN_FILE") 
            or "token.json"
        )
        
        self.folder_id = folder_id or os.environ.get("GOOGLE_DRIVE_FOLDER_ID")
        self._service = None

    @property
    def is_available(self) -> bool:
        """Check if necessary credentials exist to attempt connection."""
        # Either we have a token ready, or we have the secret to generate one.
        return os.path.exists(self.token_file) or os.path.exists(self.client_secret_file)

    def _get_credentials(self) -> Optional[Credentials]:
        """Handles the OAuth2 flow to get valid credentials."""
        creds = None
        
        # 1. Load existing token
        if os.path.exists(self.token_file):
            try:
                creds = Credentials.from_authorized_user_file(self.token_file, self.SCOPES)
            except Exception as e:
                logger.warning(f"⚠️ Invalid token file: {e}")

        # 2. Refresh or Login if needed
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    logger.debug("🔄 Refreshing Google Drive token...")
                    creds.refresh(Request())
                except Exception as e:
                    logger.error(f"❌ Token refresh failed: {e}")
                    creds = None
            
            if not creds:
                if not os.path.exists(self.client_secret_file):
                    logger.error(f"❌ Client secret '{self.client_secret_file}' not found.")
                    return None
                    
                logger.info("🔐 Initiating Google Login (Local Browser)...")
                try:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        self.client_secret_file, self.SCOPES)
                    creds = flow.run_local_server(port=0)
                except Exception as e:
                    logger.error(f"❌ OAuth flow failed: {e}")
                    return None
            
            # Save the fresh token
            with open(self.token_file, 'w') as token:
                token.write(creds.to_json())

        return creds

    def get_service(self):
        """Returns the authenticated Drive API service."""
        if self._service:
            return self._service
            
        creds = self._get_credentials()
        if creds:
            self._service = build('drive', 'v3', credentials=creds)
            return self._service
        return None

    def upload_file(self, filepath: str, mime_type: str = 'text/csv') -> Optional[str]:
        """
        Uploads a file to Google Drive.
        
        :param filepath: Local path to the file.
        :param mime_type: MIME type of the file.
        :return: File ID if successful, None otherwise.
        """
        if not self.is_available:
            logger.warning("⚠️ Google Drive setup incomplete (missing credentials).")
            return None

        service = self.get_service()
        if not service:
            return None

        try:
            filename = os.path.basename(filepath)
            file_metadata = {'name': filename}
            
            if self.folder_id:
                file_metadata['parents'] = [self.folder_id]

            media = MediaFileUpload(filepath, mimetype=mime_type)
            
            file = service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()
            
            file_id = file.get('id')
            logger.info(f"☁️ Uploaded '{filename}' to Google Drive (ID: {file_id})")
            return file_id
            
        except HttpError as error:
            logger.error(f"❌ Google Drive HTTP Error: {error}")
        except Exception as e:
            logger.error(f"❌ Upload failed: {e}")
        
        return None