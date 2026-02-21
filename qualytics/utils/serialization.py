"""Serialization utilities for YAML/JSON format handling."""

import json
from enum import Enum
from pathlib import Path

import yaml


class OutputFormat(str, Enum):
    """Supported output formats."""

    YAML = "yaml"
    JSON = "json"


class _SafeStringLoader(yaml.SafeLoader):
    """YAML loader that keeps date-like strings as strings.

    By default, PyYAML parses ISO date strings like ``2024-01-15`` or
    ``2024-01-15T10:30:00Z`` into Python ``datetime`` objects.  This
    breaks round-tripping of API data through checks export/import.
    Stripping the implicit timestamp resolver keeps every scalar as a
    plain string.
    """

    pass


# Remove the implicit timestamp resolver so dates stay as strings
_SafeStringLoader.yaml_implicit_resolvers = {
    k: [(tag, regexp) for tag, regexp in v if tag != "tag:yaml.org,2002:timestamp"]
    for k, v in yaml.SafeLoader.yaml_implicit_resolvers.copy().items()
}


def detect_format(file_path: str) -> OutputFormat:
    """Detect file format from extension.

    Returns ``JSON`` for ``.json``, ``YAML`` for everything else.
    """
    suffix = Path(file_path).suffix.lower()
    if suffix == ".json":
        return OutputFormat.JSON
    return OutputFormat.YAML


def load_data_file(file_path: str) -> dict | list:
    """Load structured data from a file, auto-detecting format by extension."""
    fmt = detect_format(file_path)
    with open(file_path) as f:
        if fmt == OutputFormat.JSON:
            return json.load(f)
        return yaml.load(f, Loader=_SafeStringLoader)


def dump_data_file(
    data: dict | list,
    file_path: str,
    fmt: OutputFormat = OutputFormat.YAML,
) -> None:
    """Write structured data to a file in the specified format."""
    with open(file_path, "w") as f:
        if fmt == OutputFormat.JSON:
            json.dump(data, f, indent=4)
        else:
            yaml.safe_dump(
                data,
                f,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )


def format_for_display(data: dict | list, fmt: OutputFormat = OutputFormat.YAML) -> str:
    """Format structured data as a string for terminal display."""
    if fmt == OutputFormat.JSON:
        return json.dumps(data, indent=2)
    return yaml.safe_dump(
        data,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    ).rstrip("\n")
