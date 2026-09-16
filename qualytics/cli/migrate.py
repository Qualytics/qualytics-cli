"""CLI commands for sheet-driven check migration.

`qualytics migrate` turns a normalized check sheet (XLSX/CSV, one row per
quality check or computed container) into Qualytics assets. `plan` is the
offline half: load, convert, validate, summarize — no auth, no network.
"""

import os

import typer
import yaml
from rich import print
from rich.console import Console
from rich.table import Table

from ..services.migrate import (
    SheetPlan,
    convert_sheet,
    load_sheet,
    summarize_sheet,
)
from . import add_suggestion_callback

migrate_app = typer.Typer(
    name="migrate",
    help="Create checks and computed containers from a normalized check sheet",
)
add_suggestion_callback(migrate_app, "migrate")

console = Console()

_KIND_LABEL = {"computed_table": "computed table", "computed_join": "computed join"}


def _load_plan(
    sheet_path: str, status: str | None, tags: list[str] | None
) -> SheetPlan:
    if not os.path.isfile(sheet_path):
        print(f"[red]Sheet not found: {sheet_path}[/red]")
        raise typer.Exit(code=1)
    try:
        rows = load_sheet(sheet_path)
    except ValueError as e:
        print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)
    if not rows:
        print("[yellow]The sheet has no data rows — nothing to migrate.[/yellow]")
        raise typer.Exit(code=0)
    return convert_sheet(
        rows,
        default_status=_resolve_status(status) or "Draft",
        extra_tags=tags or [],
    )


_VALID_STATUS = ("Active", "Draft")


def _resolve_status(status: str | None) -> str | None:
    if status is None:
        return None
    match = next((s for s in _VALID_STATUS if s.lower() == status.lower()), None)
    if match is None:
        print(f"[red]--status must be Active or Draft, got: {status}[/red]")
        raise typer.Exit(code=1)
    return match


def _print_issues(plan: SheetPlan) -> None:
    for issue in plan.errors:
        label = f"row {issue.row}" + (f" ({issue.check_id})" if issue.check_id else "")
        print(f"  [red]✗ {label}: {issue.message}[/red]")
    for issue in plan.warnings:
        label = f"row {issue.row}" + (f" ({issue.check_id})" if issue.check_id else "")
        print(f"  [yellow]⚠ {label}: {issue.message}[/yellow]")


def _print_summary(plan: SheetPlan, sheet_path: str) -> dict:
    stats = summarize_sheet(plan)

    print(
        f"\n[bold]Plan[/bold] [dim]· {os.path.basename(sheet_path)} · "
        f"{stats['checks']} checks, {stats['containers']} computed containers[/dim]\n"
    )

    if stats["by_rule"]:
        table = Table(title="Checks by rule")
        table.add_column("Rule")
        table.add_column("Checks", justify="right")
        for rule, count in stats["by_rule"].items():
            table.add_row(rule, str(count))
        table.add_section()
        table.add_row("[bold]Total[/bold]", f"[bold]{stats['checks']}[/bold]")
        console.print(table)

    if plan.containers:
        table = Table(title="Computed containers to ensure (in this order)")
        table.add_column("Kind")
        table.add_column("Name")
        table.add_column("Datastore", style="dim")
        for spec in plan.containers:
            table.add_row(
                _KIND_LABEL.get(spec.kind, spec.kind),
                spec.name,
                str(spec.datastore) if spec.datastore is not None else "default",
            )
        console.print(table)

    statuses = ", ".join(
        f"{count} {name}" for name, count in stats["by_status"].items()
    )
    if statuses:
        print(f"Landing status: [bold]{statuses}[/bold]")
    if stats["datastore_overrides"]:
        print(
            "Per-row datastore overrides: "
            f"[bold]{', '.join(stats['datastore_overrides'])}[/bold]"
        )

    if plan.issues:
        print(
            f"\n[bold]{stats['errors']} error(s), {stats['warnings']} warning(s)[/bold]"
        )
        _print_issues(plan)
        if stats["errors"]:
            print(
                "\n[red]Rows with errors will not be applied.[/red] "
                "[dim]Fix the sheet and re-run plan.[/dim]"
            )
    else:
        print("\n[green]No issues found.[/green]")

    return stats


def _safe_dir_name(name: str) -> str:
    """Reduce a sheet-derived container name to a single path segment."""
    candidate = os.path.basename(str(name).replace("\\", "/").strip().rstrip("/"))
    if candidate in ("", ".", "..") or os.path.isabs(candidate):
        return "_unresolved"
    return candidate


