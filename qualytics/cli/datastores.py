"""CLI commands for datastore management."""
import json
import typer
import requests
import typing as t
from rich import print

from ..setup import ConfigError, get_config, is_token_valid, CONNECTIONS_PATH
from ..utils import validate_and_format_url, get_connection
from ..services.datastores import (
    get_connection_by,
    get_datastore_by,
    build_new_datastore_payload,
)
from ..api import datastores as datastore


# Create Typer instance for datastores
datastore_app = typer.Typer(
    name="datastore", help="Commands for handling datastores"
)


# Helper function for API calls
def _get_default_headers(token):
    """Get default authorization headers."""
    return {"Authorization": f"Bearer {token}"}


@datastore_app.command("new", help="new datastore")
def new_datastore(
    name: str = typer.Option(..., "--name", "-n", help="Datastore name"),
    connection_name: t.Optional[str] = typer.Option(
        None,
        "--connection-name",
        "-cn",
        help="Connection name from the 'name' field in connections.yml (e.g., 'prod_snowflake_connection', not 'snowflake')",
    ),
    connection_id: t.Optional[int] = typer.Option(
        None, "--connection-id", help="Existing connection id to reference"
    ),
    database: str = typer.Option(
        ...,
        "--database",
        "-db",
        help="The database name from the connection being used",
    ),
    schema: str = typer.Option(
        ..., "--schema", "-sc", help="The schema name from the connection being used"
    ),
    tags: t.Optional[str] = typer.Option(None, "--tags", help="Comma-separated tags"),
    teams: t.Optional[str] = typer.Option(
        None, "--teams", help="Comma-separated team names"
    ),
    enrichment_only: bool = typer.Option(
        False,
        "--enrichment-only/--no-enrichment-only",
        help="Set if datastore will be an enrichment one",
    ),
    enrichment_prefix: t.Optional[str] = typer.Option(
        None, "--enrichment-prefix", help="Prefix for enrichment artifacts"
    ),
    enrichment_source_record_limit: t.Optional[int] = typer.Option(
        None, "--enrichment-source-record-limit", min=1
    ),
    enrichment_remediation_strategy: str = typer.Option(
        "none", "--enrichment-remediation-strategy"
    ),
    high_count_rollup_threshold: t.Optional[int] = typer.Option(
        None, "--high-count-rollup-threshold", min=1
    ),
    trigger_catalog: bool = typer.Option(
        True,
        "--trigger-catalog/--no-trigger-catalog",
        help="Whether to trigger catalog. Default is TRUE",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print payload only; no HTTP"
    ),
):
    config = get_config()

    if not config:
        print("[bold red] Error: No configuration found. [/bold red]")
        print("[bold yellow] Please run 'qualytics init' to set up your configuration. [/bold yellow]")
        raise typer.Exit(code=1)

    base_url = base_url = validate_and_format_url(config["url"])
    endpoint = "datastores"
    url = f"{base_url}{endpoint}"
    token = is_token_valid(config["token"])
    headers = _get_default_headers(token)

    if token:
        try:
            # Validation: require either connection_name or connection_id, but not both
            if connection_name and connection_id:
                print(
                    "[red]Error: Cannot specify both --connection-name and --connection-id. Please use only one.[/red]"
                )
                raise typer.Exit(code=1)

            if not connection_name and not connection_id:
                print(
                    "[red]Error: Must specify either --connection-name or --connection-id.[/red]"
                )
                raise typer.Exit(code=1)

            # Determine whether to use existing connection or create new one
            connection_cfg = None

            if connection_name:
                # First, check if connection already exists in Qualytics
                print(
                    f"[cyan]Checking if connection '{connection_name}' exists in Qualytics...[/cyan]"
                )
                existing_connection = get_connection_by(
                    base_url, token, connection_name=connection_name
                )

                if existing_connection:
                    # Connection exists in Qualytics, use its ID
                    connection_id = existing_connection["id"]
                    print(
                        f"[green]Found existing connection with ID: {connection_id}[/green]"
                    )
                else:
                    # Connection doesn't exist, get config from YAML to create new one
                    print(
                        f"[yellow]Connection not found in Qualytics. Getting config from YAML to create new connection...[/yellow]"
                    )
                    connection_cfg = get_connection(CONNECTIONS_PATH, connection_name)
                    connection_id = None

            # Build the payload (either with connection_id or cfg)
            payload = build_new_datastore_payload(
                cfg=connection_cfg,
                name=name,
                connection_id=connection_id,
                tags=[t.strip() for t in tags.split(",")] if tags else None,
                teams=[t.strip() for t in teams.split(",")] if teams else None,
                enrichment_only=enrichment_only,
                enrichment_prefix=enrichment_prefix,
                enrichment_source_record_limit=enrichment_source_record_limit,
                enrichment_remediation_strategy=enrichment_remediation_strategy,
                high_count_rollup_threshold=high_count_rollup_threshold,
                trigger_catalog=trigger_catalog,
                database=database,
                schema=schema,
            )

            # Pretty preview (mask sensitive fields)
            printable = json.loads(json.dumps(payload))

            # List of sensitive field names to redact
            sensitive_fields = [
                "password",
                "token",
                "api_key",
                "secret",
                "private_key",
                "private_key_der_b64",
                "private_key_path",
                "access_key",
                "secret_key",
                "credentials",
                "auth_token",
            ]

            try:
                if "connection" in printable:
                    # Redact sensitive fields in connection object
                    for field in sensitive_fields:
                        if field in printable["connection"]:
                            printable["connection"][field] = "*** redacted ***"

                    # Redact sensitive fields in parameters
                    if "parameters" in printable["connection"]:
                        for field in sensitive_fields:
                            if field in printable["connection"]["parameters"]:
                                printable["connection"]["parameters"][field] = (
                                    "*** redacted ***"
                                )

                        # Redact in nested authentication object
                        if "authentication" in printable["connection"]["parameters"]:
                            for field in sensitive_fields:
                                if (
                                    field
                                    in printable["connection"]["parameters"][
                                        "authentication"
                                    ]
                                ):
                                    printable["connection"]["parameters"][
                                        "authentication"
                                    ][field] = "*** redacted ***"
            except Exception:
                pass

            print(
                "[bold]Datastore Create Payload (preview with redacted secrets):[/bold]"
            )
            print(json.dumps(printable, indent=2))

            if dry_run:
                print("[green]Dry run successful. No HTTP request was made.[/green]")
                raise typer.Exit(code=0)

            print("[cyan]POSTing datastore to API...[/cyan]")
            result = datastore.create_datastore(payload, url, headers)
            print("[green]Datastore created successfully![/green]")
            print(f"[green]Datastore ID: {result.get('id')}[/green]")
            print(f"[green]Datastore Name: {result.get('name')}[/green]")
            if result.get("connection"):
                print(
                    f"[green]Connection ID: {result.get('connection', {}).get('id')}[/green]"
                )
        except ConfigError as e:
            print(f"[red]Config error:[/red] {e}")
            raise typer.Exit(code=2)
        except requests.RequestException as e:
            print(f"[red]Network error calling API:[/red] {e}")
            raise typer.Exit(code=4)
        except RuntimeError as e:
            error_msg = str(e)
            # Check if the error is due to a connection already existing
            if (
                "409" in error_msg
                or "already exists" in error_msg.lower()
                or "conflict" in error_msg.lower()
            ):
                print(
                    "[red]Error: A connection with these credentials already exists.[/red]"
                )
                print(
                    "[yellow]Suggestion: Use the --connection-id flag to reference the existing connection instead.[/yellow]"
                )
                print(f"[yellow]Details: {error_msg}[/yellow]")
            else:
                print(f"[red]{error_msg}[/red]")
            raise typer.Exit(code=5)
        except typer.Exit:
            raise
        except Exception as e:
            print(f"[red]Unexpected error:[/red] {e}")
            raise typer.Exit(code=1)


