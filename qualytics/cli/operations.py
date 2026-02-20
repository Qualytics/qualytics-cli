"""CLI commands for datastore operations (catalog, profile, scan, materialize, export)."""

from datetime import datetime

import typer
from rich import print

from ..api.client import get_client
from ..api.operations import abort_operation, get_operation, list_all_operations
from ..services.operations import (
    DEFAULT_POLL_INTERVAL,
    DEFAULT_TIMEOUT,
    run_catalog,
    run_export,
    run_materialize,
    run_profile,
    run_scan,
)
from ..utils import OutputFormat, format_for_display

operations_app = typer.Typer(
    name="operations",
    help="Commands for triggering and managing datastore operations",
)

_VALID_REMEDIATION = {"append", "overwrite", "none"}
_VALID_ASSET_TYPES = {"anomalies", "checks", "profiles"}


# ── helpers ──────────────────────────────────────────────────────────────


def _parse_comma_list(value: str) -> list[str]:
    """Parse '1,2,3' or '[1,2,3]' into a list of stripped strings."""
    return [x.strip() for x in value.strip("[]").split(",") if x.strip()]


def _parse_int_list(value: str) -> list[int]:
    """Parse '1,2,3' or '[1,2,3]' into a list of ints."""
    return [int(x) for x in _parse_comma_list(value)]


# ── catalog ──────────────────────────────────────────────────────────────


@operations_app.command("catalog")
def catalog_operation(
    datastore_id: str = typer.Option(
        ...,
        "--datastore-id",
        help="Comma-separated list of Datastore IDs",
    ),
    include: str | None = typer.Option(
        None,
        "--include",
        help='Comma-separated include types. Example: "table,view"',
    ),
    prune: bool = typer.Option(
        False,
        "--prune",
        help="Prune containers not found in catalog",
    ),
    recreate: bool = typer.Option(
        False,
        "--recreate",
        help="Drop and recreate all containers",
    ),
    background: bool = typer.Option(
        False,
        "--background",
        help="Start operation without waiting for completion",
    ),
    poll_interval: int = typer.Option(
        DEFAULT_POLL_INTERVAL,
        "--poll-interval",
        help="Seconds between status checks when waiting for completion",
    ),
    timeout: int = typer.Option(
        DEFAULT_TIMEOUT,
        "--timeout",
        help="Maximum seconds to wait for completion (default: 1800 = 30 min)",
    ),
):
    """Trigger a catalog operation for the specified datastores."""
    datastore_ids = _parse_int_list(datastore_id)
    client = get_client()
    include_list = _parse_comma_list(include) if include else None
    run_catalog(
        client,
        datastore_ids,
        include_list,
        prune,
        recreate,
        background,
        poll_interval=poll_interval,
        timeout=timeout,
    )


# ── profile ──────────────────────────────────────────────────────────────


