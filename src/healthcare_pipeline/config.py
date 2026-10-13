"""Dataset definitions shared by ingestion, transforms, and catalog registration.

The master file and every supporting file are declared once in
``pipeline_config.json``. Everything else (which Drive files to pull, how to
cast columns, the Parquet schema, and the Glue/Athena DDL) is derived from it,
so adding one of the supporting files means editing only that JSON file.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

# Logical types used in the config, mapped to Glue/Athena column types.
GLUE_TYPES: dict[str, str] = {
    "string": "string",
    "bigint": "bigint",
    "double": "double",
    "boolean": "boolean",
    "date": "date",
    "timestamp": "timestamp",
}


class ConfigError(ValueError):
    """Raised when the pipeline configuration is inconsistent."""


@dataclass(frozen=True)
class DatasetSpec:
    name: str
    file_name: str
    columns: dict[str, str]


@dataclass(frozen=True)
class PipelineConfig:
    output_table: str
    join_key: str
    master: DatasetSpec
    supporting: tuple[DatasetSpec, ...]
    derived: dict[str, str]

    @property
    def datasets(self) -> tuple[DatasetSpec, ...]:
        return (self.master, *self.supporting)

    def dataset(self, name: str) -> DatasetSpec:
        for spec in self.datasets:
            if spec.name == name:
                return spec
        raise KeyError(name)

    def dataset_for_file(self, file_name: str) -> DatasetSpec | None:
        for spec in self.datasets:
            if spec.file_name == file_name:
                return spec
        return None

    def output_columns(self) -> list[tuple[str, str]]:
        """Ordered (column, logical type) pairs of the curated table."""
        columns = list(self.master.columns.items())
        for spec in self.supporting:
            columns.extend((c, t) for c, t in spec.columns.items() if c != self.join_key)
        columns.extend(self.derived.items())
        return columns


def _dataset_from_dict(raw: dict) -> DatasetSpec:
    return DatasetSpec(name=raw["name"], file_name=raw["file_name"], columns=dict(raw["columns"]))


def parse_config(raw: dict) -> PipelineConfig:
    config = PipelineConfig(
        output_table=raw["output_table"],
        join_key=raw["join_key"],
        master=_dataset_from_dict(raw["master"]),
        supporting=tuple(_dataset_from_dict(d) for d in raw.get("supporting", [])),
        derived=dict(raw.get("derived", {})),
    )
    validate_config(config)
    return config


def validate_config(config: PipelineConfig) -> None:
    names = [d.name for d in config.datasets]
    files = [d.file_name for d in config.datasets]
    if len(set(names)) != len(names):
        raise ConfigError(f"Dataset names must be unique: {names}")
    if len(set(files)) != len(files):
        raise ConfigError(f"Dataset file names must be unique: {files}")

    for spec in config.datasets:
        if config.join_key not in spec.columns:
            raise ConfigError(f"{spec.name} is missing join key {config.join_key!r}")
        for column, logical_type in spec.columns.items():
            if logical_type not in GLUE_TYPES:
                raise ConfigError(f"{spec.name}.{column} has unknown type {logical_type!r}")
    for column, logical_type in config.derived.items():
        if logical_type not in GLUE_TYPES:
            raise ConfigError(f"derived.{column} has unknown type {logical_type!r}")

    # Columns are joined without prefixes, so names must not collide.
    seen: set[str] = set()
    for column, _ in config.output_columns():
        if column in seen:
            raise ConfigError(f"Column {column!r} is defined more than once")
        seen.add(column)


def load_config(path: str | Path | None = None) -> PipelineConfig:
    if path is None:
        text = resources.files(__package__).joinpath("pipeline_config.json").read_text()
    else:
        text = Path(path).read_text()
    return parse_config(json.loads(text))
