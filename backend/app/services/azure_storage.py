import uuid
from urllib.parse import urlparse, unquote
from azure.storage.blob import BlobServiceClient, ContentSettings

from app.config import get_settings

settings = get_settings()


async def upload_iopp_document(content: bytes, filename: str, content_type: str) -> str:
    """Upload a file to the configured Azure Blob container and return its URL."""
    client = BlobServiceClient.from_connection_string(settings.AZURE_STORAGE_CONNECTION_STRING)
    container = client.get_container_client(settings.AZURE_STORAGE_CONTAINER)
    try:
        container.create_container()
    except Exception:
        pass  # already exists

    blob_name = f"{uuid.uuid4()}_{filename}"
    blob = container.get_blob_client(blob_name)
    blob.upload_blob(content, overwrite=True, content_settings=ContentSettings(content_type=content_type))
    return blob.url


async def download_iopp_document(blob_url: str) -> tuple[bytes, str]:
    """Download a previously-uploaded blob by its stored URL.

    The storage account has public access disabled, so the UI can't link to
    blob_url directly — the backend fetches it (using the connection string's
    credentials) and streams it back to the authenticated frontend instead.
    """
    container_name, blob_name = unquote(urlparse(blob_url).path).lstrip("/").split("/", 1)
    client = BlobServiceClient.from_connection_string(settings.AZURE_STORAGE_CONNECTION_STRING)
    container = client.get_container_client(container_name)
    blob = container.get_blob_client(blob_name)
    downloader = blob.download_blob()
    content_type = downloader.properties.content_settings.content_type or "application/octet-stream"
    return downloader.readall(), content_type
