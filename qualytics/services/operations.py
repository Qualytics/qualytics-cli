"""Operations service functions for catalog, profile, and scan."""

import time
import requests
from datetime import datetime
from rich import print
from rich.progress import track

from ..config import load_config, OPERATION_ERROR_PATH
from ..utils import validate_and_format_url
from ..utils.file_ops import log_error


def get_default_headers(token):
    """Get default authorization headers."""
    return {"Authorization": f"Bearer {token}"}


def wait_for_operation_finishes(operation: int, token: str):
    """
    Wait for an operation to finish executing.

    Parameters:
    - operation (int): The operation ID.
    - token (str): Authentication token.

    Returns:
    - The operation response object.
    """
    config = load_config()
    base_url = validate_and_format_url(config["url"])
    headers = get_default_headers(token)
    max_retries = 10
    wait_time = 50
    for attempt in range(max_retries):
        end_scan = None
        response = None
        while not end_scan:
            print(" Waiting for operation to finish")
            response = requests.get(
                base_url + f"operations/{operation}", headers=headers
            ).json()
            time.sleep(5)
            if response["end_time"]:
                end_scan = True
        time.sleep(10)
        if response["result"] == "success":
            return response
        if attempt == max_retries - 1:
            return response
        print(f"Attempt {attempt + 1} failed. Retrying in {wait_time} seconds...")
        time.sleep(wait_time)


def check_operation_status(operation_ids: [int], token: str):
    """Check the status of one or more operations."""
    config = load_config()
    base_url = validate_and_format_url(config["url"])
    headers = get_default_headers(token)

    for curr_id in track(operation_ids, description="Processing..."):
        response = requests.get(
            base_url + f"operations/{curr_id}", headers=headers
        ).json()
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


def run_catalog(
    datastore_ids: [int],
    include: [str],
    prune: bool,
    recreate: bool,
    token: str,
    background: bool,
):
    """Run catalog operation for specified datastores."""
    config = load_config()
    base_url = validate_and_format_url(config["url"])
    endpoint = "operations/run"
    url = f"{base_url}{endpoint}"
    for datastore_id in track(datastore_ids, description="Processing..."):
        try:
            response = requests.post(
                f"{url}",
                headers=get_default_headers(token),
                json={
                    "datastore_id": datastore_id,
                    "type": "catalog",
                    "include": include,
                    "prune": prune,
                    "recreate": recreate,
                },
            )
            if not (
                200 <= response.status_code <= 299
            ):  # Operation fails before starting
                response = response.json()
                raise Exception
            catalog_id = response.json()["id"]
            print(
                f"[bold green] Started Catalog operation {catalog_id} "
                f"for datastore: {datastore_id} [/bold green]"
            )
            if background is False:
                response = wait_for_operation_finishes(response.json()["id"], token)
                if response["result"] == "success" and response["message"] is None:
                    print(
                        f"[bold green] Successfully Finished Catalog operation {catalog_id}"
                        f"for datastore: {datastore_id} [/bold green]"
                    )
                elif (
                    response["result"] == "success" and response["message"] is not None
                ):  # Warning occurred
                    msg = response["message"]
                    print(
                        f"[bold yellow] Warning for Catalog operation {catalog_id} on datastore {datastore_id}:"
                        f" {msg}[/bold yellow]"
                    )
                else:
                    print(
                        f"[bold red] Failed Catalog {catalog_id} for datastore: {datastore_id}, Please check the path: "
                        f"{OPERATION_ERROR_PATH}[/bold red]"
                    )
                    message = response["detail"]
                    current_datetime = datetime.now().strftime("[%m-%d-%Y %H:%M:%S]")
                    message = f"{current_datetime}: Error executing catalog operation: {message}\n\n"
                    log_error(message, OPERATION_ERROR_PATH)
        except Exception:
            print(
                f"[bold red] Failed Catalog for datastore: {datastore_id}, Please check the path: "
                f"{OPERATION_ERROR_PATH}[/bold red]"
            )
            message = response["detail"]
            current_datetime = datetime.now().strftime("[%m-%d-%Y %H:%M:%S]")
            message = (
                f"{current_datetime}: Error executing catalog operation: {message}\n\n"
            )
            log_error(message, OPERATION_ERROR_PATH)