@datastore_app.command("list", help="List all datastores")
def list_datastores():
    config = get_config()

    if not config:
        print("[bold red] Error: No configuration found. [/bold red]")
        print("[bold yellow] Please run 'qualytics init' to set up your configuration. [/bold yellow]")
        raise typer.Exit(code=1)

    base_url = base_url = validate_and_format_url(config["url"])
    endpoint = "datastores/listing"
    url = f"{base_url}{endpoint}"
    token = is_token_valid(config["token"])
    headers = _get_default_headers(token)
    if token:
        try:
            result = datastore.list_datastores(url, headers)
            print("[green]Datastores listed:[/green]")
            print(json.dumps(result, indent=2))
        except ConfigError as e:
            print(f"[red]Config error:[/red] {e}")
            raise typer.Exit(code=2)
        except requests.RequestException as e:
            print(f"[red]Network error calling API:[/red] {e}")
            raise typer.Exit(code=4)
        except RuntimeError as e:
            print(f"[red]{e}[/red]")
            raise typer.Exit(code=5)
        except typer.Exit:
            raise
        except Exception as e:
            print(f"[red]Unexpected error:[/red] {e}")
            raise typer.Exit(code=1)


@datastore_app.command("get", help="Get a datastore by ID or name.")
def get_datastore(
    id: int = typer.Option(None, "--id", help="Datastore ID"),
    name: str = typer.Option(None, "--name", help="Datastore name"),
):
    config = get_config()

    if not config:
        print("[bold red] Error: No configuration found. [/bold red]")
        print("[bold yellow] Please run 'qualytics init' to set up your configuration. [/bold yellow]")
        raise typer.Exit(code=1)

    base_url = validate_and_format_url(config["url"])
    token = is_token_valid(config["token"])

    if token:
        try:
            # Validation: require either id or name, but not both
            if id and name:
                print(
                    "[red]Error: Cannot specify both --id and --name. Please use only one.[/red]"
                )
                raise typer.Exit(code=1)

            if not id and not name:
                print("[red]Error: Must specify either --id or --name.[/red]")
                raise typer.Exit(code=1)

            # Fetch datastore using the helper function
            result = get_datastore_by(
                base_url=base_url, token=token, datastore_id=id, datastore_name=name
            )

            if result is None:
                identifier = f"ID {id}" if id else f"name '{name}'"
                print(f"[red]Datastore with {identifier} not found.[/red]")
                raise typer.Exit(code=1)

            print("[green]Datastore found:[/green]")
            print(json.dumps(result, indent=2))

        except ConfigError as e:
            print(f"[red]Config error:[/red] {e}")
            raise typer.Exit(code=2)
        except requests.RequestException as e:
            print(f"[red]Network error calling API:[/red] {e}")
            raise typer.Exit(code=4)
        except RuntimeError as e:
            print(f"[red]{e}[/red]")
            raise typer.Exit(code=5)
        except typer.Exit:
            raise
        except Exception as e:
            print(f"[red]Unexpected error:[/red] {e}")
            raise typer.Exit(code=1)


