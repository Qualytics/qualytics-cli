"""CLI commands for datastore operations (catalog, profile, scan)."""

import typer
from datetime import datetime

from ..config import load_config, is_token_valid
from ..services.operations import (
    run_catalog,
    run_profile,
    run_scan,
    check_operation_status,
)


# Create Typer instances for operations
run_operation_app = typer.Typer(
    name="run",
    help="Command to trigger a datastores operation. (catalog, profile, scan)",
)

check_operation_app = typer.Typer(
    name="operation",
    help="Allows the user to view information about an operation such as it's status",
)


@run_operation_app.command(
    "catalog", help="Triggers a catalog operation for the specified datastores"
)
def catalog_operation(
    datastores: str = typer.Option(
        ...,
        "--datastore",
        help="Comma-separated list of Datastore IDs or array-like format",
    ),
    include: str | None = typer.Option(
        None,
        "--include",
        help='Comma-separated list of include types or array-like format. Example: "table,view" or "[table,view]"',
    ),
    prune: bool | None = typer.Option(
        None,
        "--prune",
        help="Prune the operation. Do not include if you want prune == false",
    ),
    recreate: bool | None = typer.Option(
        None,
        "--recreate",
        help="Recreate the operation. Do not include if you want recreate == false",
    ),
    background: bool | None = typer.Option(
        False,
        "--background",
        help="Starts the catalog operation and has it run in the background, "
        "not having the terminal wait for the operation to finish",
    ),
):
    # Remove brackets if present and split by comma
    datastores = [int(x.strip()) for x in datastores.strip("[]").split(",")]
    config = load_config()
    token = is_token_valid(config["token"])
    if token:
        if include:
            include = [(x.strip()) for x in include.strip("[]").split(",")]
        if prune is None:
            prune = False
        if recreate is None:
            recreate = False
        run_catalog(datastores, include, prune, recreate, token, background)


@run_operation_app.command(
    "profile", help="Triggers a profile operation for the specified datastores"
)
def profile_operation(
    datastores: str = typer.Option(
        ...,
        "--datastore",
        help="Comma-separated list of Datastore IDs or array-like format",
    ),
    container_names: str | None = typer.Option(
        None,
        "--container_names",
        help='Comma-separated list of include types or array-like format. Example: "table,view" or "[table,view]"',
    ),
    container_tags: str | None = typer.Option(
        None,
        "--container_tags",
        help='Comma-separated list of include types or array-like format. Example: "table,view" or "[table,view]"',
    ),
    inference_threshold: int | None = typer.Option(
        None,
        "--inference_threshold",
        help="Inference quality checks threshold in profile from 0 to 5. Do not include if you want inference_threshold == 0",
    ),
    infer_as_draft: bool | None = typer.Option(
        None,
        "--infer_as_draft",
        help="Infer all quality checks in profile as DRAFT. Do not include if you want infer_as_draft == False",
    ),
    max_records_analyzed_per_partition: int | None = typer.Option(
        None,
        "--max_records_analyzed_per_partition",
        help="Number of max records analyzed per partition",
    ),
    max_count_testing_sample: int | None = typer.Option(
        None,
        "--max_count_testing_sample",
        help="The number of records accumulated during profiling for validation of inferred checks. Capped at 100,000",
    ),
    percent_testing_threshold: float | None = typer.Option(
        None, "--percent_testing_threshold", help=" Percent of Testing Threshold"
    ),
    high_correlation_threshold: float | None = typer.Option(
        None, "--high_correlation_threshold", help="Number of Correlation Threshold"
    ),
    greater_than_time: datetime | None = typer.Option(
        None,
        "--greater_than_time",
        help="Only include rows where the incremental field's value is greater than this time. Use one of these formats %Y-%m-%dT%H:%M:%S or %Y-%m-%d %H:%M:%S",
    ),
    greater_than_batch: float | None = typer.Option(
        None,
        "--greater_than_batch",
        help="Only include rows where the incremental field's value is greater than this number",
    ),
    histogram_max_distinct_values: int | None = typer.Option(
        None,
        "--histogram_max_distinct_values",
        help="Number of max distinct values of the histogram",
    ),
    background: bool | None = typer.Option(
        False,
        "--background",
        help="Starts the catalog operation and has it run in the background, "
        "not having the terminal wait for the operation to finish",
    ),
):
    # Remove brackets if present and split by comma
    datastores = [int(x.strip()) for x in datastores.strip("[]").split(",")]
    config = load_config()
    token = is_token_valid(config["token"])
    if token:
        if (
            max_records_analyzed_per_partition
            and max_records_analyzed_per_partition <= -1
        ):
            print(
                "[bold red] max_records_analyzed_per_partition must be greater than or equal to -1. Please try again"
                "[/bold red]"
            )
            exit(1)
        if container_names:
            container_names = [
                (x.strip()) for x in container_names.strip("[]").split(",")
            ]
        if container_tags:
            container_tags = [
                (x.strip()) for x in container_tags.strip("[]").split(",")
            ]
        if greater_than_time:
            greater_than_time = greater_than_time.strftime("%Y-%m-%dT%H:%M:%S.000Z")

        run_profile(
            datastore_ids=datastores,
            container_names=container_names,
            container_tags=container_tags,
            inference_threshold=inference_threshold,
            infer_as_draft=infer_as_draft,
            max_records_analyzed_per_partition=max_records_analyzed_per_partition,
            max_count_testing_sample=max_count_testing_sample,
            percent_testing_threshold=percent_testing_threshold,
            high_correlation_threshold=high_correlation_threshold,
            greater_than_time=greater_than_time,
            greater_than_batch=greater_than_batch,
            histogram_max_distinct_values=histogram_max_distinct_values,
            token=token,
            background=background,
        )


