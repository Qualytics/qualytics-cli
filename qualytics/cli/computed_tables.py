"""CLI commands for computed tables and rule imports."""

import csv
import json
import re
import time
import typer
import requests
from datetime import datetime
from pathlib import Path
from rich import print
from rich.progress import track
from rich.table import Table
from rich.console import Console
from rich.syntax import Syntax

from ..config import BASE_PATH, load_config, is_token_valid
from ..utils import validate_and_format_url, distinct_file_content, log_error


# Create Typer instance for computed tables
computed_tables_app = typer.Typer(
    name="computed-tables",
    help="Commands for handling computed tables and rule imports",
)

console = Console()

# Global debug flag
_debug_mode = False
_debug_logs_dir = None


def _get_logs_dir() -> str:
    """Get or create the logs directory inside .qualytics."""
    import os

    logs_dir = f"{BASE_PATH}/logs"
    os.makedirs(logs_dir, exist_ok=True)
    return logs_dir


def _debug_log(message: str, payload: dict = None, response: requests.Response = None):
    """Log debug information to console."""
    if not _debug_mode:
        return

    print(f"[dim][DEBUG] {message}[/dim]")

    if payload:
        print("[dim][DEBUG] Request payload:[/dim]")
        syntax = Syntax(
            json.dumps(payload, indent=2, default=str),
            "json",
            theme="monokai",
            line_numbers=False,
        )
        console.print(syntax)

    if response is not None:
        print(f"[dim][DEBUG] Response status: {response.status_code}[/dim]")
        try:
            resp_json = response.json()
            print("[dim][DEBUG] Response body:[/dim]")
            resp_str = json.dumps(resp_json, indent=2, default=str)
            if len(resp_str) > 1000:
                resp_str = resp_str[:1000] + "\n... (truncated)"
            syntax = Syntax(resp_str, "json", theme="monokai", line_numbers=False)
            console.print(syntax)
        except Exception:
            print(f"[dim][DEBUG] Response text: {response.text[:500]}[/dim]")


def _write_debug_log(
    log_type: str,
    name: str,
    message: str,
    payload: dict = None,
    response: requests.Response = None,
):
    """Write debug log to a file in .qualytics/logs/."""
    if not _debug_logs_dir:
        return

    import os

    # Sanitize name for filename
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Create log file path: .qualytics/logs/{log_type}_{name}_{timestamp}.log
    log_file = os.path.join(_debug_logs_dir, f"{log_type}_{safe_name}_{timestamp}.log")

    with open(log_file, "w") as f:
        f.write(f"{'=' * 60}\n")
        f.write(f"Type: {log_type}\n")
        f.write(f"Name: {name}\n")
        f.write(f"Timestamp: {datetime.now().isoformat()}\n")
        f.write(f"{'=' * 60}\n\n")

        f.write(f"{message}\n\n")

        if payload:
            f.write("REQUEST PAYLOAD:\n")
            f.write("-" * 40 + "\n")
            f.write(json.dumps(payload, indent=2, default=str))
            f.write("\n\n")

        if response is not None:
            f.write(f"RESPONSE STATUS: {response.status_code}\n")
            f.write("-" * 40 + "\n")
            try:
                f.write("RESPONSE BODY:\n")
                f.write(json.dumps(response.json(), indent=2, default=str))
            except Exception:
                f.write("RESPONSE TEXT:\n")
                f.write(response.text)
            f.write("\n")

    return log_file


def _get_default_headers(token):
    """Get default authorization headers."""
    return {"Authorization": f"Bearer {token}"}


def _split_select_columns(select_clause: str) -> list[str]:
    """
    Split SELECT clause into individual column expressions.
    Handles nested parentheses and quotes properly.
    """
    columns = []
    current = []
    depth = 0
    in_string = False
    string_char = None

    for char in select_clause:
        if char in ('"', "'") and not in_string:
            in_string = True
            string_char = char
            current.append(char)
        elif char == string_char and in_string:
            in_string = False
            string_char = None
            current.append(char)
        elif char == "(" and not in_string:
            depth += 1
            current.append(char)
        elif char == ")" and not in_string:
            depth -= 1
            current.append(char)
        elif char == "," and depth == 0 and not in_string:
            columns.append("".join(current).strip())
            current = []
        else:
            current.append(char)

    if current:
        columns.append("".join(current).strip())

    return columns


