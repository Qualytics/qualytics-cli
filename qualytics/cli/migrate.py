"""CLI commands for sheet-driven check migration.

`qualytics migrate` turns a normalized check sheet (XLSX/CSV, one row per
quality check or computed container) into Qualytics assets. `plan` is the
offline half: load, convert, validate, summarize — no auth, no network.
"""

import os
import re

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
    sheet_path: str,
    status: str | None,
    tags: list[str] | None,
    worksheet: str | None = None,
) -> SheetPlan:
    if not os.path.isfile(sheet_path):
        print(f"[red]Sheet not found: {sheet_path}[/red]")
        raise typer.Exit(code=1)
    try:
        rows = load_sheet(sheet_path, worksheet)
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
        from ..services.migrate import sheet_check_uid

        uid = sheet_check_uid(item.check_id)
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


_ANSI_ESCAPES = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


class _TeeStream:
    """stdout tee: everything printed also lands, timestamped and de-ANSIed,
    in the run log — one transcript, no second logging code path to drift."""

    def __init__(self, real):
        self.real = real
        self.lines: list[tuple[str, str]] = []
        self._buffer = ""

    def write(self, text: str) -> int:
        self.real.write(text)
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self.lines.append((_now_stamp(), _ANSI_ESCAPES.sub("", line).rstrip()))
        return len(text)

    def flush(self) -> None:
        self.real.flush()

    def __getattr__(self, name):
        return getattr(self.real, name)


def _now_stamp() -> str:
    from datetime import datetime

    return datetime.now().astimezone().isoformat(timespec="seconds")


def _write_run_log(path: str, *, sheet_path: str, worksheet, lines) -> None:
    from ..config import __version__

    try:
        with open(path, "w") as f:
            f.write(
                f"qualytics migrate apply — CLI v{__version__}\n"
                f"started: {lines[0][0] if lines else _now_stamp()}\n"
                f"finished: {_now_stamp()}\n"
                f"sheet: {os.path.abspath(sheet_path)}"
                + (f" (worksheet: {worksheet})" if worksheet else "")
                + "\n"
                + "-" * 72
                + "\n"
            )
            for stamp, line in lines:
                f.write(f"[{stamp}] {line}\n")
    except OSError as e:  # pragma: no cover - the log must never sink the run
        print(f"[yellow]Could not write run log {path}: {e}[/yellow]")


# ── plan ──────────────────────────────────────────────────────────────────


@migrate_app.command("plan")
def migrate_plan(
    sheet_path: str = typer.Option(
        ..., "--sheet", "-s", help="Path to the check sheet (.xlsx or .csv)"
    ),
    worksheet: str = typer.Option(
        None,
        "--worksheet",
        help="Workbook tab to read: name or 1-based position (default: first)",
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
    plan = _load_plan(sheet_path, status, tag, worksheet)
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


def _write_results_csv(
    path: str,
    outcomes_by_datastore: dict,
    base_url: str,
    failures_by_datastore: dict | None = None,
    checks_by_source: dict | None = None,
) -> int:
    """The per-check receipt: which sheet row became which check, with links.

    Terminal output stays a summary — at migration scale (dozens to hundreds
    of rows) a per-check line is scrollback noise, but the client handoff
    needs the mapping. CSV so it pastes straight back into the tracker the
    sheet came from.
    """
    import csv

    failures_by_datastore = failures_by_datastore or {}
    if not any(outcomes_by_datastore.values()) and not any(
        failures_by_datastore.values()
    ):
        return 0

    checks_by_source = checks_by_source or {}
    rows = 0
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "check_id",
                "action",
                "qualytics_check_id",
                "datastore_id",
                "container",
                "rule_type",
                "status",
                "url",
                "reason",
            ]
        )
        for ds_id, outcomes in outcomes_by_datastore.items():
            for outcome in outcomes:
                check = outcome["check"]
                meta = check.get("additional_metadata") or {}
                url = ""
                if base_url:
                    url = (
                        f"{base_url}datastores/{ds_id}/containers/"
                        f"{outcome['container_id']}/checks/{outcome['id']}/overview"
                    )
                writer.writerow(
                    [
                        meta.get("legacy_check_id", ""),
                        outcome["action"],
                        outcome["id"],
                        ds_id,
                        check.get("container", ""),
                        check.get("rule_type", ""),
                        check.get("status", ""),
                        url,
                        "",
                    ]
                )
                rows += 1
        for ds_id, failures in failures_by_datastore.items():
            for failure in failures:
                check = checks_by_source.get(failure.get("source")) or {}
                meta = check.get("additional_metadata") or {}
                writer.writerow(
                    [
                        meta.get("legacy_check_id", failure.get("source", "")),
                        "failed",
                        "",
                        ds_id,
                        check.get("container", ""),
                        check.get("rule_type", ""),
                        "",
                        "",
                        failure.get("reason", ""),
                    ]
                )
                rows += 1
    return rows


