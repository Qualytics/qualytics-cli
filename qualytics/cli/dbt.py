"""CLI commands for migrating dbt tests to Qualytics."""

import json
import os

import typer
import yaml
from rich import print
from rich.console import Console
from rich.table import Table

from ..api.client import get_client
from ..services.dbt import (
    TIER_DIRECT,
    TIER_MANUAL,
    TIER_NORMALIZE,
    convert_manifest,
    summarize,
    to_checks,
)
from ..services.quality_checks import import_checks_to_datastore
from . import add_suggestion_callback

dbt_app = typer.Typer(name="dbt", help="Migrate dbt tests to Qualytics quality checks")
add_suggestion_callback(dbt_app, "dbt")

console = Console()

_TIER_LABEL = {
    TIER_DIRECT: ("direct", "green"),
    TIER_NORMALIZE: ("normalize", "cyan"),
    TIER_MANUAL: ("manual", "yellow"),
}


# ── Helpers ───────────────────────────────────────────────────────────────


def _load_manifest(path: str) -> dict:
    """Read and parse a dbt manifest.json, with actionable errors."""
    if not os.path.isfile(path):
        print(f"[red]Manifest not found: {path}[/red]")
        print("[dim]dbt writes it to target/manifest.json after `dbt compile`.[/dim]")
        raise typer.Exit(code=1)

    try:
        with open(path) as f:
            manifest = json.load(f)
    except json.JSONDecodeError as e:
        print(f"[red]Could not parse {path} as JSON: {e}[/red]")
        raise typer.Exit(code=1)

    if not isinstance(manifest, dict) or "nodes" not in manifest:
        print(f"[red]{path} has no 'nodes' — is this a dbt manifest.json?[/red]")
        raise typer.Exit(code=1)

    return manifest


def _parse_container_map(pairs: list[str]) -> dict[str, str]:
    """Parse repeated --container-map model=container into a dict."""
    mapping = {}
    for pair in pairs or []:
        if "=" not in pair:
            print(f"[red]--container-map expects model=container, got: {pair}[/red]")
            raise typer.Exit(code=1)
        model, container = pair.split("=", 1)
        mapping[model.strip()] = container.strip()
    return mapping


def _convert(manifest, container_map, container_case, preserve_status):
    converted = convert_manifest(
        manifest,
        container_map=_parse_container_map(container_map),
        container_case=container_case,
        include_status=not preserve_status,
    )
    if not converted:
        print(
            "[yellow]No test nodes found in the manifest — nothing to migrate.[/yellow]"
        )
        raise typer.Exit(code=0)
    return converted


def _print_summary(converted) -> dict:
    stats = summarize(converted)

    table = Table(title="dbt → Qualytics coverage")
    table.add_column("Tier", style="bold")
    table.add_column("Checks", justify="right")
    table.add_column("Lands as")
    table.add_row("direct", str(stats["direct"]), "[green]Active[/green]")
    table.add_row("normalize", str(stats["normalize"]), "[cyan]Draft[/cyan]")
    table.add_row("manual", str(stats["manual"]), "[yellow]Draft[/yellow]")
    table.add_row("[bold]total[/bold]", f"[bold]{stats['total']}[/bold]", "")
    console.print(table)

    # A few dbt tests assert two things (a length range) and become two checks,
    # so check count can exceed test count. Say so rather than conflating them.
    split_note = (
        f" ([bold]{stats['dbt_tests']}[/bold] dbt tests — some assert two things "
        "and become two checks)"
        if stats["total"] != stats["dbt_tests"]
        else ""
    )
    print(
        f"\nAll dbt tests convert into [bold]{stats['total']}[/bold] checks{split_note}. "
        f"[bold]{stats['automatic']}[/bold] ({stats['automatic_pct']}%) map to a rule "
        f"automatically; [bold]{stats['manual']}[/bold] need an expression authored by hand."
    )
    print(
        f"[dim]Tiers grade effort, not feasibility. "
        f"{stats['normalize'] + stats['manual']} land as Draft for review before they fire.[/dim]"
    )

    if stats["unresolved_containers"]:
        print(
            f"\n[red]{stats['unresolved_containers']} test(s) have no resolvable container.[/red] "
            "[dim]Use --container-map model=container.[/dim]"
        )

    return stats


def _write_yaml(converted, out_dir: str) -> None:
    """Write one YAML file per check, grouped by container.

    Filenames use the dbt-derived UID rather than rule+fields, for the same reason
    the UID itself does: several dbt tests can share a container/rule/field triple.
    """
    for c in converted:
        container_dir = os.path.join(out_dir, c.container or "_unresolved")
        os.makedirs(container_dir, exist_ok=True)
        uid = c.check["additional_metadata"]["_qualytics_check_uid"]
        path = os.path.join(container_dir, f"{uid}.yaml")
        with open(path, "w") as f:
            yaml.safe_dump(c.check, f, sort_keys=False, default_flow_style=False)
    print(f"[cyan]Wrote {len(converted)} check definitions to {out_dir}/[/cyan]")


