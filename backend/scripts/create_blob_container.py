"""One-off script to create the Azure Blob container used for IOPP documents.

Run from backend/: python scripts/create_blob_container.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from azure.storage.blob import BlobServiceClient
from app.config import get_settings

settings = get_settings()


def main():
    if not settings.AZURE_STORAGE_CONNECTION_STRING:
        print("AZURE_STORAGE_CONNECTION_STRING is not set in .env")
        return

    client = BlobServiceClient.from_connection_string(settings.AZURE_STORAGE_CONNECTION_STRING)
    container = client.get_container_client(settings.AZURE_STORAGE_CONTAINER)

    if container.exists():
        print(f"Container '{settings.AZURE_STORAGE_CONTAINER}' already exists.")
    else:
        container.create_container()
        print(f"Created container '{settings.AZURE_STORAGE_CONTAINER}'.")


if __name__ == "__main__":
    main()
