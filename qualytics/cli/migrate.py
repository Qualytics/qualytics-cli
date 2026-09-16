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
