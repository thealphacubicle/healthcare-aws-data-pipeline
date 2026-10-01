import io
import json
from datetime import date

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fakes import FakeS3
from sample_data import ENCOUNTERS_CSV, FILES, INSURANCE_CSV, PATIENTS_CSV

from healthcare_pipeline.catalog import glue_table_input
from healthcare_pipeline.config import load_config
from healthcare_pipeline.transform import etl
from healthcare_pipeline.transform.clean import DataQualityError, clean_dataset
from healthcare_pipeline.transform.derive import compute_derived_fields
from healthcare_pipeline.transform.join import join_datasets
from healthcare_pipeline.transform.parquet import to_curated_table

CONFIG = load_config()


def _clean(name: str, csv: bytes) -> pd.DataFrame:
    return clean_dataset(csv, CONFIG.dataset(name), CONFIG.join_key)[0]


def test_clean_normalizes_headers_casts_types_and_reports() -> None:
    df, report = clean_dataset(PATIENTS_CSV, CONFIG.master, CONFIG.join_key)

    assert list(df.columns) == ["patient_id", "birth_date", "sex", "zip3"]
    assert df["patient_id"].tolist() == ["P001", "P002", "P003"]
    assert df.loc[1, "birth_date"] == pd.Timestamp("2010-01-01")  # whitespace stripped
    assert pd.isna(df.loc[2, "birth_date"])
    assert df["zip3"].tolist() == ["021", "100", "606"]  # leading zeros kept
    assert report == {
        "dataset": "patients",
        "rows_in": 5,
        "rows_out": 3,
        "dropped_null_keys": 1,
        "invalid_values": {"birth_date": 1},
    }


def test_clean_nulls_non_integer_bigints() -> None:
    df = _clean("encounters_summary", ENCOUNTERS_CSV)
    assert str(df["encounter_count"].dtype) == "Int64"
    assert df["encounter_count"].tolist()[:2] == [4, 0]
    assert pd.isna(df.loc[2, "encounter_count"])


def test_clean_rejects_duplicate_keys() -> None:
    csv = b"patient_id,payer_type,plan_start_date\nP1,A,2024-01-01\nP1,B,2024-02-01\n"
    with pytest.raises(DataQualityError, match="more than one row"):
        _clean("insurance", csv)


def test_clean_rejects_missing_columns() -> None:
    with pytest.raises(DataQualityError, match="plan_start_date"):
        _clean("insurance", b"patient_id,payer_type\nP1,A\n")


def _joined() -> pd.DataFrame:
    frames = {
        "patients": _clean("patients", PATIENTS_CSV),
        "encounters_summary": _clean("encounters_summary", ENCOUNTERS_CSV),
        "insurance": _clean("insurance", INSURANCE_CSV),
    }
    return join_datasets(CONFIG, frames)


def test_join_keeps_every_master_row() -> None:
    joined = _joined()
    assert joined["patient_id"].tolist() == ["P001", "P002", "P003"]
    assert joined["payer_type"].tolist()[:2] == ["Commercial", "Medicaid"]
    assert pd.isna(joined.loc[2, "payer_type"])


def test_derived_fields() -> None:
    df = compute_derived_fields(CONFIG, _joined(), date(2026, 6, 14))
    assert df["age_years"].tolist()[:2] == [45, 16]  # day before P001's birthday
    assert pd.isna(df.loc[2, "age_years"])
    assert df.loc[0, "days_since_last_encounter"] == -79
    assert df.loc[0, "avg_charge_per_encounter"] == 250.12
    assert pd.isna(df.loc[1, "avg_charge_per_encounter"])  # zero encounters


def test_curated_parquet_schema_matches_glue_table() -> None:
    df = compute_derived_fields(CONFIG, _joined(), date(2026, 10, 1))
    table = to_curated_table(df, CONFIG.output_columns())
    glue_columns = glue_table_input(CONFIG, "s3://b/t/")["StorageDescriptor"]["Columns"]

    assert table.schema.names == [c["Name"] for c in glue_columns]
    assert table.schema.field("birth_date").type == pa.date32()
    assert table.schema.field("encounter_count").type == pa.int64()
    assert table.column("birth_date").to_pylist()[0] == date(1980, 6, 15)


def test_etl_runs_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    s3 = FakeS3()
    monkeypatch.setattr(etl, "_s3", s3)
    raw_prefix = "ingest_date=2026-10-01/run_id=r1"
    for name, content in FILES.items():
        s3.put_object(Bucket="raw", Key=f"{raw_prefix}/{name}", Body=content)
    manifest = {
        "run_id": "r1",
        "ingest_date": "2026-10-01",
        "changed": ["patients"],
        "datasets": {
            "patients": f"{raw_prefix}/patients.csv",
            "encounters_summary": f"{raw_prefix}/encounters_summary.csv",
            "insurance": f"{raw_prefix}/insurance.csv",
        },
    }
    s3.put_object(
        Bucket="raw", Key=f"{raw_prefix}/_manifest.json", Body=json.dumps(manifest).encode()
    )
    s3.put_object(Bucket="curated", Key="tables/patient_summary/part-old.parquet", Body=b"old")

    result = etl.run_etl(
        config=CONFIG,
        raw_bucket="raw",
        manifest_key=f"{raw_prefix}/_manifest.json",
        curated_bucket="curated",
    )

    assert result["curated_key"] == "tables/patient_summary/part-r1.parquet"
    assert (result["rows"], result["columns"]) == (3, 12)
    assert [r["dataset"] for r in result["reports"]] == [
        "encounters_summary",
        "insurance",
        "patients",
    ]
    # The previous snapshot is replaced.
    assert s3.keys("curated") == ["tables/patient_summary/part-r1.parquet"]
    table = pq.read_table(io.BytesIO(s3.objects[("curated", result["curated_key"])]))
    assert table.column("age_years").to_pylist() == [46, 16, None]
