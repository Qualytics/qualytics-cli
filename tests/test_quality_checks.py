"""Tests for quality checks — API, services, and CLI."""

import yaml
from unittest.mock import MagicMock, patch

from qualytics.services.quality_checks import (
    generate_check_uid,
    check_filename,
    strip_for_export,
    export_checks_to_directory,
    load_checks_from_directory,
    import_checks_to_datastore,
    _build_create_payload,
    _build_update_payload,
    _build_uid_lookup,
    _UID_KEY,
)
from qualytics.api.quality_checks import (
    list_quality_checks,
    get_quality_check,
    create_quality_check,
    update_quality_check,
    delete_quality_check,
    bulk_delete_quality_checks,
    list_all_quality_checks,
)
from qualytics.qualytics import app


# ── Shared fixtures ──────────────────────────────────────────────────────


def _mock_client():
    """Return a MagicMock configured as a QualyticsClient."""
    return MagicMock()


def _make_api_check(
    check_id=42,
    rule_type="notNull",
    container_name="orders",
    field_names=None,
    tag_names=None,
    **overrides,
):
    """Build a realistic API-response check dict."""
    if field_names is None:
        field_names = ["order_id"]
    if tag_names is None:
        tag_names = ["data-quality"]
    check = {
        "id": check_id,
        "rule_type": rule_type,
        "description": f"{rule_type} check on {container_name}",
        "container": {"id": 10, "name": container_name},
        "fields": [{"id": i, "name": n} for i, n in enumerate(field_names, 1)],
        "coverage": 1.0,
        "filter": None,
        "properties": {},
        "global_tags": [{"id": i, "name": n} for i, n in enumerate(tag_names, 1)],
        "additional_metadata": None,
        "status": "Active",
        "created": "2024-01-01T00:00:00Z",
        "anomaly_count": 5,
        "is_new": False,
    }
    check.update(overrides)
    return check


def _make_portable_check(
    rule_type="notNull", container="orders", fields=None, uid=None, **overrides
):
    """Build a portable (exported) check dict."""
    if fields is None:
        fields = ["order_id"]
    if uid is None:
        uid = generate_check_uid(container, rule_type, fields)
    check = {
        "rule_type": rule_type,
        "description": f"{rule_type} on {container}",
        "container": container,
        "fields": fields,
        "coverage": 1.0,
        "filter": None,
        "properties": {},
        "tags": ["data-quality"],
        "status": "Active",
        "additional_metadata": {_UID_KEY: uid},
    }
    check.update(overrides)
    return check


# ══════════════════════════════════════════════════════════════════════════
# 1. SERVICE LAYER — UID, filenames, stripping, payload builders (existing)
# ══════════════════════════════════════════════════════════════════════════


# ── UID generation ────────────────────────────────────────────────────────


class TestGenerateCheckUID:
    def test_basic_uid(self):
        uid = generate_check_uid("orders", "notNull", ["order_id"])
        assert uid == "orders__notnull__order_id"

    def test_multi_field_sorted(self):
        uid = generate_check_uid("users", "unique", ["email", "age", "name"])
        assert uid == "users__unique__age_email_name"

    def test_no_fields(self):
        uid = generate_check_uid("products", "volumetric", [])
        assert uid == "products__volumetric"

    def test_special_chars_slugified(self):
        uid = generate_check_uid("My Table!", "notNull", ["field-1"])
        assert uid == "my_table__notnull__field_1"


# ── Filename generation ──────────────────────────────────────────────────


class TestCheckFilename:
    def test_basic_filename(self):
        fname = check_filename("notNull", ["email"])
        assert fname == "notnull__email.yaml"

    def test_multi_field(self):
        fname = check_filename("unique", ["id", "name"])
        assert fname == "unique__id_name.yaml"

    def test_no_fields(self):
        fname = check_filename("volumetric", [])
        assert fname == "volumetric.yaml"


# ── strip_for_export ─────────────────────────────────────────────────────


class TestStripForExport:
    def test_strips_id_and_timestamps(self):
        result = strip_for_export(_make_api_check())
        assert "id" not in result
        assert "created" not in result
        assert "anomaly_count" not in result

    def test_preserves_portable_fields(self):
        result = strip_for_export(_make_api_check())
        assert result["rule_type"] == "notNull"
        assert result["container"] == "orders"
        assert result["fields"] == ["order_id"]
        assert result["tags"] == ["data-quality"]
        assert result["status"] == "Active"

    def test_injects_uid(self):
        result = strip_for_export(_make_api_check())
        assert _UID_KEY in result["additional_metadata"]
        assert result["additional_metadata"][_UID_KEY] == "orders__notnull__order_id"

    def test_preserves_user_metadata(self):
        result = strip_for_export(
            _make_api_check(
                additional_metadata={"owner": "data-team", "jira": "DQ-123"}
            )
        )
        assert result["additional_metadata"]["owner"] == "data-team"
        assert result["additional_metadata"]["jira"] == "DQ-123"

    def test_strips_internal_tracking_metadata(self):
        result = strip_for_export(
            _make_api_check(
                additional_metadata={
                    "from quality check id": "99",
                    "main datastore id": "1",
                    "owner": "keep-me",
                }
            )
        )
        assert "from quality check id" not in result["additional_metadata"]
        assert "main datastore id" not in result["additional_metadata"]
        assert result["additional_metadata"]["owner"] == "keep-me"

    def test_no_container_uses_empty_string(self):
        check = _make_api_check(container=None)
        result = strip_for_export(check)
        assert result["container"] == ""

    def test_no_fields_yields_empty_list(self):
        check = _make_api_check(fields=None)
        result = strip_for_export(check)
        assert result["fields"] == []

    def test_no_tags_yields_empty_list(self):
        check = _make_api_check(global_tags=None)
        result = strip_for_export(check)
        assert result["tags"] == []


