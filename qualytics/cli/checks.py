"""CLI commands for quality checks."""
import json
import re
import typer
import requests
from datetime import datetime
from itertools import product
from rich import print
from rich.progress import track

from ..setup import BASE_PATH, get_config, is_token_valid
from ..utils import validate_and_format_url, distinct_file_content, log_error
from ..services.quality_checks import (
    get_quality_checks,
    get_check_templates,
    get_check_templates_metadata,
    get_quality_check_by_additional_metadata,
)
from ..services.containers import get_table_ids


# Create Typer instance for checks
checks_app = typer.Typer(name="checks", help="Commands for handling checks")


# Helper function for API calls
def _get_default_headers(token):
    """Get default authorization headers."""
    return {"Authorization": f"Bearer {token}"}


@checks_app.command("export")
def checks_export(
    datastore: int = typer.Option(..., "--datastore", help="Datastore ID"),
    containers: str | None = typer.Option(
        None,
        "--containers",
        help='Comma-separated list of containers IDs or array-like format. Example: "1, 2, 3" or "[1,2,3]"',
    ),
    tags: str | None = typer.Option(
        None,
        "--tags",
        help='Comma-separated list of Tag names or array-like format. Example: "tag1, tag2, tag3" or "[tag1, tag2, tag3]"',
    ),
    status: str | None = typer.Option(
        None,
        "--status",
        help='Comma-separated list of status IDs or array-like format. Example: "Active, Draft, Archived" or "[Active, Draft, Archived]"',
    ),
    output: str = typer.Option(
        BASE_PATH + "/data_checks.json", "--output", help="Output file path"
    ),
):
    """
    Export checks to a file.
    """
    config = get_config()

    if not config:
        print("[bold red] Error: No configuration found. [/bold red]")
        print("[bold yellow] Please run 'qualytics init' to set up your configuration. [/bold yellow]")
        raise typer.Exit(code=1)

    base_url = validate_and_format_url(config["url"])
    token = is_token_valid(config["token"])

    if token:
        if containers:
            containers = [int(x.strip()) for x in containers.strip("[]").split(",")]
        if tags:
            tags = [str(x.strip()) for x in tags.strip("[]").split(",")]
        if status:
            status = [str(x.strip()) for x in status.strip("[]").split(",")]

        all_quality_checks = get_quality_checks(
            base_url=base_url,
            token=token,
            datastore_id=datastore,
            containers=containers,
            tags=tags,
            status=status,
        )

        with open(output, "w") as f:
            json.dump(all_quality_checks, f, indent=4)
        print(f"[bold green]Data exported to {output}[/bold green]")


@checks_app.command("export-templates")
def check_templates_export(
    enrich_datastore_id: int | None = typer.Option(
        None, "--enrichment_datastore_id", help="Enrichment Datastore ID"
    ),
    check_templates: str | None = typer.Option(
        None,
        "--check_templates",
        help='Comma-separated list of check templates IDs or array-like format. Example: "1, 2, 3" or "[1,2,3]"',
    ),
    status: bool | None = typer.Option(
        None,
        "--status",
        help="Check Template status send `true` if it's locked or `false` to unlocked.",
    ),
    rules: str | None = typer.Option(
        None,
        "--rules",
        help='Comma-separated list of check templates rule types or array-like format. Example: "afterDateTime, aggregationComparison" or "[afterDateTime, aggregationComparison]"',
    ),
    tags: str | None = typer.Option(
        None,
        "--tags",
        help='Comma-separated list of Tag names or array-like format. Example: "tag1, tag2, tag3" or "[tag1, tag2, tag3]"',
    ),
    output: str = typer.Option(
        BASE_PATH + "/data_checks_template.json", "--output", help="Output file path"
    ),
):
    """
    Export check templates to an enrichment or file.
    """
    config = get_config()

    if not config:
        print("[bold red] Error: No configuration found. [/bold red]")
        print("[bold yellow] Please run 'qualytics init' to set up your configuration. [/bold yellow]")
        raise typer.Exit(code=1)

    base_url = validate_and_format_url(config["url"])
    token = is_token_valid(config["token"])

    if token:
        if check_templates:
            check_templates = [
                int(x.strip()) for x in check_templates.strip("[]").split(",")
            ]
        if enrich_datastore_id:
            endpoint = "export/check-templates"
            url = f"{base_url}{endpoint}?enrich_datastore_id={enrich_datastore_id}"

            if check_templates:
                containers_string = "".join(
                    f"&template_ids={check_template}"
                    for check_template in check_templates
                )
                url += containers_string

            response = requests.post(
                url, headers=_get_default_headers(token), verify=False
            )

            # Check for non-success status codes
            if response.status_code != 204:
                typer.secho(
                    f"Failed to export check templates. Server responded with: {response.status_code} - {response.text}.",
                    fg=typer.colors.RED,
                )
                raise typer.Exit(code=1)

            print(
                f"[bold green]The check templates were exported to the table `_export_check_templates` to enrichment id: {enrich_datastore_id}.[/bold green]"
            )
        else:
            if rules:
                rules = [str(x.strip()) for x in rules.strip("[]").split(",")]

            all_quality_checks = get_check_templates(
                base_url=base_url,
                token=token,
                ids=check_templates,
                status=status,
                rules=rules,
                tags=tags,
            )

            if all_quality_checks is None or len(all_quality_checks) == 0:
                print(
                    f"[bold red] No check templates found for the ids: {check_templates} [/bold red]"
                )
            else:
                print(
                    f"[bold green] Total of Check Templates exported= {len(all_quality_checks)} [/bold green]"
                )
                with open(output, "w") as f:
                    json.dump(all_quality_checks, f, indent=4)
                print(f"[bold green]Data exported to {output}[/bold green]")


