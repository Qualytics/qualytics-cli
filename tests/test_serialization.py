"""Tests for serialization utilities."""

import json

import yaml

from qualytics.utils.serialization import (
    OutputFormat,
    detect_format,
    load_data_file,
    dump_data_file,
    format_for_display,
)


class TestDetectFormat:
    """Tests for format detection by file extension."""

    def test_json_extension(self):
        assert detect_format("data.json") == OutputFormat.JSON

    def test_yaml_extension(self):
        assert detect_format("data.yaml") == OutputFormat.YAML

    def test_yml_extension(self):
        assert detect_format("data.yml") == OutputFormat.YAML

    def test_unknown_extension_defaults_to_yaml(self):
        assert detect_format("data.txt") == OutputFormat.YAML

    def test_no_extension_defaults_to_yaml(self):
        assert detect_format("data") == OutputFormat.YAML


class TestLoadDataFile:
    """Tests for loading data files."""

    def test_load_json_file(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_text(json.dumps({"key": "value"}))
        result = load_data_file(str(f))
        assert result == {"key": "value"}

    def test_load_yaml_file(self, tmp_path):
        f = tmp_path / "data.yaml"
        f.write_text(yaml.safe_dump({"key": "value"}))
        result = load_data_file(str(f))
        assert result == {"key": "value"}

    def test_load_yaml_preserves_date_strings(self, tmp_path):
        """ISO date strings must stay as strings, not become datetime objects."""
        f = tmp_path / "data.yaml"
        f.write_text("created: 2024-01-15\nupdated: 2024-01-15T10:30:00Z\n")
        result = load_data_file(str(f))
        assert isinstance(result["created"], str)
        assert result["created"] == "2024-01-15"
        assert isinstance(result["updated"], str)
        assert result["updated"] == "2024-01-15T10:30:00Z"

    def test_load_yaml_list(self, tmp_path):
        f = tmp_path / "data.yaml"
        f.write_text("- name: check1\n- name: check2\n")
        result = load_data_file(str(f))
        assert isinstance(result, list)
        assert len(result) == 2


class TestDumpDataFile:
    """Tests for writing data files."""

    def test_dump_yaml(self, tmp_path):
        f = tmp_path / "out.yaml"
        dump_data_file({"key": "value"}, str(f), OutputFormat.YAML)
        assert f.exists()
        data = yaml.safe_load(f.read_text())
        assert data == {"key": "value"}

    def test_dump_json(self, tmp_path):
        f = tmp_path / "out.json"
        dump_data_file({"key": "value"}, str(f), OutputFormat.JSON)
        assert f.exists()
        data = json.loads(f.read_text())
        assert data == {"key": "value"}

    def test_round_trip_yaml(self, tmp_path):
        original = [{"id": 1, "name": "check", "date": "2024-01-15"}]
        f = tmp_path / "round.yaml"
        dump_data_file(original, str(f), OutputFormat.YAML)
        loaded = load_data_file(str(f))
        assert loaded == original

    def test_round_trip_json(self, tmp_path):
        original = [{"id": 1, "name": "check"}]
        f = tmp_path / "round.json"
        dump_data_file(original, str(f), OutputFormat.JSON)
        loaded = load_data_file(str(f))
        assert loaded == original


class TestFormatForDisplay:
    """Tests for terminal display formatting."""

    def test_yaml_output(self):
        result = format_for_display({"key": "value"}, OutputFormat.YAML)
        assert "key: value" in result

    def test_json_output(self):
        result = format_for_display({"key": "value"}, OutputFormat.JSON)
        parsed = json.loads(result)
        assert parsed == {"key": "value"}

    def test_yaml_is_default(self):
        result = format_for_display({"key": "value"})
        assert "key: value" in result
