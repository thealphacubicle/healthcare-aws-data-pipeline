"""Parquet serialization with a schema that matches the Glue table exactly."""

from __future__ import annotations

import io

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ARROW_TYPES: dict[str, pa.DataType] = {
    "string": pa.string(),
    "bigint": pa.int64(),
    "double": pa.float64(),
    "boolean": pa.bool_(),
    "date": pa.date32(),
    "timestamp": pa.timestamp("ms"),
}


def arrow_schema(columns: list[tuple[str, str]]) -> pa.Schema:
    return pa.schema([pa.field(name, ARROW_TYPES[t]) for name, t in columns])


def to_curated_table(df: pd.DataFrame, columns: list[tuple[str, str]]) -> pa.Table:
    """Select and order the curated columns, casting to the catalog types."""
    df = df[[name for name, _ in columns]].copy()
    for name, logical_type in columns:
        if logical_type == "date":
            df[name] = df[name].dt.date.astype(object).where(df[name].notna(), None)
    table = pa.Table.from_pandas(df, preserve_index=False)
    return table.cast(arrow_schema(columns))


def frame_to_parquet_bytes(df: pd.DataFrame) -> bytes:
    """Intermediate (staging) files keep pandas dtypes for the next step."""
    buffer = io.BytesIO()
    df.to_parquet(buffer, engine="pyarrow", index=False)
    return buffer.getvalue()


def table_to_parquet_bytes(table: pa.Table) -> bytes:
    buffer = io.BytesIO()
    pq.write_table(table, buffer, compression="snappy")
    return buffer.getvalue()


def parquet_bytes_to_frame(data: bytes) -> pd.DataFrame:
    return pd.read_parquet(io.BytesIO(data), engine="pyarrow")