def _has_alias(column_expr: str) -> bool:
    """
    Check if a column expression already has an alias.
    """
    expr = column_expr.strip()

    # Check for explicit AS keyword
    if re.search(r"\s+[Aa][Ss]\s+\w+\s*$", expr):
        return True

    # Check for implicit alias after closing paren
    match = re.search(r"\)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*$", expr)
    if match:
        potential_alias = match.group(1).upper()
        sql_keywords = {
            "FROM",
            "WHERE",
            "AND",
            "OR",
            "JOIN",
            "ON",
            "LEFT",
            "RIGHT",
            "INNER",
            "OUTER",
            "GROUP",
            "ORDER",
            "BY",
            "HAVING",
            "UNION",
            "DISTINCT",
        }
        if potential_alias not in sql_keywords:
            return True

    return False


def _add_aliases_to_query(sql: str) -> tuple[str, int]:
    """
    Add aliases to SELECT columns that don't have them.

    Columns without aliases get unique aliases like: expr_1, expr_2, etc.

    Returns: (modified_sql, count_of_aliases_added)
    """
    if not isinstance(sql, str):
        return sql, 0

    # Find SELECT ... FROM pattern
    select_match = re.search(
        r"\bSELECT\s+(DISTINCT\s+)?(.*?)\s+FROM\b", sql, re.IGNORECASE | re.DOTALL
    )

    if not select_match:
        return sql, 0

    distinct_keyword = select_match.group(1) or ""
    select_clause = select_match.group(2)
    select_start = select_match.start()
    select_end = select_match.end()

    columns = _split_select_columns(select_clause)

    modified_columns = []
    alias_counter = 1
    aliases_added = 0

    for col in columns:
        col = col.strip()
        if not col:
            continue

        if _has_alias(col):
            modified_columns.append(col)
        else:
            alias = f"expr_{alias_counter}"
            modified_columns.append(f"{col} as {alias}")
            alias_counter += 1
            aliases_added += 1

    if aliases_added == 0:
        return sql, 0

    new_select_clause = ", ".join(modified_columns)
    before_select = sql[:select_start]
    after_from = sql[select_end - 4 :]  # Keep "FROM" and everything after

    new_sql = (
        f"{before_select}SELECT {distinct_keyword}{new_select_clause} {after_from}"
    )

    return new_sql, aliases_added


def _read_xlsx_file(file_path: str) -> list[dict]:
    """
    Read computed table definitions from an Excel file (.xlsx).

    Uses positional columns:
    - Column 1: name
    - Column 2: description
    - Column 3: query

    Returns list of records.
    """
    try:
        import openpyxl
    except ImportError:
        raise typer.BadParameter(
            "openpyxl is required for reading .xlsx files. Install it with: pip install openpyxl"
        )

    wb = openpyxl.load_workbook(file_path)
    ws = wb.active

    records = []
    # Skip first row (header) and read data
    for row in ws.iter_rows(min_row=2, values_only=True):
        # Get values from first 3 columns
        name = row[0] if len(row) > 0 else None
        description = row[1] if len(row) > 1 else ""
        query = row[2] if len(row) > 2 else ""

        if name is not None and str(name).strip():
            records.append(
                {
                    "name": str(name).strip(),
                    "description": str(description or "").strip(),
                    "query": str(query or "").strip(),
                }
            )

    return records


def _read_csv_file(file_path: str, delimiter: str = ",") -> list[dict]:
    """
    Read computed table definitions from a CSV file.

    Uses positional columns:
    - Column 1: name
    - Column 2: description
    - Column 3: query

    Handles multiline SQL queries properly.

    Returns list of records.
    """
    records = []

    with open(file_path, newline="", encoding="utf-8") as csvfile:
        # Configure reader to handle multiline quoted fields
        reader = csv.reader(
            csvfile,
            delimiter=delimiter,
            quotechar='"',
            doublequote=True,
        )

        # Skip header row
        try:
            next(reader)
        except StopIteration:
            raise typer.BadParameter("CSV file appears to be empty.")

        for row in reader:
            # Skip empty rows
            if not row or len(row) < 3:
                continue

            name = row[0]
            description = row[1]
            query = row[2]

            # Skip if name is empty
            if not name or not str(name).strip():
                continue

            records.append(
                {
                    "name": str(name).strip(),
                    "description": str(description or "").strip(),
                    "query": str(query or "").strip(),
                }
            )

    return records


