"""Tests for the containers import auto-alias (utils/sql_aliases.py)."""

from unittest.mock import MagicMock, patch

import pytest

from qualytics.cli.computed_tables import _create_computed_table
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
    ],
)
def test_unnamed_expressions_get_aliases(sql, expected):
    result, added = add_missing_aliases(sql)
    assert result == expected
    assert added == expected.count("expr_") - sql.count("expr_")


@patch("qualytics.cli.computed_tables.api_create_container")
def test_import_sends_customer_query_unchanged(mock_create, tmp_path):
    mock_create.return_value = {"id": 1}

    _create_computed_table(
        MagicMock(),
        20,
        "DQT_srcods_PO_Qty_By_Posting_Yr",
        CUSTOMER_QUERY,
        "",
        str(tmp_path / "errors.log"),
    )

    assert mock_create.call_args.args[1]["query"] == CUSTOMER_QUERY
