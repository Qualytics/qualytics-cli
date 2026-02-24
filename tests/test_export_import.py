"""Tests for the export/import config-as-code feature."""

import re
from unittest.mock import ANY, MagicMock, patch

import pytest
import yaml


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text (Rich/Typer help output on some platforms)."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


from qualytics.qualytics import app
from qualytics.services.export_import import (
    _generate_env_var_name,
    _import_computed_fields,
    _import_connections,
    _import_containers,
    _import_datastore,
    _resolve_connection_secrets,
    _resolve_container_refs,
    _slugify,
    _write_yaml,
    export_config,
    import_config,
    strip_computed_field_for_export,
    strip_connection_for_export,
    strip_container_for_export,
    strip_datastore_for_export,
)


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def mock_client():
    return MagicMock()


@pytest.fixture
def sample_connection():
    return {
        "id": 1,
        "name": "prod-pg",
        "type": "postgresql",
        "host": "db.example.com",
        "port": 5432,
        "username": "admin",
        "password": "secret123",
        "secret_key": "sk_abc",
        "created": "2024-01-15T10:00:00Z",
        "connection_type": "JDBC",
        "datastores": [{"id": 1}],
        "product_name": "PostgreSQL",
        "product_version": "15.0",
        "driver_name": "pg-driver",
        "driver_version": "42.5",
        "jdbc_fetch_size": 1000,
    }


@pytest.fixture
def sample_datastore():
    return {
        "id": 10,
        "name": "prod-warehouse",
        "store_type": "JDBC",
        "type": "postgresql",
        "database": "analytics",
        "schema": "public",
        "tags": ["production"],
        "teams": ["data-eng"],
        "connection": {"id": 1, "name": "prod-pg", "type": "postgresql"},
        "enrich_datastore": {"id": 20, "name": "enrichment-ds"},
        "created": "2024-01-15T10:00:00Z",
        "connected": True,
        "favorite": False,
        "latest_operation": {"id": 99},
        "metrics": {},
        "anomaly_count": 0,
        "check_count": 5,
        "container_count": 3,
        "field_count": 50,
        "record_count": 1000,
        "score": 95,
    }


@pytest.fixture
def sample_container():
    return {
        "id": 100,
        "name": "filtered_orders",
        "container_type": "computed_table",
        "query": "SELECT * FROM orders WHERE status = 'active'",
        "created": "2024-01-15T10:00:00Z",
        "status": "active",
        "metrics": {},
        "computed_fields": [],
        "field_count": 10,
        "anomaly_count": 0,
        "check_count": 2,
        "record_count": 500,
        "score": 90,
        "cataloged": True,
        "datastore": {"id": 10, "name": "prod-warehouse"},
        "tags": ["computed"],
    }


@pytest.fixture
def sample_computed_join():
    return {
        "id": 101,
        "name": "orders_customers",
        "container_type": "computed_join",
        "select_clause": "o.*, c.name",
        "left_container": {"id": 100, "name": "orders"},
        "right_container": {"id": 200, "name": "customers"},
        "left_join_field_name": "customer_id",
        "right_join_field_name": "id",
        "join_type": "inner",
        "created": "2024-01-15T10:00:00Z",
        "status": "active",
        "datastore": {"id": 10, "name": "prod-warehouse"},
    }


# ── Helper tests ─────────────────────────────────────────────────────────


class TestSlugify:
    def test_simple(self):
        assert _slugify("Hello World") == "hello_world"

    def test_special_chars(self):
        assert _slugify("prod-db (main)") == "prod_db_main"

    def test_multiple_spaces(self):
        assert _slugify("a   b") == "a_b"

    def test_leading_trailing(self):
        assert _slugify("  --hello--  ") == "hello"


class TestWriteYaml:
    def test_creates_file(self, tmp_path):
        path = tmp_path / "test.yaml"
        result = _write_yaml(path, {"key": "value"})
        assert result is True
        assert path.exists()
        with open(path) as f:
            data = yaml.safe_load(f)
        assert data == {"key": "value"}

    def test_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "a" / "b" / "c" / "test.yaml"
        _write_yaml(path, {"key": "value"})
        assert path.exists()

    def test_no_write_when_unchanged(self, tmp_path):
        path = tmp_path / "test.yaml"
        _write_yaml(path, {"key": "value"})
        result = _write_yaml(path, {"key": "value"})
        assert result is False

    def test_overwrites_when_changed(self, tmp_path):
        path = tmp_path / "test.yaml"
        _write_yaml(path, {"key": "old"})
        result = _write_yaml(path, {"key": "new"})
        assert result is True
        with open(path) as f:
            data = yaml.safe_load(f)
        assert data == {"key": "new"}


class TestGenerateEnvVarName:
    def test_simple(self):
        assert _generate_env_var_name("prod-pg", "password") == "${PROD_PG_PASSWORD}"

    def test_special_chars(self):
        assert (
            _generate_env_var_name("my db (main)", "secret_key")
            == "${MY_DB_MAIN_SECRET_KEY}"
        )


# ── Strip functions ──────────────────────────────────────────────────────


