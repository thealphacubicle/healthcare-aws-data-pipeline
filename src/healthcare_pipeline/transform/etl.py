"""ETL Lambda, invoked directly by the ingest Lambda after each ingestion run.

Runs the steps in sequence within one invocation:

    read manifest -> clean each file -> join -> derive -> publish Parquet

Input: {"bucket": <raw bucket>, "manifest_key": <.../_manifest.json>}
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date
from typing import Any

import boto3

from healthcare_pipeline.config import PipelineConfig, load_config
from healthcare_pipeline.transform.clean import clean_dataset
from healthcare_pipeline.transform.derive import compute_derived_fields
from healthcare_pipeline.transform.join import join_datasets
from healthcare_pipeline.transform.parquet import table_to_parquet_bytes, to_curated_table

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_s3 = None


def s3_client():
    global _s3
    if _s3 is None:
        _s3 = boto3.client("s3")
    return _s3


def _read(bucket: str, key: str) -> bytes:
    return s3_client().get_object(Bucket=bucket, Key=key)["Body"].read()


def run_etl(
    *,
    config: PipelineConfig,
    raw_bucket: str,
    manifest_key: str,
    curated_bucket: str,
    tables_prefix: str = "tables",
) -> dict[str, Any]:
    s3 = s3_client()
    manifest = json.loads(_read(raw_bucket, manifest_key))
    run_id = manifest["run_id"]
    logger.info("Run %s changed datasets: %s", run_id, manifest["changed"])

    # 1. Clean every dataset listed in the manifest.
    frames = {}
    reports = []
    for name, raw_key in sorted(manifest["datasets"].items()):
        df, report = clean_dataset(
            _read(raw_bucket, raw_key), config.dataset(name), config.join_key
        )
        logger.info("Clean report: %s", json.dumps(report))
        frames[name] = df
        reports.append(report)

    # 2. Join, 3. derive.
    joined = join_datasets(config, frames)
    derived = compute_derived_fields(config, joined, date.fromisoformat(manifest["ingest_date"]))
    table = to_curated_table(derived, config.output_columns())

    # 4. Publish (version-aware, so out-of-order async runs never roll back):
    # run_ids sort chronologically. Skip if a newer snapshot already exists,
    # write ours, then delete only older snapshots. The table location is
    # never empty and a newer snapshot is never deleted by an older run.
    prefix = f"{tables_prefix}/{config.output_table}/"
    new_key = f"{prefix}part-{run_id}.parquet"
    summary = {
        "run_id": run_id,
        "curated_key": new_key,
        "rows": table.num_rows,
        "columns": table.num_columns,
        "reports": reports,
    }
    if _snapshots_newer_than(s3, curated_bucket, prefix, run_id):
        logger.warning("Run %s superseded by a newer snapshot; not publishing", run_id)
        return {**summary, "status": "superseded"}

    s3.put_object(Bucket=curated_bucket, Key=new_key, Body=table_to_parquet_bytes(table))

    # A newer run may have published while we were writing; if so, step aside.
    if _snapshots_newer_than(s3, curated_bucket, prefix, run_id):
        s3.delete_objects(Bucket=curated_bucket, Delete={"Objects": [{"Key": new_key}]})
        logger.warning("Run %s superseded during publish; removed its snapshot", run_id)
        return {**summary, "status": "superseded"}

    stale = [
        {"Key": key}
        for key in _list_snapshots(s3, curated_bucket, prefix)
        if _run_id_of(key, prefix) < run_id
    ]
    for i in range(0, len(stale), 1000):
        s3.delete_objects(
            Bucket=curated_bucket, Delete={"Objects": stale[i : i + 1000], "Quiet": True}
        )

    logger.info("Published %d rows to s3://%s/%s", table.num_rows, curated_bucket, new_key)
    return {**summary, "status": "published"}


def _list_snapshots(s3, bucket: str, prefix: str) -> list[str]:
    keys = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        keys.extend(o["Key"] for o in page.get("Contents", []))
    return keys


def _run_id_of(key: str, prefix: str) -> str:
    return key[len(prefix) :].removeprefix("part-").removesuffix(".parquet")


def _snapshots_newer_than(s3, bucket: str, prefix: str, run_id: str) -> bool:
    return any(_run_id_of(k, prefix) > run_id for k in _list_snapshots(s3, bucket, prefix))


def handler(event: dict, context: Any) -> dict[str, Any]:
    return run_etl(
        config=load_config(),
        raw_bucket=event["bucket"],
        manifest_key=event["manifest_key"],
        curated_bucket=os.environ["CURATED_BUCKET"],
        tables_prefix=os.environ.get("CURATED_TABLES_PREFIX", "tables"),
    )