# ── Directory export/import ──────────────────────────────────────────────


class TestDirectoryExport:
    def _make_checks(self):
        return [
            _make_api_check(1, "notNull", "users", ["email"], []),
            _make_api_check(
                2,
                "between",
                "users",
                ["age"],
                ["validation"],
                properties={"min": 0, "max": 150},
            ),
            _make_api_check(3, "notNull", "orders", ["order_id"], [], status="Draft"),
        ]

    def test_export_creates_directory_structure(self, tmp_path):
        result = export_checks_to_directory(self._make_checks(), str(tmp_path))
        assert result["exported"] == 3
        assert result["containers"] == 2
        assert (tmp_path / "users").is_dir()
        assert (tmp_path / "orders").is_dir()

    def test_export_creates_one_file_per_check(self, tmp_path):
        export_checks_to_directory(self._make_checks(), str(tmp_path))
        user_files = list((tmp_path / "users").glob("*.yaml"))
        order_files = list((tmp_path / "orders").glob("*.yaml"))
        assert len(user_files) == 2
        assert len(order_files) == 1

    def test_exported_yaml_is_valid(self, tmp_path):
        export_checks_to_directory(self._make_checks(), str(tmp_path))
        for yaml_file in tmp_path.rglob("*.yaml"):
            with open(yaml_file) as f:
                data = yaml.safe_load(f)
            assert "rule_type" in data
            assert "container" in data
            assert isinstance(data["container"], str)

    def test_round_trip(self, tmp_path):
        checks = self._make_checks()
        export_checks_to_directory(checks, str(tmp_path))
        loaded = load_checks_from_directory(str(tmp_path))
        assert len(loaded) == 3
        for check in loaded:
            assert "rule_type" in check
            assert "container" in check
            assert "_source_file" in check

    def test_duplicate_filenames_deduplicated(self, tmp_path):
        """Two checks with the same rule_type+fields in same container get unique names."""
        checks = [
            _make_api_check(1, "notNull", "users", ["email"], []),
            _make_api_check(
                2,
                "notNull",
                "users",
                ["email"],
                [],
                description="Second check same fields",
            ),
        ]
        result = export_checks_to_directory(checks, str(tmp_path))
        assert result["exported"] == 2
        files = list((tmp_path / "users").glob("*.yaml"))
        assert len(files) == 2
        names = sorted(f.name for f in files)
        assert names == ["notnull__email.yaml", "notnull__email_2.yaml"]

    def test_triple_duplicate_filenames(self, tmp_path):
        """Three identical rule_type+fields produce _2 and _3 suffixes."""
        checks = [
            _make_api_check(i, "notNull", "users", ["email"], []) for i in range(1, 4)
        ]
        result = export_checks_to_directory(checks, str(tmp_path))
        assert result["exported"] == 3
        names = sorted(f.name for f in (tmp_path / "users").glob("*.yaml"))
        assert names == [
            "notnull__email.yaml",
            "notnull__email_2.yaml",
            "notnull__email_3.yaml",
        ]

    def test_no_container_uses_fallback_dir(self, tmp_path):
        """Check with no container goes into _no_container directory."""
        check = _make_api_check(1, "notNull", "orders", ["id"], [], container=None)
        result = export_checks_to_directory([check], str(tmp_path))
        assert result["exported"] == 1
        assert (tmp_path / "_no_container").is_dir()


# ── Payload builders ─────────────────────────────────────────────────────


class TestPayloadBuilders:
    def test_build_create_payload(self):
        check = _make_portable_check()
        payload = _build_create_payload(check, container_id=42)
        assert payload["container_id"] == 42
        assert payload["rule"] == "notNull"
        assert payload["description"] == "notNull on orders"
        assert payload["fields"] == ["order_id"]
        assert payload["tags"] == ["data-quality"]

    def test_build_update_payload(self):
        check = {
            "description": "Updated description",
            "fields": ["email"],
            "coverage": 0.5,
            "filter": "status = 'active'",
            "properties": {"pattern": ".*@.*"},
            "tags": ["updated"],
            "status": "Draft",
            "additional_metadata": {},
        }
        payload = _build_update_payload(check)
        assert payload["description"] == "Updated description"
        assert payload["coverage"] == 0.5
        assert "container_id" not in payload
        assert "rule" not in payload

    def test_create_payload_defaults_missing_fields(self):
        check = {"rule_type": "notNull"}
        payload = _build_create_payload(check, container_id=1)
        assert payload["description"] == ""
        assert payload["fields"] == []
        assert payload["properties"] == {}
        assert payload["tags"] == []
        assert payload["status"] == "Active"


# ── Load from directory ──────────────────────────────────────────────────