def _emit_yaml(plan: SheetPlan, out_dir: str) -> None:
    """One YAML file per check (grouped by container) + the container specs."""
    root = os.path.realpath(out_dir)
    written = 0
    for item in plan.checks:
        container_dir = os.path.join(root, _safe_dir_name(item.container or ""))
        if os.path.commonpath([root, os.path.realpath(container_dir)]) != root:
            print(f"[red]Refusing to write outside {out_dir}: {item.container}[/red]")
            continue
        os.makedirs(container_dir, exist_ok=True)
        uid = item.check["additional_metadata"]["_qualytics_check_uid"]
        with open(os.path.join(container_dir, f"{uid}.yaml"), "w") as f:
            yaml.safe_dump(item.check, f, sort_keys=False, default_flow_style=False)
        written += 1
    if plan.containers:
        os.makedirs(root, exist_ok=True)
        specs = [{"datastore": spec.datastore, **spec.spec} for spec in plan.containers]
        with open(os.path.join(root, "_computed_containers.yaml"), "w") as f:
            yaml.safe_dump(specs, f, sort_keys=False, default_flow_style=False)
    print(
        f"[cyan]Wrote {written} check definition(s)"
        + (f" and {len(plan.containers)} container spec(s)" if plan.containers else "")
        + f" to {out_dir}/[/cyan]"
    )


# ── plan ──────────────────────────────────────────────────────────────────


@migrate_app.command("plan")
def migrate_plan(
    sheet_path: str = typer.Option(
        ..., "--sheet", "-s", help="Path to the check sheet (.xlsx or .csv)"
    ),
    status: str = typer.Option(
        None,
        "--status",
        help="Default landing status for rows without one (default: Draft)",
    ),
    tag: list[str] = typer.Option(
        None, "--tag", help="Tag to attach to every check (repeatable)"
    ),
    show_checks: bool = typer.Option(
        False, "--show-checks", help="List every row and the check it produces"
    ),
    emit_yaml: str = typer.Option(
        None, "--emit-yaml", help="Also write the converted checks to this directory"
    ),
    strict: bool = typer.Option(
        False, "--strict", help="Exit non-zero when the sheet has error rows"
    ),
):
    """Validate and summarize a check sheet. Offline — no auth required."""
    plan = _load_plan(sheet_path, status, tag)
    stats = _print_summary(plan, sheet_path)

    if show_checks and plan.checks:
        detail = Table(title="Checks")
        detail.add_column("Row", justify="right", style="dim")
        detail.add_column("check_id")
        detail.add_column("Rule")
        detail.add_column("Container")
        detail.add_column("Fields", style="dim")
        detail.add_column("Status")
        for item in plan.checks:
            detail.add_row(
                str(item.row),
                item.check_id,
                item.check["rule_type"],
                item.container,
                ", ".join(item.check.get("fields") or []),
                item.check.get("status") or "",
            )
        console.print(detail)

    if emit_yaml:
        _emit_yaml(plan, emit_yaml)

    if strict and stats["errors"]:
        raise typer.Exit(code=1)


# ── apply ─────────────────────────────────────────────────────────────────


def _resolve_datastore_overrides(client, plan: SheetPlan) -> tuple[dict, list[str]]:
    """Resolve per-row datastore overrides (name or id) to datastore ids."""
    from ..services.datastores import get_datastore_by_name

    resolved: dict = {}
    errors: list[str] = []
    overrides = {
        item.datastore
        for item in [*plan.checks, *plan.containers]
        if item.datastore is not None
    }
    for override in overrides:
        text = str(override).strip()
        if text.isdigit():
            resolved[override] = int(text)
            continue
        datastore = get_datastore_by_name(client, text)
        if datastore is None:
            errors.append(f"datastore '{text}' not found on the target instance")
        else:
            resolved[override] = datastore["id"]
    return resolved, errors


def _route(items, base_ids: list[int], resolved: dict) -> dict[int, list]:
    """Group sheet items by target datastore id.

    Rows without a datastore override go to every --datastore-id target; a row
    with an override goes only to that datastore.
    """
    routed: dict[int, list] = {}
    for item in items:
        if item.datastore is not None:
            targets = [resolved[item.datastore]] if item.datastore in resolved else []
        else:
            targets = base_ids
        for ds_id in targets:
            routed.setdefault(ds_id, []).append(item)
    return routed