@checks_app.command("import")
def checks_import(
    datastore: str = typer.Option(
        ...,
        "--datastore",
        help="Comma-separated list of Datastore IDs or array-like format",
    ),
    input_file: str = typer.Option(
        BASE_PATH + "/data_checks.json", "--input", help="Input file path"
    ),
):
    """
    Import checks from a file.
    """
    # Remove brackets if present and split by comma
    datastores = [int(x.strip()) for x in datastore.strip("[]").split(",")]
    config = get_config()

    if not config:
        print("[bold red] Error: No configuration found. [/bold red]")
        print("[bold yellow] Please run 'qualytics init' to set up your configuration. [/bold yellow]")
        raise typer.Exit(code=1)

    base_url = validate_and_format_url(config["url"])
    token = is_token_valid(config["token"])
    error_log_path = f"/errors-{datetime.now().strftime('%Y-%m-%d')}.log"
    if token:
        with open(input_file) as f:
            all_quality_checks = json.load(f)
            total_created_checks = 0
            total_updated_checks = 0

            # Create pairs of datastore and quality_check to process
            pairs_to_process = list(product(datastores, all_quality_checks))

            # Now use the track function to show the progress bar
            for datastore_id, quality_check in track(
                pairs_to_process, description="Processing..."
            ):
                # for datastore_id in datastores:
                table_ids = get_table_ids(
                    base_url=base_url, token=token, datastore_id=datastore_id
                )

                # for quality_check in all_quality_checks:
                container_id = None
                if table_ids:
                    try:
                        container_id = table_ids[quality_check["container"]["name"]]
                    except Exception:
                        print(
                            f"[bold red] Profile `{quality_check['container']['name']}` was not found in datastore id: {datastore_id}[/bold red]"
                        )
                        log_error(
                            f"Profile `{quality_check['container']['name']}` of quality check {quality_check['id']} was not found in datastore id: {datastore_id}",
                            BASE_PATH + error_log_path,
                        )
                    if container_id:
                        additional_metadata = {
                            "from quality check id": f"{quality_check['id']}",
                            "main datastore id": f"{datastore_id}",
                        }

                        if quality_check["additional_metadata"] is None:
                            quality_check["additional_metadata"] = additional_metadata
                        else:
                            quality_check["additional_metadata"].update(
                                additional_metadata
                            )

                        payload = {
                            "fields": [
                                field["name"] for field in quality_check["fields"]
                            ],
                            "description": f"{quality_check['description']}",
                            "rule": quality_check["rule_type"],
                            "coverage": quality_check["coverage"],
                            "is_new": quality_check["is_new"],
                            "filter": quality_check["filter"],
                            "properties": quality_check["properties"],
                            "tags": [
                                global_tag["name"]
                                for global_tag in quality_check["global_tags"]
                            ],
                            "container_id": container_id,
                            "additional_metadata": quality_check["additional_metadata"],
                            "status": quality_check["status"],
                        }
                        # gets the quality_check by the description
                        quality_check_id = get_quality_check_by_additional_metadata(
                            base_url=base_url,
                            token=token,
                            additional_metadata=additional_metadata,
                        )

                        # If a quality check contains the description, we sync
                        if quality_check_id:
                            print(
                                f"[bold yellow]Quality check for container: {quality_check['container']['name']} was already created on datastore id: {datastore_id}. Updating quality check id: {quality_check_id}[/bold yellow]"
                            )
                            response = requests.put(
                                base_url + f"quality-checks/{quality_check_id}",
                                headers=_get_default_headers(token),
                                json=payload,
                                verify=False,
                            )
                            if response.status_code == 200:
                                print(
                                    f"[bold green]Quality check id: {quality_check_id} updated successfully for datastore id: {datastore_id}[/bold green]"
                                )
                                total_updated_checks += 1
                            else:
                                print(
                                    f"[bold red]Error updating quality check id: {quality_check_id} [/bold red]"
                                )
                                log_error(
                                    f"Error updating quality check id: {quality_check_id} on datastore id: {datastore_id}. Details: {response.text}",
                                    BASE_PATH + error_log_path,
                                )
                        # If a quality check does not contain the description:
                        # 1. We try to create quality check and verify for conflict
                        #    a. If we notify a conflict, it will  update the check
                        #    b. If there's no conflict, it will create a new one
                        else:
                            new_check_from_template = False
                            if quality_check["template"] is not None:
                                check_templates = get_check_templates_metadata(
                                    base_url=base_url,
                                    token=token,
                                    ids=[quality_check["template"]["id"]],
                                )
                                if len(check_templates) > 0:
                                    for check_template in check_templates:
                                        check_template_payload = {
                                            "fields": [
                                                field["name"]
                                                for field in quality_check["fields"]
                                            ],
                                            "description": f"{check_template['description']}",
                                            "rule": check_template["rule_type"],
                                            "coverage": check_template["coverage"],
                                            "filter": check_template["filter"],
                                            "properties": check_template["properties"],
                                            "tags": [
                                                global_tag["name"]
                                                for global_tag in check_template[
                                                    "global_tags"
                                                ]
                                            ],
                                            "container_id": container_id,
                                            "additional_metadata": check_template[
                                                "additional_metadata"
                                            ],
                                            "template_id": check_template["id"],
                                            "status": quality_check["status"],
                                        }
                                        response = requests.post(
                                            base_url + "quality-checks",
                                            headers=_get_default_headers(token),
                                            json=check_template_payload,
                                            verify=False,
                                        )
                                        if response.status_code == 409:
                                            match = re.search(
                                                r"id: (\d+)", response.text
                                            )
                                            print(
                                                f"[bold yellow]Quality check for container: {quality_check['container']['name']} was already created on datastore id: {datastore_id}. Updating check id: {match.group(1)}.[/bold yellow]"
                                            )
                                            response = requests.put(
                                                base_url
                                                + f"quality-checks/{match.group(1)}",
                                                headers=_get_default_headers(token),
                                                json=check_template_payload,
                                                verify=False,
                                            )
                                            if response.status_code == 200:
                                                print(
                                                    f"[bold green]Quality check id: {match.group(1)} updated successfully for datastore id: {datastore_id} from the template: '{check_template['id']}'[/bold green]"
                                                )
                                                total_updated_checks += 1
                                            else:
                                                print(
                                                    f"[bold red]Error updating quality check id: {match.group(1)} from the template: '{check_template['id']}' [/bold red]"
                                                )
                                                log_error(
                                                    f"Error updating quality check id: {match.group(1)} on datastore id: {datastore_id} from the template: '{check_template['id']}'. Details: {response.text}",
                                                    BASE_PATH + error_log_path,
                                                )
                                        elif response.status_code == 200:
                                            print(
                                                f"[bold green]Quality check id: {response.json()['id']} for container: {quality_check['container']['name']} created successfully from the template: '{check_template['id']}'[/bold green]"
                                            )
                                            total_created_checks += 1
                                        elif response.status_code == 404:
                                            print(
                                                f"[bold yellow]Error creating quality check id: {match.group(1)} from the template: '{check_template['id']}'. Creating check without a template [/bold yellow]"
                                            )
                                            new_check_from_template = True
                                        else:
                                            log_error(
                                                f"Error creating quality check for datastore id: {datastore_id}. Details: {response.text} from the template: '{check_template['id']}",
                                                BASE_PATH + error_log_path,
                                            )
                                else:
                                    print(
                                        f"[bold yellow]Error creating quality check id: {quality_check['id']} from the template: '{quality_check['template']['id']}'. Attempt to create the check without a template [/bold yellow]"
                                    )
                                    new_check_from_template = True
                            if (
                                new_check_from_template
                                or quality_check["template"] is None
                            ):
                                response = requests.post(
                                    base_url + "quality-checks",
                                    headers=_get_default_headers(token),
                                    json=payload,
                                    verify=False,
                                )
                                if response.status_code == 409:
                                    match = re.search(r"id: (\d+)", response.text)
                                    print(
                                        f"[bold yellow]Quality check for container: {quality_check['container']['name']} was already created on datastore id: {datastore_id}. Updating check id: {match.group(1)}.[/bold yellow]"
                                    )
                                    response = requests.put(
                                        base_url + f"quality-checks/{match.group(1)}",
                                        headers=_get_default_headers(token),
                                        json=payload,
                                        verify=False,
                                    )
                                    if response.status_code == 200:
                                        print(
                                            f"[bold green]Quality check id: {match.group(1)} updated successfully for datastore id: {datastore_id}[/bold green]"
                                        )
                                        total_updated_checks += 1
                                    else:
                                        print(
                                            f"[bold red]Error updating quality check id: {match.group(1)} [/bold red]"
                                        )
                                        log_error(
                                            f"Error updating quality check id: {match.group(1)} on datastore id: {datastore_id}. Details: {response.text}",
                                            BASE_PATH + error_log_path,
                                        )
                                elif response.status_code == 200:
                                    print(
                                        f"[bold green]Quality check id: {response.json()['id']} for container: {quality_check['container']['name']} created successfully[/bold green]"
                                    )
                                    total_created_checks += 1
                                else:
                                    log_error(
                                        f"Error creating quality check for datastore id: {datastore_id}. Details: {response.text}",
                                        BASE_PATH + error_log_path,
                                    )

            print(f"Updated a total of {total_updated_checks} quality checks.")
            print(f"Created a total of {total_created_checks} quality checks.")
            distinct_file_content(BASE_PATH + error_log_path)