class TestLoadChecksFromDirectory:
    def test_ignores_non_check_files(self, tmp_path):
        (tmp_path / "readme.yaml").write_text("title: not a check\n")
        (tmp_path / "check.yaml").write_text(
            "rule_type: notNull\ncontainer: orders\nfields: [order_id]\n"
        )
        loaded = load_checks_from_directory(str(tmp_path))
        assert len(loaded) == 1
        assert loaded[0]["rule_type"] == "notNull"

    def test_loads_nested_directories(self, tmp_path):
        container_dir = tmp_path / "orders"
        container_dir.mkdir()
        (container_dir / "check1.yaml").write_text(
            "rule_type: notNull\ncontainer: orders\nfields: [id]\n"
        )
        (container_dir / "check2.yaml").write_text(
            "rule_type: between\ncontainer: orders\nfields: [amount]\n"
            "properties:\n  min: 0\n  max: 100\n"
        )
        loaded = load_checks_from_directory(str(tmp_path))
        assert len(loaded) == 2

    def test_empty_directory(self, tmp_path):
        loaded = load_checks_from_directory(str(tmp_path))
        assert loaded == []

    def test_source_file_relative_to_base(self, tmp_path):
        container_dir = tmp_path / "orders"
        container_dir.mkdir()
        (container_dir / "check.yaml").write_text(
            "rule_type: notNull\ncontainer: orders\nfields: [id]\n"
        )
        loaded = load_checks_from_directory(str(tmp_path))
        assert loaded[0]["_source_file"] == "orders/check.yaml"


# ══════════════════════════════════════════════════════════════════════════
# 2. API LAYER — Mock HTTP responses, verify endpoints and params
# ══════════════════════════════════════════════════════════════════════════


