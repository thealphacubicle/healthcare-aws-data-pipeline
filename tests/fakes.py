"""In-memory stand-ins for the AWS and Google clients used in tests."""

from __future__ import annotations

import io

from healthcare_pipeline.drive import DriveFile


class FakeS3:
    class exceptions:  # noqa: N801 - mirrors boto3's client.exceptions
        class NoSuchKey(Exception):
            pass

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, **_: object) -> dict:
        self.objects[(Bucket, Key)] = Body
        return {}

    def get_object(self, *, Bucket: str, Key: str) -> dict:
        try:
            return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}
        except KeyError:
            raise self.exceptions.NoSuchKey(Key) from None

    def delete_objects(self, *, Bucket: str, Delete: dict) -> dict:
        for obj in Delete["Objects"]:
            self.objects.pop((Bucket, obj["Key"]), None)
        return {}

    def keys(self, bucket: str, prefix: str = "") -> list[str]:
        return sorted(k for b, k in self.objects if b == bucket and k.startswith(prefix))

    def get_paginator(self, name: str):
        assert name == "list_objects_v2"
        s3 = self

        class Paginator:
            def paginate(self, *, Bucket: str, Prefix: str):
                yield {"Contents": [{"Key": k} for k in s3.keys(Bucket, Prefix)]}

        return Paginator()


class FakeDrive:
    def __init__(self) -> None:
        self.files: dict[str, tuple[DriveFile, bytes]] = {}
        self.queries: list[str | None] = []

    def add(self, file_id: str, name: str, modified: str, content: bytes) -> None:
        self.files[file_id] = (DriveFile(file_id, name, "text/csv", modified), content)

    def list_files(self, folder_id: str, modified_since: str | None) -> list[DriveFile]:
        self.queries.append(modified_since)
        return [
            f
            for f, _ in self.files.values()
            if not modified_since or f.modified_time >= modified_since
        ]

    def download(self, file: DriveFile) -> bytes:
        return self.files[file.id][1]
