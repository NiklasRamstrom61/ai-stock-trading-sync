"""Graph and Blob operations authenticated by the Function managed identity."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256

import requests
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient


class GraphError(RuntimeError):
    pass


class GraphWorkbook:
    def __init__(self, drive_id: str, item_id: str):
        self.drive_id, self.item_id = drive_id, item_id
        self.credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)

    def _headers(self) -> dict[str, str]:
        token = self.credential.get_token("https://graph.microsoft.com/.default").token
        return {"Authorization": f"Bearer {token}"}

    @property
    def url(self) -> str:
        return f"https://graph.microsoft.com/v1.0/drives/{self.drive_id}/items/{self.item_id}"

    def metadata(self) -> dict:
        response = requests.get(self.url, headers=self._headers(), params={"$select": "id,name,size,eTag,lastModifiedDateTime,file"}, timeout=60)
        if not response.ok:
            raise GraphError(f"metadata request failed: HTTP {response.status_code}")
        return response.json()

    def download(self) -> bytes:
        response = requests.get(f"{self.url}/content", headers=self._headers(), timeout=120, allow_redirects=True)
        if not response.ok:
            raise GraphError(f"download failed: HTTP {response.status_code}")
        return response.content

    def replace(self, content: bytes, expected_etag: str) -> dict:
        response = requests.put(f"{self.url}/content", headers={**self._headers(), "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "If-Match": expected_etag}, data=content, timeout=180)
        if response.status_code == 412:
            raise GraphError("workbook changed after download; upload rejected")
        if not response.ok:
            raise GraphError(f"upload failed: HTTP {response.status_code}")
        return response.json()


def durable_backup(content: bytes, connection: str, container: str, source_etag: str) -> str:
    service = BlobServiceClient.from_connection_string(connection)
    client = service.get_container_client(container)
    client.create_container(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"AI_Stock_Trading_Simulator_v1/{stamp}_{sha256(content).hexdigest()[:12]}.xlsx"
    client.upload_blob(name, content, overwrite=False, metadata={"source_etag": source_etag})
    return name
