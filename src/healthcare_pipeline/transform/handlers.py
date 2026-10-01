"""Lambda handlers invoked in sequence by the Step Functions state machine.

    PrepareRun -> Map(CleanDataset) -> JoinDatasets -> DeriveAndPublish

Intermediate results are passed between steps as Parquet files under the
curated bucket's ``staging/`` prefix (expired by an S3 lifecycle rule); the
state machine only carries S3 keys.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date
from typing import Any

import boto3

from healthcare_pipeline.config import load_config
from healthcare_pipeline.transform.clean import clean_dataset
from healthcare_pipeline.transform.derive import compute_derived_fields
from healthcare_pipeline.transform.join import join_datasets
from healthcare_pipeline.transform.parquet import (
    frame_to_parquet_bytes,
    parquet_bytes_to_frame,
    table_to_parquet_bytes,
    to_curated_table,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_s3 = None


def s3_client():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3")
    return _s3


def _curated_bucket() -> str:
    return os.environ["CURATED_BUCKET"]


def _staging_prefix(run_id: str) -> str:
    return f"staging/run_id={run_id}"


def _table_prefix(table: str) -> str:
    return f"{os.environ.get('CURATED_TABLES_PREFIX', 'tables')}/{table}/"


def _read(bucket: str, key: str) -> bytes:
    return s3_client().get_object(Bucket=bucket, Key=key)["Body"].read()


def prepare_run(event: dict, context: Any) -> dict:
    """Input: {"bucket", "manifest_key"} from the S3 -> EventBridge rule."""
    manifest = json.loads(_read(event["bucket"], event["manifest_key"]))
    logger.info("Run %s changed datasets: %s", manifest["run_id"], manifest["changed"])
    return {
        "run_id": manifest["run_id"],
        "ingest_date": manifest["ingest_date"],
        "raw_bucket": event["bucket"],
        "datasets": [
            {"name": name, "raw_key": key} for name, key in sorted(manifest["datasets"].items())
        ],
    }


def clean(event: dict, context: Any) -> dict:
    """Input: {"run_id", "raw_bucket", "name", "raw_key"} (one Map iteration)."""
    config = load_config()
    spec = config.dataset(event["name"])
    df, report = clean_dataset(_read(event["raw_bucket"], event["raw_key"]), spec, config.join_key)
    logger.info("Clean report: %s", json.dumps(report))
    key = f"{_staging_prefix(event['run_id'])}/clean/{spec.name}.parquet"
    s3_client().put_object(Bucket=_curated_bucket(), Key=key, Body=frame_to_parquet_bytes(df))
    return {"name": spec.name, "staging_key": key, "report": report}


def join(event: dict, context: Any) -> dict:
    """Input: {"run_id", "cleaned": [{"name", "staging_key", ...}, ...]}."""
    config = load_config()
    bucket = _curated_bucket()
    frames = {
        item["name"]: parquet_bytes_to_frame(_read(bucket, item["staging_key"]))
        for item in event["cleaned"]
    }
    joined = join_datasets(config, frames)
    key = f"{_staging_prefix(event['run_id'])}/joined.parquet"
    s3_client().put_object(Bucket=bucket, Key=key, Body=frame_to_parquet_bytes(joined))
    return {"joined_key": key, "rows": len(joined)}


def derive_and_publish(event: dict, context: Any) -> dict:
    """Input: {"run_id", "ingest_date", "joined_key"}.

    Writes the new snapshot first, then deletes the previous one, so the
    Athena table location is never empty (readers can briefly see both).
    """
    config = load_config()
    bucket = _curated_bucket()
    s3 = s3_client()

    joined = parquet_bytes_to_frame(_read(bucket, event["joined_key"]))
    derived = compute_derived_fields(config, joined, date.fromisoformat(event["ingest_date"]))
    table = to_curated_table(derived, config.output_columns())

    prefix = _table_prefix(config.output_table)
    new_key = f"{prefix}part-{event['run_id']}.parquet"
    s3.put_object(Bucket=bucket, Key=new_key, Body=table_to_parquet_bytes(table))

    stale = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        stale.extend({"Key": o["Key"]} for o in page.get("Contents", []) if o["Key"] != new_key)
    for page in s3.get_paginator("list_objects_v2").paginate(
        Bucket=bucket, Prefix=_staging_prefix(event["run_id"])
    ):
        stale.extend({"Key": o["Key"]} for o in page.get("Contents", []))
    for i in range(0, len(stale), 1000):
        s3.delete_objects(Bucket=bucket, Delete={"Objects": stale[i : i + 1000], "Quiet": True})

    logger.info("Published %d rows to s3://%s/%s", table.num_rows, bucket, new_key)
    return {"curated_key": new_key, "rows": table.num_rows, "columns": table.num_columns}
