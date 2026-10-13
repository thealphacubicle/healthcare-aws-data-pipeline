"""Derived fields computed on the joined dataset.

Every column listed under ``derived`` in pipeline_config.json needs a function
here; ``compute_derived_fields`` fails fast if one is missing.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import pandas as pd

from healthcare_pipeline.config import PipelineConfig

DerivedFn = Callable[[pd.DataFrame, date], pd.Series]


def _age_years(df: pd.DataFrame, as_of: date) -> pd.Series:
    birth = df["birth_date"]
    had_birthday = (birth.dt.month < as_of.month) | (
        (birth.dt.month == as_of.month) & (birth.dt.day <= as_of.day)
    )
    age = as_of.year - birth.dt.year - (~had_birthday).astype(int)
    return age.astype("Int64")


def _days_since_last_encounter(df: pd.DataFrame, as_of: date) -> pd.Series:
    return (pd.Timestamp(as_of) - df["last_encounter_date"]).dt.days.astype("Int64")


def _avg_charge_per_encounter(df: pd.DataFrame, as_of: date) -> pd.Series:
    count = df["encounter_count"].astype("Float64")
    return (df["total_charges"] / count.where(count > 0)).round(2)


DERIVED_FIELDS: dict[str, DerivedFn] = {
    "age_years": _age_years,
    "days_since_last_encounter": _days_since_last_encounter,
    "avg_charge_per_encounter": _avg_charge_per_encounter,
}


def compute_derived_fields(config: PipelineConfig, df: pd.DataFrame, as_of: date) -> pd.DataFrame:
    missing = [name for name in config.derived if name not in DERIVED_FIELDS]
    if missing:
        raise KeyError(f"No implementation in derive.py for derived fields {missing}")
    df = df.copy()
    for name in config.derived:
        df[name] = DERIVED_FIELDS[name](df, as_of)
    return df