def _read_txt_file(file_path: str, delimiter: str = "\t") -> list[dict]:
    """
    Read computed table definitions from a text file with delimiter.

    Uses positional columns:
    - Column 1: name
    - Column 2: description
    - Column 3: query

    Returns list of records.
    """
    return _read_csv_file(file_path, delimiter=delimiter)


def _read_definitions_file(file_path: str, delimiter: str | None = None) -> list[dict]:
    """
    Read computed table definitions from a file based on its extension.

    Supports: .xlsx, .xls, .csv, .txt

    File structure (positional columns):
    - Column 1: name (required)
    - Column 2: description (optional)
    - Column 3: query (required)

    Returns list of records.
    """
    path = Path(file_path)

    if not path.exists():
        raise typer.BadParameter(f"File not found: {file_path}")

    extension = path.suffix.lower()

    if extension in [".xlsx", ".xls"]:
        return _read_xlsx_file(file_path)
    elif extension == ".csv":
        return _read_csv_file(file_path, delimiter=delimiter or ",")
    elif extension == ".txt":
        return _read_txt_file(file_path, delimiter=delimiter or "\t")
    else:
        raise typer.BadParameter(
            f"Unsupported file format: {extension}. Supported formats: .xlsx, .xls, .csv, .txt"
        )


def _validate_records(
    records: list[dict], error_log_path: str
) -> tuple[list[dict], list[str]]:
    """
    Validate records for duplicates and missing data.

    Returns a tuple of (valid_records, warnings).
    """
    warnings = []
    seen_names = {}
    valid_records = []

    for i, record in enumerate(records, 1):
        name = record["name"]

        # Check for empty name
        if not name:
            msg = f"Row {i}: Empty name, skipping."
            warnings.append(msg)
            log_error(msg, error_log_path)
            continue

        # Check for empty query
        if not record["query"]:
            msg = f"Row {i}: '{name}' has empty query, skipping."
            warnings.append(msg)
            log_error(msg, error_log_path)
            continue

        # Check for duplicates
        if name in seen_names:
            msg = f"Row {i}: Duplicate name '{name}' (first seen at row {seen_names[name]}), skipping."
            warnings.append(msg)
            log_error(msg, error_log_path)
            continue

        seen_names[name] = i
        valid_records.append(record)

    return valid_records, warnings


def _create_computed_table(
    base_url: str,
    token: str,
    datastore_id: int,
    name: str,
    query: str,
    description: str,
    error_log_path: str,
) -> dict | None:
    """
    Create a computed table in a datastore.

    Adds aliases to SELECT columns without them (e.g., expr_1, expr_2).
    The description is stored in additional_metadata.

    Returns the created computed table response or None if failed.
    """
    headers = _get_default_headers(token)

    # Add aliases to columns without them
    final_query, aliases_added = _add_aliases_to_query(query)
    if aliases_added > 0:
        _debug_log(f"Added {aliases_added} aliases to query for {name}")

    payload = {
        "container_type": "computed_table",
        "datastore_id": datastore_id,
        "name": name,
        "query": final_query,
        "additional_metadata": {
            "description": description or "",
            "rule_id": _extract_rule_id(name),
            "imported_from": "qualytics-cli",
            "import_timestamp": datetime.now().isoformat(),
        },
    }

    _debug_log(f"Creating computed table: {name}", payload=payload)

    response = requests.post(
        f"{base_url}containers",
        headers=headers,
        json=payload,
        verify=False,
    )

    _debug_log(f"Create computed table response for: {name}", response=response)

    # Write to individual log file
    log_message = f"Creating computed table: {name}\nDatastore ID: {datastore_id}\nAliases added: {aliases_added}\n\nOriginal Query:\n{query}\n\nFinal Query:\n{final_query}"

    log_file = _write_debug_log(
        log_type="computed_table",
        name=name,
        message=log_message,
        payload=payload,
        response=response,
    )
    if log_file:
        _debug_log(f"Log written to: {log_file}")

    if response.status_code == 200:
        return response.json()
    else:
        error_msg = f"Failed to create computed table '{name}': {response.status_code} - {response.text}"
        log_error(error_msg, error_log_path)
        return None


