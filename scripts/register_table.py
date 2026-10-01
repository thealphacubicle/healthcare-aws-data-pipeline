"""One-time registration of the curated table in the Glue Data Catalog.

No Glue Crawler is involved. Re-run only when pipeline_config.json changes the
output columns.

    # Print DDL to paste into the Athena query editor:
    uv run python scripts/register_table.py --database healthcare --bucket <curated-bucket>

    # Or create the table directly via the Glue API:
    uv run python scripts/register_table.py --database healthcare --bucket <curated-bucket> --apply

    # After a schema change, replace the existing definition:
    uv run python scripts/register_table.py ... --apply --replace
"""

from __future__ import annotations

import argparse

from healthcare_pipeline.catalog import create_table_ddl, glue_table_input, table_location
from healthcare_pipeline.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", required=True, help="Glue database (Terraform output)")
    parser.add_argument("--bucket", required=True, help="Curated bucket (Terraform output)")
    parser.add_argument("--tables-prefix", default="tables")
    parser.add_argument("--config", help="Alternate pipeline_config.json path")
    parser.add_argument("--apply", action="store_true", help="Call glue.create_table")
    parser.add_argument("--replace", action="store_true", help="Update an existing table")
    parser.add_argument("--region", help="AWS region (defaults to the AWS CLI configuration)")
    args = parser.parse_args()

    config = load_config(args.config)
    location = table_location(args.bucket, config, args.tables_prefix)

    if not args.apply:
        print(create_table_ddl(config, args.database, location))
        return

    import boto3

    glue = boto3.client("glue", region_name=args.region)
    table_input = glue_table_input(config, location)
    if args.replace:
        glue.update_table(DatabaseName=args.database, TableInput=table_input)
        print(f"Updated {args.database}.{config.output_table} -> {location}")
    else:
        glue.create_table(DatabaseName=args.database, TableInput=table_input)
        print(f"Created {args.database}.{config.output_table} -> {location}")


if __name__ == "__main__":
    main()