@datastore_app.command("remove", help="Remove a datastore. Use with caution!")
def remove_datastore(
    id: int = typer.Option(..., "--id", help="Datastore id"),
):
    config = get_config()

    if not config:
        print("[bold red] Error: No configuration found. [/bold red]")
        print("[bold yellow] Please run 'qualytics init' to set up your configuration. [/bold yellow]")
        raise typer.Exit(code=1)

    base_url = base_url = validate_and_format_url(config["url"])
    endpoint = f"datastores/{id}"
    url = f"{base_url}{endpoint}"
    token = is_token_valid(config["token"])
    headers = _get_default_headers(token)

    if token:
        try:
            result = datastore.remove_datastore(url, headers)
            print(f"[green]✓ Datastore with ID {id} removed successfully![/green]")
            if result.get("message"):
                print(f"[green]{result.get('message')}[/green]")
        except ConfigError as e:
            print(f"[red]Config error:[/red] {e}")
            raise typer.Exit(code=2)
        except requests.RequestException as e:
            print(f"[red]Network error calling API:[/red] {e}")
            raise typer.Exit(code=4)
        except RuntimeError as e:
            print(f"[red]{e}[/red]")
            raise typer.Exit(code=5)
        except typer.Exit:
            raise
        except Exception as e:
            print(f"[red]Unexpected error:[/red] {e}")
            raise typer.Exit(code=1)

