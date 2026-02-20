# Computed Tables Guide

Computed tables let you define SQL-based virtual containers in Qualytics and automatically generate `satisfiesExpression` quality checks for error detection. This guide covers bulk import from files (Excel, CSV, TXT) using the `computed-tables` command group.

For creating individual computed containers, see `qualytics containers create --type computed_table`.

## Input File Structure

The input file must have **3 columns in positional order** (the first row is treated as a header and skipped):

| Column | Name | Required | Description |
|--------|------|----------|-------------|
| 1 | name | Yes | Unique identifier for the computed table |
| 2 | description | No | Description stored in metadata and check |
| 3 | query | Yes | SQL query for the computed table |

Column names in the header row don't matter -- only the position matters.

### Excel Example (.xlsx)

| check_id | check_description | check_query |
|-----------|------------------------------------|--------------------------------------------------------------------|
| CHK001 | Detect orders with negative totals | SELECT * FROM sales_orders WHERE total_amount < 0 |
| CHK002 | Find customers without email | SELECT * FROM customer_master WHERE email IS NULL OR email = '' |
| CHK003 | Identify duplicate invoices | SELECT invoice_no, COUNT(*) FROM invoices GROUP BY invoice_no HAVING COUNT(*) > 1 |

### CSV Example (.csv)

```csv
check_id,check_description,check_query
CHK001,Detect orders with negative totals,"SELECT * FROM sales_orders WHERE total_amount < 0"
CHK002,Find customers without email,"SELECT * FROM customer_master WHERE email IS NULL OR email = ''"
CHK003,Identify duplicate invoices,"SELECT invoice_no, COUNT(*) FROM invoices GROUP BY invoice_no HAVING COUNT(*) > 1"
```

For multiline SQL queries in CSV, wrap the entire query in double quotes:

```csv
check_id,check_description,check_query
CHK004,Complex order validation,"SELECT o.*
FROM sales_orders o
JOIN customer_master c ON o.customer_id = c.id
WHERE o.status = 'SHIPPED'
  AND c.country IS NULL"
```

## Validation Rules

The import process validates each row before processing:

| Validation | Behavior |
|------------|----------|
| Empty name | Row is **skipped** with warning |
| Empty query | Row is **skipped** with warning |
| Empty description | Row is **processed** (description defaults to "") |
| Duplicate name | Second occurrence is **skipped** with warning |
| Blank row | Row is **skipped** silently |

Example validation output:

```
Found 5 records in the file.
Warnings during validation:
  - Row 3: Empty name, skipping.
  - Row 4: 'CHK001' has empty query, skipping.
  - Row 7: Duplicate name 'CHK002' (first seen at row 2), skipping.
3 valid records to import.
```

## Import Command

```bash
qualytics computed-tables import --datastore DATASTORE_ID --input FILE_PATH [OPTIONS]
```

### Options

| Option | Type | Description | Default |
|--------|------|-------------|---------|
| `--datastore` | INTEGER | Datastore ID to create computed tables in | Required |
| `--input` | TEXT | Input file path (.xlsx, .csv, or .txt) | Required |
| `--prefix` | TEXT | Prefix for computed table names | `ct_` |
| `--delimiter` | TEXT | Delimiter for CSV/TXT files | `,` for CSV, `\t` for TXT |
| `--as-draft` | FLAG | Create checks in Draft status (default) | True |
| `--as-active` | FLAG | Create checks in Active status | False |
| `--skip-checks` | FLAG | Skip creating quality checks (only create computed tables) | False |
| `--skip-profile-wait` | FLAG | Skip waiting for profile operation | False |
| `--tags` | TEXT | Tags for checks (comma-separated) | None |
| `--dry-run` | FLAG | Preview what would be created without making changes | False |
| `--debug` | FLAG | Enable debug mode with API logging | False |

## Use Cases

### 1. Basic Import (Default)

```bash
qualytics computed-tables import --datastore 123 --input checks.xlsx
```

Creates computed tables with `ct_` prefix, waits for profile operation, creates quality checks in **Draft** status. Skips existing computed tables and existing checks.

### 2. Import with Active Checks

```bash
qualytics computed-tables import --datastore 123 --input checks.xlsx --as-active
```

Same as basic import but checks are created in **Active** status and will run during the next scan. Use when rules are tested and ready for production.

### 3. Import Only Computed Tables (No Checks)

```bash
qualytics computed-tables import --datastore 123 --input checks.xlsx --skip-checks
```

Creates computed tables only, no quality checks. Use when you want to configure checks manually in the UI.

### 4. Skip Profile Wait

```bash
qualytics computed-tables import --datastore 123 --input checks.xlsx --skip-profile-wait
```

Creates computed tables without waiting for profile. **Warning:** checks will likely fail because the container has no fields until profiling completes. Only use with `--skip-checks` for bulk computed table creation.

### 5. Import with Custom Prefix

```bash
qualytics computed-tables import --datastore 123 --input checks.xlsx --prefix "dq_"
```

Computed tables use `dq_` prefix instead of `ct_`. Example: `CHK001` becomes `dq_CHK001`.

