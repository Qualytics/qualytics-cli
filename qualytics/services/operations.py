"""Operations service functions for catalog, profile, and scan."""

import time
from datetime import datetime

from rich import print
from rich.progress import track

from ..api.client import QualyticsAPIError, QualyticsClient
from ..config import OPERATION_ERROR_PATH
from ..utils.file_ops import log_error

# Default polling configuration
DEFAULT_POLL_INTERVAL = 10  # seconds between polls
DEFAULT_TIMEOUT = 1800  # 30 minutes max wait


def wait_for_operation_finishes(
    client: QualyticsClient,
    operation: int,
    poll_interval: int = DEFAULT_POLL_INTERVAL,
    timeout: int = DEFAULT_TIMEOUT,
):
    """
    Wait for an operation to finish executing.

    Uses elapsed-time based timeout instead of fixed retry count.
    Shows periodic status updates during long polls.

    Parameters:
    - client: API client instance
    - operation: The operation ID.
    - poll_interval: Seconds between status checks (default 10).
    - timeout: Maximum seconds to wait (default 1800 = 30 min).

    Returns:
    - The operation response dict, or None on timeout.
    """
    start_time = time.monotonic()
    last_status_time = start_time

    while True:
        elapsed = time.monotonic() - start_time

        if elapsed >= timeout:
            print(
                f"[bold red] Operation {operation} timed out after {int(elapsed)}s [/bold red]"
            )
            return None

        response = client.get(f"operations/{operation}").json()

        if response.get("end_time"):
            return response

        # Print elapsed time every 60 seconds
        now = time.monotonic()
        if now - last_status_time >= 60:
            print(
                f"  [dim]Operation {operation} still running... ({int(elapsed)}s elapsed)[/dim]"
            )
            last_status_time = now

        time.sleep(poll_interval)


def check_operation_status(client: QualyticsClient, operation_ids: list[int]):
    """Check the status of one or more operations."""
    for curr_id in track(operation_ids, description="Processing..."):
        response = client.get(f"operations/{curr_id}").json()
        if "result" not in response.keys():
            print(f"[bold red] Operation: {curr_id} Not Found")
        elif response["result"] == "success":
            if response["end_time"]:
                print(
                    f"[bold green] Successfully Finished Operation: {curr_id} [/bold green]"
                )
        elif response["result"] == "running":
            print(f"[bold blue] Operation: {curr_id} is still running [/bold blue]")
        elif response["result"] == "failure":
            message = response["message"]
            print(
                f"[bold red] Operation: {curr_id} failed because {message} [/bold red]"
            )
        elif response["result"] == "aborted":
            print(f"[bold red] Operation: {curr_id} was aborted [/bold red]")


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


def run_catalog(
    client: QualyticsClient,
    datastore_ids: list[int],
    include: list[str],
    prune: bool,
    recreate: bool,
    background: bool,
    poll_interval: int = DEFAULT_POLL_INTERVAL,
    timeout: int = DEFAULT_TIMEOUT,
):
    """Run catalog operation for specified datastores."""
    for datastore_id in track(datastore_ids, description="Processing..."):
        try:
            response = client.post(
                "operations/run",
                json={
                    "datastore_id": datastore_id,
                    "type": "catalog",
                    "include": include,
                    "prune": prune,
                    "recreate": recreate,
                },
            )
            catalog_id = response.json()["id"]
            print(
                f"[bold green] Started Catalog operation {catalog_id} "
                f"for datastore: {datastore_id} [/bold green]"
            )
            if background is False:
                result = wait_for_operation_finishes(
                    client,
                    catalog_id,
                    poll_interval=poll_interval,
                    timeout=timeout,
                )
                _handle_operation_result(result, "Catalog", catalog_id, datastore_id)
        except QualyticsAPIError as e:
            print(
                f"[bold red] Failed Catalog for datastore: {datastore_id}, Please check the path: "
                f"{OPERATION_ERROR_PATH}[/bold red]"
            )
            current_datetime = datetime.now().strftime("[%m-%d-%Y %H:%M:%S]")
            log_error(
                f"{current_datetime}: Error executing catalog operation: {e.message}\n\n",
                OPERATION_ERROR_PATH,
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
    greater_than_time: datetime | None,
    greater_than_batch: float | None,
    histogram_max_distinct_values: int | None,
    background: bool,
    poll_interval: int = DEFAULT_POLL_INTERVAL,
    timeout: int = DEFAULT_TIMEOUT,
):
    """Run profile operation for specified datastores."""
    for datastore_id in track(datastore_ids, description="Processing..."):
        try:
            response = client.post(
                "operations/run",
                json={
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
                },
            )
            profile_id = response.json()["id"]
            print(
                f"[bold green] Successfully Started Profile {profile_id} for datastore: {datastore_id} [/bold green]"
            )
            if background is False:
                result = wait_for_operation_finishes(
                    client,
                    profile_id,
                    poll_interval=poll_interval,
                    timeout=timeout,
                )
                _handle_operation_result(result, "Profile", profile_id, datastore_id)
        except QualyticsAPIError as e:
            print(
                f"[bold red] Failed Profile for datastore: {datastore_id}, Please check the path: "
                f"{OPERATION_ERROR_PATH}[/bold red]"
            )
            current_datetime = datetime.now().strftime("[%m-%d-%Y %H:%M:%S]")
            log_error(
                f"{current_datetime}: Error executing profile operation: {e.message}\n\n",
                OPERATION_ERROR_PATH,
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
    greater_than_time: datetime | None,
    greater_than_batch: float | None,
    background: bool,
    poll_interval: int = DEFAULT_POLL_INTERVAL,
    timeout: int = DEFAULT_TIMEOUT,
):
    """Run scan operation for specified datastores."""
    for datastore_id in track(datastore_ids, description="Processing..."):
        try:
            response = client.post(
                "operations/run",
                json={
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
                },
            )
            scan_id = response.json()["id"]
            print(
                f"[bold green] Successfully Started Scan {scan_id} for datastore: {datastore_id} [/bold green]"
            )
            if background is False:
                result = wait_for_operation_finishes(
                    client,
                    scan_id,
                    poll_interval=poll_interval,
                    timeout=timeout,
                )
                _handle_operation_result(result, "Scan", scan_id, datastore_id)
        except QualyticsAPIError as e:
            print(
                f"[bold red] Failed Scan for datastore: {datastore_id}, Please check the path: "
                f"{OPERATION_ERROR_PATH}[/bold red]"
            )
            current_datetime = datetime.now().strftime("[%m-%d-%Y %H:%M:%S]")
            log_error(
                f"{current_datetime}: Error executing scan operation: {e.message}\n\n",
                OPERATION_ERROR_PATH,
            )