def run_profile(
    datastore_ids: [int],
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
    token: str,
    background: bool,
):
    """Run profile operation for specified datastores."""
    config = load_config()
    base_url = validate_and_format_url(config["url"])
    endpoint = "operations/run"
    url = f"{base_url}{endpoint}"

    for datastore_id in track(datastore_ids, description="Processing..."):
        try:
            response = requests.post(
                f"{url}",
                headers=get_default_headers(token),
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
            if not (
                200 <= response.status_code <= 299
            ):  # Operation fails before starting
                response = response.json()
                raise Exception
            profile_id = response.json()["id"]
            print(
                f"[bold green] Successfully Started Profile {profile_id} for datastore: {datastore_id} [/bold green]"
            )
            if background is False:
                response = wait_for_operation_finishes(response.json()["id"], token)
                if response["result"] == "success" and response["message"] is None:
                    print(
                        f"[bold green] Successfully Finished Profile operation {profile_id} "
                        f"for datastore: {datastore_id} [/bold green]"
                    )
                elif (
                    response["result"] == "success" and response["message"] is not None
                ):  # Warning occurred
                    msg = response["message"]
                    print(
                        f"[bold yellow] Warning for profile operation {profile_id} on datastore {datastore_id}:"
                        f" {msg}[/bold yellow]"
                    )
                else:
                    print(
                        f"[bold red] Failed Profile {profile_id} for datastore: {datastore_id}, Please check the path: "
                        f"{OPERATION_ERROR_PATH}[/bold red]"
                    )
                    message = response["detail"]
                    current_datetime = datetime.now().strftime("[%m-%d-%Y %H:%M:%S]")
                    message = f"{current_datetime}: Error executing profile operation: {message}\n\n"
                    log_error(message, OPERATION_ERROR_PATH)
        except Exception:
            print(
                f"[bold red] Failed Profile for datastore: {datastore_id}, Please check the path: "
                f"{OPERATION_ERROR_PATH}[/bold red]"
            )
            message = response["detail"]
            current_datetime = datetime.now().strftime("[%m-%d-%Y %H:%M:%S]")
            message = (
                f"{current_datetime}: Error executing profile operation: {message}\n\n"
            )
            log_error(message, OPERATION_ERROR_PATH)


def run_scan(
    datastore_ids: [int],
    container_names: list[str] | None,
    container_tags: list[str] | None,
    incremental: bool | None,
    remediation: str | None,
    max_records_analyzed_per_partition: int | None,
    enrichment_source_record_limit: int | None,
    greater_than_time: datetime | None,
    greater_than_batch: float | None,
    token: str,
    background: bool,
):
    """Run scan operation for specified datastores."""
    config = load_config()
    base_url = validate_and_format_url(config["url"])
    endpoint = "operations/run"
    url = f"{base_url}{endpoint}"
    for datastore_id in track(datastore_ids, description="Processing..."):
        try:
            response = requests.post(
                f"{url}",
                headers=get_default_headers(token),
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
            if not (
                200 <= response.status_code <= 299
            ):  # Operation fails before starting
                response = response.json()
                raise Exception
            scan_id = response.json()["id"]
            print(
                f"[bold green] Successfully Started Scan {scan_id} for datastore: {datastore_id} [/bold green]"
            )
            if background is False:
                response = wait_for_operation_finishes(response.json()["id"], token)
                if response["result"] == "success" and response["message"] is None:
                    print(
                        f"[bold green] Successfully Finished Scan operation {scan_id} "
                        f"for datastore: {datastore_id} [/bold green]"
                    )
                elif (
                    response["result"] == "success" and response["message"] is not None
                ):
                    msg = response["message"]
                    print(
                        f"[bold yellow] Warning for scan operation {scan_id}on datastore {datastore_id}:"
                        f" {msg}[/bold yellow]"
                    )
                else:
                    print(
                        f"[bold red] Failed Scan {scan_id} for datastore: {datastore_id}, Please check the path: "
                        f"{OPERATION_ERROR_PATH}[/bold red]"
                    )
                    with open(OPERATION_ERROR_PATH, "a") as error_file:
                        message = response["detail"]
                        current_datetime = datetime.now().strftime(
                            "[%m-%d-%Y %H:%M:%S]"
                        )
                        error_file.write(
                            f"{current_datetime} : Error executing catalog operation: {message}\n\n"
                        )
        except Exception:
            print(
                f"[bold red] Failed Scan for datastore: {datastore_id}, Please check the path: "
                f"{OPERATION_ERROR_PATH}[/bold red]"
            )
            with open(OPERATION_ERROR_PATH, "a") as error_file:
                message = response["detail"]
                current_datetime = datetime.now().strftime("[%m-%d-%Y %H:%M:%S]")
                error_file.write(
                    f"{current_datetime} : Error executing catalog operation: {message}\n\n"
                )
