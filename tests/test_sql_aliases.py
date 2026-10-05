"""Tests for the containers import auto-alias (utils/sql_aliases.py)."""

from unittest.mock import MagicMock, patch

import pytest
import typer

from qualytics.api.client import QualyticsAPIError
from qualytics.cli.computed_tables import (
    _create_computed_table,
    import_computed_tables,
)
from qualytics.utils import add_missing_aliases

# A Redshift query from a customer bulk import. The UI accepted it, but the
# old regex rewrite stopped at the FROM inside EXTRACT and sent
# `SELECT extract(year as expr_1 from po_date) ...`.
CUSTOMER_QUERY = """select
extract(year from po_date) as srcods_po_yr,
cast(sum(srcods_po_line_amount) as DECIMAL(38,2))  as srcods_po_line_amount
from
(
select
distinct pol.ebeln,
pol.ebelp,
BEDAT as po_date,
case when isnull(poh.Bsart, '') = 'NB2' then MENGE * -1 else MENGE end as srcods_Po_quantity,
case when isnull(poh.Bsart, '') = 'NB2' then NETWR * -1 else NETWR end as srcods_Po_line_amount,
case when isnull(pol.LOEkZ, '') = 'L'and ekbe.po_nbr is null then 'Y'else 'N'end as exp_isdeleted
from
srcods_vw.sap_hana_int_po_dtl_ekpo_vw pol
inner join srcods_vw.sap_hana_int_po_hdr_ekko_vw poh on pol.ebeln = poh.ebeln
left join
(
select
distinct po_nbr, po_line_number
from
sap_s4_ods.sap_hana_purchasing_doc_hist_ekbe
where
VGABE < 4) ekbe
on ekbe.po_nbr = pol.ebeln and ekbe.po_line_number = pol.ebelp
where isnull(poh.memory, '') <> 'X'and pol.BSTYP = 'F'and trunc(BEDAT) between '2025-01-01' and DATE(date_trunc('month', current_date) - INTERVAL '1' DAY))
where exp_isdeleted = 'N'
group by 1
order by 1"""


