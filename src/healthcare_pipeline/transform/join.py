"""Join the master dataset with every supporting dataset."""

from __future__ import annotations

import pandas as pd

from healthcare_pipeline.config import PipelineConfig


def join_datasets(config: PipelineConfig, frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Left-join each supporting frame onto the master, one row per join key.

    ``validate="one_to_one"`` makes pandas raise instead of silently fanning
    out rows if a supporting file ever has duplicate keys.
    """
    joined = frames[config.master.name]
    for spec in config.supporting:
        joined = joined.merge(
            frames[spec.name],
            how="left",
            on=config.join_key,
            validate="one_to_one",
        )
    return joined
