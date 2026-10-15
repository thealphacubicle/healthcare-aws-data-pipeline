"""Shut down pipeline compute when the monthly AWS Budget is exceeded.

Triggered by SNS from a 100% actual-spend notification. Stops new spend from
EC2, scheduled ingestion, Lambda, and Athena. S3/Glue stay (they hold data and
cost almost nothing idle). Billing data lags by hours, so this is a backstop.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def shutdown(
    *,
    ec2: Any,
    events: Any,
    lambda_client: Any,
    athena: Any,
    instance_id: str,
    rule_name: str,
    function_names: list[str],
    workgroup: str,
) -> dict[str, str]:
    """Disable every running compute path in the pipeline."""
    logger.info("Budget exceeded; shutting down pipeline compute")
    ec2.stop_instances(InstanceIds=[instance_id])
    events.disable_rule(Name=rule_name)
    for name in function_names:
        lambda_client.put_function_concurrency(FunctionName=name, ReservedConcurrentExecutions=0)
    athena.update_work_group(WorkGroup=workgroup, State="DISABLED")
    return {
        "instance_id": instance_id,
        "rule_name": rule_name,
        "functions": ",".join(function_names),
        "workgroup": workgroup,
        "status": "shut_down",
    }


def handler(event: dict[str, Any], context: object) -> dict[str, str]:
    import boto3

    functions = [name for name in os.environ["PIPELINE_FUNCTIONS"].split(",") if name]
    return shutdown(
        ec2=boto3.client("ec2"),
        events=boto3.client("events"),
        lambda_client=boto3.client("lambda"),
        athena=boto3.client("athena"),
        instance_id=os.environ["DASHBOARD_INSTANCE_ID"],
        rule_name=os.environ["INGEST_RULE_NAME"],
        function_names=functions,
        workgroup=os.environ["ATHENA_WORKGROUP"],
    )