def _instance_base_url(client) -> str:
    """The UI base URL: the API base with its trailing api path removed."""
    base = getattr(client, "base_url", "") or ""
    if base.endswith("api/"):
        base = base[: -len("api/")]
    return base


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


def _apply_body(
    *,
    sheet_path: str,
    worksheet: str | None,
    datastore_id: list[int],
    dry_run: bool,
    status: str | None,
    preserve_status: bool,
    tag: list[str] | None,
    validate_fields: bool,
    skip_containers: bool,
    on_existing: str,
    force_drop_fields: bool,
    profile_timeout: int,
    emit_yaml: str | None,
    failures_log: str,
    results_csv: str,
    strict: bool,
    run_dir: str | None,
) -> None:
    from ..api.client import get_client
    from ..services.containers import get_table_ids
    from ..services.migrate import ensure_containers, repair_container_names
    from .import_flow import run_check_import

    if on_existing not in ("skip", "update"):
        print(f"[red]--on-existing must be skip or update, got: {on_existing}[/red]")
        raise typer.Exit(code=1)

    plan = _load_plan(sheet_path, status, tag, worksheet)
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
    if run_dir:
        # The as-applied YAML is part of the run's audit trail.
        _emit_yaml(plan, os.path.join(run_dir, "yaml"))

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
                force_drop_fields=force_drop_fields,
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
        # Containers this run creates don't exist yet during a dry run; name
        # them so dependent checks count as creates, not spurious failures.
        pending = {
            ds_id: {spec.name for spec in specs}
            for ds_id, specs in routed_containers.items()
        }
        outcome = run_check_import(
            client,
            checks_by_datastore,
            validate_fields=validate_fields,
            dry_run=dry_run,
            failures_log=failures_log,
            log_title="migrate apply failures",
            log_origin=f"sheet: {sheet_path}",
            pending_containers_by_datastore=pending,
            uid_key="legacy_check_id",
        )
        total_failed = outcome["total_failed"]

        if not dry_run and results_csv:
            outcomes_by_datastore = {
                ds_id: result.get("outcomes") or []
                for ds_id, result in outcome["results"].items()
            }
            failures_by_datastore = {
                ds_id: result.get("failures") or []
                for ds_id, result in outcome["results"].items()
            }
            checks_by_source = {
                check.get("_source_file"): check
                for checks in checks_by_datastore.values()
                for check in checks
            }
            written = _write_results_csv(
                results_csv,
                outcomes_by_datastore,
                _instance_base_url(client),
                failures_by_datastore,
                checks_by_source,
            )
            if written:
                print(
                    f"[cyan]Per-check results written to {results_csv} "
                    f"({written} check(s))[/cyan]"
                )

    if not dry_run and stats["by_status"].get("Draft"):
        print(
            "\n[dim]Draft checks activate in the product after review; re-applies "
            "with --preserve-status keep those activations.[/dim]"
        )

    if strict and (
        stats["errors"] or override_errors or container_failures or total_failed
    ):
        raise typer.Exit(code=1)


_RUN_DIR_HELP = (
    "Directory for this run's artifacts — run.log (timestamped transcript), "
    "results.csv (per-check OK/FAIL ledger), yaml/ (the as-applied check "
    "definitions). Default: migrate-runs/<UTC timestamp>. Pass an empty "
    "string to disable. Dry runs write nothing."
)