def _wait_for_profile_operation(
    base_url: str,
    token: str,
    container_id: int,
    datastore_id: int,
    max_retries: int = 10,
    wait_time: int = 30,
) -> bool:
    """
    Wait for the profile operation triggered by computed table creation.

    Polls the operation endpoint until it finishes, then verifies container has fields.

    Parameters:
    - max_retries: Number of retry attempts if operation doesn't succeed
    - wait_time: Seconds to wait between retry attempts

    Returns True if profile succeeded and container has fields, False otherwise.
    """
    headers = _get_default_headers(token)

    _debug_log(f"Looking for profile operation for container {container_id}")

    # First, find the profile operation for this container
    response = requests.get(
        f"{base_url}operations",
        headers=headers,
        params={
            "type": "profile",
            "datastore_id": datastore_id,
            "container_id": container_id,
            "sort": "desc",
            "size": 1,
        },
        verify=False,
    )

    if response.status_code != 200:
        _debug_log(f"Failed to get operations: {response.status_code}")
        return False

    data = response.json()
    if not data.get("items") or len(data["items"]) == 0:
        _debug_log("No profile operation found for container")
        return False

    operation_id = data["items"][0]["id"]
    _debug_log(f"Found profile operation ID: {operation_id}")

    # Now wait for the operation to finish
    for attempt in range(max_retries):
        # Poll until operation has end_time
        poll_count = 0
        while True:
            op_response = requests.get(
                f"{base_url}operations/{operation_id}",
                headers=headers,
                verify=False,
            )

            if op_response.status_code != 200:
                _debug_log(f"Failed to get operation status: {op_response.status_code}")
                break

            op_data = op_response.json()
            if op_data.get("end_time"):
                _debug_log(
                    f"Operation {operation_id} finished with result: {op_data.get('result')}"
                )
                break

            poll_count += 1
            if poll_count % 3 == 0:  # Log every 3rd poll
                _debug_log(
                    f"Operation {operation_id} still running... (poll #{poll_count})"
                )
            time.sleep(5)

        # Check result
        if op_response.status_code == 200:
            op_data = op_response.json()
            result = op_data.get("result")

            if result == "success":
                # Verify container has field profiles
                field_profiles_response = requests.get(
                    f"{base_url}containers/{container_id}/field-profiles",
                    headers=headers,
                    verify=False,
                )

                if field_profiles_response.status_code == 200:
                    fields = field_profiles_response.json().get("items", [])
                    _debug_log(
                        f"Container {container_id} has {len(fields)} field profiles after profile"
                    )
                    if fields and len(fields) > 0:
                        return True

            elif result == "failure":
                _debug_log(
                    f"Profile operation failed: {op_data.get('message', 'No message')}"
                )
                return False

        # If we're on last attempt, return what we have
        if attempt == max_retries - 1:
            _debug_log(f"Max retries ({max_retries}) reached, giving up")
            return False

        # Wait before retrying
        print(
            f"  [dim]Attempt {attempt + 1} - profile not ready, retrying in {wait_time}s...[/dim]"
        )
        time.sleep(wait_time)

    return False


def _get_existing_computed_tables(
    base_url: str, token: str, datastore_id: int
) -> dict[str, int]:
    """
    Get existing computed tables in a datastore.

    Returns a dict mapping table name to container ID.
    """
    headers = _get_default_headers(token)

    response = requests.get(
        f"{base_url}containers/listing",
        headers=headers,
        params={"datastore": datastore_id, "type": "computed_table"},
        verify=False,
    )

    if response.status_code == 200:
        tables = response.json()
        return {t["name"]: t["id"] for t in tables}

    return {}


def _get_existing_checks_for_container(
    base_url: str, token: str, container_id: int
) -> list[dict]:
    """
    Get existing quality checks for a container.

    Returns list of checks.
    """
    headers = _get_default_headers(token)

    response = requests.get(
        f"{base_url}quality-checks",
        headers=headers,
        params={"container": container_id, "size": 100},
        verify=False,
    )

    if response.status_code == 200:
        data = response.json()
        return data.get("items", [])

    return []


def _get_container_fields(
    base_url: str, token: str, container_id: int
) -> list[dict] | None:
    """Get field profiles for a container after profiling."""
    headers = _get_default_headers(token)

    response = requests.get(
        f"{base_url}containers/{container_id}/field-profiles",
        headers=headers,
        verify=False,
    )

    if response.status_code == 200:
        return response.json().get("items", [])
    return None


