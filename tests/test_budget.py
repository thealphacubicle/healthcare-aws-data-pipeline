from healthcare_pipeline.budget import shutdown


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def stop_instances(self, **kwargs: object) -> None:
        self.calls.append(("stop_instances", kwargs))

    def disable_rule(self, **kwargs: object) -> None:
        self.calls.append(("disable_rule", kwargs))

    def put_function_concurrency(self, **kwargs: object) -> None:
        self.calls.append(("put_function_concurrency", kwargs))

    def update_work_group(self, **kwargs: object) -> None:
        self.calls.append(("update_work_group", kwargs))


def test_shutdown_stops_every_compute_path() -> None:
    client = Recorder()

    result = shutdown(
        ec2=client,
        events=client,
        lambda_client=client,
        athena=client,
        instance_id="i-123",
        rule_name="healthcare-pipeline-dev-ingest-schedule",
        function_names=["healthcare-pipeline-dev-ingest", "healthcare-pipeline-dev-etl"],
        workgroup="healthcare-pipeline-dev",
    )

    assert result["status"] == "shut_down"
    assert ("stop_instances", {"InstanceIds": ["i-123"]}) in client.calls
    assert ("disable_rule", {"Name": "healthcare-pipeline-dev-ingest-schedule"}) in client.calls
    assert (
        "put_function_concurrency",
        {"FunctionName": "healthcare-pipeline-dev-ingest", "ReservedConcurrentExecutions": 0},
    ) in client.calls
    assert (
        "put_function_concurrency",
        {"FunctionName": "healthcare-pipeline-dev-etl", "ReservedConcurrentExecutions": 0},
    ) in client.calls
    assert (
        "update_work_group",
        {"WorkGroup": "healthcare-pipeline-dev", "State": "DISABLED"},
    ) in client.calls