@pytest.mark.parametrize(
    "sql",
    [
        pytest.param(CUSTOMER_QUERY, id="customer-extract-query"),
        pytest.param("select * from t", id="star"),
        pytest.param("select t.* from t", id="qualified-star"),
        pytest.param("select * exclude (a) from t", id="star-with-modifier"),
        pytest.param('select a, t.b, "C", t."D" from t', id="column-references"),
        pytest.param("select trim(both ' ' from c) as x from t", id="trim-from"),
        pytest.param("select substring(c from 1 for 3) as x from t", id="substring"),
        pytest.param("select position('a' in c) as x from t", id="position"),
        pytest.param("select a is distinct from b as x from t", id="is-distinct-from"),
        pytest.param(
            "select a is not distinct from b as x from t", id="is-not-distinct-from"
        ),
        pytest.param("select (select max(y) from u) as m from t", id="scalar-subquery"),
        pytest.param('select a as "My Col" from t', id="quoted-alias"),
        pytest.param(
            "select a b, sum(x) total, 'lit' label from t", id="aliases-without-as"
        ),
        pytest.param(
            "select interval '1 day' d, interval '1' day e from t",
            id="aliases-after-interval",
        ),
        pytest.param(
            "select min(d) start, max(d) end, 1 + 1 null from t",
            id="end-and-null-aliases-without-as",
        ),
        pytest.param(
            "select case when a then 1 end end from t", id="end-alias-after-case"
        ),
        pytest.param("select x as id, y as id from t", id="repeated-aliases-kept"),
        pytest.param('select "ID", "id" from t', id="quoted-names-differ-by-case"),
        pytest.param("select[My Col] from t", id="bracket-name-after-select"),
        pytest.param("select a[1] first_item from t", id="alias-after-subscript"),
        pytest.param(
            "select x::struct<a: map<string, int>, b: int> as s from t",
            id="nested-type",
        ),
        pytest.param("select 'data from sap' as src from t", id="from-in-string"),
        pytest.param("select explode(m) as (k, v) from t", id="multi-alias"),
        pytest.param("select {'a': 1, 'b': 2} as obj from t", id="object-constant"),
        pytest.param("select x::map<string, int> as m from t", id="map-type"),
        pytest.param(
            "select count(*) as n -- count from t\nfrom t", id="from-in-comment"
        ),
        pytest.param("/* select 1 + 1 from */ select a from t", id="select-in-comment"),
        pytest.param("select 1 union select 2", id="set-operation-before-from"),
        pytest.param("select 1", id="no-from"),
        pytest.param("(select a + 1 from t)", id="no-outer-select"),
        pytest.param("select a + 1 into t2 from t", id="select-into"),
        pytest.param("select 'it\\'s' || x from t", id="backslash-escaped-quote"),
        pytest.param("select 'unterminated from t", id="unterminated-string"),
        pytest.param("select a /* unterminated from t", id="unterminated-comment"),
        pytest.param(
            "select count(*) from t where x = 'open", id="unterminated-string-later"
        ),
        pytest.param(
            "select count(*) from t /* unterminated", id="unterminated-comment-later"
        ),
        pytest.param("select count(*) from (select 1", id="unclosed-bracket"),
        pytest.param("", id="empty"),
    ],
)
def test_query_is_left_unchanged(sql):
    assert add_missing_aliases(sql) == (sql, 0)


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        pytest.param(
            "SELECT coalesce(trim(name), 'Blank'), upper(status), id as order_id "
            "FROM orders",
            "SELECT coalesce(trim(name), 'Blank') as expr_1, upper(status) as expr_2, "
            "id as order_id FROM orders",
            id="documented-example",
        ),
        pytest.param(
            "select count(*) from t",
            "select count(*) as expr_1 from t",
            id="aggregate",
        ),
        pytest.param(
            "SELECT\n    upper(name),\n    id\nFROM t",
            "SELECT\n    upper(name) as expr_1,\n    id\nFROM t",
            id="formatting-kept",
        ),
        pytest.param(
            "select case when a > 0 then 'pos' else 'neg' end from t",
            "select case when a > 0 then 'pos' else 'neg' end as expr_1 from t",
            id="case",
        ),
        pytest.param(
            "select case when a then case when b then 1 end end from t",
            "select case when a then case when b then 1 end end as expr_1 from t",
            id="nested-case",
        ),
        pytest.param(
            "select a.id, b.id, count(*) from a join b on a.k = b.k group by 1, 2",
            "select a.id, b.id as expr_1, count(*) as expr_2 "
            "from a join b on a.k = b.k group by 1, 2",
            id="repeated-column-name",
        ),
        pytest.param(
            "select id, x as id from t",
            "select id as expr_1, x as id from t",
            id="column-name-taken-by-alias",
        ),
        pytest.param(
            'select "ID", id, ID from t',
            'select "ID", id as expr_1, ID as expr_2 from t',
            id="unknown-source-flags-any-clash",
        ),
        pytest.param(
            "select ARRAY[1, 2], a[1], v['key'] from t",
            "select ARRAY[1, 2] as expr_1, a[1] as expr_2, v['key'] as expr_3 from t",
            id="array-and-subscripts",
        ),
        pytest.param(
            "select map < 3, count(*) from t where map < 5",
            "select map < 3 as expr_1, count(*) as expr_2 from t where map < 5",
            id="comparison-with-map-column",
        ),
        pytest.param(
            "select ts at time zone tz from t",
            "select ts at time zone tz as expr_1 from t",
            id="at-time-zone-column",
        ),
        pytest.param(
            "select a + b, a || b, -a, x::date from t",
            "select a + b as expr_1, a || b as expr_2, -a as expr_3, "
            "x::date as expr_4 from t",
            id="operators",
        ),
        pytest.param(
            "select a is null, a is not distinct from b from t",
            "select a is null as expr_1, a is not distinct from b as expr_2 from t",
            id="predicates",
        ),
        pytest.param(
            "select extract(year from d), trim(both ' ' from c) from t",
            "select extract(year from d) as expr_1, "
            "trim(both ' ' from c) as expr_2 from t",
            id="from-inside-functions",
        ),
        pytest.param(
            "select (select max(y) from u) from t",
            "select (select max(y) from u) as expr_1 from t",
            id="scalar-subquery",
        ),
        pytest.param(
            "select 1, 'x', null from t",
            "select 1 as expr_1, 'x' as expr_2, null as expr_3 from t",
            id="literals",
        ),
        pytest.param(
            "select distinct upper(a) from t",
            "select distinct upper(a) as expr_1 from t",
            id="distinct",
        ),
        pytest.param(
            "select distinct on (a) a, lower(b) from t",
            "select distinct on (a) a, lower(b) as expr_1 from t",
            id="distinct-on",
        ),
        pytest.param(
            "select top 10 upper(a) from t",
            "select top 10 upper(a) as expr_1 from t",
            id="top",
        ),
        pytest.param(
            "with c as (select a + 1 from t) select b * 2 from c",
            "with c as (select a + 1 from t) select b * 2 as expr_1 from c",
            id="outer-select-after-cte",
        ),
        pytest.param(
            "select a + 1 from t union select b + 1 from u",
            "select a + 1 as expr_1 from t union select b + 1 from u",
            id="first-branch-of-union",
        ),
        pytest.param(
            "select row_number() over (partition by a order by b) from t",
            "select row_number() over (partition by a order by b) as expr_1 from t",
            id="window-function",
        ),
        pytest.param(
            "select listagg(a, ',') within group (order by a) from t",
            "select listagg(a, ',') within group (order by a) as expr_1 from t",
            id="within-group",
        ),
        pytest.param(
            "select count(*)from t",
            "select count(*) as expr_1 from t",
            id="no-space-before-from",
        ),
        pytest.param(
            "select sum(x) -- total\nfrom t",
            "select sum(x) as expr_1 -- total\nfrom t",
            id="before-trailing-comment",
        ),
        pytest.param(
            "select expr_1, count(*) from t",
            "select expr_1, count(*) as expr_2 from t",
            id="skips-taken-alias",
        ),
        pytest.param(
            """select 'it''s' || name, "a""b" from t""",
            """select 'it''s' || name as expr_1, "a""b" from t""",
            id="doubled-quotes",
        ),
        pytest.param(
            "select $$a, b$$ from t",
            "select $$a, b$$ as expr_1 from t",
            id="dollar-quoted-string",
        ),
        pytest.param(
            "select [My Col], upper(`x`) from t",
            "select [My Col], upper(`x`) as expr_1 from t",
            id="bracket-and-backtick-names",
        ),
        pytest.param(
            "select next value for seq from t",
            "select next value for seq as expr_1 from t",
            id="next-value-for",
        ),
        pytest.param(
            "select a similar to b from t",
            "select a similar to b as expr_1 from t",
            id="similar-to",
        ),
        pytest.param(
            "select interval '1' day, d - interval 2 hour from t",
            "select interval '1' day as expr_1, d - interval 2 hour as expr_2 from t",
            id="interval-unit",
        ),
        pytest.param(
            "select interval '1-2' year to month from t",
            "select interval '1-2' year to month as expr_1 from t",
            id="interval-range",
        ),
    ],
)
def test_unnamed_expressions_get_aliases(sql, expected):
    result, added = add_missing_aliases(sql)
    assert result == expected
    assert added == expected.count("expr_") - sql.count("expr_")