def _build_satisfies_expression(fields: list[dict]) -> tuple[str, list[str]]:
    """
    Build a satisfies expression that passes when all fields are NULL.

    This means:
    - Empty result set (no rows) = PASS (all checks pass)
    - Any rows returned = FAIL (each row is an anomaly)

    Returns a tuple of (expression, field_names).
    """
    field_names = [f["name"] for f in fields]

    # Expression: all fields should be null
    # When query returns empty = pass, when returns records = anomalies
    # Wrap field names with backticks to handle special characters and functions
    null_conditions = [f"`{field}` IS NULL" for field in field_names]
    expression = " AND ".join(null_conditions)

    return expression, field_names


def _create_satisfies_expression_check(
    base_url: str,
    token: str,
    container_id: int,
    description: str,
    name: str,
    tags: list[str],
    as_draft: bool,
    error_log_path: str,
) -> dict | None:
    """
    Create a satisfiesExpression check for a computed table.

    The check expression is built so that:
    - Empty result set = PASS
    - Any rows = FAIL (rows are anomalies)

    Returns the created check response or None if failed.
    """
    headers = _get_default_headers(token)

    _debug_log(f"Getting fields for container {container_id}")
    fields = _get_container_fields(base_url, token, container_id)

    if not fields:
        error_msg = f"Container {container_id} has no fields. Cannot create check."
        _debug_log(error_msg)
        log_error(error_msg, error_log_path)
        return None

    _debug_log(
        f"Container {container_id} has {len(fields)} fields: {[f['name'] for f in fields]}"
    )

    expression, field_names = _build_satisfies_expression(fields)

    payload = {
        "description": description or f"Satisfies expression check for {name}",
        "rule": "satisfiesExpression",
        "coverage": 1.0,
        "fields": field_names,
        "properties": {"expression": expression},
        "tags": tags,
        "container_id": container_id,
        "additional_metadata": {
            "rule_id": _extract_rule_id(name),
            "computed_table_name": name,
            "original_description": description,
            "imported_from": "qualytics-cli",
            "import_timestamp": datetime.now().isoformat(),
        },
        "status": "Draft" if as_draft else "Active",
    }

    _debug_log(f"Creating check for container {container_id}", payload=payload)

    response = requests.post(
        f"{base_url}quality-checks",
        headers=headers,
        json=payload,
        verify=False,
    )

    _debug_log(f"Create check response for container {container_id}", response=response)

    # Write to individual log file
    log_file = _write_debug_log(
        log_type="check",
        name=name,
        message=f"Creating satisfiesExpression check for: {name}\nContainer ID: {container_id}\nExpression: {expression}",
        payload=payload,
        response=response,
    )
    if log_file:
        _debug_log(f"Log written to: {log_file}")

    if response.status_code == 200:
        return response.json()
    else:
        error_msg = f"Failed to create check for '{name}': {response.status_code} - {response.text}"
        log_error(error_msg, error_log_path)
        return None


def _parse_tags(tags_str: str) -> list[str]:
    """Parse tags string to list."""
    if not tags_str:
        return []
    tags_str = tags_str.replace(";", ",")
    return [t.strip() for t in tags_str.split(",") if t.strip()]


def _extract_rule_id(name: str) -> str:
    """
    Extract clean rule_id from name by removing common suffixes.

    Examples:
        "1000664_SF" -> "1000664"
        "1000656_sf" -> "1000656"
        "rule_123_DB" -> "rule_123"
        "check_001" -> "check_001"
    """
    import re

    # Remove common suffixes like _SF, _sf, _DB, _db, _BQ, _bq (database indicators)
    cleaned = re.sub(
        r"_(?:SF|sf|DB|db|BQ|bq|PG|pg|SNOW|snow|SNOWFLAKE|snowflake)$", "", name
    )
    return cleaned