### 6. Import with Tags

```bash
qualytics computed-tables import --datastore 123 --input checks.xlsx --tags "production,finance"
```

Checks are created with the specified tags for filtering in the UI.

### 7. Dry Run (Preview Only)

```bash
qualytics computed-tables import --datastore 123 --input checks.xlsx --dry-run
```

No changes are made. Shows a preview table of what would be created and which tables would be skipped.

### 8. Debug Mode

```bash
qualytics computed-tables import --datastore 123 --input checks.xlsx --debug
```

Shows API requests/responses in the console and writes detailed logs to `~/.qualytics/logs/`. Use when troubleshooting import failures.

### 9. CSV with Custom Delimiter

```bash
qualytics computed-tables import --datastore 123 --input checks.txt --delimiter ";"
```

Reads the file using semicolon as delimiter. Use for files exported from systems with non-standard delimiters.

### 10. Production-Ready Import

```bash
qualytics computed-tables import --datastore 123 --input checks.xlsx \
  --prefix "prod_" \
  --tags "production,automated" \
  --as-active \
  --debug
```

Computed tables with `prod_` prefix, checks in **Active** status, tagged for filtering, and full API logging for audit trail.

### 11. Fast Bulk Import (Minimal)

```bash
qualytics computed-tables import --datastore 123 --input checks.xlsx \
  --skip-checks \
  --skip-profile-wait
```

Fastest possible import -- no profile waiting, no checks created. Computed tables only. Add checks manually after profiling completes. This is the recommended way to use `--skip-profile-wait`.

## Check Status: Draft vs Active

| Status | Flag | Behavior |
|--------|------|----------|
| Draft | `--as-draft` | Check exists but won't run during scans. Review before activating. |
| Active | `--as-active` | Check runs immediately during scan operations. |

Default: checks are created as **Draft** for safety.

## Computed Table Naming

The final computed table name follows the pattern `<prefix><name>`:

- Input name `CHK001` with prefix `ct_` becomes `ct_CHK001`
- Input name `order_validation` with prefix `ct_` becomes `ct_order_validation`

Common suffixes like `_SF`, `_DB`, `_BQ`, `_SNOWFLAKE` are automatically stripped from the `rule_id` stored in metadata:

- Input name `CHK001_SF` becomes `rule_id: CHK001` in metadata

## Check Behavior

When checks are created (default behavior), a `satisfiesExpression` check is automatically generated where:

- **Empty result set (no rows)** = PASS (all data is valid)
- **Any rows returned** = FAIL (each row is flagged as an anomaly)

This is ideal for error detection queries where returned results indicate data quality issues.

The check expression wraps all field names with backticks for compatibility:

```sql
`order_id` IS NULL AND `customer_name` IS NULL AND `coalesce(trim(status))` IS NULL
```

## Metadata Storage

Both the computed table and quality check store metadata for traceability.

**Computed table `additional_metadata`:**

```json
{
  "description": "Detect orders with negative totals",
  "rule_id": "CHK001",
  "imported_from": "qualytics-cli",
  "import_timestamp": "2026-01-28T12:00:00"
}
```

**Quality check `additional_metadata`:**

```json
{
  "rule_id": "CHK001",
  "computed_table_name": "ct_CHK001",
  "original_description": "Detect orders with negative totals",
  "imported_from": "qualytics-cli",
  "import_timestamp": "2026-01-28T12:00:00"
}
```

## SQL Query Handling

Cross-catalog/schema references are preserved as-is:

```sql
SELECT * FROM analytics_prod.sales_schema.orders o
JOIN finance_db.accounting.invoices i ON o.invoice_id = i.id
WHERE o.status = 'PENDING'
```

Columns without aliases get unique aliases added automatically (`expr_1`, `expr_2`, etc.):

```sql
-- Original query
SELECT coalesce(trim(name), 'Blank'), upper(status), id as order_id FROM orders

-- After processing
SELECT coalesce(trim(name), 'Blank') as expr_1, upper(status) as expr_2, id as order_id FROM orders
```

This ensures all fields have proper names for the quality check expression.

## List and Preview Commands

### List Computed Tables

```bash
qualytics computed-tables list --datastore 123
```

Example output:

```
+------+--------------------+
| ID   | Name               |
+------+--------------------+
| 101  | ct_CHK001          |
| 102  | ct_CHK002          |
| 103  | ct_CHK003          |
+------+--------------------+

Total: 3 computed tables
```

### Preview File

Preview computed table definitions from a file without importing:

```bash
qualytics computed-tables preview --input checks.xlsx --limit 3
```

| Option | Type | Description | Default |
|--------|------|-------------|---------|
| `--input` | TEXT | Input file path (.xlsx, .csv, or .txt) | Required |
| `--delimiter` | TEXT | Delimiter for CSV/TXT files | `,` for CSV, `\t` for TXT |
| `--limit` | INTEGER | Number of records to preview | 5 |
| `--prefix` | TEXT | Prefix to show for computed table names | `ct_` |
