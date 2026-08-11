"""Failed-import log shared by the bulk check importers.

Both `dbt import` and `checks import` print per-check errors as they happen,
but the on-screen lines scroll away. When anything fails, a log file keeps the
record: one entry per failed check with where it came from (a dbt test's
unique_id, a YAML file's path), what the check was, and why it failed.
"""

from datetime import datetime


def failure_entry(ds_id: int, source: str, check: dict | None, reason: str) -> str:
    """One failed check: its source, what the check was, and why it failed —
    enough to act on without re-running the import."""
    lines = [f"[datastore {ds_id}] {source}"]
    if check:
        what = f"{check.get('rule_type')} on {check.get('container') or '<unresolved>'}"
        fields = ", ".join(check.get("fields") or [])
        if fields:
            what += f" ({fields})"
        lines.append(f"  check: {what}")
    lines.append(f"  reason: {reason}")
    return "\n".join(lines)


def write_failures_log(path: str, title: str, origin: str, entries: list[str]) -> None:
    header = f"{title}\nrun: {datetime.now().isoformat(timespec='seconds')}\n{origin}\n"
    with open(path, "w") as f:
        f.write(header + "\n" + "\n\n".join(entries) + "\n")
