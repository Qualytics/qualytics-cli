"""Operations service functions for catalog, profile, scan, materialize, and export."""

import time
from datetime import datetime

from rich import print
from rich.progress import track

from ..api.client import QualyticsAPIError, QualyticsClient
from ..api.operations import get_operation, run_operation
from ..config import OPERATION_ERROR_PATH
from ..utils.file_ops import log_error

# Default polling configuration
DEFAULT_POLL_INTERVAL = 10  # seconds between polls
DEFAULT_TIMEOUT = 1800  # 30 minutes max wait

# Valid operation types
VALID_OPERATION_TYPES = {"catalog", "profile", "scan", "materialize", "export"}


def wait_for_operation(
    client: QualyticsClient,
    operation_id: int,
    poll_interval: int = DEFAULT_POLL_INTERVAL,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict | None:
    """Wait for an operation to finish executing.

    Uses elapsed-time based timeout instead of fixed retry count.
    Shows progress counters for profile/scan operations.

    Returns the operation response dict, or None on timeout.
    """
    start_time = time.monotonic()
    last_status_time = start_time

    while True:
        elapsed = time.monotonic() - start_time

        if elapsed >= timeout:
            print(
                f"[bold red] Operation {operation_id} timed out after {int(elapsed)}s [/bold red]"
            )
            return None

        response = get_operation(client, operation_id)

        if response.get("end_time"):
            return response

        # Show progress counters for profile/scan
        now = time.monotonic()
        if now - last_status_time >= 60:
            status_info = response.get("status", {})
            total = status_info.get("total_containers", "?")
            analyzed = status_info.get("containers_analyzed", "?")
            records = status_info.get("records_processed", "?")
            print(
                f"  [dim]Operation {operation_id} still running... "
                f"({int(elapsed)}s elapsed, {analyzed}/{total} containers, "
                f"{records} records)[/dim]"
            )
            last_status_time = now

        time.sleep(poll_interval)


# Keep legacy name as alias for backward compat within the codebase
wait_for_operation_finishes = wait_for_operation


def _handle_operation_result(response, op_type, op_id, datastore_id):
    """Handle the result of a completed operation."""
    if response is None:
        print(
            f"[bold red] {op_type} {op_id} for datastore: {datastore_id} timed out [/bold red]"
        )
    elif response["result"] == "success" and response["message"] is None:
        print(
            f"[bold green] Successfully Finished {op_type} operation {op_id} "
            f"for datastore: {datastore_id} [/bold green]"
        )
    elif response["result"] == "success" and response["message"] is not None:
        msg = response["message"]
        print(
            f"[bold yellow] Warning for {op_type.lower()} operation {op_id} on datastore {datastore_id}:"
            f" {msg}[/bold yellow]"
        )
    else:
        print(
            f"[bold red] Failed {op_type} {op_id} for datastore: {datastore_id}, Please check the path: "
            f"{OPERATION_ERROR_PATH}[/bold red]"
        )
        message = response.get("detail", response.get("message", "Unknown error"))
        current_datetime = datetime.now().strftime("[%m-%d-%Y %H:%M:%S]")
        log_error(
            f"{current_datetime}: Error executing {op_type.lower()} operation: {message}\n\n",
            OPERATION_ERROR_PATH,
        )


def _run_for_datastores(
    client: QualyticsClient,
    op_type: str,
    datastore_ids: list[int],
    build_payload,
    background: bool,
    poll_interval: int = DEFAULT_POLL_INTERVAL,
    timeout: int = DEFAULT_TIMEOUT,
):
    """Shared runner that iterates over datastores, triggers an operation, and optionally waits."""
    for datastore_id in track(datastore_ids, description="Processing..."):
        try:
            payload = build_payload(datastore_id)
            result = run_operation(client, payload)
            op_id = result["id"]
            print(
                f"[bold green] Started {op_type} operation {op_id} "
                f"for datastore: {datastore_id} [/bold green]"
            )
            if not background:
                op_result = wait_for_operation(
                    client,
                    op_id,
                    poll_interval=poll_interval,
                    timeout=timeout,
                )
                _handle_operation_result(op_result, op_type, op_id, datastore_id)
        except QualyticsAPIError as e:
            print(
                f"[bold red] Failed {op_type} for datastore: {datastore_id}, Please check the path: "
                f"{OPERATION_ERROR_PATH}[/bold red]"
            )
            current_datetime = datetime.now().strftime("[%m-%d-%Y %H:%M:%S]")
            log_error(
                f"{current_datetime}: Error executing {op_type.lower()} operation: {e.message}\n\n",
                OPERATION_ERROR_PATH,
            )


def run_catalog(
    client: QualyticsClient,
    datastore_ids: list[int],
    include: list[str] | None,
    prune: bool,
    recreate: bool,
    background: bool,
    poll_interval: int = DEFAULT_POLL_INTERVAL,
    timeout: int = DEFAULT_TIMEOUT,
):
    """Run catalog operation for specified datastores."""

    def build_payload(datastore_id):
        return {
            "datastore_id": datastore_id,
            "type": "catalog",
            "include": include,
            "prune": prune,
            "recreate": recreate,
        }

    _run_for_datastores(
        client,
        "Catalog",
        datastore_ids,
        build_payload,
        background,
        poll_interval,
        timeout,
    )


def run_profile(
    client: QualyticsClient,
    datastore_ids: list[int],
    container_names: list[str] | None,
    container_tags: list[str] | None,
    inference_threshold: int | None,
    infer_as_draft: bool | None,
    max_records_analyzed_per_partition: int | None,
    max_count_testing_sample: int | None,
    percent_testing_threshold: float | None,
    high_correlation_threshold: float | None,
    greater_than_time: str | None,
    greater_than_batch: float | None,
    histogram_max_distinct_values: int | None,
    background: bool,
    poll_interval: int = DEFAULT_POLL_INTERVAL,
    timeout: int = DEFAULT_TIMEOUT,
):
    """Run profile operation for specified datastores."""

    def build_payload(datastore_id):
        return {
            "datastore_id": datastore_id,
            "type": "profile",
            "container_names": container_names,
            "container_tags": container_tags,
            "inference_threshold": inference_threshold,
            "infer_as_draft": infer_as_draft,
            "max_records_analyzed_per_partition": max_records_analyzed_per_partition,
            "max_count_testing_sample": max_count_testing_sample,
            "percent_testing_threshold": percent_testing_threshold,
            "high_correlation_threshold": high_correlation_threshold,
            "greater_than_time": greater_than_time,
            "greater_than_batch": greater_than_batch,
            "histogram_max_distinct_values": histogram_max_distinct_values,
        }

    _run_for_datastores(
        client,
        "Profile",
        datastore_ids,
        build_payload,
        background,
        poll_interval,
        timeout,
    )


def run_scan(
    client: QualyticsClient,
    datastore_ids: list[int],
    container_names: list[str] | None,
    container_tags: list[str] | None,
    incremental: bool | None,
    remediation: str | None,
    max_records_analyzed_per_partition: int | None,
    enrichment_source_record_limit: int | None,
    greater_than_time: str | None,
    greater_than_batch: float | None,
    background: bool,
    poll_interval: int = DEFAULT_POLL_INTERVAL,
    timeout: int = DEFAULT_TIMEOUT,
):
    """Run scan operation for specified datastores."""

    def build_payload(datastore_id):
        return {
            "datastore_id": datastore_id,
            "type": "scan",
            "container_names": container_names,
            "container_tags": container_tags,
            "incremental": incremental,
            "remediation": remediation,
            "max_records_analyzed_per_partition": max_records_analyzed_per_partition,
            "enrichment_source_record_limit": enrichment_source_record_limit,
            "greater_than_time": greater_than_time,
            "greater_than_batch": greater_than_batch,
        }

    _run_for_datastores(
        client, "Scan", datastore_ids, build_payload, background, poll_interval, timeout
    )


def run_materialize(
    client: QualyticsClient,
    datastore_ids: list[int],
    container_names: list[str] | None,
    container_tags: list[str] | None,
    max_records_per_partition: int | None,
    background: bool,
    poll_interval: int = DEFAULT_POLL_INTERVAL,
    timeout: int = DEFAULT_TIMEOUT,
):
    """Run materialize operation for specified datastores."""

    def build_payload(datastore_id):
        return {
            "datastore_id": datastore_id,
            "type": "materialize",
            "container_names": container_names,
            "container_tags": container_tags,
            "max_records_per_partition": max_records_per_partition,
        }

    _run_for_datastores(
        client,
        "Materialize",
        datastore_ids,
        build_payload,
        background,
        poll_interval,
        timeout,
    )


def run_export(
    client: QualyticsClient,
    datastore_ids: list[int],
    asset_type: str,
    container_ids: list[int] | None,
    container_tags: list[str] | None,
    include_deleted: bool,
    background: bool,
    poll_interval: int = DEFAULT_POLL_INTERVAL,
    timeout: int = DEFAULT_TIMEOUT,
):
    """Run export operation for specified datastores."""

    def build_payload(datastore_id):
        return {
            "datastore_id": datastore_id,
            "type": "export",
            "asset_type": asset_type,
            "container_ids": container_ids,
            "container_tags": container_tags,
            "include_deleted": include_deleted,
        }

    _run_for_datastores(
        client,
        "Export",
        datastore_ids,
        build_payload,
        background,
        poll_interval,
        timeout,
    )