@migrate_app.command("apply")
def migrate_apply(
    sheet_path: str = typer.Option(
        ..., "--sheet", "-s", help="Path to the check sheet (.xlsx or .csv)"
    ),
    worksheet: str = typer.Option(
        None,
        "--worksheet",
        help="Workbook tab to read: name or 1-based position (default: first)",
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
    force_drop_fields: bool = typer.Option(
        False,
        "--force-drop-fields",
        help="With --on-existing update: allow definition changes that drop "
        "fields carrying quality checks (the platform preserves those checks; "
        "they reactivate if the fields reappear)",
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
        None,
        "--failures-log",
        help="Failure log path (default: <run-dir>/failures.log)",
    ),
    results_csv: str = typer.Option(
        None,
        "--results-csv",
        help="Per-check OK/FAIL ledger path (default: <run-dir>/results.csv); "
        "empty string to skip",
    ),
    run_dir: str = typer.Option(None, "--run-dir", help=_RUN_DIR_HELP),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Exit non-zero when the sheet has error rows or anything fails",
    ),
):
    """Create the sheet's computed containers and checks on the target instance.

    Two phases: computed containers first (validate all, create in declaration
    order, wait for each container's own profile operation), then the checks.
    Checks upsert on the sheet's check_id (stored as legacy_check_id), so
    re-running after sheet edits updates in place rather than duplicating.

    Every real run leaves an artifact folder (see --run-dir): a timestamped
    run.log, a per-check results.csv, and the as-applied YAML definitions.

    Rows with error-level issues are skipped and reported; fix the sheet and
    re-apply. By default everything lands as Draft for review — activate in
    the product, and use --preserve-status on re-applies so activations stick.
    """
    import sys
    from datetime import datetime, timezone as _tz

    effective_run_dir = None
    if not dry_run and run_dir != "":
        effective_run_dir = run_dir or os.path.join(
            "migrate-runs", datetime.now(_tz.utc).strftime("%Y%m%d-%H%M%S")
        )
        os.makedirs(effective_run_dir, exist_ok=True)
    if results_csv is None:
        results_csv = (
            os.path.join(effective_run_dir, "results.csv") if effective_run_dir else ""
        )
    if failures_log is None:
        failures_log = (
            os.path.join(effective_run_dir, "failures.log")
            if effective_run_dir
            else "migrate-apply-failures.log"
        )

    tee = None
    if effective_run_dir:
        tee = _TeeStream(sys.stdout)
        sys.stdout = tee
    try:
        _apply_body(
            sheet_path=sheet_path,
            worksheet=worksheet,
            datastore_id=datastore_id,
            dry_run=dry_run,
            status=status,
            preserve_status=preserve_status,
            tag=tag,
            validate_fields=validate_fields,
            skip_containers=skip_containers,
            on_existing=on_existing,
            force_drop_fields=force_drop_fields,
            profile_timeout=profile_timeout,
            emit_yaml=emit_yaml,
            failures_log=failures_log,
            results_csv=results_csv,
            strict=strict,
            run_dir=effective_run_dir,
        )
    finally:
        if tee is not None:
            sys.stdout = tee.real
            _write_run_log(
                os.path.join(effective_run_dir, "run.log"),
                sheet_path=sheet_path,
                worksheet=worksheet,
                lines=tee.lines,
            )
            print(
                f"[cyan]Run artifacts in {effective_run_dir}/ — run.log, "
                f"results.csv, yaml/[/cyan]"
            )


# ── validate ──────────────────────────────────────────────────────────────