@operations_app.command("profile")
def profile_operation(
    datastore_id: str = typer.Option(
        ...,
        "--datastore-id",
        help="Comma-separated list of Datastore IDs",
    ),
    container_names: str | None = typer.Option(
        None,
        "--container-names",
        help='Comma-separated container names. Example: "orders,customers"',
    ),
    container_tags: str | None = typer.Option(
        None,
        "--container-tags",
        help='Comma-separated container tags. Example: "production,finance"',
    ),
    inference_threshold: int | None = typer.Option(
        None,
        "--inference-threshold",
        help="Inference quality checks threshold (0 to 5)",
    ),
    infer_as_draft: bool = typer.Option(
        False,
        "--infer-as-draft",
        help="Infer all quality checks as Draft",
    ),
    max_records_analyzed_per_partition: int | None = typer.Option(
        None,
        "--max-records-analyzed-per-partition",
        help="Max records analyzed per partition (-1 for unlimited)",
    ),
    max_count_testing_sample: int | None = typer.Option(
        None,
        "--max-count-testing-sample",
        help="Records accumulated for validation of inferred checks (max 100000)",
    ),
    percent_testing_threshold: float | None = typer.Option(
        None, "--percent-testing-threshold", help="Percent of testing threshold"
    ),
    high_correlation_threshold: float | None = typer.Option(
        None, "--high-correlation-threshold", help="Correlation threshold"
    ),
    greater_than_time: datetime | None = typer.Option(
        None,
        "--greater-than-time",
        help="Incremental: only rows with field value greater than this time (YYYY-MM-DDTHH:MM:SS)",
    ),
    greater_than_batch: float | None = typer.Option(
        None,
        "--greater-than-batch",
        help="Incremental: only rows with field value greater than this number",
    ),
    histogram_max_distinct_values: int | None = typer.Option(
        None,
        "--histogram-max-distinct-values",
        help="Max distinct values for histogram",
    ),
    background: bool = typer.Option(
        False,
        "--background",
        help="Start operation without waiting for completion",
    ),
    poll_interval: int = typer.Option(
        DEFAULT_POLL_INTERVAL,
        "--poll-interval",
        help="Seconds between status checks when waiting for completion",
    ),
    timeout: int = typer.Option(
        DEFAULT_TIMEOUT,
        "--timeout",
        help="Maximum seconds to wait for completion (default: 1800 = 30 min)",
    ),
):
    """Trigger a profile operation for the specified datastores."""
    datastore_ids = _parse_int_list(datastore_id)
    client = get_client()

    if (
        max_records_analyzed_per_partition is not None
        and max_records_analyzed_per_partition < -1
    ):
        print(
            "[bold red]--max-records-analyzed-per-partition must be >= -1.[/bold red]"
        )
        raise typer.Exit(code=1)

    names_list = _parse_comma_list(container_names) if container_names else None
    tags_list = _parse_comma_list(container_tags) if container_tags else None
    gt_time = (
        greater_than_time.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        if greater_than_time
        else None
    )

    run_profile(
        client=client,
        datastore_ids=datastore_ids,
        container_names=names_list,
        container_tags=tags_list,
        inference_threshold=inference_threshold,
        infer_as_draft=infer_as_draft if infer_as_draft else None,
        max_records_analyzed_per_partition=max_records_analyzed_per_partition,
        max_count_testing_sample=max_count_testing_sample,
        percent_testing_threshold=percent_testing_threshold,
        high_correlation_threshold=high_correlation_threshold,
        greater_than_time=gt_time,
        greater_than_batch=greater_than_batch,
        histogram_max_distinct_values=histogram_max_distinct_values,
        background=background,
        poll_interval=poll_interval,
        timeout=timeout,
    )


# ── scan ─────────────────────────────────────────────────────────────────