class TestStripConnectionForExport:
    def test_removes_internal_fields(self, sample_connection):
        result = strip_connection_for_export(sample_connection)
        for field in ("id", "created", "connection_type", "datastores"):
            assert field not in result

    def test_replaces_secrets_with_env_vars(self, sample_connection):
        result = strip_connection_for_export(sample_connection)
        assert result["password"] == "${PROD_PG_PASSWORD}"
        assert result["secret_key"] == "${PROD_PG_SECRET_KEY}"

    def test_keeps_non_secret_fields(self, sample_connection):
        result = strip_connection_for_export(sample_connection)
        assert result["name"] == "prod-pg"
        assert result["type"] == "postgresql"
        assert result["host"] == "db.example.com"
        assert result["port"] == 5432
        assert result["username"] == "admin"
        assert result["jdbc_fetch_size"] == 1000


class TestStripDatastoreForExport:
    def test_replaces_connection_with_name(self, sample_datastore):
        result = strip_datastore_for_export(sample_datastore)
        assert result["connection_name"] == "prod-pg"
        assert "connection" not in result

    def test_replaces_enrichment_with_name(self, sample_datastore):
        result = strip_datastore_for_export(sample_datastore)
        assert result["enrich_datastore_name"] == "enrichment-ds"
        assert "enrich_datastore" not in result

    def test_removes_internal_fields(self, sample_datastore):
        result = strip_datastore_for_export(sample_datastore)
        for field in (
            "id",
            "created",
            "connected",
            "favorite",
            "latest_operation",
            "metrics",
        ):
            assert field not in result

    def test_keeps_core_fields(self, sample_datastore):
        result = strip_datastore_for_export(sample_datastore)
        assert result["name"] == "prod-warehouse"
        assert result["database"] == "analytics"
        assert result["schema"] == "public"
        assert result["tags"] == ["production"]


class TestStripContainerForExport:
    def test_removes_internal_fields(self, sample_container):
        result = strip_container_for_export(sample_container, "prod-warehouse")
        for field in ("id", "created", "status", "metrics", "datastore"):
            assert field not in result

    def test_adds_datastore_name(self, sample_container):
        result = strip_container_for_export(sample_container, "prod-warehouse")
        assert result["datastore_name"] == "prod-warehouse"

    def test_keeps_computed_fields(self, sample_container):
        result = strip_container_for_export(sample_container, "prod-warehouse")
        assert result["name"] == "filtered_orders"
        assert result["container_type"] == "computed_table"
        assert result["query"] == "SELECT * FROM orders WHERE status = 'active'"

    def test_resolves_join_container_names(self, sample_computed_join):
        result = strip_container_for_export(sample_computed_join, "prod-warehouse")
        assert result["left_container_name"] == "orders"
        assert result["right_container_name"] == "customers"
        assert "left_container" not in result
        assert "right_container" not in result
        assert "left_container_id" not in result
        assert "right_container_id" not in result


# ── Import helpers ───────────────────────────────────────────────────────


class TestResolveConnectionSecrets:
    def test_resolves_env_vars(self, monkeypatch):
        monkeypatch.setenv("MY_PASSWORD", "secret123")
        data = {"name": "test", "password": "${MY_PASSWORD}"}
        result = _resolve_connection_secrets(data)
        assert result["password"] == "secret123"

    def test_raises_on_unresolved(self):
        data = {"password": "${NONEXISTENT_VAR_12345}"}
        with pytest.raises(ValueError, match="Unresolved"):
            _resolve_connection_secrets(data)

    def test_leaves_non_sensitive_fields(self, monkeypatch):
        monkeypatch.setenv("MY_PW", "secret")
        data = {"name": "test", "host": "localhost", "password": "${MY_PW}"}
        result = _resolve_connection_secrets(data)
        assert result["host"] == "localhost"
        assert result["name"] == "test"


class TestResolveContainerRefs:
    def test_resolves_source_name(self, mock_client):
        data = {"source_container_name": "orders", "container_type": "computed_file"}
        with patch(
            "qualytics.services.export_import.get_container_by_name",
            return_value={"id": 5, "name": "orders"},
        ):
            _resolve_container_refs(mock_client, data, 10)
        assert data["source_container_id"] == 5
        assert "source_container_name" not in data

    def test_resolves_join_names(self, mock_client):
        def mock_get(client, ds_id, name):
            return {"id": 10 if name == "left" else 20, "name": name}

        data = {
            "left_container_name": "left",
            "right_container_name": "right",
            "container_type": "computed_join",
        }
        with patch(
            "qualytics.services.export_import.get_container_by_name",
            side_effect=mock_get,
        ):
            _resolve_container_refs(mock_client, data, 10)
        assert data["left_container_id"] == 10
        assert data["right_container_id"] == 20

    def test_raises_on_missing_ref(self, mock_client):
        data = {"source_container_name": "nonexistent"}
        with patch(
            "qualytics.services.export_import.get_container_by_name",
            return_value=None,
        ):
            with pytest.raises(ValueError, match="not found"):
                _resolve_container_refs(mock_client, data, 10)


# ── Import connections ───────────────────────────────────────────────────