# ── plan ──────────────────────────────────────────────────────────────────


@dbt_app.command("plan")
def dbt_plan(
    manifest_path: str = typer.Option(
        "target/manifest.json", "--manifest", "-m", help="Path to dbt manifest.json"
    ),
    container_map: list[str] = typer.Option(
        None, "--container-map", help="Override a container name: model=container"
    ),
    container_case: str = typer.Option(
        None, "--container-case", help="Force container name case: upper or lower"
    ),
    show_checks: bool = typer.Option(
        False, "--show-checks", help="List every dbt test and the rule it maps to"
    ),
):
    """Preview what a dbt manifest would migrate to. Offline — no auth required."""
    manifest = _load_manifest(manifest_path)
    converted = _convert(manifest, container_map, container_case, False)

    _print_summary(converted)

    if show_checks:
        detail = Table(title="Crosswalk")
        detail.add_column("Tier")
        detail.add_column("dbt test", style="dim")
        detail.add_column("Container")
        detail.add_column("Qualytics rule")
        for c in sorted(converted, key=lambda x: (x.tier, x.dbt_test)):
            label, color = _TIER_LABEL[c.tier]
            detail.add_row(
                f"[{color}]{label}[/{color}]",
                c.dbt_test,
                c.container or "[red]unresolved[/red]",
                c.check["rule_type"],
            )
        console.print(detail)


# ── import ────────────────────────────────────────────────────────────────


@dbt_app.command("import")
def dbt_import(
    datastore_id: list[int] = typer.Option(
        ..., "--datastore-id", help="Target datastore ID (repeat for multiple)"
    ),
    manifest_path: str = typer.Option(
        "target/manifest.json", "--manifest", "-m", help="Path to dbt manifest.json"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Preview what would be created/updated"
    ),
    container_map: list[str] = typer.Option(
        None, "--container-map", help="Override a container name: model=container"
    ),
    container_case: str = typer.Option(
        None, "--container-case", help="Force container name case: upper or lower"
    ),
    preserve_status: bool = typer.Option(
        False,
        "--preserve-status",
        help="Omit status so re-imports keep what was set in the product",
    ),
    emit_yaml: str = typer.Option(
        None, "--emit-yaml", help="Also write the converted checks to this directory"
    ),
):
    """Convert a dbt manifest and import the checks (upsert) into a datastore.

    Conversion happens in memory; checks upsert on a UID derived from each dbt
    test's unique_id, so re-running after the dbt suite changes updates in place
    rather than duplicating.

    The datastore must be catalogued first — checks reference containers and
    fields by name.
    """
    manifest = _load_manifest(manifest_path)
    converted = _convert(manifest, container_map, container_case, preserve_status)

    stats = _print_summary(converted)

    if emit_yaml:
        _write_yaml(converted, emit_yaml)

    client = get_client()
    checks = to_checks(converted)

    if dry_run:
        print("\n[bold yellow]DRY RUN — no changes will be made.[/bold yellow]")

    summary_table = Table(title="Import Summary")
    summary_table.add_column("Datastore ID", style="cyan")
    summary_table.add_column("Created", style="green")
    summary_table.add_column("Updated", style="yellow")
    summary_table.add_column("Failed", style="red")

    total_failed = 0
    for ds_id in datastore_id:
        print(
            f"\n[cyan]{'[DRY RUN] ' if dry_run else ''}Importing {len(checks)} checks "
            f"to datastore {ds_id}...[/cyan]"
        )
        result = import_checks_to_datastore(client, ds_id, checks, dry_run=dry_run)

        summary_table.add_row(
            str(ds_id),
            str(result["created"]),
            str(result["updated"]),
            str(result["failed"]),
        )
        total_failed += result["failed"]

        for err in result["errors"]:
            print(f"  [red]{err}[/red]")

    console.print(summary_table)

    if total_failed:
        print(
            "[dim]Container-not-found errors usually mean the datastore has not been "
            "catalogued, or dbt model names differ from the warehouse tables "
            "(try --container-map or --container-case).[/dim]"
        )
        raise typer.Exit(code=1)

    if stats["manual"] and not dry_run:
        print(
            f"\n[yellow]{stats['manual']} check(s) landed as Draft with an empty "
            "expression — author those before they can fire.[/yellow]"
        )
