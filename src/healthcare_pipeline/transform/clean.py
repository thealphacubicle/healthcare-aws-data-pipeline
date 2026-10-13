"""Clean one raw CSV into a typed DataFrame that matches its DatasetSpec."""

from __future__ import annotations

import io
import re

import pandas as pd

from healthcare_pipeline.config import DatasetSpec

TRUE_VALUES = {"true", "t", "yes", "y", "1"}
FALSE_VALUES = {"false", "f", "no", "n", "0"}


class DataQualityError(ValueError):
    """Raised when a file cannot be cleaned into a usable dataset."""


def normalize_column_name(name: str) -> str:
    name = re.sub(r"[^0-9a-zA-Z]+", "_", name.strip()).strip("_")
    return name.lower()


def _cast(series: pd.Series, logical_type: str) -> pd.Series:
    if logical_type == "string":
        return series.astype("string")
    if logical_type == "bigint":
        numeric = pd.to_numeric(series, errors="coerce")
        numeric = numeric.where(numeric.isna() | (numeric % 1 == 0))
        return numeric.astype("Int64")
    if logical_type == "double":
        return pd.to_numeric(series, errors="coerce").astype("Float64")
    if logical_type == "boolean":
        lowered = series.str.lower()
        mapped = pd.Series(pd.NA, index=series.index, dtype="boolean")
        mapped[lowered.isin(TRUE_VALUES)] = True
        mapped[lowered.isin(FALSE_VALUES)] = False
        return mapped
    if logical_type == "date":
        return pd.to_datetime(series, errors="coerce").dt.normalize()
    if logical_type == "timestamp":
        return pd.to_datetime(series, errors="coerce", utc=True).dt.tz_localize(None)
    raise ValueError(f"Unknown logical type {logical_type!r}")


def clean_dataset(raw_csv: bytes, spec: DatasetSpec, join_key: str) -> tuple[pd.DataFrame, dict]:
    """Return the cleaned frame plus a small data-quality report."""
    df = pd.read_csv(io.BytesIO(raw_csv), dtype=str, keep_default_na=False)
    df.columns = [normalize_column_name(c) for c in df.columns]

    missing = [c for c in spec.columns if c not in df.columns]
    if missing:
        raise DataQualityError(f"{spec.name}: missing required columns {missing}")

    df = df[list(spec.columns)]
    df = df.apply(lambda s: s.str.strip()).replace("", pd.NA)
    rows_in = len(df)
    df = df.dropna(how="all").drop_duplicates()

    invalid_values: dict[str, int] = {}
    for column, logical_type in spec.columns.items():
        before = df[column].notna().sum()
        df[column] = _cast(df[column], logical_type)
        lost = int(before - df[column].notna().sum())
        if lost:
            invalid_values[column] = lost

    null_keys = int(df[join_key].isna().sum())
    df = df[df[join_key].notna()]
    duplicate_keys = df[join_key][df[join_key].duplicated()].unique().tolist()
    if duplicate_keys:
        sample = duplicate_keys[:5]
        raise DataQualityError(
            f"{spec.name}: {len(duplicate_keys)} {join_key} values appear on more than one "
            f"row (e.g. {sample}); aggregate this file to one row per key before joining"
        )

    report = {
        "dataset": spec.name,
        "rows_in": rows_in,
        "rows_out": len(df),
        "dropped_null_keys": null_keys,
        "invalid_values": invalid_values,
    }
    return df.reset_index(drop=True), report