@computed_tables_app.command("import")
def import_computed_tables(
    datastore: int = typer.Option(
        ..., "--datastore", help="Datastore ID to create computed tables in"
    ),
    input_file: str = typer.Option(
        ..., "--input", help="Input file path (.xlsx, .csv, or .txt)"
    ),
    delimiter: str | None = typer.Option(
        None,
        "--delimiter",
        help="Delimiter for CSV/TXT files (default: ',' for CSV, '\\t' for TXT)",
    ),
    prefix: str = typer.Option(
        "ct_",
        "--prefix",
        help="Prefix for computed table names (default: 'ct_')",
    ),
    as_draft: bool = typer.Option(
        True,
        "--as-draft/--as-active",
        help="Create checks as Draft (default) or Active",
    ),
    skip_checks: bool = typer.Option(
        False,
        "--skip-checks",
        help="Skip creating quality checks (only create computed tables)",
    ),
    skip_profile_wait: bool = typer.Option(
        False,
        "--skip-profile-wait",
        help="Skip waiting for profile operation (WARNING: checks will fail without profile - use with --skip-checks)",
    ),
    tags: str | None = typer.Option(
        None,
        "--tags",
        help="Tags for checks (comma-separated)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Preview what would be created without making any changes",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Enable debug mode - shows API requests/responses and writes logs to ~/.qualytics/logs/",
    ),
):
    """
    Import computed tables from a file and create satisfiesExpression checks.

    FILE STRUCTURE (positional columns, first row is header):
      - Column 1: name (required) - will become computed table name with prefix
      - Column 2: description (optional) - stored as check description and metadata
      - Column 3: query (required) - SQL query for the computed table

    COMPUTED TABLE NAMING:
      The final name will be: <prefix><name>
      Default prefix is 'ct_', so a row with name '1000664' becomes 'ct_1000664'

    EXISTING TABLES:
      Existing computed tables are SKIPPED (not recreated).
      Checks are only created if they don't already exist for the container.

    CHECK BEHAVIOR:
      Creates a satisfiesExpression check where:
      - Empty result set (no rows) = PASS
      - Any rows returned = FAIL (each row is an anomaly)

      This is ideal for error detection queries where results indicate problems.

    SQL QUERIES:
      Queries are used exactly as provided in the input file.
      Cross-catalog/schema references (e.g., catalog.schema.table) are preserved.

    Example:
        qualytics computed-tables import --datastore 123 --input tables.csv
        qualytics computed-tables import --datastore 123 --input rules.xlsx --prefix "rule_"
        qualytics computed-tables import --datastore 123 --input data.csv --skip-checks
        qualytics computed-tables import --datastore 123 --input data.csv --as-active --tags "prod"
    """
    # Set debug mode
    global _debug_mode, _debug_logs_dir
    _debug_mode = debug

    if _debug_mode:
        _debug_logs_dir = _get_logs_dir()
        print("[bold cyan]Debug mode enabled[/bold cyan]")
        print(f"[dim]Debug logs will be written to: {_debug_logs_dir}/[/dim]")

    config = load_config()
    if not config:
        print(
            "[bold red]Configuration not found. Please run 'qualytics init' first.[/bold red]"
        )
        raise typer.Exit(code=1)

    base_url = validate_and_format_url(config["url"])
    token = is_token_valid(config["token"])

    if not token:
        raise typer.Exit(code=1)

    _debug_log(f"Base URL: {base_url}")
    _debug_log(f"Datastore ID: {datastore}")

    error_log_path = f"{BASE_PATH}/computed-table-import-errors-{datetime.now().strftime('%Y-%m-%d')}.log"

    default_tags = _parse_tags(tags) if tags else []

    print(f"[bold blue]Reading definitions from: {input_file}[/bold blue]")
    try:
        records = _read_definitions_file(input_file, delimiter=delimiter)
    except typer.BadParameter as e:
        print(f"[bold red]Error reading file: {e}[/bold red]")
        raise typer.Exit(code=1)

    if not records:
        print("[bold yellow]No records found in the input file.[/bold yellow]")
        raise typer.Exit(code=0)

    print(f"[bold green]Found {len(records)} records in the file.[/bold green]")

    valid_records, warnings = _validate_records(records, error_log_path)

    if warnings:
        print(f"[bold yellow]Warnings during validation:[/bold yellow]")
        for warning in warnings[:5]:
            print(f"  [yellow]- {warning}[/yellow]")
        if len(warnings) > 5:
            print(f"  [yellow]... and {len(warnings) - 5} more warnings[/yellow]")

    if not valid_records:
        print("[bold red]No valid records to import after validation.[/bold red]")
        raise typer.Exit(code=1)

    print(f"[bold green]{len(valid_records)} valid records to import.[/bold green]")

    # Get existing computed tables
    print(f"[dim]Checking for existing computed tables...[/dim]")
    existing_tables = _get_existing_computed_tables(base_url, token, datastore)
    if existing_tables:
        print(
            f"[dim]Found {len(existing_tables)} existing computed tables in datastore.[/dim]"
        )

    if dry_run:
        print(
            "\n[bold cyan]DRY RUN - Preview of computed tables to be created:[/bold cyan]"
        )

        table = Table(title="Computed Tables Preview")
        table.add_column("Computed Table Name", style="cyan")
        table.add_column("Status", style="yellow")
        table.add_column("Description", style="dim", max_width=30)
        table.add_column("Check", style="green")

        for record in valid_records[:10]:
            table_name = f"{prefix}{record['name']}"
            desc = (
                record["description"][:30] + "..."
                if len(record["description"]) > 30
                else record["description"]
            )

            if table_name in existing_tables:
                status = "skip"
            else:
                status = "create"

            table.add_row(
                table_name,
                status,
                desc or "(none)",
                "skip" if skip_checks else "satisfiesExpression",
            )

        if len(valid_records) > 10:
            table.add_row("...", "...", "...", f"({len(valid_records) - 10} more)")

        console.print(table)
        print("\n[bold cyan]No changes were made (dry run).[/bold cyan]")
        raise typer.Exit(code=0)

    # Import records
    created_tables = 0
    skipped_tables = 0
    created_checks = 0
    skipped_checks = 0
    failed_tables = 0
    failed_checks = 0

    for record in track(valid_records, description="Importing..."):
        name = record["name"]
        description = record["description"]
        query = record["query"]

        table_name = f"{prefix}{name}"
        container_id = None

        # Check if table already exists
        if table_name in existing_tables:
            print(
                f"[yellow]Skipping existing computed table: {table_name} (ID: {existing_tables[table_name]})[/yellow]"
            )
            skipped_tables += 1
            container_id = existing_tables[table_name]
        else:
            # Create new computed table
            computed_table = _create_computed_table(
                base_url=base_url,
                token=token,
                datastore_id=datastore,
                name=table_name,
                query=query,
                description=description,
                error_log_path=error_log_path,
            )

            if computed_table:
                created_tables += 1
                container_id = computed_table["id"]
                print(
                    f"[green]Created computed table: {table_name} (ID: {container_id})[/green]"
                )

                if not skip_profile_wait:
                    print(f"  [dim]Waiting for profile operation to complete...[/dim]")
                    profile_success = _wait_for_profile_operation(
                        base_url=base_url,
                        token=token,
                        container_id=container_id,
                        datastore_id=datastore,
                    )
                    if profile_success:
                        print(f"  [green]Profile completed successfully[/green]")
                    else:
                        print(
                            f"  [yellow]Warning: Profile may not have completed for {table_name}[/yellow]"
                        )
            else:
                failed_tables += 1
                print(f"[red]Failed to create computed table: {table_name}[/red]")

        # Create check if we have a container ID
        if container_id and not skip_checks:
            # Check if check already exists for this container
            existing_checks = _get_existing_checks_for_container(
                base_url, token, container_id
            )

            if existing_checks:
                print(
                    f"  [yellow]Check already exists for {table_name}, skipping[/yellow]"
                )
                skipped_checks += 1
            else:
                check = _create_satisfies_expression_check(
                    base_url=base_url,
                    token=token,
                    container_id=container_id,
                    description=description,
                    name=name,
                    tags=default_tags,
                    as_draft=as_draft,
                    error_log_path=error_log_path,
                )

                if check:
                    created_checks += 1
                    status = "Draft" if as_draft else "Active"
                    print(
                        f"  [green]Created check ({status}): ID {check['id']}[/green]"
                    )
                else:
                    failed_checks += 1
                    print(f"  [red]Failed to create check for {table_name}[/red]")

    # Summary
    print("\n[bold]Import Summary:[/bold]")
    print(f"  [green]Computed tables created: {created_tables}[/green]")
    if skipped_tables > 0:
        print(
            f"  [yellow]Computed tables skipped (existing): {skipped_tables}[/yellow]"
        )
    if not skip_checks:
        print(f"  [green]Checks created: {created_checks}[/green]")
        if skipped_checks > 0:
            print(f"  [yellow]Checks skipped (existing): {skipped_checks}[/yellow]")

    if failed_tables > 0 or failed_checks > 0:
        print(f"  [red]Failed computed tables: {failed_tables}[/red]")
        if not skip_checks:
            print(f"  [red]Failed checks: {failed_checks}[/red]")
        print(f"\n[yellow]Check error log for details: {error_log_path}[/yellow]")

    distinct_file_content(error_log_path)


