import json
from datetime import UTC, datetime

from fakes import FakeDrive, FakeS3
from sample_data import FILES

from healthcare_pipeline.config import load_config
from healthcare_pipeline.drive import build_query
from healthcare_pipeline.ingest import STATE_KEY, run_ingestion

BUCKET = "raw"


def _run(drive: FakeDrive, s3: FakeS3, when: datetime, etl_calls: list | None = None) -> dict:
    return run_ingestion(
        config=load_config(),
        drive=drive,
        s3=s3,
        bucket=BUCKET,
        folder_id="folder",
        start_etl=etl_calls.append if etl_calls is not None else None,
        now=when,
    )


def _drive_with_all_files() -> FakeDrive:
    drive = FakeDrive()
    for i, (name, content) in enumerate(FILES.items()):
        drive.add(f"id-{name}", name, f"2026-09-30T10:00:0{i}.000Z", content)
    drive.add("id-notes", "notes.csv", "2026-09-30T10:00:09.000Z", b"x\n1\n")
    return drive


def test_first_run_uploads_all_files_writes_manifest_and_starts_etl() -> None:
    drive, s3, etl_calls = _drive_with_all_files(), FakeS3(), []
    result = _run(drive, s3, datetime(2026, 10, 1, 6, tzinfo=UTC), etl_calls)

    assert result["status"] == "ingested"
    assert result["changed"] == ["encounters_summary", "insurance", "patients"]
    prefix = "ingest_date=2026-10-01/run_id=20261001T060000Z"
    assert s3.keys(BUCKET, prefix) == [
        f"{prefix}/_manifest.json",
        f"{prefix}/encounters_summary.csv",
        f"{prefix}/insurance.csv",
        f"{prefix}/patients.csv",
    ]
    manifest = json.loads(s3.objects[(BUCKET, result["manifest_key"])])
    assert manifest["datasets"]["patients"] == f"{prefix}/patients.csv"
    assert drive.queries == [None]
    assert etl_calls == [{"bucket": BUCKET, "manifest_key": result["manifest_key"]}]


def test_unchanged_files_are_not_reingested() -> None:
    drive, s3, etl_calls = _drive_with_all_files(), FakeS3(), []
    _run(drive, s3, datetime(2026, 10, 1, 6, tzinfo=UTC))
    result = _run(drive, s3, datetime(2026, 10, 2, 6, tzinfo=UTC), etl_calls)

    assert result["status"] == "no_changes"
    assert etl_calls == []
    # The watermark from the first run is used for the incremental query.
    assert drive.queries[-1] == "2026-09-30T10:00:02.000Z"
    assert s3.keys(BUCKET, "ingest_date=2026-10-02") == []


def test_changed_file_triggers_manifest_with_carried_forward_keys() -> None:
    drive, s3 = _drive_with_all_files(), FakeS3()
    _run(drive, s3, datetime(2026, 10, 1, 6, tzinfo=UTC))
    drive.add("id-insurance.csv", "insurance.csv", "2026-10-01T12:00:00.000Z", b"new")
    result = _run(drive, s3, datetime(2026, 10, 2, 6, tzinfo=UTC))

    assert result["changed"] == ["insurance"]
    manifest = json.loads(s3.objects[(BUCKET, result["manifest_key"])])
    assert manifest["datasets"]["insurance"].startswith("ingest_date=2026-10-02/")
    assert manifest["datasets"]["patients"].startswith("ingest_date=2026-10-01/")
    state = json.loads(s3.objects[(BUCKET, STATE_KEY)])
    assert state["watermark"] == "2026-10-01T12:00:00.000Z"


def test_incomplete_dataset_set_does_not_write_manifest_or_start_etl() -> None:
    drive, s3, etl_calls = FakeDrive(), FakeS3(), []
    drive.add("p", "patients.csv", "2026-09-30T10:00:00.000Z", FILES["patients.csv"])
    result = _run(drive, s3, datetime(2026, 10, 1, 6, tzinfo=UTC), etl_calls)

    assert result["manifest_key"] is None
    assert result["missing"] == ["encounters_summary", "insurance"]
    assert not any(k.endswith("_manifest.json") for k in s3.keys(BUCKET))
    assert etl_calls == []


def test_drive_query_filters_folder_type_and_watermark() -> None:
    query = build_query("abc123", "2026-09-30T10:00:00.000Z")
    assert "'abc123' in parents" in query
    assert "trashed = false" in query
    assert "mimeType = 'text/csv'" in query
    assert "modifiedTime >= '2026-09-30T10:00:00.000Z'" in query
    assert "modifiedTime" not in build_query("abc123", None)