@operations_app.command("scan")
def scan_operation(
    datastore_id: str = typer.Option(
        ...,
        "--datastore-id",
        help="Comma-separated list of Datastore IDs",
    ),
    container_names: str | None = typer.Option(
        None,
        "--container-names",
        help='Comma-separated container names. Example: "orders,customers"',
    ),
    container_tags: str | None = typer.Option(
        None,
        "--container-tags",
        help='Comma-separated container tags. Example: "production,finance"',
    ),
    incremental: bool = typer.Option(
        False,
        "--incremental",
        help="Process only new or updated records since last scan",
    ),
    remediation: str = typer.Option(
        "none",
        "--remediation",
        help="Replication strategy: 'append', 'overwrite', or 'none'",
    ),
    max_records_analyzed_per_partition: int | None = typer.Option(
        None,
        "--max-records-analyzed-per-partition",
        help="Max records analyzed per partition (-1 for unlimited)",
    ),
    enrichment_source_record_limit: int | None = typer.Option(
        None,
        "--enrichment-source-record-limit",
        help="Limit of enrichment source records per run (>= 1)",
    ),
    greater_than_time: datetime | None = typer.Option(
        None,
        "--greater-than-time",
        help="Incremental: only rows with field value greater than this time (YYYY-MM-DDTHH:MM:SS)",
    ),
    greater_than_batch: float | None = typer.Option(
        None,
        "--greater-than-batch",
        help="Incremental: only rows with field value greater than this number",
    ),
    background: bool = typer.Option(
        False,
        "--background",
        help="Start operation without waiting for completion",
    ),
    poll_interval: int = typer.Option(
        DEFAULT_POLL_INTERVAL,
        "--poll-interval",
        help="Seconds between status checks when waiting for completion",
    ),
    timeout: int = typer.Option(
        DEFAULT_TIMEOUT,
        "--timeout",
        help="Maximum seconds to wait for completion (default: 1800 = 30 min)",
    ),
):
    """Trigger a scan operation for the specified datastores."""
    datastore_ids = _parse_int_list(datastore_id)
    client = get_client()

    if (
        enrichment_source_record_limit is not None
        and enrichment_source_record_limit < 1
    ):
        print("[bold red]--enrichment-source-record-limit must be >= 1.[/bold red]")
        raise typer.Exit(code=1)
    if (
        max_records_analyzed_per_partition is not None
        and max_records_analyzed_per_partition < -1
    ):
        print(
            "[bold red]--max-records-analyzed-per-partition must be >= -1.[/bold red]"
        )
        raise typer.Exit(code=1)
    if remediation not in _VALID_REMEDIATION:
        print(
            f"[bold red]--remediation must be one of: {', '.join(sorted(_VALID_REMEDIATION))}.[/bold red]"
        )
        raise typer.Exit(code=1)

    names_list = _parse_comma_list(container_names) if container_names else None
    tags_list = _parse_comma_list(container_tags) if container_tags else None
    gt_time = (
        greater_than_time.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        if greater_than_time
        else None
    )

    run_scan(
        client=client,
        datastore_ids=datastore_ids,
        container_names=names_list,
        container_tags=tags_list,
        incremental=incremental if incremental else None,
        remediation=remediation,
        max_records_analyzed_per_partition=max_records_analyzed_per_partition,
        enrichment_source_record_limit=enrichment_source_record_limit,
        greater_than_time=gt_time,
        greater_than_batch=greater_than_batch,
        background=background,
        poll_interval=poll_interval,
        timeout=timeout,
    )


# ── materialize ──────────────────────────────────────────────────────────


@operations_app.command("materialize")
def materialize_operation(
    datastore_id: str = typer.Option(
        ...,
        "--datastore-id",
        help="Comma-separated list of Datastore IDs",
    ),
    container_names: str | None = typer.Option(
        None,
        "--container-names",
        help='Comma-separated container names. Example: "orders,customers"',
    ),
    container_tags: str | None = typer.Option(
        None,
        "--container-tags",
        help='Comma-separated container tags. Example: "production,finance"',
    ),
    max_records_per_partition: int | None = typer.Option(
        None,
        "--max-records-per-partition",
        help="Max records per partition (-1 for unlimited)",
    ),
    background: bool = typer.Option(
        False,
        "--background",
        help="Start operation without waiting for completion",
    ),
    poll_interval: int = typer.Option(
        DEFAULT_POLL_INTERVAL,
        "--poll-interval",
        help="Seconds between status checks when waiting for completion",
    ),
    timeout: int = typer.Option(
        DEFAULT_TIMEOUT,
        "--timeout",
        help="Maximum seconds to wait for completion (default: 1800 = 30 min)",
    ),
):
    """Trigger a materialize operation for computed containers."""
    datastore_ids = _parse_int_list(datastore_id)
    client = get_client()
    names_list = _parse_comma_list(container_names) if container_names else None
    tags_list = _parse_comma_list(container_tags) if container_tags else None
    run_materialize(
        client,
        datastore_ids,
        names_list,
        tags_list,
        max_records_per_partition,
        background,
        poll_interval=poll_interval,
        timeout=timeout,
    )


# ── export ───────────────────────────────────────────────────────────────


