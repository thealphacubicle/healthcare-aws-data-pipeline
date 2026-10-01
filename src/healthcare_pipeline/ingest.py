"""Scheduled Lambda: incremental pull from Google Drive into the S3 raw zone.

Each run lists files modified since the stored watermark, uploads new versions
to ``ingest_date=YYYY-MM-DD/run_id=<id>/<file_name>`` and then writes a
``_manifest.json`` next to them. The manifest names the latest S3 copy of
*every* dataset (unchanged files are carried forward), so the transform always
joins a complete set. Only the manifest key triggers Step Functions, which
means one execution per ingestion run rather than one per file.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

from healthcare_pipeline.config import PipelineConfig, load_config
from healthcare_pipeline.drive import DriveFile, DriveSource

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

STATE_KEY = "_state/ingest_state.json"
MANIFEST_NAME = "_manifest.json"


def load_state(s3, bucket: str) -> dict[str, Any]:
    try:
        body = s3.get_object(Bucket=bucket, Key=STATE_KEY)["Body"].read()
    except s3.exceptions.NoSuchKey:
        return {"watermark": None, "datasets": {}}
    return json.loads(body)


def select_changed_files(
    config: PipelineConfig, files: list[DriveFile], state: dict[str, Any]
) -> dict[str, DriveFile]:
    """Map dataset name -> newest Drive file that differs from what was ingested."""
    newest: dict[str, DriveFile] = {}
    for file in files:
        spec = config.dataset_for_file(file.name)
        if spec is None:
            logger.info("Ignoring unconfigured Drive file %s", file.name)
            continue
        current = newest.get(spec.name)
        if current is None or file.modified_time > current.modified_time:
            newest[spec.name] = file

    changed: dict[str, DriveFile] = {}
    for name, file in newest.items():
        previous = state["datasets"].get(name)
        if (
            previous
            and previous["drive_file_id"] == file.id
            and previous["modified_time"] == file.modified_time
        ):
            continue
        changed[name] = file
    return changed


def run_ingestion(
    *,
    config: PipelineConfig,
    drive: DriveSource,
    s3,
    bucket: str,
    folder_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    state = load_state(s3, bucket)
    files = drive.list_files(folder_id, state["watermark"])
    changed = select_changed_files(config, files, state)
    if not changed:
        logger.info("No new or changed files since %s", state["watermark"])
        return {"status": "no_changes", "watermark": state["watermark"]}

    run_id = now.strftime("%Y%m%dT%H%M%SZ")
    prefix = f"ingest_date={now:%Y-%m-%d}/run_id={run_id}"
    datasets = dict(state["datasets"])
    for name, file in sorted(changed.items()):
        key = f"{prefix}/{config.dataset(name).file_name}"
        s3.put_object(Bucket=bucket, Key=key, Body=drive.download(file), ContentType="text/csv")
        datasets[name] = {
            "s3_key": key,
            "drive_file_id": file.id,
            "modified_time": file.modified_time,
        }
        logger.info(
            "Uploaded %s (modified %s) to s3://%s/%s", file.name, file.modified_time, bucket, key
        )

    watermark = max([state["watermark"] or "", *(f.modified_time for f in changed.values())])
    new_state = {"watermark": watermark, "datasets": datasets}

    missing = [d.name for d in config.datasets if d.name not in datasets]
    manifest_key = None
    if missing:
        # The join needs every file; wait for the rest to appear in Drive.
        logger.warning("Not triggering transform; datasets never ingested: %s", missing)
    else:
        manifest_key = f"{prefix}/{MANIFEST_NAME}"
        manifest = {
            "run_id": run_id,
            "ingest_date": f"{now:%Y-%m-%d}",
            "changed": sorted(changed),
            "datasets": {name: datasets[name]["s3_key"] for name in sorted(datasets)},
        }
        s3.put_object(
            Bucket=bucket,
            Key=manifest_key,
            Body=json.dumps(manifest, indent=2).encode(),
            ContentType="application/json",
        )

    # State is written last so a failed run is simply retried next time.
    s3.put_object(Bucket=bucket, Key=STATE_KEY, Body=json.dumps(new_state, indent=2).encode())
    return {
        "status": "ingested",
        "run_id": run_id,
        "changed": sorted(changed),
        "missing": missing,
        "manifest_key": manifest_key,
        "watermark": watermark,
    }


def _google_credentials(parameter_name: str) -> str:
    import boto3

    ssm = boto3.client("ssm")
    return ssm.get_parameter(Name=parameter_name, WithDecryption=True)["Parameter"]["Value"]


def handler(event: dict, context: Any) -> dict[str, Any]:
    import boto3

    from healthcare_pipeline.drive import GoogleDriveClient

    drive = GoogleDriveClient.from_service_account_info(
        _google_credentials(os.environ["GOOGLE_CREDENTIALS_PARAMETER"])
    )
    return run_ingestion(
        config=load_config(),
        drive=drive,
        s3=boto3.client("s3"),
        bucket=os.environ["RAW_BUCKET"],
        folder_id=os.environ["DRIVE_FOLDER_ID"],
    )