@computed_tables_app.command("list")
def list_computed_tables(
    datastore: int = typer.Option(
        ..., "--datastore", help="Datastore ID to list computed tables from"
    ),
):
    """
    List all computed tables in a datastore.
    """
    config = load_config()
    if not config:
        print(
            "[bold red]Configuration not found. Please run 'qualytics init' first.[/bold red]"
        )
        raise typer.Exit(code=1)

    base_url = validate_and_format_url(config["url"])
    token = is_token_valid(config["token"])

    if not token:
        raise typer.Exit(code=1)

    headers = _get_default_headers(token)

    response = requests.get(
        f"{base_url}containers/listing",
        headers=headers,
        params={"datastore": datastore, "type": "computed_table"},
        verify=False,
    )

    if response.status_code != 200:
        print(
            f"[bold red]Failed to list computed tables: {response.status_code} - {response.text}[/bold red]"
        )
        raise typer.Exit(code=1)

    tables = response.json()

    if not tables:
        print(f"[yellow]No computed tables found in datastore {datastore}.[/yellow]")
        return

    table = Table(title=f"Computed Tables in Datastore {datastore}")
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="green")

    for t in tables:
        table.add_row(str(t["id"]), t["name"])

    console.print(table)
    print(f"\n[bold]Total: {len(tables)} computed tables[/bold]")