@pytest.mark.parametrize(
    ("query", "sent"),
    [
        pytest.param(CUSTOMER_QUERY, CUSTOMER_QUERY, id="customer-query-unchanged"),
        pytest.param(
            "select count(*) from t",
            "select count(*) as expr_1 from t",
            id="unnamed-expression-aliased",
        ),
    ],
)
@patch("qualytics.cli.computed_tables.api_create_container")
def test_import_payload_query(mock_create, query, sent, tmp_path):
    mock_create.return_value = {"id": 1}

    _create_computed_table(
        MagicMock(), 20, "ct_import", query, "", str(tmp_path / "errors.log")
    )

    assert mock_create.call_args.args[1]["query"] == sent


@pytest.mark.parametrize(
    ("source_type", "sql", "sent"),
    [
        pytest.param(
            "postgresql",
            'select "ID", id from t',
            'select "ID", id from t',
            id="postgresql-folds-lower",
        ),
        pytest.param(
            "snowflake",
            'select "ID", id from t',
            'select "ID", id as expr_1 from t',
            id="snowflake-folds-upper",
        ),
        pytest.param(
            "sqlserver",
            "select id, ID from t",
            "select id, ID from t",
            id="sqlserver-keeps-case",
        ),
        pytest.param(
            "redshift",
            "select id, ID from t",
            "select id, ID as expr_1 from t",
            id="redshift-folds-lower",
        ),
    ],
)
def test_repeated_names_follow_source_case(source_type, sql, sent):
    assert add_missing_aliases(sql, source_type)[0] == sent