@operations_app.command("export")
def export_operation(
    datastore_id: str = typer.Option(
        ...,
        "--datastore-id",
        help="Comma-separated list of Datastore IDs",
    ),
    asset_type: str = typer.Option(
        ...,
        "--asset-type",
        help="Asset type to export: anomalies, checks, or profiles",
    ),
    container_ids: str | None = typer.Option(
        None,
        "--container-ids",
        help="Comma-separated container IDs to export",
    ),
    container_tags: str | None = typer.Option(
        None,
        "--container-tags",
        help="Comma-separated container tags to export",
    ),
    include_deleted: bool = typer.Option(
        False,
        "--include-deleted",
        help="Include deleted items in export",
    ),
    background: bool = typer.Option(
        False,
        "--background",
        help="Start operation without waiting for completion",
    ),
    poll_interval: int = typer.Option(
        DEFAULT_POLL_INTERVAL,
        "--poll-interval",
        help="Seconds between status checks when waiting for completion",
    ),
    timeout: int = typer.Option(
        DEFAULT_TIMEOUT,
        "--timeout",
        help="Maximum seconds to wait for completion (default: 1800 = 30 min)",
    ),
):
    """Trigger an export operation to the enrichment datastore."""
    if asset_type not in _VALID_ASSET_TYPES:
        print(
            f"[bold red]--asset-type must be one of: {', '.join(sorted(_VALID_ASSET_TYPES))}.[/bold red]"
        )
        raise typer.Exit(code=1)

    datastore_ids = _parse_int_list(datastore_id)
    client = get_client()
    cid_list = _parse_int_list(container_ids) if container_ids else None
    tags_list = _parse_comma_list(container_tags) if container_tags else None
    run_export(
        client,
        datastore_ids,
        asset_type,
        cid_list,
        tags_list,
        include_deleted,
        background,
        poll_interval=poll_interval,
        timeout=timeout,
    )


# ── get ──────────────────────────────────────────────────────────────────


@operations_app.command("get")
def operations_get(
    operation_id: int = typer.Option(..., "--id", help="Operation ID"),
    fmt: OutputFormat = typer.Option(
        OutputFormat.YAML, "--format", help="Output format: yaml or json"
    ),
):
    """Get full details for a single operation."""
    client = get_client()
    result = get_operation(client, operation_id)
    print(format_for_display(result, fmt))


# ── list ─────────────────────────────────────────────────────────────────


@operations_app.command("list")
def operations_list(
    datastore_id: str | None = typer.Option(
        None, "--datastore-id", help="Comma-separated Datastore IDs to filter by"
    ),
    operation_type: str | None = typer.Option(
        None,
        "--type",
        help="Operation type: catalog, profile, scan, materialize, export",
    ),
    status: str | None = typer.Option(
        None,
        "--status",
        help="Comma-separated result statuses: running, success, failure, aborted",
    ),
    start_date: str | None = typer.Option(
        None, "--start-date", help="Start date filter (YYYY-MM-DD)"
    ),
    end_date: str | None = typer.Option(
        None, "--end-date", help="End date filter (YYYY-MM-DD)"
    ),
    fmt: OutputFormat = typer.Option(
        OutputFormat.YAML, "--format", help="Output format: yaml or json"
    ),
):
    """List operations with optional filters."""
    client = get_client()
    ds_list = _parse_int_list(datastore_id) if datastore_id else None
    result_list = _parse_comma_list(status) if status else None

    all_ops = list_all_operations(
        client,
        datastore=ds_list,
        operation_type=operation_type,
        result=result_list,
        start_date=start_date,
        end_date=end_date,
        sort_created="desc",
    )
    print(f"[green]Found {len(all_ops)} operations.[/green]")
    print(format_for_display(all_ops, fmt))


# ── abort ────────────────────────────────────────────────────────────────


@operations_app.command("abort")
def operations_abort(
    operation_id: int = typer.Option(..., "--id", help="Operation ID to abort"),
):
    """Abort a running operation (best-effort)."""
    client = get_client()
    result = abort_operation(client, operation_id)
    op_result = result.get("result", "unknown")
    if op_result == "aborted":
        print(f"[green]Operation {operation_id} aborted.[/green]")
    elif op_result in ("success", "failure"):
        print(
            f"[yellow]Operation {operation_id} already finished with result: {op_result}.[/yellow]"
        )
    else:
        print(
            f"[green]Abort requested for operation {operation_id} (result: {op_result}).[/green]"
        )