class TestListQualityChecks:
    def test_basic_call(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {
            "items": [{"id": 1}],
            "total": 1,
            "page": 1,
            "size": 100,
        }
        result = list_quality_checks(client, datastore_id=42)
        client.get.assert_called_once_with(
            "quality-checks",
            params={"datastore": 42, "page": 1, "size": 100},
        )
        assert result["items"] == [{"id": 1}]

    def test_with_filters(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {"items": [], "total": 0}
        list_quality_checks(
            client,
            42,
            containers=[1, 2],
            tags=["prod"],
            status="Active",
            archived="only",
        )
        expected_params = {
            "datastore": 42,
            "page": 1,
            "size": 100,
            "status": "Active",
            "archived": "only",
            "tag": ["prod"],
            "container": [1, 2],
        }
        client.get.assert_called_once_with("quality-checks", params=expected_params)

    def test_none_filters_excluded(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {"items": [], "total": 0}
        list_quality_checks(client, 42)
        params = client.get.call_args.kwargs["params"]
        assert "status" not in params
        assert "tag" not in params
        assert "container" not in params
        assert "archived" not in params


class TestGetQualityCheck:
    def test_calls_correct_endpoint(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {"id": 99, "rule_type": "notNull"}
        result = get_quality_check(client, 99)
        client.get.assert_called_once_with("quality-checks/99")
        assert result["id"] == 99


class TestCreateQualityCheck:
    def test_posts_payload(self):
        client = _mock_client()
        client.post.return_value.json.return_value = {"id": 100, "rule_type": "notNull"}
        payload = {"container_id": 1, "rule": "notNull", "fields": ["order_id"]}
        result = create_quality_check(client, payload)
        client.post.assert_called_once_with("quality-checks", json=payload)
        assert result["id"] == 100


class TestUpdateQualityCheck:
    def test_puts_payload(self):
        client = _mock_client()
        client.put.return_value.json.return_value = {"id": 42, "description": "updated"}
        payload = {"description": "updated"}
        result = update_quality_check(client, 42, payload)
        client.put.assert_called_once_with("quality-checks/42", json=payload)
        assert result["description"] == "updated"


class TestDeleteQualityCheck:
    def test_default_params(self):
        client = _mock_client()
        delete_quality_check(client, 42)
        client.delete.assert_called_once_with(
            "quality-checks/42",
            params={
                "archive": "true",
                "status": "Discarded",
                "delete_anomalies": "true",
            },
        )

    def test_hard_delete(self):
        client = _mock_client()
        delete_quality_check(client, 42, archive=False)
        params = client.delete.call_args.kwargs["params"]
        assert params["archive"] == "false"


class TestBulkDeleteQualityChecks:
    def test_sends_items_as_json(self):
        client = _mock_client()
        items = [{"id": 1, "archive": True}, {"id": 2, "archive": False}]
        bulk_delete_quality_checks(client, items)
        client.delete.assert_called_once_with("quality-checks", json=items)


class TestListAllQualityChecks:
    def test_single_page(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {
            "items": [{"id": 1}, {"id": 2}],
            "total": 2,
            "page": 1,
            "size": 100,
        }
        result = list_all_quality_checks(client, 42)
        assert len(result) == 2
        assert client.get.call_count == 1

    def test_multi_page(self):
        client = _mock_client()
        page1 = {
            "items": [{"id": i} for i in range(100)],
            "total": 150,
            "page": 1,
            "size": 100,
        }
        page2 = {
            "items": [{"id": i} for i in range(100, 150)],
            "total": 150,
            "page": 2,
            "size": 100,
        }
        client.get.return_value.json.side_effect = [page1, page2]
        result = list_all_quality_checks(client, 42)
        assert len(result) == 150
        assert client.get.call_count == 2

    def test_empty_datastore(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {
            "items": [],
            "total": 0,
            "page": 1,
            "size": 100,
        }
        result = list_all_quality_checks(client, 42)
        assert result == []

    def test_passes_filters_to_each_page(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {
            "items": [{"id": 1}],
            "total": 1,
            "page": 1,
            "size": 100,
        }
        list_all_quality_checks(client, 42, tags=["prod"], status="Active")
        params = client.get.call_args.kwargs["params"]
        assert params["tag"] == ["prod"]
        assert params["status"] == "Active"


# ══════════════════════════════════════════════════════════════════════════
# 3. SERVICE LAYER — Import upsert, UID lookup, dry-run
# ══════════════════════════════════════════════════════════════════════════


class TestBuildUidLookup:
    @patch("qualytics.services.quality_checks.list_all_quality_checks")
    def test_builds_lookup(self, mock_list):
        client = _mock_client()
        mock_list.return_value = [
            {"id": 1, "additional_metadata": {_UID_KEY: "orders__notnull__id"}},
            {"id": 2, "additional_metadata": {_UID_KEY: "users__unique__email"}},
            {"id": 3, "additional_metadata": None},
            {"id": 4, "additional_metadata": {"other": "key"}},
        ]
        lookup = _build_uid_lookup(client, 42)
        assert lookup == {
            "orders__notnull__id": 1,
            "users__unique__email": 2,
        }

    @patch("qualytics.services.quality_checks.list_all_quality_checks")
    def test_empty_datastore(self, mock_list):
        client = _mock_client()
        mock_list.return_value = []
        lookup = _build_uid_lookup(client, 42)
        assert lookup == {}


class TestImportChecksToDatastore:
    def _setup_mocks(self):
        client = _mock_client()
        table_ids = {"orders": 100, "users": 200}
        uid_lookup = {}
        return client, table_ids, uid_lookup

    @patch("qualytics.services.quality_checks.create_quality_check")
    @patch("qualytics.services.quality_checks.list_all_quality_checks")
    @patch("qualytics.services.quality_checks.get_table_ids")
    def test_creates_new_checks(self, mock_tables, mock_list, mock_create):
        client = _mock_client()
        mock_tables.return_value = {"orders": 100}
        mock_list.return_value = []  # No existing checks
        mock_create.return_value = {"id": 999}

        checks = [_make_portable_check("notNull", "orders", ["order_id"])]
        result = import_checks_to_datastore(client, 42, checks)

        assert result["created"] == 1
        assert result["updated"] == 0
        assert result["failed"] == 0
        mock_create.assert_called_once()

    @patch("qualytics.services.quality_checks.update_quality_check")
    @patch("qualytics.services.quality_checks.list_all_quality_checks")
    @patch("qualytics.services.quality_checks.get_table_ids")
    def test_updates_existing_checks(self, mock_tables, mock_list, mock_update):
        client = _mock_client()
        mock_tables.return_value = {"orders": 100}
        uid = generate_check_uid("orders", "notNull", ["order_id"])
        mock_list.return_value = [
            {"id": 50, "additional_metadata": {_UID_KEY: uid}},
        ]
        mock_update.return_value = {"id": 50}

        checks = [_make_portable_check("notNull", "orders", ["order_id"])]
        result = import_checks_to_datastore(client, 42, checks)

        assert result["created"] == 0
        assert result["updated"] == 1
        assert result["failed"] == 0
        mock_update.assert_called_once()

    @patch("qualytics.services.quality_checks.list_all_quality_checks")
    @patch("qualytics.services.quality_checks.get_table_ids")
    def test_dry_run_creates_nothing(self, mock_tables, mock_list):
        client = _mock_client()
        mock_tables.return_value = {"orders": 100}
        mock_list.return_value = []

        checks = [_make_portable_check("notNull", "orders", ["order_id"])]
        result = import_checks_to_datastore(client, 42, checks, dry_run=True)

        assert result["created"] == 1
        assert result["updated"] == 0
        assert result["failed"] == 0
        # No API calls should be made in dry_run
        client.post.assert_not_called()
        client.put.assert_not_called()

    @patch("qualytics.services.quality_checks.list_all_quality_checks")
    @patch("qualytics.services.quality_checks.get_table_ids")
    def test_dry_run_shows_updates(self, mock_tables, mock_list):
        client = _mock_client()
        mock_tables.return_value = {"orders": 100}
        uid = generate_check_uid("orders", "notNull", ["order_id"])
        mock_list.return_value = [
            {"id": 50, "additional_metadata": {_UID_KEY: uid}},
        ]

        checks = [_make_portable_check("notNull", "orders", ["order_id"])]
        result = import_checks_to_datastore(client, 42, checks, dry_run=True)

        assert result["created"] == 0
        assert result["updated"] == 1

    @patch("qualytics.services.quality_checks.get_table_ids")
    def test_container_not_found_fails(self, mock_tables):
        client = _mock_client()
        mock_tables.return_value = {"orders": 100}  # No "products" container

        checks = [_make_portable_check("notNull", "products", ["sku"])]

        with patch(
            "qualytics.services.quality_checks.list_all_quality_checks", return_value=[]
        ):
            result = import_checks_to_datastore(client, 42, checks)

        assert result["failed"] == 1
        assert result["created"] == 0
        assert "products" in result["errors"][0]

    @patch("qualytics.services.quality_checks.get_table_ids")
    def test_table_resolution_failure(self, mock_tables):
        """When get_table_ids returns None, all checks fail."""
        client = _mock_client()
        mock_tables.return_value = None

        checks = [_make_portable_check()]
        result = import_checks_to_datastore(client, 42, checks)

        assert result["failed"] == 1
        assert result["created"] == 0
        assert "Could not resolve" in result["errors"][0]

    @patch("qualytics.services.quality_checks.create_quality_check")
    @patch("qualytics.services.quality_checks.list_all_quality_checks")
    @patch("qualytics.services.quality_checks.get_table_ids")
    def test_api_error_counted_as_failed(self, mock_tables, mock_list, mock_create):
        client = _mock_client()
        mock_tables.return_value = {"orders": 100}
        mock_list.return_value = []
        mock_create.side_effect = Exception("Server error")

        checks = [_make_portable_check("notNull", "orders", ["order_id"])]
        result = import_checks_to_datastore(client, 42, checks)

        assert result["failed"] == 1
        assert result["created"] == 0
        assert "Server error" in result["errors"][0]

    @patch("qualytics.services.quality_checks.create_quality_check")
    @patch("qualytics.services.quality_checks.list_all_quality_checks")
    @patch("qualytics.services.quality_checks.get_table_ids")
    def test_mixed_create_update_fail(self, mock_tables, mock_list, mock_create):
        """A batch with creates, updates, and failures."""
        client = _mock_client()
        mock_tables.return_value = {"orders": 100, "users": 200}
        uid = generate_check_uid("orders", "notNull", ["order_id"])
        mock_list.return_value = [
            {"id": 50, "additional_metadata": {_UID_KEY: uid}},
        ]
        mock_create.return_value = {"id": 999}

        checks = [
            _make_portable_check("notNull", "orders", ["order_id"]),  # update
            _make_portable_check("between", "users", ["age"]),  # create
            _make_portable_check("notNull", "missing_table", ["id"]),  # fail
        ]

        with patch(
            "qualytics.services.quality_checks.update_quality_check",
            return_value={"id": 50},
        ):
            result = import_checks_to_datastore(client, 42, checks)

        assert result["updated"] == 1
        assert result["created"] == 1
        assert result["failed"] == 1

    @patch("qualytics.services.quality_checks.create_quality_check")
    @patch("qualytics.services.quality_checks.list_all_quality_checks")
    @patch("qualytics.services.quality_checks.get_table_ids")
    def test_new_uid_registered_within_run(self, mock_tables, mock_list, mock_create):
        """After creating a check, its UID is registered to prevent double-create."""
        client = _mock_client()
        mock_tables.return_value = {"orders": 100}
        mock_list.return_value = []
        mock_create.return_value = {"id": 999}

        checks = [
            _make_portable_check("notNull", "orders", ["order_id"]),
            _make_portable_check("notNull", "orders", ["order_id"]),  # same UID
        ]

        with patch(
            "qualytics.services.quality_checks.update_quality_check",
            return_value={"id": 999},
        ) as mock_update:
            result = import_checks_to_datastore(client, 42, checks)

        # First should create, second should update (UID now known)
        assert result["created"] == 1
        assert result["updated"] == 1
        mock_create.assert_called_once()
        mock_update.assert_called_once()


# ══════════════════════════════════════════════════════════════════════════
# 4. CLI COMMAND TESTS — CliRunner with mocked API calls
# ══════════════════════════════════════════════════════════════════════════


class TestChecksGetCLI:
    @patch("qualytics.cli.checks.get_quality_check")
    @patch("qualytics.cli.checks.get_client")
    def test_get_outputs_check(self, mock_gc, mock_get, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_get.return_value = {"id": 42, "rule_type": "notNull"}
        result = cli_runner.invoke(app, ["checks", "get", "--id", "42"])
        assert result.exit_code == 0
        mock_get.assert_called_once()

    @patch("qualytics.cli.checks.get_quality_check")
    @patch("qualytics.cli.checks.get_client")
    def test_get_json_format(self, mock_gc, mock_get, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_get.return_value = {"id": 42, "rule_type": "notNull"}
        result = cli_runner.invoke(
            app, ["checks", "get", "--id", "42", "--format", "json"]
        )
        assert result.exit_code == 0


class TestChecksListCLI:
    @patch("qualytics.cli.checks.list_all_quality_checks")
    @patch("qualytics.cli.checks.get_client")
    def test_list_basic(self, mock_gc, mock_list, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_list.return_value = [{"id": 1}, {"id": 2}]
        result = cli_runner.invoke(app, ["checks", "list", "--datastore-id", "42"])
        assert result.exit_code == 0
        assert "Found 2 quality checks" in result.output

    @patch("qualytics.cli.checks.list_all_quality_checks")
    @patch("qualytics.cli.checks.get_client")
    def test_list_with_filters(self, mock_gc, mock_list, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_list.return_value = []
        result = cli_runner.invoke(
            app,
            [
                "checks",
                "list",
                "--datastore-id",
                "42",
                "--containers",
                "1,2",
                "--tags",
                "prod",
                "--status",
                "Active",
            ],
        )
        assert result.exit_code == 0
        mock_list.assert_called_once()
        _, kwargs = mock_list.call_args
        assert kwargs["containers"] == [1, 2]
        assert kwargs["tags"] == ["prod"]
        assert kwargs["status"] == "Active"

    @patch("qualytics.cli.checks.list_all_quality_checks")
    @patch("qualytics.cli.checks.get_client")
    def test_list_archived_status(self, mock_gc, mock_list, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_list.return_value = []
        result = cli_runner.invoke(
            app, ["checks", "list", "--datastore-id", "42", "--status", "Archived"]
        )
        assert result.exit_code == 0
        _, kwargs = mock_list.call_args
        assert kwargs["archived"] == "only"
        assert kwargs["status"] is None


class TestChecksCreateCLI:
    @patch("qualytics.cli.checks.create_quality_check")
    @patch("qualytics.cli.checks.get_table_ids")
    @patch("qualytics.cli.checks.get_client")
    def test_create_single(
        self, mock_gc, mock_tables, mock_create, cli_runner, tmp_path
    ):
        mock_gc.return_value = _mock_client()
        mock_tables.return_value = {"orders": 100}
        mock_create.return_value = {"id": 999}

        check_file = tmp_path / "check.yaml"
        check_file.write_text(
            "rule_type: notNull\ncontainer: orders\nfields: [order_id]\n"
        )

        result = cli_runner.invoke(
            app, ["checks", "create", "--datastore-id", "42", "--file", str(check_file)]
        )
        assert result.exit_code == 0
        assert "Created 1" in result.output
        mock_create.assert_called_once()

    @patch("qualytics.cli.checks.create_quality_check")
    @patch("qualytics.cli.checks.get_table_ids")
    @patch("qualytics.cli.checks.get_client")
    def test_create_bulk(self, mock_gc, mock_tables, mock_create, cli_runner, tmp_path):
        mock_gc.return_value = _mock_client()
        mock_tables.return_value = {"orders": 100, "users": 200}
        mock_create.return_value = {"id": 999}

        check_file = tmp_path / "checks.yaml"
        checks = [
            {"rule_type": "notNull", "container": "orders", "fields": ["order_id"]},
            {"rule_type": "notNull", "container": "users", "fields": ["email"]},
        ]
        check_file.write_text(yaml.dump(checks))

        result = cli_runner.invoke(
            app, ["checks", "create", "--datastore-id", "42", "--file", str(check_file)]
        )
        assert result.exit_code == 0
        assert "Created 2" in result.output
        assert mock_create.call_count == 2

    @patch("qualytics.cli.checks.get_table_ids")
    @patch("qualytics.cli.checks.get_client")
    def test_create_container_not_found(
        self, mock_gc, mock_tables, cli_runner, tmp_path
    ):
        mock_gc.return_value = _mock_client()
        mock_tables.return_value = {"orders": 100}  # No "products"

        check_file = tmp_path / "check.yaml"
        check_file.write_text(
            "rule_type: notNull\ncontainer: products\nfields: [sku]\n"
        )

        result = cli_runner.invoke(
            app, ["checks", "create", "--datastore-id", "42", "--file", str(check_file)]
        )
        assert result.exit_code == 0
        assert "failed 1" in result.output

    @patch("qualytics.cli.checks.get_table_ids")
    @patch("qualytics.cli.checks.get_client")
    def test_create_table_resolution_fails(
        self, mock_gc, mock_tables, cli_runner, tmp_path
    ):
        mock_gc.return_value = _mock_client()
        mock_tables.return_value = None

        check_file = tmp_path / "check.yaml"
        check_file.write_text("rule_type: notNull\ncontainer: orders\nfields: [id]\n")

        result = cli_runner.invoke(
            app, ["checks", "create", "--datastore-id", "42", "--file", str(check_file)]
        )
        assert result.exit_code == 1


class TestChecksUpdateCLI:
    @patch("qualytics.cli.checks.update_quality_check")
    @patch("qualytics.cli.checks.get_client")
    def test_update(self, mock_gc, mock_update, cli_runner, tmp_path):
        mock_gc.return_value = _mock_client()
        mock_update.return_value = {"id": 42}

        check_file = tmp_path / "check.yaml"
        check_file.write_text("description: Updated\nfields: [email]\nstatus: Draft\n")

        result = cli_runner.invoke(
            app, ["checks", "update", "--id", "42", "--file", str(check_file)]
        )
        assert result.exit_code == 0
        assert "updated successfully" in result.output


class TestChecksDeleteCLI:
    @patch("qualytics.cli.checks.delete_quality_check")
    @patch("qualytics.cli.checks.get_client")
    def test_delete_single(self, mock_gc, mock_delete, cli_runner):
        mock_gc.return_value = _mock_client()
        result = cli_runner.invoke(app, ["checks", "delete", "--id", "42"])
        assert result.exit_code == 0
        assert "Archived" in result.output
        mock_delete.assert_called_once()

    @patch("qualytics.cli.checks.delete_quality_check")
    @patch("qualytics.cli.checks.get_client")
    def test_delete_no_archive(self, mock_gc, mock_delete, cli_runner):
        mock_gc.return_value = _mock_client()
        result = cli_runner.invoke(
            app, ["checks", "delete", "--id", "42", "--no-archive"]
        )
        assert result.exit_code == 0
        assert "Deleted" in result.output
        mock_delete.assert_called_once_with(mock_gc.return_value, 42, archive=False)

    @patch("qualytics.cli.checks.bulk_delete_quality_checks")
    @patch("qualytics.cli.checks.get_client")
    def test_bulk_delete(self, mock_gc, mock_bulk, cli_runner):
        mock_gc.return_value = _mock_client()
        result = cli_runner.invoke(app, ["checks", "delete", "--ids", "1,2,3"])
        assert result.exit_code == 0
        assert "3 quality checks" in result.output
        mock_bulk.assert_called_once()
        items = mock_bulk.call_args.args[1]
        assert len(items) == 3

    def test_delete_no_id_or_ids(self, cli_runner):
        with patch("qualytics.cli.checks.get_client"):
            result = cli_runner.invoke(app, ["checks", "delete"])
        assert result.exit_code == 1


class TestChecksExportCLI:
    @patch("qualytics.cli.checks.export_checks_to_directory")
    @patch("qualytics.cli.checks.list_all_quality_checks")
    @patch("qualytics.cli.checks.get_client")
    def test_export_basic(self, mock_gc, mock_list, mock_export, cli_runner, tmp_path):
        mock_gc.return_value = _mock_client()
        mock_list.return_value = [{"id": 1, "rule_type": "notNull"}]
        mock_export.return_value = {"exported": 1, "containers": 1}

        output_dir = str(tmp_path / "checks")
        result = cli_runner.invoke(
            app, ["checks", "export", "--datastore-id", "42", "--output", output_dir]
        )
        assert result.exit_code == 0
        assert "Exported 1 checks" in result.output

    @patch("qualytics.cli.checks.list_all_quality_checks")
    @patch("qualytics.cli.checks.get_client")
    def test_export_no_checks(self, mock_gc, mock_list, cli_runner, tmp_path):
        mock_gc.return_value = _mock_client()
        mock_list.return_value = []

        result = cli_runner.invoke(
            app, ["checks", "export", "--datastore-id", "42", "--output", str(tmp_path)]
        )
        assert result.exit_code == 0
        assert "No quality checks found" in result.output


class TestChecksImportCLI:
    @patch("qualytics.cli.checks.import_checks_to_datastore")
    @patch("qualytics.cli.checks.load_checks_from_directory")
    @patch("qualytics.cli.checks.get_client")
    def test_import_basic(self, mock_gc, mock_load, mock_import, cli_runner, tmp_path):
        mock_gc.return_value = _mock_client()
        mock_load.return_value = [{"rule_type": "notNull", "container": "orders"}]
        mock_import.return_value = {
            "created": 1,
            "updated": 0,
            "failed": 0,
            "errors": [],
        }

        # Create the input directory so os.path.isdir passes
        input_dir = tmp_path / "checks"
        input_dir.mkdir()

        result = cli_runner.invoke(
            app, ["checks", "import", "--datastore-id", "42", "--input", str(input_dir)]
        )
        assert result.exit_code == 0
        assert "Loaded 1 check" in result.output
        mock_import.assert_called_once()

    @patch("qualytics.cli.checks.import_checks_to_datastore")
    @patch("qualytics.cli.checks.load_checks_from_directory")
    @patch("qualytics.cli.checks.get_client")
    def test_import_multi_datastore(
        self, mock_gc, mock_load, mock_import, cli_runner, tmp_path
    ):
        mock_gc.return_value = _mock_client()
        mock_load.return_value = [{"rule_type": "notNull", "container": "orders"}]
        mock_import.return_value = {
            "created": 1,
            "updated": 0,
            "failed": 0,
            "errors": [],
        }

        input_dir = tmp_path / "checks"
        input_dir.mkdir()

        result = cli_runner.invoke(
            app,
            [
                "checks",
                "import",
                "--datastore-id",
                "42",
                "--datastore-id",
                "43",
                "--input",
                str(input_dir),
            ],
        )
        assert result.exit_code == 0
        assert mock_import.call_count == 2

    @patch("qualytics.cli.checks.import_checks_to_datastore")
    @patch("qualytics.cli.checks.load_checks_from_directory")
    @patch("qualytics.cli.checks.get_client")
    def test_import_dry_run(
        self, mock_gc, mock_load, mock_import, cli_runner, tmp_path
    ):
        mock_gc.return_value = _mock_client()
        mock_load.return_value = [{"rule_type": "notNull", "container": "orders"}]
        mock_import.return_value = {
            "created": 1,
            "updated": 0,
            "failed": 0,
            "errors": [],
        }

        input_dir = tmp_path / "checks"
        input_dir.mkdir()

        result = cli_runner.invoke(
            app,
            [
                "checks",
                "import",
                "--datastore-id",
                "42",
                "--input",
                str(input_dir),
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "DRY RUN" in result.output
        _, kwargs = mock_import.call_args
        assert kwargs["dry_run"] is True

    @patch("qualytics.cli.checks.get_client")
    def test_import_nonexistent_dir(self, mock_gc, cli_runner):
        mock_gc.return_value = _mock_client()
        result = cli_runner.invoke(
            app,
            [
                "checks",
                "import",
                "--datastore-id",
                "42",
                "--input",
                "/nonexistent/path",
            ],
        )
        assert result.exit_code == 1

    @patch("qualytics.cli.checks.load_checks_from_directory")
    @patch("qualytics.cli.checks.get_client")
    def test_import_empty_dir(self, mock_gc, mock_load, cli_runner, tmp_path):
        mock_gc.return_value = _mock_client()
        mock_load.return_value = []

        input_dir = tmp_path / "checks"
        input_dir.mkdir()

        result = cli_runner.invoke(
            app, ["checks", "import", "--datastore-id", "42", "--input", str(input_dir)]
        )
        assert result.exit_code == 0
        assert "No check YAML files found" in result.output

    @patch("qualytics.cli.checks.import_checks_to_datastore")
    @patch("qualytics.cli.checks.load_checks_from_directory")
    @patch("qualytics.cli.checks.get_client")
    def test_import_shows_errors(
        self, mock_gc, mock_load, mock_import, cli_runner, tmp_path
    ):
        mock_gc.return_value = _mock_client()
        mock_load.return_value = [{"rule_type": "notNull", "container": "orders"}]
        mock_import.return_value = {
            "created": 0,
            "updated": 0,
            "failed": 1,
            "errors": ["Container 'orders' not found in datastore 42"],
        }

        input_dir = tmp_path / "checks"
        input_dir.mkdir()

        result = cli_runner.invoke(
            app, ["checks", "import", "--datastore-id", "42", "--input", str(input_dir)]
        )
        assert result.exit_code == 0
        assert "not found" in result.output


# ══════════════════════════════════════════════════════════════════════════
# 5. INTEGRATION — Full promotion workflow (export → import)
# ══════════════════════════════════════════════════════════════════════════


class TestPromotionWorkflow:
    """End-to-end: export from 'dev', import to 'test' and 'prod'."""

    def _dev_checks(self):
        """Simulate API response from a Dev datastore."""
        return [
            _make_api_check(1, "notNull", "orders", ["order_id"], ["data-quality"]),
            _make_api_check(
                2,
                "between",
                "orders",
                ["amount"],
                [],
                properties={"min": 0, "max": 10000},
            ),
            _make_api_check(
                3,
                "matchesPattern",
                "users",
                ["email"],
                ["validation"],
                properties={"pattern": ".*@.*"},
            ),
        ]

    def test_export_import_round_trip(self, tmp_path):
        """Export from dev, then load — all checks preserved."""
        dev_checks = self._dev_checks()
        result = export_checks_to_directory(dev_checks, str(tmp_path))
        assert result["exported"] == 3
        assert result["containers"] == 2

        loaded = load_checks_from_directory(str(tmp_path))
        assert len(loaded) == 3

        # All UIDs are present
        for check in loaded:
            assert _UID_KEY in check.get("additional_metadata", {})

        # All containers are string names (not nested dicts)
        for check in loaded:
            assert isinstance(check["container"], str)

    def test_export_import_preserves_rule_types(self, tmp_path):
        dev_checks = self._dev_checks()
        export_checks_to_directory(dev_checks, str(tmp_path))
        loaded = load_checks_from_directory(str(tmp_path))

        rule_types = sorted(c["rule_type"] for c in loaded)
        assert rule_types == ["between", "matchesPattern", "notNull"]

    @patch("qualytics.services.quality_checks.create_quality_check")
    @patch("qualytics.services.quality_checks.list_all_quality_checks")
    @patch("qualytics.services.quality_checks.get_table_ids")
    def test_import_to_multiple_datastores(
        self, mock_tables, mock_list, mock_create, tmp_path
    ):
        """Import the same checks to two datastores (test + prod)."""
        dev_checks = self._dev_checks()
        export_checks_to_directory(dev_checks, str(tmp_path))
        loaded = load_checks_from_directory(str(tmp_path))

        mock_tables.return_value = {"orders": 100, "users": 200}
        mock_list.return_value = []  # Fresh datastores
        mock_create.return_value = {"id": 999}

        client = _mock_client()

        # Import to "test" datastore
        result_test = import_checks_to_datastore(client, 10, loaded)
        assert result_test["created"] == 3
        assert result_test["failed"] == 0

        # Reset and import to "prod" datastore
        mock_create.reset_mock()
        mock_list.return_value = []  # Fresh
        result_prod = import_checks_to_datastore(client, 20, loaded)
        assert result_prod["created"] == 3
        assert result_prod["failed"] == 0

    @patch("qualytics.services.quality_checks.update_quality_check")
    @patch("qualytics.services.quality_checks.create_quality_check")
    @patch("qualytics.services.quality_checks.list_all_quality_checks")
    @patch("qualytics.services.quality_checks.get_table_ids")
    def test_reimport_updates_existing(
        self, mock_tables, mock_list, mock_create, mock_update, tmp_path
    ):
        """Second import of same checks should update, not create."""
        dev_checks = self._dev_checks()
        export_checks_to_directory(dev_checks, str(tmp_path))
        loaded = load_checks_from_directory(str(tmp_path))

        mock_tables.return_value = {"orders": 100, "users": 200}
        mock_create.return_value = {"id": 999}
        mock_update.return_value = {"id": 999}

        # First import: all creates
        mock_list.return_value = []
        client = _mock_client()
        result1 = import_checks_to_datastore(client, 10, loaded)
        assert result1["created"] == 3

        # Simulate that the datastore now has those checks
        existing_with_uids = []
        for i, check in enumerate(loaded, 50):
            uid = check.get("additional_metadata", {}).get(_UID_KEY)
            existing_with_uids.append(
                {
                    "id": i,
                    "additional_metadata": {_UID_KEY: uid},
                }
            )
        mock_list.return_value = existing_with_uids

        # Second import: all updates
        result2 = import_checks_to_datastore(client, 10, loaded)
        assert result2["updated"] == 3
        assert result2["created"] == 0
