"""Minimal Google Drive v3 client for incremental pulls from one folder.

Uses ``google-auth`` with ``requests`` directly instead of the full
``google-api-python-client`` to keep the Lambda package small.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

DRIVE_API = "https://www.googleapis.com/drive/v3"
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
GOOGLE_SHEET_MIME = "application/vnd.google-apps.spreadsheet"
CSV_MIME_TYPES = ("text/csv", GOOGLE_SHEET_MIME)


@dataclass(frozen=True)
class DriveFile:
    id: str
    name: str
    mime_type: str
    modified_time: str  # RFC 3339, e.g. "2026-09-30T12:34:56.789Z"


class DriveSource(Protocol):
    def list_files(self, folder_id: str, modified_since: str | None) -> list[DriveFile]: ...

    def download(self, file: DriveFile) -> bytes: ...


def build_query(folder_id: str, modified_since: str | None) -> str:
    mime_filter = " or ".join(f"mimeType = '{m}'" for m in CSV_MIME_TYPES)
    query = f"'{folder_id}' in parents and trashed = false and ({mime_filter})"
    if modified_since:
        # ">=" plus de-duplication in ingest.py avoids missing files that share
        # the watermark's timestamp.
        query += f" and modifiedTime >= '{modified_since}'"
    return query


class GoogleDriveClient:
    def __init__(self, session) -> None:
        self._session = session

    @classmethod
    def from_service_account_info(cls, info: dict | str) -> GoogleDriveClient:
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account

        if isinstance(info, str):
            info = json.loads(info)
        credentials = service_account.Credentials.from_service_account_info(
            info, scopes=DRIVE_SCOPES
        )
        return cls(AuthorizedSession(credentials))

    def list_files(self, folder_id: str, modified_since: str | None) -> list[DriveFile]:
        params = {
            "q": build_query(folder_id, modified_since),
            "fields": "nextPageToken, files(id, name, mimeType, modifiedTime)",
            "pageSize": 1000,
            "orderBy": "modifiedTime",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        files: list[DriveFile] = []
        while True:
            response = self._session.get(f"{DRIVE_API}/files", params=params, timeout=30)
            response.raise_for_status()
            body = response.json()
            files.extend(
                DriveFile(
                    id=f["id"],
                    name=f["name"],
                    mime_type=f["mimeType"],
                    modified_time=f["modifiedTime"],
                )
                for f in body.get("files", [])
            )
            token = body.get("nextPageToken")
            if not token:
                return files
            params["pageToken"] = token

    def download(self, file: DriveFile) -> bytes:
        if file.mime_type == GOOGLE_SHEET_MIME:
            url = f"{DRIVE_API}/files/{file.id}/export"
            params = {"mimeType": "text/csv"}
        else:
            url = f"{DRIVE_API}/files/{file.id}"
            params = {"alt": "media", "supportsAllDrives": "true"}
        response = self._session.get(url, params=params, timeout=120)
        response.raise_for_status()
        return response.content