@computed_tables_app.command("preview")
def preview_file(
    input_file: str = typer.Option(
        ..., "--input", help="Input file path (.xlsx, .csv, or .txt)"
    ),
    delimiter: str | None = typer.Option(
        None,
        "--delimiter",
        help="Delimiter for CSV/TXT files (default: ',' for CSV, '\\t' for TXT)",
    ),
    limit: int = typer.Option(
        5, "--limit", help="Number of records to preview (default: 5)"
    ),
    prefix: str = typer.Option(
        "ct_",
        "--prefix",
        help="Prefix to show for computed table names (default: 'ct_')",
    ),
):
    """
    Preview computed table definitions from a file without importing.

    FILE STRUCTURE (positional columns):
      - Column 1: name
      - Column 2: description
      - Column 3: query
    """
    print(f"[bold blue]Reading definitions from: {input_file}[/bold blue]")

    try:
        records = _read_definitions_file(input_file, delimiter=delimiter)
    except typer.BadParameter as e:
        print(f"[bold red]Error reading file: {e}[/bold red]")
        raise typer.Exit(code=1)

    if not records:
        print("[bold yellow]No records found in the input file.[/bold yellow]")
        raise typer.Exit(code=0)

    print(f"[bold green]Found {len(records)} records in the file.[/bold green]\n")

    # Check for duplicates
    seen_names = {}
    duplicates = []
    for i, record in enumerate(records, 1):
        if record["name"] in seen_names:
            duplicates.append((record["name"], seen_names[record["name"]], i))
        else:
            seen_names[record["name"]] = i

    if duplicates:
        print("[bold yellow]Warning: Duplicate names found:[/bold yellow]")
        for name, first_row, dup_row in duplicates[:5]:
            print(
                f"  [yellow]- '{name}' appears at rows {first_row} and {dup_row}[/yellow]"
            )
        if len(duplicates) > 5:
            print(f"  [yellow]... and {len(duplicates) - 5} more duplicates[/yellow]")
        print()

    print(f"[bold]Preview of first {min(limit, len(records))} records:[/bold]\n")

    for i, record in enumerate(records[:limit], 1):
        table_name = f"{prefix}{record['name']}"
        print(f"[cyan]Record {i}:[/cyan]")
        print(f"  [bold]Computed Table Name:[/bold] {table_name}")

        desc = record.get("description", "")
        if len(desc) > 100:
            desc = desc[:100] + "..."
        print(f"  [bold]Description:[/bold] {desc or '(none)'}")

        sql = record["query"]
        if len(sql) > 200:
            sql = sql[:200] + "..."
        print(f"  [bold]Query:[/bold] {sql}")
        print()

    if len(records) > limit:
        print(f"[dim]... and {len(records) - limit} more records[/dim]")