def _validate_online(plan: SheetPlan, base_ids: list[int]) -> int:
    """Read-only checks against the target instance; returns the error count.

    Resolves everything `apply` would need — target containers, field names,
    cross-references, join sources — with GETs only, so a broken sheet fails
    here instead of one POST at a time mid-migration.
    """
    from ..api.client import get_client
    from ..api.fields import container_field_names
    from ..services.containers import get_table_ids
    from ..services.datastores import get_datastore_by_name
    from ..services.rules import resolve_check_fields
    from .import_flow import field_catalogue

    client = get_client()
    errors = 0

    resolved, override_errors = _resolve_datastore_overrides(client, plan)
    for message in override_errors:
        print(f"  [red]✗ {message}[/red]")
        errors += 1

    routed_checks = _route(plan.checks, base_ids, resolved)
    routed_containers = _route(plan.containers, base_ids, resolved)

    datastore_cache: dict[str, int | None] = {}

    def _resolve_ref_datastore(properties: dict, default_id: int) -> int | None:
        if "ref_datastore_id" in properties:
            return int(properties["ref_datastore_id"])
        name = properties.get("ref_datastore_name")
        if not name:
            return default_id
        if name not in datastore_cache:
            found = get_datastore_by_name(client, name)
            datastore_cache[name] = found["id"] if found else None
        return datastore_cache[name]

    table_cache: dict[int, dict] = {}

    def _tables(ds_id: int) -> dict:
        if ds_id not in table_cache:
            table_cache[ds_id] = get_table_ids(client=client, datastore_id=ds_id) or {}
        return table_cache[ds_id]

    for ds_id in sorted(set(routed_checks) | set(routed_containers)):
        print(f"\n[cyan]Validating against datastore {ds_id} (read-only)...[/cyan]")
        ds_errors = 0
        tables = _tables(ds_id)
        lower_tables = {name.lower(): name for name in tables}
        in_sheet = {spec.name for spec in routed_containers.get(ds_id, [])}

        # Join sources resolve against the catalogue or earlier sheet rows.
        for spec in routed_containers.get(ds_id, []):
            for source in spec.spec.get("sources") or []:
                name = source["container"]
                if name in tables or name.lower() in lower_tables or name in in_sheet:
                    continue
                print(
                    f"  [red]✗ row {spec.row} ({spec.check_id}): join source "
                    f"'{name}' not found in datastore {ds_id}[/red]"
                )
                ds_errors += 1

        # Target containers exist (or this sheet creates them).
        resolvable: list = []
        for item in routed_checks.get(ds_id, []):
            name = item.container
            if name in tables or name.lower() in lower_tables:
                resolvable.append(item)
            elif name in in_sheet:
                print(
                    f"  [dim]row {item.row} ({item.check_id}): container "
                    f"'{name}' will be created by this sheet — field names "
                    "checked after profiling[/dim]"
                )
            else:
                print(
                    f"  [red]✗ row {item.row} ({item.check_id}): container "
                    f"'{name}' not found in datastore {ds_id}[/red]"
                )
                ds_errors += 1

        # Field names against the catalogue (with the casing repair apply uses).
        checks = [
            {
                **item.check,
                "container": lower_tables.get(item.container.lower(), item.container),
            }
            for item in resolvable
        ]
        catalogue = field_catalogue(
            client, ds_id, {check["container"] for check in checks}
        )
        _importable, rejected, corrections = resolve_check_fields(checks, catalogue)
        for correction in corrections:
            print(f"  [dim]field casing repaired: {correction}[/dim]")
        for item in rejected:
            print(f"  [red]✗ {item['reason']}[/red]")
            ds_errors += 1

        # Cross-references resolve to a real container (and field).
        ref_field_cache: dict[int, list[str]] = {}
        for item in routed_checks.get(ds_id, []):
            properties = item.check.get("properties") or {}
            ref_name = properties.get("ref_container_name")
            if not ref_name:
                continue
            ref_ds = _resolve_ref_datastore(properties, ds_id)
            if ref_ds is None:
                print(
                    f"  [red]✗ row {item.row} ({item.check_id}): referenced "
                    f"datastore '{properties.get('ref_datastore_name')}' not "
                    "found[/red]"
                )
                ds_errors += 1
                continue
            ref_tables = _tables(ref_ds)
            ref_lower = {name.lower(): name for name in ref_tables}
            actual = ref_tables.get(ref_name) or ref_tables.get(
                ref_lower.get(ref_name.lower(), "")
            )
            if actual is None and ref_name in in_sheet and ref_ds == ds_id:
                print(
                    f"  [dim]row {item.row} ({item.check_id}): ref container "
                    f"'{ref_name}' will be created by this sheet[/dim]"
                )
                continue
            if actual is None:
                print(
                    f"  [red]✗ row {item.row} ({item.check_id}): ref_container "
                    f"'{ref_name}' not found in datastore {ref_ds}[/red]"
                )
                ds_errors += 1
                continue
            print(
                f"  [dim]row {item.row} ({item.check_id}): ref '{ref_name}' → "
                f"container {actual} in datastore {ref_ds}[/dim]"
            )
            ref_field = properties.get("field_name")
            if ref_field:
                if actual not in ref_field_cache:
                    try:
                        ref_field_cache[actual] = container_field_names(client, actual)
                    except Exception:  # noqa: BLE001 - lookup is best-effort
                        ref_field_cache[actual] = []
                known = ref_field_cache[actual]
                if (
                    known
                    and ref_field not in known
                    and ref_field.lower() not in {name.lower() for name in known}
                ):
                    print(
                        f"  [red]✗ row {item.row} ({item.check_id}): ref_field "
                        f"'{ref_field}' not found in '{ref_name}'[/red]"
                    )
                    ds_errors += 1

        if ds_errors:
            print(f"  [red]{ds_errors} problem(s) in datastore {ds_id}[/red]")
        else:
            print(f"  [green]datastore {ds_id}: all references resolve[/green]")
        errors += ds_errors

    return errors


@migrate_app.command("validate")
def migrate_validate(
    sheet_path: str = typer.Option(
        ..., "--sheet", "-s", help="Path to the check sheet (.xlsx or .csv)"
    ),
    worksheet: str = typer.Option(
        None,
        "--worksheet",
        help="Workbook tab to read: name or 1-based position (default: first)",
    ),
    datastore_id: list[int] = typer.Option(
        None,
        "--datastore-id",
        help="Also resolve containers/fields/refs against this datastore, "
        "read-only (repeat for multiple)",
    ),
):
    """Fail-early validation: everything `plan` checks, plus read-only
    resolution against target datastores when --datastore-id is given.
    Makes no changes; exits non-zero on any problem."""
    plan = _load_plan(sheet_path, None, None, worksheet)
    stats = _print_summary(plan, sheet_path)

    total_errors = stats["errors"]
    if datastore_id:
        total_errors += _validate_online(plan, list(datastore_id))
    elif any(item.datastore is not None for item in [*plan.checks, *plan.containers]):
        print(
            "[dim]Pass --datastore-id to also resolve containers, fields and "
            "references against the target instance.[/dim]"
        )

    if total_errors:
        print(f"\n[bold red]Validation failed — {total_errors} problem(s).[/bold red]")
        raise typer.Exit(code=1)
    print("\n[bold green]Validation passed.[/bold green]")
