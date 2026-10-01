import copy
import json
from importlib import resources

import pytest

from healthcare_pipeline.config import ConfigError, load_config, parse_config


def _raw_config() -> dict:
    text = resources.files("healthcare_pipeline").joinpath("pipeline_config.json").read_text()
    return json.loads(text)


def test_bundled_config_is_valid() -> None:
    config = load_config()
    assert config.master.name == "patients"
    assert config.dataset_for_file("insurance.csv").name == "insurance"
    assert config.dataset_for_file("unknown.csv") is None


def test_output_columns_include_join_key_once_and_derived_last() -> None:
    names = [name for name, _ in load_config().output_columns()]
    assert names.count("patient_id") == 1
    assert names[-3:] == ["age_years", "days_since_last_encounter", "avg_charge_per_encounter"]


def test_rejects_column_collisions() -> None:
    raw = _raw_config()
    raw["supporting"][1]["columns"]["sex"] = "string"
    with pytest.raises(ConfigError, match="'sex'"):
        parse_config(raw)


def test_rejects_missing_join_key() -> None:
    raw = copy.deepcopy(_raw_config())
    del raw["supporting"][0]["columns"]["patient_id"]
    with pytest.raises(ConfigError, match="join key"):
        parse_config(raw)


def test_rejects_unknown_types() -> None:
    raw = _raw_config()
    raw["derived"]["age_years"] = "integer"
    with pytest.raises(ConfigError, match="unknown type"):
        parse_config(raw)
