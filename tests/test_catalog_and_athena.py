import pytest

from healthcare_pipeline.athena import AthenaQueryError, run_query
from healthcare_pipeline.catalog import (
    PARQUET_SERDE,
    create_table_ddl,
    glue_table_input,
    table_location,
)
from healthcare_pipeline.config import load_config

CONFIG = load_config()


def test_ddl_and_table_input_agree() -> None:
    location = table_location("curated-bucket", CONFIG)
    ddl = create_table_ddl(CONFIG, "healthcare", location)
    table_input = glue_table_input(CONFIG, location)

    assert location == "s3://curated-bucket/tables/patient_summary/"
    assert ddl.startswith("CREATE EXTERNAL TABLE IF NOT EXISTS `healthcare`.`patient_summary`")
    assert "STORED AS PARQUET" in ddl
    assert f"LOCATION '{location}'" in ddl
    for column in table_input["StorageDescriptor"]["Columns"]:
        assert f"`{column['Name']}` {column['Type']}" in ddl
    assert table_input["StorageDescriptor"]["SerdeInfo"]["SerializationLibrary"] == PARQUET_SERDE


class FakeAthena:
    def __init__(self, states: list[str], pages: list[dict]) -> None:
        self.states = states
        self.pages = pages
        self.started: dict | None = None

    def start_query_execution(self, **kwargs) -> dict:
        self.started = kwargs
        return {"QueryExecutionId": "q1"}

    def get_query_execution(self, QueryExecutionId: str) -> dict:
        state = self.states.pop(0)
        return {"QueryExecution": {"Status": {"State": state, "StateChangeReason": "boom"}}}

    def get_paginator(self, name: str):
        pages = self.pages

        class Paginator:
            def paginate(self, QueryExecutionId: str):
                return iter(pages)

        return Paginator()


def _page(rows: list[list[str | None]], header: bool) -> dict:
    data = [{"Data": [{"VarCharValue": v} if v is not None else {} for v in r]} for r in rows]
    if header:
        data.insert(0, {"Data": [{"VarCharValue": "a"}, {"VarCharValue": "b"}]})
    return {
        "ResultSet": {
            "Rows": data,
            "ResultSetMetadata": {"ColumnInfo": [{"Name": "a"}, {"Name": "b"}]},
        }
    }


def test_run_query_collects_pages_and_skips_header() -> None:
    athena = FakeAthena(
        ["RUNNING", "SUCCEEDED"], [_page([["1", "x"]], header=True), _page([["2", None]], False)]
    )
    df = run_query(athena, "SELECT 1", database="db", workgroup="wg", poll_seconds=0)

    assert athena.started["WorkGroup"] == "wg"
    assert df["a"].tolist() == ["1", "2"]
    assert df.loc[0, "b"] == "x"
    assert df["b"].isna().tolist() == [False, True]


def test_run_query_raises_on_failure() -> None:
    athena = FakeAthena(["FAILED"], [])
    with pytest.raises(AthenaQueryError, match="boom"):
        run_query(athena, "SELECT 1", database="db", workgroup="wg", poll_seconds=0)