class TestImportConnections:
    def test_creates_new_connection(self, mock_client, tmp_path):
        conn_dir = tmp_path / "connections"
        conn_dir.mkdir()
        (conn_dir / "prod_pg.yaml").write_text(
            yaml.safe_dump(
                {"name": "prod-pg", "type": "postgresql", "host": "db.example.com"}
            )
        )

        with (
            patch(
                "qualytics.services.export_import.get_connection_by_name",
                return_value=None,
            ),
            patch(
                "qualytics.services.export_import.create_connection",
                return_value={"id": 1},
            ) as mock_create,
        ):
            result = _import_connections(mock_client, conn_dir)

        assert result["created"] == 1
        assert result["updated"] == 0
        mock_create.assert_called_once()

    def test_updates_existing_connection(self, mock_client, tmp_path):
        conn_dir = tmp_path / "connections"
        conn_dir.mkdir()
        (conn_dir / "prod_pg.yaml").write_text(
            yaml.safe_dump(
                {"name": "prod-pg", "type": "postgresql", "host": "db.example.com"}
            )
        )

        with (
            patch(
                "qualytics.services.export_import.get_connection_by_name",
                return_value={"id": 1, "name": "prod-pg"},
            ),
            patch(
                "qualytics.services.export_import.update_connection",
            ) as mock_update,
        ):
            result = _import_connections(mock_client, conn_dir)

        assert result["updated"] == 1
        assert result["created"] == 0
        mock_update.assert_called_once()

    def test_dry_run(self, mock_client, tmp_path):
        conn_dir = tmp_path / "connections"
        conn_dir.mkdir()
        (conn_dir / "new.yaml").write_text(
            yaml.safe_dump({"name": "new-conn", "type": "postgresql"})
        )

        with patch(
            "qualytics.services.export_import.get_connection_by_name",
            return_value=None,
        ):
            result = _import_connections(mock_client, conn_dir, dry_run=True)

        assert result["created"] == 1
        assert result["updated"] == 0

    def test_missing_name_field(self, mock_client, tmp_path):
        conn_dir = tmp_path / "connections"
        conn_dir.mkdir()
        (conn_dir / "bad.yaml").write_text(yaml.safe_dump({"type": "postgresql"}))

        result = _import_connections(mock_client, conn_dir)
        assert result["failed"] == 1
        assert len(result["errors"]) == 1

    def test_empty_directory(self, mock_client, tmp_path):
        conn_dir = tmp_path / "connections"
        conn_dir.mkdir()
        result = _import_connections(mock_client, conn_dir)
        assert result == {"created": 0, "updated": 0, "failed": 0, "errors": []}

    def test_nonexistent_directory(self, mock_client, tmp_path):
        result = _import_connections(mock_client, tmp_path / "nonexistent")
        assert result == {"created": 0, "updated": 0, "failed": 0, "errors": []}

    def test_resolves_env_vars(self, mock_client, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PASS", "mysecret")
        conn_dir = tmp_path / "connections"
        conn_dir.mkdir()
        (conn_dir / "conn.yaml").write_text(
            yaml.safe_dump({"name": "conn", "type": "pg", "password": "${DB_PASS}"})
        )

        with (
            patch(
                "qualytics.services.export_import.get_connection_by_name",
                return_value=None,
            ),
            patch(
                "qualytics.services.export_import.create_connection",
                return_value={"id": 1},
            ) as mock_create,
        ):
            result = _import_connections(mock_client, conn_dir)

        assert result["created"] == 1
        # Verify password was resolved
        call_args = mock_create.call_args
        assert call_args[0][1]["password"] == "mysecret"

    def test_unresolved_env_var_fails(self, mock_client, tmp_path):
        conn_dir = tmp_path / "connections"
        conn_dir.mkdir()
        (conn_dir / "conn.yaml").write_text(
            yaml.safe_dump(
                {"name": "conn", "type": "pg", "password": "${UNSET_VAR_XYZ123}"}
            )
        )

        with patch(
            "qualytics.services.export_import.get_connection_by_name",
            return_value=None,
        ):
            result = _import_connections(mock_client, conn_dir)

        assert result["failed"] == 1
        assert "Unresolved" in result["errors"][0]


# ── Import datastore ─────────────────────────────────────────────────────


class TestImportDatastore:
    def test_creates_new_datastore(self, mock_client, tmp_path):
        ds_dir = tmp_path / "my_ds"
        ds_dir.mkdir()
        (ds_dir / "_datastore.yaml").write_text(
            yaml.safe_dump(
                {
                    "name": "my-ds",
                    "database": "db",
                    "schema": "public",
                    "connection_name": "prod-pg",
                }
            )
        )

        with (
            patch(
                "qualytics.services.export_import.get_connection_by_name",
                return_value={"id": 1},
            ),
            patch(
                "qualytics.services.export_import.get_datastore_by_name",
                return_value=None,
            ),
            patch(
                "qualytics.services.export_import.create_datastore",
                return_value={"id": 10},
            ) as mock_create,
        ):
            result = _import_datastore(mock_client, ds_dir)

        assert result["created"] == 1
        assert result["datastore_id"] == 10
        mock_create.assert_called_once()

    def test_updates_existing_datastore(self, mock_client, tmp_path):
        ds_dir = tmp_path / "my_ds"
        ds_dir.mkdir()
        (ds_dir / "_datastore.yaml").write_text(
            yaml.safe_dump(
                {
                    "name": "my-ds",
                    "database": "db",
                    "schema": "public",
                    "connection_name": "prod-pg",
                }
            )
        )

        with (
            patch(
                "qualytics.services.export_import.get_connection_by_name",
                return_value={"id": 1},
            ),
            patch(
                "qualytics.services.export_import.get_datastore_by_name",
                return_value={"id": 10, "name": "my-ds"},
            ),
            patch(
                "qualytics.services.export_import.update_datastore",
            ) as mock_update,
        ):
            result = _import_datastore(mock_client, ds_dir)

        assert result["updated"] == 1
        assert result["datastore_id"] == 10
        mock_update.assert_called_once()

    def test_connection_not_found(self, mock_client, tmp_path):
        ds_dir = tmp_path / "my_ds"
        ds_dir.mkdir()
        (ds_dir / "_datastore.yaml").write_text(
            yaml.safe_dump({"name": "my-ds", "connection_name": "nonexistent"})
        )

        with patch(
            "qualytics.services.export_import.get_connection_by_name",
            return_value=None,
        ):
            result = _import_datastore(mock_client, ds_dir)

        assert result["failed"] == 1
        assert "not found" in result["errors"][0]

    def test_links_enrichment(self, mock_client, tmp_path):
        ds_dir = tmp_path / "my_ds"
        ds_dir.mkdir()
        (ds_dir / "_datastore.yaml").write_text(
            yaml.safe_dump(
                {
                    "name": "my-ds",
                    "connection_name": "prod-pg",
                    "enrich_datastore_name": "enrichment-ds",
                }
            )
        )

        with (
            patch(
                "qualytics.services.export_import.get_connection_by_name",
                return_value={"id": 1},
            ),
            patch(
                "qualytics.services.export_import.get_datastore_by_name",
                side_effect=[None, {"id": 20, "name": "enrichment-ds"}],
            ),
            patch(
                "qualytics.services.export_import.create_datastore",
                return_value={"id": 10},
            ),
            patch(
                "qualytics.services.export_import.connect_enrichment",
            ) as mock_enrich,
        ):
            result = _import_datastore(mock_client, ds_dir)

        assert result["created"] == 1
        mock_enrich.assert_called_once_with(mock_client, 10, 20)

    def test_dry_run(self, mock_client, tmp_path):
        ds_dir = tmp_path / "my_ds"
        ds_dir.mkdir()
        (ds_dir / "_datastore.yaml").write_text(
            yaml.safe_dump({"name": "my-ds", "connection_name": "prod-pg"})
        )

        with (
            patch(
                "qualytics.services.export_import.get_connection_by_name",
                return_value={"id": 1},
            ),
            patch(
                "qualytics.services.export_import.get_datastore_by_name",
                return_value={"id": 10, "name": "my-ds"},
            ),
        ):
            result = _import_datastore(mock_client, ds_dir, dry_run=True)

        assert result["updated"] == 1
        assert result["datastore_id"] == 10

    def test_missing_datastore_file(self, mock_client, tmp_path):
        ds_dir = tmp_path / "my_ds"
        ds_dir.mkdir()
        result = _import_datastore(mock_client, ds_dir)
        assert result["created"] == 0
        assert result["datastore_id"] is None


# ── Import containers ────────────────────────────────────────────────────


class TestImportContainers:
    def test_creates_computed_container(self, mock_client, tmp_path):
        ds_dir = tmp_path / "my_ds"
        containers_dir = ds_dir / "containers" / "filtered_orders"
        containers_dir.mkdir(parents=True)
        (containers_dir / "_container.yaml").write_text(
            yaml.safe_dump(
                {
                    "name": "filtered_orders",
                    "container_type": "computed_table",
                    "query": "SELECT * FROM orders",
                    "datastore_name": "my-ds",
                }
            )
        )

        with (
            patch(
                "qualytics.services.export_import.get_container_by_name",
                return_value=None,
            ),
            patch(
                "qualytics.services.export_import.create_container",
                return_value={"id": 100},
            ) as mock_create,
        ):
            result = _import_containers(mock_client, ds_dir, 10)

        assert result["created"] == 1
        mock_create.assert_called_once()

    def test_updates_existing_container(self, mock_client, tmp_path):
        ds_dir = tmp_path / "my_ds"
        containers_dir = ds_dir / "containers" / "filtered_orders"
        containers_dir.mkdir(parents=True)
        (containers_dir / "_container.yaml").write_text(
            yaml.safe_dump(
                {
                    "name": "filtered_orders",
                    "container_type": "computed_table",
                    "query": "SELECT * FROM orders",
                    "datastore_name": "my-ds",
                }
            )
        )

        with (
            patch(
                "qualytics.services.export_import.get_container_by_name",
                return_value={"id": 100, "name": "filtered_orders"},
            ),
            patch(
                "qualytics.services.export_import.update_container",
            ) as mock_update,
        ):
            result = _import_containers(mock_client, ds_dir, 10)

        assert result["updated"] == 1
        mock_update.assert_called_once()

    def test_skips_non_computed(self, mock_client, tmp_path):
        ds_dir = tmp_path / "my_ds"
        containers_dir = ds_dir / "containers" / "raw_table"
        containers_dir.mkdir(parents=True)
        (containers_dir / "_container.yaml").write_text(
            yaml.safe_dump(
                {
                    "name": "raw_table",
                    "container_type": "table",
                    "datastore_name": "my-ds",
                }
            )
        )

        result = _import_containers(mock_client, ds_dir, 10)
        assert result["created"] == 0
        assert result["updated"] == 0

    def test_dry_run(self, mock_client, tmp_path):
        ds_dir = tmp_path / "my_ds"
        containers_dir = ds_dir / "containers" / "filtered_orders"
        containers_dir.mkdir(parents=True)
        (containers_dir / "_container.yaml").write_text(
            yaml.safe_dump(
                {
                    "name": "filtered_orders",
                    "container_type": "computed_table",
                    "query": "SELECT * FROM orders",
                    "datastore_name": "my-ds",
                }
            )
        )

        with patch(
            "qualytics.services.export_import.get_container_by_name",
            return_value=None,
        ):
            result = _import_containers(mock_client, ds_dir, 10, dry_run=True)

        assert result["created"] == 1

    def test_empty_containers_dir(self, mock_client, tmp_path):
        ds_dir = tmp_path / "my_ds"
        result = _import_containers(mock_client, ds_dir, 10)
        assert result == {"created": 0, "updated": 0, "failed": 0, "errors": []}


# ── Export orchestrator ──────────────────────────────────────────────────


class TestExportConfig:
    def test_full_export(self, mock_client, tmp_path):
        mock_ds = {
            "id": 10,
            "name": "prod-warehouse",
            "connection": {"id": 1, "name": "prod-pg", "type": "postgresql"},
            "enrichment_datastore": None,
        }

        with (
            patch(
                "qualytics.services.export_import.get_datastore",
                return_value=mock_ds,
            ),
            patch(
                "qualytics.services.export_import.list_all_containers",
                return_value=[
                    {
                        "id": 100,
                        "name": "computed_orders",
                        "container_type": "computed_table",
                        "query": "SELECT 1",
                    }
                ],
            ),
            patch(
                "qualytics.services.export_import.get_container",
                return_value={
                    "id": 100,
                    "name": "computed_orders",
                    "computed_fields": [],
                },
            ),
            patch(
                "qualytics.services.export_import.list_all_quality_checks",
                return_value=[],
            ),
        ):
            result = export_config(mock_client, [10], str(tmp_path))

        assert result["connections"] == 1
        assert result["datastores"] == 1
        assert result["containers"] == 1
        assert result["computed_fields"] == 0
        assert result["checks"] == 0

        # Verify files exist
        assert (tmp_path / "connections" / "prod_pg.yaml").exists()
        assert (tmp_path / "datastores" / "prod_warehouse" / "_datastore.yaml").exists()
        assert (
            tmp_path
            / "datastores"
            / "prod_warehouse"
            / "containers"
            / "computed_orders"
            / "_container.yaml"
        ).exists()

    def test_export_with_include_filter(self, mock_client, tmp_path):
        mock_ds = {
            "id": 10,
            "name": "test-ds",
            "connection": {"id": 1, "name": "conn", "type": "pg"},
        }

        with patch(
            "qualytics.services.export_import.get_datastore",
            return_value=mock_ds,
        ):
            result = export_config(
                mock_client, [10], str(tmp_path), include={"connections"}
            )

        assert result["connections"] == 1
        assert result["datastores"] == 0
        assert result["containers"] == 0
        assert result["checks"] == 0

    def test_deduplicates_connections(self, mock_client, tmp_path):
        """Same connection referenced by two datastores is only exported once."""
        mock_ds = {
            "id": 10,
            "name": "ds-a",
            "connection": {"id": 1, "name": "shared-conn", "type": "pg"},
        }
        mock_ds2 = {
            "id": 20,
            "name": "ds-b",
            "connection": {"id": 1, "name": "shared-conn", "type": "pg"},
        }

        with (
            patch(
                "qualytics.services.export_import.get_datastore",
                side_effect=[mock_ds, mock_ds2],
            ),
            patch(
                "qualytics.services.export_import.list_all_containers",
                return_value=[],
            ),
            patch(
                "qualytics.services.export_import.list_all_quality_checks",
                return_value=[],
            ),
        ):
            result = export_config(mock_client, [10, 20], str(tmp_path))

        assert result["connections"] == 1

    def test_skips_non_computed_containers(self, mock_client, tmp_path):
        mock_ds = {
            "id": 10,
            "name": "test-ds",
            "connection": {"id": 1, "name": "conn", "type": "pg"},
        }

        with (
            patch(
                "qualytics.services.export_import.get_datastore",
                return_value=mock_ds,
            ),
            patch(
                "qualytics.services.export_import.list_all_containers",
                return_value=[
                    {"id": 100, "name": "raw_table", "container_type": "table"},
                    {
                        "id": 101,
                        "name": "computed_view",
                        "container_type": "computed_table",
                        "query": "SELECT 1",
                    },
                ],
            ),
            patch(
                "qualytics.services.export_import.get_container",
                return_value={"id": 100, "computed_fields": []},
            ),
            patch(
                "qualytics.services.export_import.list_all_quality_checks",
                return_value=[],
            ),
        ):
            result = export_config(mock_client, [10], str(tmp_path))

        assert result["containers"] == 1


# ── Computed fields ──────────────────────────────────────────────────────


class TestStripComputedFieldForExport:
    def test_strips_internal_fields(self):
        cf = {
            "id": 42,
            "name": "cleaned_company",
            "container_id": 100,
            "transformation_type": "cleanedEntityName",
            "source_fields": ["company_name"],
            "properties": {"drop_from_suffix": True},
            "additional_metadata": None,
            "last_editor_id": 6,
            "last_editor": {"id": 6, "name": "admin"},
        }
        result = strip_computed_field_for_export(cf)
        assert "id" not in result
        assert "container_id" not in result
        assert "last_editor_id" not in result
        assert "last_editor" not in result

    def test_normalizes_transformation_key(self):
        cf = {
            "id": 1,
            "name": "cast_field",
            "container_id": 100,
            "transformation_type": "cast",
            "source_fields": ["amount"],
            "properties": {"target_type": "integer"},
        }
        result = strip_computed_field_for_export(cf)
        assert result["transformation"] == "cast"
        assert "transformation_type" not in result

    def test_keeps_portable_fields(self):
        cf = {
            "id": 1,
            "name": "full_name",
            "container_id": 100,
            "transformation_type": "customExpression",
            "source_fields": None,
            "properties": {"column_expression": "CONCAT(first, ' ', last)"},
            "additional_metadata": {"note": "user-defined"},
        }
        result = strip_computed_field_for_export(cf)
        assert result["name"] == "full_name"
        assert result["transformation"] == "customExpression"
        assert result["source_fields"] is None
        assert result["properties"]["column_expression"] == "CONCAT(first, ' ', last)"
        assert result["additional_metadata"]["note"] == "user-defined"


class TestExportComputedFields:
    def test_exports_computed_fields_from_container(self, mock_client, tmp_path):
        mock_ds = {
            "id": 10,
            "name": "test-ds",
            "connection": {"id": 1, "name": "conn", "type": "pg"},
        }
        mock_container_detail = {
            "id": 100,
            "name": "accounts",
            "container_type": "table",
            "computed_fields": [
                {
                    "id": 1,
                    "name": "cleaned_name",
                    "container_id": 100,
                    "transformation_type": "cleanedEntityName",
                    "source_fields": ["company_name"],
                    "properties": {"drop_from_suffix": True},
                    "last_editor_id": 6,
                }
            ],
        }

        with (
            patch(
                "qualytics.services.export_import.get_datastore",
                return_value=mock_ds,
            ),
            patch(
                "qualytics.services.export_import.list_all_containers",
                return_value=[
                    {"id": 100, "name": "accounts", "container_type": "table"}
                ],
            ),
            patch(
                "qualytics.services.export_import.get_container",
                return_value=mock_container_detail,
            ),
            patch(
                "qualytics.services.export_import.list_all_quality_checks",
                return_value=[],
            ),
        ):
            result = export_config(mock_client, [10], str(tmp_path))

        assert result["computed_fields"] == 1
        cf_path = (
            tmp_path
            / "datastores"
            / "test_ds"
            / "containers"
            / "accounts"
            / "computed_fields"
            / "cleaned_name.yaml"
        )
        assert cf_path.exists()
        data = yaml.safe_load(cf_path.read_text())
        assert data["name"] == "cleaned_name"
        assert data["transformation"] == "cleanedEntityName"
        assert "id" not in data
        assert "container_id" not in data

    def test_skips_containers_without_computed_fields(self, mock_client, tmp_path):
        mock_ds = {
            "id": 10,
            "name": "test-ds",
            "connection": {"id": 1, "name": "conn", "type": "pg"},
        }

        with (
            patch(
                "qualytics.services.export_import.get_datastore",
                return_value=mock_ds,
            ),
            patch(
                "qualytics.services.export_import.list_all_containers",
                return_value=[{"id": 100, "name": "orders", "container_type": "table"}],
            ),
            patch(
                "qualytics.services.export_import.get_container",
                return_value={"id": 100, "name": "orders", "computed_fields": []},
            ),
            patch(
                "qualytics.services.export_import.list_all_quality_checks",
                return_value=[],
            ),
        ):
            result = export_config(mock_client, [10], str(tmp_path))

        assert result["computed_fields"] == 0


class TestImportComputedFields:
    def test_creates_computed_fields(self, mock_client, tmp_path):
        # Set up directory structure
        container_dir = tmp_path / "containers" / "accounts"
        cf_dir = container_dir / "computed_fields"
        cf_dir.mkdir(parents=True)
        (container_dir / "_container.yaml").write_text(
            yaml.safe_dump({"name": "accounts", "container_type": "table"})
        )
        (cf_dir / "cleaned_name.yaml").write_text(
            yaml.safe_dump(
                {
                    "name": "cleaned_name",
                    "transformation": "cleanedEntityName",
                    "source_fields": ["company_name"],
                    "properties": {"drop_from_suffix": True},
                }
            )
        )

        with (
            patch(
                "qualytics.services.export_import.get_container_by_name",
                return_value={"id": 100, "name": "accounts"},
            ),
            patch(
                "qualytics.services.export_import.get_container",
                return_value={"id": 100, "computed_fields": []},
            ),
            patch(
                "qualytics.services.export_import.create_computed_field",
                return_value={"id": 1, "name": "cleaned_name"},
            ) as mock_create,
        ):
            result = _import_computed_fields(mock_client, tmp_path, datastore_id=10)

        assert result["created"] == 1
        assert result["updated"] == 0
        mock_create.assert_called_once()
        payload = mock_create.call_args[0][1]
        assert payload["name"] == "cleaned_name"
        assert payload["container_id"] == 100

    def test_updates_existing_computed_fields(self, mock_client, tmp_path):
        container_dir = tmp_path / "containers" / "accounts"
        cf_dir = container_dir / "computed_fields"
        cf_dir.mkdir(parents=True)
        (container_dir / "_container.yaml").write_text(
            yaml.safe_dump({"name": "accounts", "container_type": "table"})
        )
        (cf_dir / "cleaned_name.yaml").write_text(
            yaml.safe_dump(
                {
                    "name": "cleaned_name",
                    "transformation": "cleanedEntityName",
                    "source_fields": ["company_name"],
                    "properties": {"drop_from_suffix": True},
                }
            )
        )

        with (
            patch(
                "qualytics.services.export_import.get_container_by_name",
                return_value={"id": 100, "name": "accounts"},
            ),
            patch(
                "qualytics.services.export_import.get_container",
                return_value={
                    "id": 100,
                    "computed_fields": [{"id": 42, "name": "cleaned_name"}],
                },
            ),
            patch(
                "qualytics.services.export_import.update_computed_field",
                return_value={"id": 42, "name": "cleaned_name"},
            ) as mock_update,
        ):
            result = _import_computed_fields(mock_client, tmp_path, datastore_id=10)

        assert result["updated"] == 1
        assert result["created"] == 0
        mock_update.assert_called_once_with(mock_client, 42, ANY)

    def test_dry_run(self, mock_client, tmp_path):
        container_dir = tmp_path / "containers" / "accounts"
        cf_dir = container_dir / "computed_fields"
        cf_dir.mkdir(parents=True)
        (container_dir / "_container.yaml").write_text(
            yaml.safe_dump({"name": "accounts", "container_type": "table"})
        )
        (cf_dir / "cleaned_name.yaml").write_text(
            yaml.safe_dump({"name": "cleaned_name", "transformation": "cast"})
        )

        with (
            patch(
                "qualytics.services.export_import.get_container_by_name",
                return_value={"id": 100, "name": "accounts"},
            ),
            patch(
                "qualytics.services.export_import.get_container",
                return_value={"id": 100, "computed_fields": []},
            ),
        ):
            result = _import_computed_fields(
                mock_client, tmp_path, datastore_id=10, dry_run=True
            )

        assert result["created"] == 1

    def test_missing_container_errors(self, mock_client, tmp_path):
        container_dir = tmp_path / "containers" / "missing"
        cf_dir = container_dir / "computed_fields"
        cf_dir.mkdir(parents=True)
        (container_dir / "_container.yaml").write_text(
            yaml.safe_dump({"name": "missing_container", "container_type": "table"})
        )
        (cf_dir / "some_field.yaml").write_text(
            yaml.safe_dump({"name": "some_field", "transformation": "cast"})
        )

        with patch(
            "qualytics.services.export_import.get_container_by_name",
            return_value=None,
        ):
            result = _import_computed_fields(mock_client, tmp_path, datastore_id=10)

        assert result["failed"] == 1
        assert "not found" in result["errors"][0]

    def test_no_computed_fields_dir(self, mock_client, tmp_path):
        container_dir = tmp_path / "containers" / "accounts"
        container_dir.mkdir(parents=True)
        (container_dir / "_container.yaml").write_text(
            yaml.safe_dump({"name": "accounts"})
        )

        result = _import_computed_fields(mock_client, tmp_path, datastore_id=10)
        assert result["created"] == 0
        assert result["updated"] == 0


# ── Import orchestrator ──────────────────────────────────────────────────


class TestImportConfig:
    def test_full_import(self, mock_client, tmp_path):
        # Set up directory structure
        conn_dir = tmp_path / "connections"
        conn_dir.mkdir()
        (conn_dir / "prod_pg.yaml").write_text(
            yaml.safe_dump({"name": "prod-pg", "type": "postgresql"})
        )

        ds_dir = tmp_path / "datastores" / "prod_warehouse"
        ds_dir.mkdir(parents=True)
        (ds_dir / "_datastore.yaml").write_text(
            yaml.safe_dump({"name": "prod-warehouse", "connection_name": "prod-pg"})
        )

        with (
            patch(
                "qualytics.services.export_import.get_connection_by_name",
                side_effect=[None, {"id": 1}],
            ),
            patch(
                "qualytics.services.export_import.create_connection",
                return_value={"id": 1},
            ),
            patch(
                "qualytics.services.export_import.get_datastore_by_name",
                return_value=None,
            ),
            patch(
                "qualytics.services.export_import.create_datastore",
                return_value={"id": 10},
            ),
        ):
            result = import_config(mock_client, str(tmp_path))

        assert result["connections"]["created"] == 1
        assert result["datastores"]["created"] == 1

    def test_import_with_include_filter(self, mock_client, tmp_path):
        conn_dir = tmp_path / "connections"
        conn_dir.mkdir()
        (conn_dir / "conn.yaml").write_text(
            yaml.safe_dump({"name": "conn", "type": "pg"})
        )

        ds_dir = tmp_path / "datastores" / "ds"
        ds_dir.mkdir(parents=True)
        (ds_dir / "_datastore.yaml").write_text(
            yaml.safe_dump({"name": "ds", "connection_name": "conn"})
        )

        with (
            patch(
                "qualytics.services.export_import.get_connection_by_name",
                return_value=None,
            ),
            patch(
                "qualytics.services.export_import.create_connection",
                return_value={"id": 1},
            ),
        ):
            result = import_config(mock_client, str(tmp_path), include={"connections"})

        assert result["connections"]["created"] == 1
        assert result["datastores"]["created"] == 0

    def test_import_nonexistent_datastores_dir(self, mock_client, tmp_path):
        """No datastores/ directory is fine — just returns zeros."""
        conn_dir = tmp_path / "connections"
        conn_dir.mkdir()
        (conn_dir / "conn.yaml").write_text(
            yaml.safe_dump({"name": "conn", "type": "pg"})
        )

        with (
            patch(
                "qualytics.services.export_import.get_connection_by_name",
                return_value=None,
            ),
            patch(
                "qualytics.services.export_import.create_connection",
                return_value={"id": 1},
            ),
        ):
            result = import_config(mock_client, str(tmp_path))

        assert result["connections"]["created"] == 1
        assert result["datastores"]["created"] == 0


# ── CLI smoke tests ──────────────────────────────────────────────────────


class TestConfigExportCLI:
    def test_export_help(self, cli_runner):
        result = cli_runner.invoke(app, ["config", "export", "--help"])
        assert result.exit_code == 0
        output = _strip_ansi(result.output)
        assert "--datastore-id" in output
        assert "--output" in output
        assert "--include" in output

    def test_export_requires_datastore_id(self, cli_runner):
        result = cli_runner.invoke(app, ["config", "export"])
        assert result.exit_code != 0

    def test_export_runs(self, cli_runner):
        with (
            patch("qualytics.cli.export_import.get_client") as mock_gc,
            patch(
                "qualytics.cli.export_import.export_config",
                return_value={
                    "connections": 1,
                    "datastores": 1,
                    "containers": 0,
                    "checks": 5,
                },
            ),
        ):
            mock_gc.return_value = MagicMock()
            result = cli_runner.invoke(
                app,
                [
                    "config",
                    "export",
                    "--datastore-id",
                    "1",
                    "--output",
                    "/tmp/test-export",
                ],
            )
        assert result.exit_code == 0
        assert "Export complete" in result.output


class TestConfigImportCLI:
    def test_import_help(self, cli_runner):
        result = cli_runner.invoke(app, ["config", "import", "--help"])
        assert result.exit_code == 0
        output = _strip_ansi(result.output)
        assert "--input" in output
        assert "--dry-run" in output
        assert "--include" in output

    def test_import_nonexistent_dir(self, cli_runner):
        result = cli_runner.invoke(
            app, ["config", "import", "--input", "/nonexistent/dir"]
        )
        assert result.exit_code != 0

    def test_import_runs(self, cli_runner, tmp_path):
        # Create empty but valid directory
        (tmp_path / "connections").mkdir()

        with (
            patch("qualytics.cli.export_import.get_client") as mock_gc,
            patch(
                "qualytics.cli.export_import.import_config",
                return_value={
                    "connections": {
                        "created": 1,
                        "updated": 0,
                        "failed": 0,
                        "errors": [],
                    },
                    "datastores": {
                        "created": 0,
                        "updated": 0,
                        "failed": 0,
                        "errors": [],
                    },
                    "containers": {
                        "created": 0,
                        "updated": 0,
                        "failed": 0,
                        "errors": [],
                    },
                    "computed_fields": {
                        "created": 0,
                        "updated": 0,
                        "failed": 0,
                        "errors": [],
                    },
                    "checks": {
                        "created": 0,
                        "updated": 0,
                        "failed": 0,
                        "errors": [],
                    },
                },
            ),
        ):
            mock_gc.return_value = MagicMock()
            result = cli_runner.invoke(
                app, ["config", "import", "--input", str(tmp_path)]
            )
        assert result.exit_code == 0
        assert "Import complete" in result.output

    def test_import_dry_run(self, cli_runner, tmp_path):
        (tmp_path / "connections").mkdir()

        with (
            patch("qualytics.cli.export_import.get_client") as mock_gc,
            patch(
                "qualytics.cli.export_import.import_config",
                return_value={
                    "connections": {
                        "created": 1,
                        "updated": 0,
                        "failed": 0,
                        "errors": [],
                    },
                    "datastores": {
                        "created": 0,
                        "updated": 0,
                        "failed": 0,
                        "errors": [],
                    },
                    "containers": {
                        "created": 0,
                        "updated": 0,
                        "failed": 0,
                        "errors": [],
                    },
                    "computed_fields": {
                        "created": 0,
                        "updated": 0,
                        "failed": 0,
                        "errors": [],
                    },
                    "checks": {
                        "created": 0,
                        "updated": 0,
                        "failed": 0,
                        "errors": [],
                    },
                },
            ),
        ):
            mock_gc.return_value = MagicMock()
            result = cli_runner.invoke(
                app,
                ["config", "import", "--input", str(tmp_path), "--dry-run"],
            )
        assert result.exit_code == 0
        assert "DRY RUN" in result.output

    def test_import_shows_errors(self, cli_runner, tmp_path):
        (tmp_path / "connections").mkdir()

        with (
            patch("qualytics.cli.export_import.get_client") as mock_gc,
            patch(
                "qualytics.cli.export_import.import_config",
                return_value={
                    "connections": {
                        "created": 0,
                        "updated": 0,
                        "failed": 1,
                        "errors": ["Connection 'bad' failed: 500"],
                    },
                    "datastores": {
                        "created": 0,
                        "updated": 0,
                        "failed": 0,
                        "errors": [],
                    },
                    "containers": {
                        "created": 0,
                        "updated": 0,
                        "failed": 0,
                        "errors": [],
                    },
                    "computed_fields": {
                        "created": 0,
                        "updated": 0,
                        "failed": 0,
                        "errors": [],
                    },
                    "checks": {
                        "created": 0,
                        "updated": 0,
                        "failed": 0,
                        "errors": [],
                    },
                },
            ),
        ):
            mock_gc.return_value = MagicMock()
            result = cli_runner.invoke(
                app, ["config", "import", "--input", str(tmp_path)]
            )
        assert result.exit_code == 0
        assert "error" in result.output.lower()


# ── CLI registration smoke test ──────────────────────────────────────────


class TestConfigCommandRegistered:
    def test_config_help(self, cli_runner):
        result = cli_runner.invoke(app, ["config", "--help"])
        assert result.exit_code == 0
        assert "export" in result.output.lower()
        assert "import" in result.output.lower()