@pytest.mark.parametrize(
    ("datastore", "sent"),
    [
        pytest.param(
            {"id": 7, "type": "postgresql"},
            'select "ID", id from t',
            id="postgresql-datastore",
        ),
        pytest.param(
            {"id": 7, "type": "snowflake"},
            'select "ID", id as expr_1 from t',
            id="snowflake-datastore",
        ),
    ],
)
@patch("qualytics.cli.computed_tables.distinct_file_content")
@patch("qualytics.cli.computed_tables.api_create_container")
@patch("qualytics.cli.computed_tables._get_existing_computed_tables")
@patch("qualytics.cli.computed_tables.get_datastore")
@patch("qualytics.cli.computed_tables.get_client")
def test_import_compares_names_with_datastore_type(
    mock_client,
    mock_get_datastore,
    mock_existing,
    mock_create,
    _distinct,
    datastore,
    sent,
    tmp_path,
):
    mock_get_datastore.return_value = datastore
    mock_existing.return_value = {}
    mock_create.return_value = {"id": 1}
    source = tmp_path / "tables.csv"
    source.write_text('name,description,query\nct1,,"select ""ID"", id from t"\n')

    import_computed_tables(
        datastore=7,
        input_file=str(source),
        delimiter=None,
        prefix="ct_",
        as_draft=True,
        skip_checks=True,
        skip_profile_wait=True,
        tags=None,
        dry_run=False,
        debug=False,
    )

    mock_get_datastore.assert_called_once_with(mock_client.return_value, 7)
    assert mock_create.call_args.args[1]["query"] == sent


@pytest.mark.parametrize(
    "lookup",
    [
        pytest.param(QualyticsAPIError(403, "Forbidden"), id="lookup-fails"),
        pytest.param({"id": 7}, id="no-type"),
    ],
)
@patch("qualytics.cli.computed_tables.api_create_container")
@patch("qualytics.cli.computed_tables.get_datastore")
@patch("qualytics.cli.computed_tables.get_client")
def test_import_stops_without_datastore_type(
    _client, mock_get_datastore, mock_create, lookup, tmp_path
):
    if isinstance(lookup, Exception):
        mock_get_datastore.side_effect = lookup
    else:
        mock_get_datastore.return_value = lookup
    source = tmp_path / "tables.csv"
    source.write_text('name,description,query\nct1,,"select ""ID"", id from t"\n')

    with pytest.raises(typer.Exit) as stopped:
        import_computed_tables(
            datastore=7,
            input_file=str(source),
            delimiter=None,
            prefix="ct_",
            as_draft=True,
            skip_checks=True,
            skip_profile_wait=True,
            tags=None,
            dry_run=False,
            debug=False,
        )

    assert stopped.value.exit_code == 1
    mock_create.assert_not_called()


@patch("qualytics.cli.computed_tables._get_existing_computed_tables")
@patch("qualytics.cli.computed_tables.get_datastore")
@patch("qualytics.cli.computed_tables.get_client")
def test_dry_run_does_not_read_datastore(
    _client, mock_get_datastore, mock_existing, tmp_path
):
    mock_get_datastore.side_effect = QualyticsAPIError(403, "Forbidden")
    mock_existing.return_value = {}
    source = tmp_path / "tables.csv"
    source.write_text('name,description,query\nct1,,"select count(*) from t"\n')

    with pytest.raises(typer.Exit) as stopped:
        import_computed_tables(
            datastore=7,
            input_file=str(source),
            delimiter=None,
            prefix="ct_",
            as_draft=True,
            skip_checks=True,
            skip_profile_wait=True,
            tags=None,
            dry_run=True,
            debug=False,
        )

    assert stopped.value.exit_code == 0
    mock_get_datastore.assert_not_called()
