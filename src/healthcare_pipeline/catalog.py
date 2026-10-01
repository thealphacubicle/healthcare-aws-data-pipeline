"""Glue Data Catalog table definition for the curated Parquet output.

Registered once by hand (``scripts/register_table.py``) instead of running a
Glue Crawler. Both forms below are generated from pipeline_config.json, so the
catalog cannot drift from what the ETL writes.
"""

from __future__ import annotations

from healthcare_pipeline.config import GLUE_TYPES, PipelineConfig

PARQUET_INPUT_FORMAT = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
PARQUET_OUTPUT_FORMAT = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"
PARQUET_SERDE = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"


def table_location(bucket: str, config: PipelineConfig, tables_prefix: str = "tables") -> str:
    return f"s3://{bucket}/{tables_prefix}/{config.output_table}/"


def glue_table_input(config: PipelineConfig, location: str) -> dict:
    """``TableInput`` for ``glue.create_table`` / ``glue.update_table``."""
    return {
        "Name": config.output_table,
        "TableType": "EXTERNAL_TABLE",
        "Parameters": {"classification": "parquet", "EXTERNAL": "TRUE"},
        "StorageDescriptor": {
            "Columns": [{"Name": c, "Type": GLUE_TYPES[t]} for c, t in config.output_columns()],
            "Location": location,
            "InputFormat": PARQUET_INPUT_FORMAT,
            "OutputFormat": PARQUET_OUTPUT_FORMAT,
            "SerdeInfo": {"SerializationLibrary": PARQUET_SERDE},
        },
    }


def create_table_ddl(config: PipelineConfig, database: str, location: str) -> str:
    """Equivalent ``CREATE EXTERNAL TABLE`` to paste into the Athena editor."""
    columns = ",\n".join(f"  `{c}` {GLUE_TYPES[t]}" for c, t in config.output_columns())
    return (
        f"CREATE EXTERNAL TABLE IF NOT EXISTS `{database}`.`{config.output_table}` (\n"
        f"{columns}\n"
        ")\n"
        "STORED AS PARQUET\n"
        f"LOCATION '{location}'\n"
        "TBLPROPERTIES ('classification' = 'parquet');"
    )
