"""Shared orchestration for the bulk check importers.

`dbt import` and `migrate apply` both end the same way: validate field names
against the catalogue per target datastore, upsert the checks, print a summary
table, and write the failures log. One implementation keeps their behavior
identical — per-check errors are printed and logged, and the process still
exits 0 (failures are reported, not raised), matching `checks import`.
"""

from rich import print
from rich.console import Console
from rich.table import Table

from ..api.fields import container_field_names
from ..services.containers import get_table_ids
from ..services.quality_checks import import_checks_to_datastore
from ..services.rules import resolve_check_fields
from ..utils.failure_log import failure_entry, write_failures_log

console = Console()


def field_catalogue(client, datastore_id: int, containers: set[str]) -> dict:
    """Catalogued field names for the containers these checks target.

    Only the containers actually referenced are fetched. A container the
    importer will reject anyway, or one whose fields cannot be read, is simply
    left out — validation then passes those checks through rather than blocking
    the import on a lookup problem.
    """
    table_ids = get_table_ids(client=client, datastore_id=datastore_id)
    if not table_ids:
        return {}

    catalogue: dict[str, list[str]] = {}
    for name in sorted(containers):
        container_id = table_ids.get(name)
        if container_id is None:
            continue
        try:
            catalogue[name] = container_field_names(client, container_id)
        except Exception as e:  # noqa: BLE001 - lookup failure must not block import
            print(f"[dim]Could not read fields for '{name}': {e}[/dim]")
    return catalogue


def run_check_import(
    client,
    checks_by_datastore: dict[int, list[dict]],
    *,
    validate_fields: bool = True,
    dry_run: bool = False,
    failures_log: str | None = None,
    log_title: str = "check import failures",
    log_origin: str = "",
) -> dict:
    """Import portable checks into each target datastore, with the shared
    summary table and failures log.

    ``checks_by_datastore`` maps each target datastore id to the checks bound
    for it (callers with identical checks for every target pass the same list
    per id). Each check's ``_source_file`` names it in failure reports.

    Returns ``{"total_failed": int, "results": {datastore_id: import_result}}``.
    """
    summary_table = Table(title="Import Summary")
    summary_table.add_column("Datastore ID", style="cyan")
    summary_table.add_column("Created", style="green")
    summary_table.add_column("Updated", style="yellow")
    summary_table.add_column("Failed", style="red")

    total_failed = 0
    failure_entries: list[str] = []
    results: dict[int, dict] = {}

    for ds_id, checks in checks_by_datastore.items():
        by_source = {check.get("_source_file", "unknown"): check for check in checks}
        containers = {c["container"] for c in checks if c.get("container")}

        payload = checks
        rejected: list[dict] = []
        if validate_fields:
            # Field names are catalogued per datastore, so this resolves per
            # target.
            payload, rejected, corrections = resolve_check_fields(
                checks, field_catalogue(client, ds_id, containers)
            )
            if corrections:
                print(
                    f"[cyan]Corrected {len(corrections)} field name(s) to catalogue "
                    f"casing: {', '.join(corrections[:5])}"
                    f"{'…' if len(corrections) > 5 else ''}[/cyan]"
                )

        print(
            f"\n[cyan]{'[DRY RUN] ' if dry_run else ''}Importing {len(payload)} checks "
            f"to datastore {ds_id}...[/cyan]"
        )
        result = import_checks_to_datastore(client, ds_id, payload, dry_run=dry_run)
        results[ds_id] = result

        failed = result["failed"] + len(rejected)
        summary_table.add_row(
            str(ds_id),
            str(result["created"]),
            str(result["updated"]),
            str(failed),
        )
        total_failed += failed

        for item in rejected:
            print(f"  [red]{item['reason']}[/red]")
        for err in result["errors"]:
            print(f"  [red]{err}[/red]")

        # Field-validation rejections and importer failures both land in the
        # log; the on-screen lines scroll away, the file is the record.
        for item in rejected:
            source = item["check"].get("_source_file", "unknown")
            failure_entries.append(
                failure_entry(ds_id, source, item["check"], item["reason"])
            )
        for failure in result.get("failures", []):
            source = failure.get("source", "unknown")
            failure_entries.append(
                failure_entry(
                    ds_id, source, by_source.get(source), failure.get("reason", "")
                )
            )

    console.print(summary_table)

    # A dry run promises no changes, so the log is only written on real runs.
    if failure_entries and failures_log and not dry_run:
        write_failures_log(failures_log, log_title, log_origin, failure_entries)
        print(
            f"\n[yellow]{len(failure_entries)} failed check(s) logged to "
            f"{failures_log}[/yellow]"
        )

    return {"total_failed": total_failed, "results": results}
