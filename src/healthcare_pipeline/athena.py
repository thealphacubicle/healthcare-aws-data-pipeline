"""Small synchronous Athena query helper used by the dashboard."""

from __future__ import annotations

import time

import pandas as pd

TERMINAL_STATES = {"SUCCEEDED", "FAILED", "CANCELLED"}


class AthenaQueryError(RuntimeError):
    pass


def run_query(
    athena,
    sql: str,
    *,
    database: str,
    workgroup: str,
    poll_seconds: float = 0.5,
    timeout_seconds: float = 120,
) -> pd.DataFrame:
    """Run ``sql`` in ``workgroup`` and return all rows as strings.

    The workgroup enforces the result location and per-query scan limit, so
    none is passed here.
    """
    execution_id = athena.start_query_execution(
        QueryString=sql,
        QueryExecutionContext={"Database": database},
        WorkGroup=workgroup,
    )["QueryExecutionId"]

    deadline = time.monotonic() + timeout_seconds
    while True:
        status = athena.get_query_execution(QueryExecutionId=execution_id)["QueryExecution"][
            "Status"
        ]
        if status["State"] in TERMINAL_STATES:
            break
        if time.monotonic() > deadline:
            athena.stop_query_execution(QueryExecutionId=execution_id)
            raise AthenaQueryError(f"Query {execution_id} timed out")
        time.sleep(poll_seconds)
    if status["State"] != "SUCCEEDED":
        reason = status.get("StateChangeReason", status["State"])
        raise AthenaQueryError(f"Query {execution_id} failed: {reason}")

    columns: list[str] | None = None
    rows: list[list[str | None]] = []
    paginator = athena.get_paginator("get_query_results")
    for page in paginator.paginate(QueryExecutionId=execution_id):
        result_rows = page["ResultSet"]["Rows"]
        if columns is None:
            columns = [c["Name"] for c in page["ResultSet"]["ResultSetMetadata"]["ColumnInfo"]]
            result_rows = result_rows[1:]  # first row of the first page is the header
        rows.extend([d.get("VarCharValue") for d in r["Data"]] for r in result_rows)
    return pd.DataFrame(rows, columns=columns or [])