@checks_app.command("import-templates")
def check_templates_import(
    input_file: str = typer.Option(
        BASE_PATH + "/data_checks_template.json", "--input", help="Input file path"
    ),
):
    """
    Import check templates from a file. Only creates new templates, no updates.
    """
    config = get_config()

    if not config:
        print("[bold red] Error: No configuration found. [/bold red]")
        print("[bold yellow] Please run 'qualytics init' to set up your configuration. [/bold yellow]")
        raise typer.Exit(code=1)

    base_url = validate_and_format_url(config["url"])
    token = is_token_valid(config["token"])
    error_log_path = f"/errors-{datetime.now().strftime('%Y-%m-%d')}.log"

    if token:
        with open(input_file) as f:
            all_check_templates = json.load(f)
            total_created_templates = 0

            # Process each check template from the file
            for check_template in track(
                all_check_templates, description="Processing templates..."
            ):
                try:
                    additional_metadata = {
                        "from quality check id": f"{check_template.get('id', None)}",
                    }

                    if check_template.get("additional_metadata", None) is None:
                        check_template["additional_metadata"] = additional_metadata
                    else:
                        check_template["additional_metadata"].update(
                            additional_metadata
                        )

                    # Build the payload for the API request
                    payload = {
                        "fields": [field["name"] for field in check_template["fields"]],
                        "description": check_template["description"],
                        "rule": check_template["rule_type"],
                        "coverage": check_template["coverage"],
                        "properties": check_template["properties"],
                        "tags": [
                            global_tag["name"]
                            for global_tag in check_template["global_tags"]
                        ],
                        "template_locked": check_template.get("template_locked", False),
                        "template_only": True,  # Mark as a template
                        "additional_metadata": check_template.get(
                            "additional_metadata", None
                        ),
                    }

                    # Create a new check template via POST request
                    response = requests.post(
                        base_url + "quality-checks",
                        headers=_get_default_headers(token),
                        json=payload,
                        verify=False,
                    )
                    if response.status_code == 200:
                        print(
                            f"[bold green]Check template id: {response.json()['id']} created successfully[/bold green]"
                        )
                        total_created_templates += 1
                    else:
                        print("[bold red]Error creating check template [/bold red]")
                        log_error(
                            f"Error creating check template. Details: {response.text}",
                            BASE_PATH + error_log_path,
                        )
                except Exception as e:
                    print(
                        f"[bold red]Error processing check template {check_template['id']}: {str(e)}[/bold red]"
                    )
                    log_error(
                        f"Error processing check template {check_template['id']}. Details: {str(e)}",
                        BASE_PATH + error_log_path,
                    )

            # Print summary of created templates
            print(f"Created a total of {total_created_templates} check templates.")
            distinct_file_content(BASE_PATH + error_log_path)