@run_operation_app.command(
    "scan", help="Triggers a scan operation for the specified datastores"
)
def scan_operation(
    datastores: str = typer.Option(
        ...,
        "--datastore",
        help="Comma-separated list of Datastore IDs or array-like format",
    ),
    container_names: str | None = typer.Option(
        None,
        "--container_names",
        help='Comma-separated list of include types or array-like format. Example: "table,view" or "[table,view]"',
    ),
    container_tags: str | None = typer.Option(
        None,
        "--container_tags",
        help='Comma-separated list of include types or array-like format. Example: "table,view" or "[table,view]"',
    ),
    incremental: bool | None = typer.Option(
        False,
        "--incremental",
        help="Process only new or records updated since the last incremental scan",
    ),
    remediation: str | None = typer.Option(
        "none",
        "--remediation",
        help="Replication strategy for source tables in the enrichment datastore. Either 'append', 'overwrite', or 'none'",
    ),
    max_records_analyzed_per_partition: int | None = typer.Option(
        None,
        "--max_records_analyzed_per_partition",
        help="Number of max records analyzed per partition. Value must be Greater than or equal to 0",
    ),
    enrichment_source_record_limit: int | None = typer.Option(
        10,
        "--enrichment_source_record_limit",
        help="Limit of enrichment source records per . Value must be Greater than or equal to -1",
    ),
    greater_than_time: datetime | None = typer.Option(
        None,
        "--greater_than_time",
        help="Only include rows where the incremental field's value is greater than this time. Use one of these formats %Y-%m-%dT%H:%M:%S or %Y-%m-%d %H:%M:%S",
    ),
    greater_than_batch: float | None = typer.Option(
        None,
        "--greater_than_batch",
        help="Only include rows where the incremental field's value is greater than this number",
    ),
    background: bool | None = typer.Option(
        False,
        "--background",
        help="Starts the catalog operation and has it run in the background, "
        "not having the terminal wait for the operation to finish",
    ),
):
    # Remove brackets if present and split by comma
    datastores = [int(x.strip()) for x in datastores.strip("[]").split(",")]
    config = load_config()
    token = is_token_valid(config["token"])
    if token:
        if enrichment_source_record_limit < 1:
            print(
                "[bold red] enrichment_source_record_limit must be greater than or equal to 1. Please try again "
                "[/bold red]"
            )
            exit(1)
        if (
            max_records_analyzed_per_partition
            and max_records_analyzed_per_partition <= -1
        ):
            print(
                "[bold red] max_records_analyzed_per_partition must be greater than or equal to -1. Please try again"
                "[/bold red]"
            )
            exit(1)
        if container_names:
            container_names = [
                (x.strip()) for x in container_names.strip("[]").split(",")
            ]
        if container_tags:
            container_tags = [
                (x.strip()) for x in container_tags.strip("[]").split(",")
            ]
        if remediation and (remediation not in ["append", "overwrite", "none"]):
            print(
                "[bold red] Remediation must be either 'append', 'overwrite', or 'none'. Please try again with "
                "the correct values[/bold red]"
            )
            exit(1)
        if greater_than_time:
            greater_than_time = greater_than_time.strftime("%Y-%m-%dT%H:%M:%S.000Z")

        run_scan(
            datastore_ids=datastores,
            container_names=container_names,
            container_tags=container_tags,
            incremental=incremental,
            remediation=remediation,
            max_records_analyzed_per_partition=max_records_analyzed_per_partition,
            enrichment_source_record_limit=enrichment_source_record_limit,
            greater_than_time=greater_than_time,
            greater_than_batch=greater_than_batch,
            token=token,
            background=background,
        )


# ========================================== CHECK_OPERATION_APP COMMANDS =================================================================
@check_operation_app.command("check_status", help="checks the status of a operation")
def operation_status(
    ids: str = typer.Option(
        ...,
        "--ids",
        help="Comma-separated list of Operation IDs or array-like format",
    ),
):
    ids = [int(x.strip()) for x in ids.strip("[]").split(",")]
    config = load_config()
    token = is_token_valid(config["token"])
    check_operation_status(ids, token=token)


# ========================================== DATASTORE COMMANDS ============================================================================