@migrate_app.command("apply")
def migrate_apply(
    sheet_path: str = typer.Option(
        ..., "--sheet", "-s", help="Path to the check sheet (.xlsx or .csv)"
    ),
    datastore_id: list[int] = typer.Option(
        None,
        "--datastore-id",
        help="Target datastore ID for rows without a datastore column "
        "(repeat for multiple)",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Preview what would be created/updated"
    ),
    status: str = typer.Option(
        None,
        "--status",
        help="Default landing status for rows without one (default: Draft)",
    ),
    preserve_status: bool = typer.Option(
        False,
        "--preserve-status",
        help="Omit status so re-applies keep what was set in the product "
        "(e.g. hand-activated checks stay Active)",
    ),
    tag: list[str] = typer.Option(
        None, "--tag", help="Tag to attach to every check (repeatable)"
    ),
    validate_fields: bool = typer.Option(
        True,
        "--validate-fields/--no-validate-fields",
        help="Check field names against the catalogue and correct their casing",
    ),
    skip_containers: bool = typer.Option(
        False,
        "--skip-containers",
        help="Skip the computed-container phase (containers already ensured)",
    ),
    on_existing: str = typer.Option(
        "skip",
        "--on-existing",
        help="What to do when a computed container already exists: skip or update",
    ),
    profile_timeout: int = typer.Option(
        900,
        "--profile-timeout",
        help="Seconds to wait for each created container's profile operation",
    ),
    emit_yaml: str = typer.Option(
        None, "--emit-yaml", help="Also write the converted checks to this directory"
    ),
    failures_log: str = typer.Option(
        "migrate-apply-failures.log",
        "--failures-log",
        help="Write checks that failed to import (which row, why) to this file",
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Exit non-zero when the sheet has error rows or anything fails",
    ),
):
    """Create the sheet's computed containers and checks on the target instance.

    Two phases: computed containers first (validate all, create in declaration
    order, wait for each container's own profile operation), then the checks.
    Checks upsert on a UID derived from the sheet's check_id, so re-running
    after sheet edits updates in place rather than duplicating.

    Rows with error-level issues are skipped and reported; fix the sheet and
    re-apply. By default everything lands as Draft for review — activate in
    the product, and use --preserve-status on re-applies so activations stick.
    """
    from ..api.client import get_client
    from ..services.containers import get_table_ids
    from ..services.migrate import ensure_containers, repair_container_names
    from .import_flow import run_check_import

    if on_existing not in ("skip", "update"):
        print(f"[red]--on-existing must be skip or update, got: {on_existing}[/red]")
        raise typer.Exit(code=1)

    plan = _load_plan(sheet_path, status, tag)
    stats = _print_summary(plan, sheet_path)

    if stats["errors"]:
        print(
            f"\n[yellow]{stats['errors']} row(s) with errors will NOT be "
            "applied.[/yellow]"
        )

    if preserve_status:
        for item in plan.checks:
            item.check.pop("status", None)

    if emit_yaml:
        _emit_yaml(plan, emit_yaml)

    base_ids = list(datastore_id or [])
    needs_base = any(
        item.datastore is None for item in [*plan.checks, *plan.containers]
    )
    if needs_base and not base_ids:
        print(
            "[red]--datastore-id is required: the sheet has rows without a "
            "datastore column.[/red]"
        )
        raise typer.Exit(code=1)

    client = get_client()

    resolved, override_errors = _resolve_datastore_overrides(client, plan)
    for message in override_errors:
        print(f"[red]{message}[/red]")

    routed_containers = _route(plan.containers, base_ids, resolved)
    routed_checks = _route(plan.checks, base_ids, resolved)

    if dry_run:
        print("\n[bold yellow]DRY RUN — no changes will be made.[/bold yellow]")

    container_failures = 0
    blocked_datastores: set[int] = set()
    if not skip_containers:
        for ds_id, specs in routed_containers.items():
            print(
                f"\n[cyan]{'[DRY RUN] ' if dry_run else ''}Ensuring {len(specs)} "
                f"computed container(s) in datastore {ds_id}...[/cyan]"
            )
            result = ensure_containers(
                client,
                specs,
                ds_id,
                on_existing=on_existing,
                profile_timeout=profile_timeout,
                dry_run=dry_run,
                report=lambda message: print(f"  {message}"),
            )
            for error in result["errors"]:
                print(f"  [red]{error}[/red]")
            container_failures += result["failed"]
            if result["failed"]:
                # Dependent checks would fail one by one against a missing or
                # unprofiled container; skip the datastore's check phase and
                # say so instead.
                blocked_datastores.add(ds_id)
                print(
                    f"  [red]Container phase failed — skipping the check phase "
                    f"for datastore {ds_id}.[/red]"
                )

    checks_by_datastore: dict[int, list[dict]] = {}
    for ds_id, items in routed_checks.items():
        if ds_id in blocked_datastores:
            continue
        checks = []
        for item in items:
            check = {**item.check, "_source_file": f"row {item.row} ({item.check_id})"}
            checks.append(check)
        table_ids = get_table_ids(client=client, datastore_id=ds_id) or {}
        corrections = repair_container_names(checks, list(table_ids.keys()))
        if corrections:
            print(
                f"[cyan]Corrected {len(corrections)} container name(s) to catalogue "
                f"casing in datastore {ds_id}: {', '.join(corrections[:5])}"
                f"{'…' if len(corrections) > 5 else ''}[/cyan]"
            )
        checks_by_datastore[ds_id] = checks

    total_failed = 0
    if checks_by_datastore:
        outcome = run_check_import(
            client,
            checks_by_datastore,
            validate_fields=validate_fields,
            dry_run=dry_run,
            failures_log=failures_log,
            log_title="migrate apply failures",
            log_origin=f"sheet: {sheet_path}",
        )
        total_failed = outcome["total_failed"]

    if not dry_run and stats["by_status"].get("Draft"):
        print(
            "\n[dim]Draft checks activate in the product after review; re-applies "
            "with --preserve-status keep those activations.[/dim]"
        )

    if strict and (
        stats["errors"] or override_errors or container_failures or total_failed
    ):
        raise typer.Exit(code=1)
