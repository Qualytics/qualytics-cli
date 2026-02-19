"""Quality checks service functions."""

import requests
import typer
from rich import print
from rich.progress import track


def get_default_headers(token):
    """Get default authorization headers."""
    return {"Authorization": f"Bearer {token}"}


def get_quality_checks(
    base_url: str,
    token: str,
    datastore_id: int,
    containers: list[int] | None,
    tags: list[str] | None,
    status: list[str] | None,
):
    """Retrieve quality checks from the API with pagination."""
    endpoint = "quality-checks"
    url = f"{base_url}{endpoint}?datastore={datastore_id}"

    if containers:
        containers_string = "".join(
            f"&container={container}" for container in containers
        )
        url += containers_string

    if tags:
        tags_string = "".join(f"&tag={tag}" for tag in tags)
        url += tags_string

    status_string = ""
    if status:
        archived_only = False
        active_or_draft_count = 0

        # Process each status
        for check_status in status:
            check_status = check_status.lower()

            if check_status not in ["active", "draft", "archived"]:
                print(
                    f"[bold red] The following status: {check_status} doesn't exist [/bold red]"
                )
            elif check_status == "archived":
                archived_only = True
            elif check_status in ["active", "draft"]:
                active_or_draft_count += 1

        # If archived is present, we only use archived=only and skip others
        if archived_only:
            status_string = "&archived=only"
        # If only one of active or draft is present, append it
        elif active_or_draft_count == 1:
            for check_status in status:
                if check_status in ["active", "draft"]:
                    status_string += f"&status={check_status.capitalize()}"

        # Add status_string to the url
        url += status_string
    else:
        status = "Active"

    page = 1
    size = 100
    params = {"sort_created": "asc", "size": size, "page": page}

    response = requests.get(
        url, headers=get_default_headers(token), params=params, verify=False
    )

    # Check for non-success status codes
    if response.status_code != 200:
        typer.secho(
            f"Failed to retrieve quality checks. Server responded with: {response.status_code} - {response.text}. Please verify if your credentials are correct.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    data = response.json()

    # Check if "total" is in the response data
    if "total" not in data:
        typer.secho(
            f"Unexpected server response. 'total' field missing in: {data}. Please verify if your credentials are correct.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    total = data["total"]
    all_quality_checks = []

    total_pages = -(-total // size)

    # Loop through the pages based on total number and size
    for current_page in track(
        range(total_pages), description="Exporting quality checks..."
    ):
        # Append the current page's data to the concatenated array
        all_quality_checks.extend(data["items"])

        total -= size
        page += 1

        params["page"] = page
        response = requests.get(
            url, headers=get_default_headers(token), params=params, verify=False
        )
        data = response.json()

    print(f"[bold green] Total of Quality Checks = {data['total']} [/bold green]")
    print(f"[bold green] Total pages = {total_pages} [/bold green]")
    return all_quality_checks


def get_quality_check_by_additional_metadata(
    base_url: str, token: str, additional_metadata: dict
):
    """Get a quality check by its additional metadata."""
    endpoint = "quality-checks"
    quality_check_key = "from quality check id"
    datastore_id_key = "main datastore id"
    params = {
        "datastore": additional_metadata[datastore_id_key],
        "search": f'"{quality_check_key}": "{additional_metadata[quality_check_key]}", "{datastore_id_key}": "{additional_metadata[datastore_id_key]}"',
    }
    url = f"{base_url}{endpoint}"

    response = requests.get(
        url, headers=get_default_headers(token), params=params, verify=False
    )

    if response.status_code == 200:
        quality_check = response.json()["items"]

        if len(quality_check) == 1:
            return response.json()["items"][0]["id"]

    return None


def get_check_templates(
    base_url: str,
    token: str,
    ids: list[int] | None,
    status: bool | None,
    rules: list[str] | None,
    tags: list[str] | None,
):
    """Retrieve check templates from the API."""
    endpoint = "quality-checks"
    url = f"{base_url}{endpoint}?template_only=true"

    if status:
        url += f"&template_locked={status}"

    if rules:
        rules_string = "".join(f"&rule_type={rule}" for rule in rules)
        url += rules_string

    if tags:
        tags_string = "".join(f"&tag={tag}" for tag in tags)
        url += tags_string
    page = 1
    size = 100
    params = {"sort_created": "asc", "size": size, "page": page}

    response = requests.get(
        url, headers=get_default_headers(token), params=params, verify=False
    )

    # Check for non-success status codes
    if response.status_code != 200:
        typer.secho(
            f"Failed to retrieve check templates. Server responded with: {response.status_code} - {response.text}. Please verify if your credentials are correct.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    data = response.json()

    # Check if "total" is in the response data
    if "total" not in data:
        typer.secho(
            f"Unexpected server response. 'total' field missing in: {data}. Please verify if your credentials are correct.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    total = data["total"]
    all_quality_checks = []

    total_pages = -(-total // size)

    # Loop through the pages based on total number and size
    for current_page in track(
        range(total_pages), description="Exporting quality checks..."
    ):
        # Append the current page's data to the concatenated array
        all_quality_checks.extend(data["items"])

        total -= size
        page += 1

        params["page"] = page
        response = requests.get(
            url, headers=get_default_headers(token), params=params, verify=False
        )
        data = response.json()

    if ids:
        all_quality_checks = [
            check for check in all_quality_checks if check["id"] in ids
        ]

    return all_quality_checks


def get_check_templates_metadata(
    base_url: str,
    token: str,
    ids: list[int] | None,
):
    """Retrieve check templates metadata from the API."""
    endpoint = "quality-checks"
    url = f"{base_url}{endpoint}?template_only=true"

    page = 1
    size = 100
    params = {"sort_created": "asc", "size": size, "page": page}

    response = requests.get(
        url, headers=get_default_headers(token), params=params, verify=False
    )

    # Check for non-success status codes
    if response.status_code != 200:
        typer.secho(
            f"Failed to retrieve check templates. Server responded with: {response.status_code} - {response.text}. Please verify if your credentials are correct.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    data = response.json()

    # Check if "total" is in the response data
    if "total" not in data:
        typer.secho(
            f"Unexpected server response. 'total' field missing in: {data}. Please verify if your credentials are correct.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    total = data["total"]
    all_quality_checks = []

    total_pages = -(-total // size)

    # Loop through the pages based on total number and size
    for current_page in range(total_pages):
        # Append the current page's data to the concatenated array
        all_quality_checks.extend(data["items"])

        total -= size
        page += 1

        params["page"] = page
        response = requests.get(
            url, headers=get_default_headers(token), params=params, verify=False
        )
        data = response.json()

    if ids:
        all_quality_checks = [
            check for check in all_quality_checks if check["id"] in ids
        ]

    return all_quality_checks
