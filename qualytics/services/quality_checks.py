"""Quality checks service functions."""

import typer
from rich import print
from rich.progress import track

from ..api.client import QualyticsClient


def get_quality_checks(
    client: QualyticsClient,
    datastore_id: int,
    containers: list[int] | None,
    tags: list[str] | None,
    status: list[str] | None,
):
    """Retrieve quality checks from the API with pagination."""
    endpoint = "quality-checks"
    url_path = f"{endpoint}?datastore={datastore_id}"

    if containers:
        containers_string = "".join(
            f"&container={container}" for container in containers
        )
        url_path += containers_string

    if tags:
        tags_string = "".join(f"&tag={tag}" for tag in tags)
        url_path += tags_string

    status_string = ""
    if status:
        archived_only = False
        active_or_draft_count = 0

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

        if archived_only:
            status_string = "&archived=only"
        elif active_or_draft_count == 1:
            for check_status in status:
                if check_status in ["active", "draft"]:
                    status_string += f"&status={check_status.capitalize()}"

        url_path += status_string
    else:
        status = "Active"

    page = 1
    size = 100
    params = {"sort_created": "asc", "size": size, "page": page}

    response = client.get(url_path, params=params)
    data = response.json()

    if "total" not in data:
        typer.secho(
            f"Unexpected server response. 'total' field missing in: {data}. Please verify if your credentials are correct.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    total = data["total"]
    all_quality_checks = []

    total_pages = -(-total // size)

    for current_page in track(
        range(total_pages), description="Exporting quality checks..."
    ):
        all_quality_checks.extend(data["items"])

        total -= size
        page += 1

        params["page"] = page
        response = client.get(url_path, params=params)
        data = response.json()

    print(f"[bold green] Total of Quality Checks = {data['total']} [/bold green]")
    print(f"[bold green] Total pages = {total_pages} [/bold green]")
    return all_quality_checks


def get_quality_check_by_additional_metadata(
    client: QualyticsClient, additional_metadata: dict
):
    """Get a quality check by its additional metadata."""
    endpoint = "quality-checks"
    quality_check_key = "from quality check id"
    datastore_id_key = "main datastore id"
    params = {
        "datastore": additional_metadata[datastore_id_key],
        "search": f'"{quality_check_key}": "{additional_metadata[quality_check_key]}", "{datastore_id_key}": "{additional_metadata[datastore_id_key]}"',
    }

    response = client.get(endpoint, params=params)
    quality_check = response.json()["items"]

    if len(quality_check) == 1:
        return response.json()["items"][0]["id"]

    return None


def get_check_templates(
    client: QualyticsClient,
    ids: list[int] | None,
    status: bool | None,
    rules: list[str] | None,
    tags: list[str] | None,
):
    """Retrieve check templates from the API."""
    endpoint = "quality-checks"
    url_path = f"{endpoint}?template_only=true"

    if status:
        url_path += f"&template_locked={status}"

    if rules:
        rules_string = "".join(f"&rule_type={rule}" for rule in rules)
        url_path += rules_string

    if tags:
        tags_string = "".join(f"&tag={tag}" for tag in tags)
        url_path += tags_string
    page = 1
    size = 100
    params = {"sort_created": "asc", "size": size, "page": page}

    response = client.get(url_path, params=params)
    data = response.json()

    if "total" not in data:
        typer.secho(
            f"Unexpected server response. 'total' field missing in: {data}. Please verify if your credentials are correct.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    total = data["total"]
    all_quality_checks = []

    total_pages = -(-total // size)

    for current_page in track(
        range(total_pages), description="Exporting quality checks..."
    ):
        all_quality_checks.extend(data["items"])

        total -= size
        page += 1

        params["page"] = page
        response = client.get(url_path, params=params)
        data = response.json()

    if ids:
        all_quality_checks = [
            check for check in all_quality_checks if check["id"] in ids
        ]

    return all_quality_checks


def get_check_templates_metadata(
    client: QualyticsClient,
    ids: list[int] | None,
):
    """Retrieve check templates metadata from the API."""
    endpoint = "quality-checks"
    url_path = f"{endpoint}?template_only=true"

    page = 1
    size = 100
    params = {"sort_created": "asc", "size": size, "page": page}

    response = client.get(url_path, params=params)
    data = response.json()

    if "total" not in data:
        typer.secho(
            f"Unexpected server response. 'total' field missing in: {data}. Please verify if your credentials are correct.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    total = data["total"]
    all_quality_checks = []

    total_pages = -(-total // size)

    for current_page in range(total_pages):
        all_quality_checks.extend(data["items"])

        total -= size
        page += 1

        params["page"] = page
        response = client.get(url_path, params=params)
        data = response.json()

    if ids:
        all_quality_checks = [
            check for check in all_quality_checks if check["id"] in ids
        ]

    return all_quality_checks
