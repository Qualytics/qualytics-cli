"""CLI command: generate-driver — probe a JDBC driver JAR and emit a YAML driver definition."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import zipfile
from typing import Annotated

import typer
import yaml
from rich import print
from rich.console import Console
from rich.table import Table

from . import BRAND, add_suggestion_callback, print_banner
from .progress import status

# ---------------------------------------------------------------------------
# Java probe source — compiled at runtime inside a temp dir.
# Outputs a single JSON object to stdout; all diagnostic chatter goes to stderr.
# ---------------------------------------------------------------------------

_PROBE_JAVA_SOURCE = r"""
import java.io.*;
import java.net.URL;
import java.net.URLClassLoader;
import java.sql.*;
import java.util.*;
import java.util.concurrent.*;

public class JdbcProbe {

    // ── helpers ──────────────────────────────────────────────────────────

    private static String jq(String s) {
        if (s == null) return "null";
        return "\"" + s.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n") + "\"";
    }

    private static boolean tryQuery(Connection c, String sql, int timeoutSecs) {
        try {
            Statement st = c.createStatement();
            st.setQueryTimeout(timeoutSecs);
            st.execute(sql);
            st.close();
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    // ── main ─────────────────────────────────────────────────────────────

    public static void main(String[] args) throws Exception {
        // args: <jarPath> <jdbcUrl> [user] [password] [key=val ...]
        if (args.length < 2) {
            System.err.println("Usage: JdbcProbe <jarPath> <jdbcUrl> [user] [password] [key=val...]");
            System.exit(2);
        }
        String jarPath = args[0];
        String jdbcUrl = args[1];
        String user    = args.length > 2 ? args[2] : null;
        String pass    = args.length > 3 ? args[3] : null;

        Properties extraProps = new Properties();
        for (int i = 4; i < args.length; i++) {
            int eq = args[i].indexOf('=');
            if (eq > 0) {
                extraProps.setProperty(args[i].substring(0, eq), args[i].substring(eq + 1));
            }
        }

        // -- Load JAR into an isolated class loader
        URL jarUrl = new File(jarPath).toURI().toURL();
        URLClassLoader loader = new URLClassLoader(new URL[]{jarUrl},
                ClassLoader.getSystemClassLoader().getParent());

        // Discover Driver via ServiceLoader then DriverManager fallback
        Driver driver = null;
        try {
            ServiceLoader<Driver> sl = ServiceLoader.load(Driver.class, loader);
            for (Driver d : sl) {
                if (d.acceptsURL(jdbcUrl)) { driver = d; break; }
            }
        } catch (Exception ignored) {}

        if (driver == null) {
            // Try enumerating classes from the JAR manifest Main-Class / known names
            // Fallback: ask DriverManager after registering via Class.forName scan
            try {
                java.util.jar.JarFile jar = new java.util.jar.JarFile(jarPath);
                java.util.Enumeration<java.util.jar.JarEntry> entries = jar.entries();
                while (entries.hasMoreElements()) {
                    java.util.jar.JarEntry e = entries.nextElement();
                    String name = e.getName();
                    if (name.endsWith(".class") && !name.contains("$")) {
                        String cls = name.replace('/', '.').replace(".class", "");
                        try {
                            Class<?> c = loader.loadClass(cls);
                            if (Driver.class.isAssignableFrom(c) && !c.isInterface()) {
                                Driver d = (Driver) c.getDeclaredConstructor().newInstance();
                                if (d.acceptsURL(jdbcUrl)) { driver = d; break; }
                            }
                        } catch (Throwable ignored2) {}
                    }
                }
                jar.close();
            } catch (Exception e) {
                System.err.println("JAR scan error: " + e.getMessage());
            }
        }

        if (driver == null) {
            System.err.println("ERROR: No Driver found in JAR that accepts URL: " + jdbcUrl);
            System.exit(3);
        }

        String className = driver.getClass().getName();
        System.err.println("Driver class: " + className);

        // -- Connect
        Properties connProps = new Properties();
        connProps.putAll(extraProps);
        if (user != null && !user.equals("null")) connProps.setProperty("user", user);
        if (pass != null && !pass.equals("null")) connProps.setProperty("password", pass);

        Connection conn;
        try {
            conn = driver.connect(jdbcUrl, connProps);
            if (conn == null) throw new SQLException("driver.connect() returned null");
        } catch (SQLException e) {
            System.err.println("CONNECTION_ERROR: " + e.getMessage());
            System.exit(4);
            return;
        }
        System.err.println("Connected successfully.");

        DatabaseMetaData meta = conn.getMetaData();

        // databaseProductName / databaseProductVersion
        String dbProductName = "null";
        String dbProductVersion = "null";
        try {
            dbProductName = jq(meta.getDatabaseProductName());
            dbProductVersion = jq(meta.getDatabaseProductVersion());
        } catch (Exception e) { System.err.println("dbProduct err: " + e.getMessage()); }

        // ── Phase 1: metadata (no SQL) ────────────────────────────────────

        // identifierQuoteChar
        String quoteChar = "null";
        try {
            String q = meta.getIdentifierQuoteString();
            quoteChar = (q != null && !q.isBlank()) ? jq(q.trim()) : jq("\"");
        } catch (Exception e) { System.err.println("identifierQuoteChar err: " + e.getMessage()); }

        // transactionIsolation
        String txIsolation = "null";
        try {
            int ti = meta.getDefaultTransactionIsolation();
            switch (ti) {
                case Connection.TRANSACTION_NONE:             txIsolation = "\"NONE\""; break;
                case Connection.TRANSACTION_READ_UNCOMMITTED: txIsolation = "\"READ_UNCOMMITTED\""; break;
                case Connection.TRANSACTION_READ_COMMITTED:   txIsolation = "\"READ_COMMITTED\""; break;
                case Connection.TRANSACTION_REPEATABLE_READ:  txIsolation = "\"REPEATABLE_READ\""; break;
                case Connection.TRANSACTION_SERIALIZABLE:     txIsolation = "\"SERIALIZABLE\""; break;
                default: txIsolation = "\"READ_COMMITTED\"";
            }
        } catch (Exception e) { System.err.println("transactionIsolation err: " + e.getMessage()); }

        // tableNameCasing
        String casing = "\"AS_IS\"";
        try {
            if (meta.storesUpperCaseIdentifiers()) casing = "\"UPPER\"";
            else if (meta.storesLowerCaseIdentifiers()) casing = "\"LOWER\"";
        } catch (Exception e) { System.err.println("tableNameCasing err: " + e.getMessage()); }

        // ── Phase 2: SQL probes (5s timeout each) ────────────────────────

        // connectionTest
        String validationQuery = "null";
        String[] valCandidates = {"SELECT 1", "SELECT 1 FROM DUAL", "VALUES 1"};
        for (String q : valCandidates) {
            if (tryQuery(conn, q, 5)) { validationQuery = jq(q); break; }
        }

        // getTablesUsesNullCatalog
        String nullCatalog = "false";
        try {
            String catalog = conn.getCatalog();
            ResultSet rs1 = meta.getTables(catalog, null, "%", new String[]{"TABLE"});
            int c1 = 0; while (rs1.next()) c1++;
            rs1.close();
            ResultSet rs2 = meta.getTables(null, null, "%", new String[]{"TABLE"});
            int c2 = 0; while (rs2.next()) c2++;
            rs2.close();
            nullCatalog = (c2 > c1) ? "true" : "false";
        } catch (Exception e) { System.err.println("getTablesUsesNullCatalog err: " + e.getMessage()); }

        // subqueryAlias — does a derived-table subquery require an `AS alias`?
        // Default true (ANSI / PostgreSQL family). Probe an alias-LESS derived table:
        // if it succeeds, the DB does NOT require an alias (historically Oracle) → false.
        String subAlias = "true";
        if (tryQuery(conn, "SELECT * FROM (SELECT 1 AS x) WHERE 1=0", 5)) {
            subAlias = "false";
        }

        // supportsSchemas — does this database organise tables into schemas?
        // Drives whether the connection form exposes an optional `schema` field. PostgreSQL,
        // Redshift, Oracle, SQL Server etc. return schemas; MySQL/MariaDB use catalogs and return none.
        String supportsSchemas = "false";
        try {
            ResultSet schemaRs = meta.getSchemas();
            if (schemaRs.next()) supportsSchemas = "true";
            schemaRs.close();
        } catch (Exception e) { System.err.println("supportsSchemas err: " + e.getMessage()); }

        // approxCountDistinctFunction
        // Closed vocab: APPROX_COUNT_DISTINCT, APPROX_DISTINCT (NDV is not a valid dataplane token)
        String approxFn = "null";
        if (tryQuery(conn, "SELECT APPROX_COUNT_DISTINCT(1)", 5)) approxFn = "\"APPROX_COUNT_DISTINCT\"";
        else if (tryQuery(conn, "SELECT APPROX_DISTINCT(1)", 5)) approxFn = "\"APPROX_DISTINCT\"";


        // rowLimitStyle — find a real accessible table first
        String rowLimit = "null";
        String sampleTable = null;
        try {
            ResultSet tables = meta.getTables(null, null, "%", new String[]{"TABLE"});
            if (tables.next()) {
                String tcat = tables.getString(1);
                String tsch = tables.getString(2);
                String tnam = tables.getString(3);
                // build qualified name
                StringBuilder sb = new StringBuilder();
                if (tcat != null && !tcat.isBlank()) sb.append(tcat).append(".");
                if (tsch != null && !tsch.isBlank()) sb.append(tsch).append(".");
                sb.append(tnam);
                sampleTable = sb.toString();
            }
            tables.close();
        } catch (Exception e) { System.err.println("table scan err: " + e.getMessage()); }

        // Try LIMIT first: it is the ANSI-ish, most common idiom and the dataplane default.
        // PostgreSQL-family engines (incl. Redshift) accept BOTH `LIMIT` and `TOP`, so probing
        // TOP first would misclassify them as a SQL Server dialect. SQL Server / Teradata reject
        // LIMIT and correctly fall through to TOP; Oracle falls through to FETCH FIRST / ROWNUM.
        if (sampleTable != null) {
            if (tryQuery(conn, "SELECT 1 FROM " + sampleTable + " LIMIT 1", 5))
                rowLimit = "\"LIMIT\"";
            else if (tryQuery(conn, "SELECT TOP 1 1 FROM " + sampleTable, 5))
                rowLimit = "\"TOP\"";
            else if (tryQuery(conn, "SELECT 1 FROM " + sampleTable + " FETCH FIRST 1 ROWS ONLY", 5))
                rowLimit = "\"FETCH_FIRST\"";
            else if (tryQuery(conn, "SELECT 1 FROM " + sampleTable + " WHERE ROWNUM <= 1", 5))
                rowLimit = "\"ROWNUM\"";
        } else {
            // no tables — try without a table
            if (tryQuery(conn, "SELECT 1 LIMIT 1", 5))       rowLimit = "\"LIMIT\"";
            else if (tryQuery(conn, "SELECT TOP 1 1", 5))    rowLimit = "\"TOP\"";
            else if (tryQuery(conn, "VALUES 1 FETCH FIRST 1 ROWS ONLY", 5)) rowLimit = "\"FETCH_FIRST\"";
        }

        // tableSampleTemplate
        String sampleTemplate = "null";
        if (sampleTable != null) {
            String[][] candidates = {
                {"TABLESAMPLE SYSTEM (1)", "\"TABLESAMPLE SYSTEM ({pct})\""},
                {"TABLESAMPLE BERNOULLI (1)", "\"TABLESAMPLE BERNOULLI ({pct})\""},
                {"TABLESAMPLE SYSTEM (1 PERCENT)", "\"TABLESAMPLE SYSTEM ({pct} PERCENT)\""},
                {"SAMPLE (1)", "\"SAMPLE ({pct})\""},
                {"TABLESAMPLE (1)", "\"TABLESAMPLE ({pct})\""},
                {"SAMPLE (1 PERCENT)", "\"SAMPLE ({pct} PERCENT)\""},
            };
            for (String[] pair : candidates) {
                if (tryQuery(conn, "SELECT 1 FROM " + sampleTable + " " + pair[0], 5)) {
                    sampleTemplate = pair[1];
                    break;
                }
            }
        }

        // viewSampleFallback — the row-varying random function used for view/sampling.
        // Order is significant and beats "first function that parses":
        //   RANDOM            — PostgreSQL family (incl. Redshift), Snowflake; most common, so preferred.
        //   NEWID             — before RAND because SQL Server HAS RAND() but it is constant per query
        //                       (only NEWID() varies per row, so only NEWID can shuffle rows there).
        //   RAND              — MySQL / MariaDB and engines without RANDOM().
        //   DBMS_RANDOM_VALUE — Oracle (needs the DUAL form).
        // Null when none match (e.g. the dialect needs a function not in the closed vocab) — the
        // generator then emits no sql.functions entry rather than guessing RAND.
        String viewSampleFallback = "null";
        if (tryQuery(conn, "SELECT RANDOM()", 5))
            viewSampleFallback = "\"RANDOM\"";
        else if (tryQuery(conn, "SELECT NEWID()", 5))
            viewSampleFallback = "\"NEWID\"";
        else if (tryQuery(conn, "SELECT RAND()", 5))
            viewSampleFallback = "\"RAND\"";
        else if (tryQuery(conn, "SELECT DBMS_RANDOM.VALUE FROM DUAL", 5))
            viewSampleFallback = "\"DBMS_RANDOM_VALUE\"";

        // timestampLiteralStyle — detect DB-specific timestamp cast syntax
        String timestampLiteralStyle = "\"PLAIN\"";
        if (tryQuery(conn, "SELECT CAST('2000-01-01 00:00:00' AS DATETIME2)", 5))
            timestampLiteralStyle = "\"CAST_DATETIME2\"";
        else if (tryQuery(conn, "SELECT TO_TIMESTAMP('2000-01-01 00:00:00', 'YYYY-MM-DD HH24:MI:SS') FROM DUAL", 5))
            timestampLiteralStyle = "\"TO_TIMESTAMP\"";
        else if (tryQuery(conn, "SELECT TIMESTAMP '2000-01-01 00:00:00'", 5))
            timestampLiteralStyle = "\"TIMESTAMP_PREFIX\"";

        // dateLiteralStyle — detect Oracle-style TO_DATE (DUAL distinguishes Oracle from others)
        String dateLiteralStyle = "\"PLAIN\"";
        if (tryQuery(conn, "SELECT TO_DATE('2000-01-01', 'YYYY-MM-DD') FROM DUAL", 5))
            dateLiteralStyle = "\"TO_DATE\"";

        // schemaOnly — how to wrap a query to return 0 rows (for schema inspection).
        // SQLSERVER_TOP0 is only correct for the SQL Server family: `SELECT TOP 0` also parses on
        // PostgreSQL-family engines (incl. Redshift) that support TOP as an alias for LIMIT, so it is
        // gated on TOP being the detected row-limit idiom. Everything else (incl. Redshift, which now
        // resolves to LIMIT) falls through to the CTE default, which the dataplane handles generically.
        String schemaOnlyStyle = "\"CTE\"";
        if (sampleTable != null) {
            if (rowLimit.equals("\"TOP\"") && tryQuery(conn, "SELECT TOP 0 * FROM " + sampleTable, 5))
                schemaOnlyStyle = "\"SQLSERVER_TOP0\"";
            else if (tryQuery(conn, "SELECT * FROM " + sampleTable + " WHERE 1=0", 5)
                     && dateLiteralStyle.equals("\"TO_DATE\""))
                // Oracle: WHERE 1=0 works but no alias required
                schemaOnlyStyle = "\"ORACLE_WHERE_FALSE\"";
        }

        // rowCount — probe metadata tables for optimized row count access
        String rowCountStyle = "\"COUNT_STAR\"";
        if (tryQuery(conn, "SELECT ROW_COUNT FROM INFORMATION_SCHEMA.TABLES WHERE 1=0", 5))
            rowCountStyle = "\"INFORMATION_SCHEMA_ROW_COUNT\"";
        else if (tryQuery(conn, "SELECT DATA_LENGTH FROM INFORMATION_SCHEMA.TABLES WHERE 1=0", 5))
            rowCountStyle = "\"INFORMATION_SCHEMA_TABLES_WITH_SIZE\"";
        else if (tryQuery(conn, "SELECT NUM_ROWS FROM ALL_TABLES WHERE 1=0", 5))
            rowCountStyle = "\"ALL_TABLES\"";

        conn.close();

        // ── Emit JSON ─────────────────────────────────────────────────────
        StringBuilder out = new StringBuilder();
        out.append("{\n");
        out.append("  \"className\": ").append(jq(className)).append(",\n");
        out.append("  \"dbProductName\": ").append(dbProductName).append(",\n");
        out.append("  \"dbProductVersion\": ").append(dbProductVersion).append(",\n");
        out.append("  \"identifierQuoteChar\": ").append(quoteChar).append(",\n");
        out.append("  \"transactionIsolation\": ").append(txIsolation).append(",\n");
        out.append("  \"tableNameCasing\": ").append(casing).append(",\n");
        out.append("  \"connectionTest\": ").append(validationQuery).append(",\n");
        out.append("  \"getTablesUsesNullCatalog\": ").append(nullCatalog).append(",\n");
        out.append("  \"supportsSchemas\": ").append(supportsSchemas).append(",\n");
        out.append("  \"subqueryAlias\": ").append(subAlias).append(",\n");
        out.append("  \"approxCountDistinctFunction\": ").append(approxFn).append(",\n");
        out.append("  \"rowLimitStyle\": ").append(rowLimit).append(",\n");
        out.append("  \"tableSampleTemplate\": ").append(sampleTemplate).append(",\n");
        out.append("  \"viewSampleFallback\": ").append(viewSampleFallback).append(",\n");
        out.append("  \"timestampLiteralStyle\": ").append(timestampLiteralStyle).append(",\n");
        out.append("  \"dateLiteralStyle\": ").append(dateLiteralStyle).append(",\n");
        out.append("  \"schemaOnly\": ").append(schemaOnlyStyle).append(",\n");
        out.append("  \"rowCount\": ").append(rowCountStyle).append("\n");
        out.append("}\n");
        System.out.println(out.toString());
    }
}
"""

# ---------------------------------------------------------------------------
# Java toolchain helpers
# ---------------------------------------------------------------------------


def _require_java_tool(name: str) -> str:
    """Return full path to *name* (javac/java), or raise typer.Exit(1)."""
    path = shutil.which(name)
    if path is None:
        print(
            f"[red]'{name}' not found on PATH.[/red]\n"
            "[yellow]A Java Development Kit (JDK) is required to run driver probes.[/yellow]\n"
            "Install a JDK (e.g. OpenJDK 11+) and make sure 'java' and 'javac' are on your PATH."
        )
        raise typer.Exit(code=1)
    return path


def _compile_probe(tmpdir: str) -> str:
    """Write and compile JdbcProbe.java; return path to the class directory."""
    src_path = os.path.join(tmpdir, "JdbcProbe.java")
    with open(src_path, "w") as fh:
        fh.write(_PROBE_JAVA_SOURCE)

    javac = _require_java_tool("javac")
    result = subprocess.run(
        [javac, "-source", "11", "-target", "11", src_path],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"[red]Failed to compile Java probe:[/red]\n{result.stderr}")
        raise typer.Exit(code=1)
    return tmpdir


# ---------------------------------------------------------------------------
# Core probe runner
# ---------------------------------------------------------------------------


def _run_probe(
    *,
    jar_path: str,
    jdbc_url: str,
    user: str | None,
    password: str | None,
    properties: list[str],
) -> dict:
    """Compile + run JdbcProbe; return parsed JSON dict."""
    tmpdir = tempfile.mkdtemp(prefix="qualytics_jdbc_probe_")
    try:
        class_dir = _compile_probe(tmpdir)
        java = _require_java_tool("java")

        cmd = [
            java,
            "-cp",
            class_dir,
            "JdbcProbe",
            os.path.abspath(jar_path),
            jdbc_url,
            user or "null",
            password or "null",
        ] + list(properties)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )

        # Forward stderr from the probe to our stderr for debugging
        if result.stderr.strip():
            for line in result.stderr.strip().splitlines():
                if line.startswith("CONNECTION_ERROR:"):
                    print(
                        f"[red]JDBC connection failed: {line[len('CONNECTION_ERROR:') :].strip()}[/red]"
                    )
                    raise typer.Exit(code=1)
                if line.startswith("ERROR:"):
                    print(f"[red]{line[len('ERROR:') :].strip()}[/red]")
                    raise typer.Exit(code=1)

        if result.returncode == 4:
            print(
                "[red]Could not connect to the database. Check --url, --user, and --password.[/red]"
            )
            raise typer.Exit(code=1)
        if result.returncode == 3:
            print(
                "[red]No compatible JDBC driver found in the provided JAR for the given URL.[/red]"
            )
            raise typer.Exit(code=1)
        if result.returncode != 0:
            print(f"[red]Probe exited with code {result.returncode}.[/red]")
            if result.stderr:
                print(f"[dim]{result.stderr.strip()}[/dim]")
            raise typer.Exit(code=1)

        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            print(f"[red]Could not parse probe output as JSON: {exc}[/red]")
            print(f"[dim]Raw output: {result.stdout[:500]}[/dim]")
            raise typer.Exit(code=1)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# YAML generation helpers
# ---------------------------------------------------------------------------


def _extract_prefix(jdbc_url: str) -> str | None:
    """Parse 'jdbc:<prefix>:' from a JDBC URL."""
    m = re.match(r"jdbc:([^:]+):", jdbc_url, re.IGNORECASE)
    return m.group(1).lower() if m else None


def _derive_url_metadata(jdbc_url: str) -> tuple[int | None, str, set[str]]:
    """
    Derive a defaultPort, a jdbcUrlTemplate, and the set of URL components that
    were present in the probe URL from a JDBC URL.

    Returns (port_or_None, template_string, url_components).
    url_components is a subset of {"host", "port", "database"} reflecting which
    parts were actually found in the URL.  This is used to decide which
    connectionSpec fields should be marked required.

    Template replaces hostname → {host}, port → {port}, first path segment → {database}.
    """
    url_components: set[str] = set()

    # Try the standard jdbc:scheme://[authority]/path form first
    m = re.match(r"(jdbc:[^:]+://)([^/?#]*)(.*)", jdbc_url, re.IGNORECASE)
    if m:
        scheme = m.group(1)
        authority = m.group(2)
        rest = m.group(3)

        # host — present if authority is non-empty after stripping credentials/port/params
        host_part = re.sub(r"^[^@]+@", "", authority)  # strip user:pass@
        host_part = re.sub(r":\d+(?:$|;)", "", host_part)  # strip :port
        host_part = re.sub(r";.*$", "", host_part)  # strip ;params (SQL Server style)
        if host_part.strip():
            url_components.add("host")

        port_m = re.search(r":(\d+)(?:$|;)", authority)
        port = int(port_m.group(1)) if port_m else None
        if port is not None:
            url_components.add("port")

        # database — present if the path has a non-empty first segment
        db_m = re.match(r"/([^/?#;]+)", rest)
        if db_m and db_m.group(1):
            url_components.add("database")

        tmpl_authority = re.sub(r"^[^:@/]+", "{host}", authority)
        tmpl_authority = re.sub(r":\d+(?:$|;)", ":{port}", tmpl_authority)
        tmpl_rest = re.sub(r"^/([^/?#]+)", "/{database}", rest)
        tmpl_rest = re.sub(r"\?.*$", "", tmpl_rest)

        return port, f"{scheme}{tmpl_authority}{tmpl_rest}", url_components

    # Fallback: jdbc:scheme:path (no authority) — e.g. jdbc:sqlite:/path, jdbc:h2:file:/path
    m2 = re.match(r"(jdbc:[^:]+:)(.+)", jdbc_url, re.IGNORECASE)
    if m2:
        scheme = m2.group(1)
        path = m2.group(2)
        # Only treat as a "database" path if it looks like a file path (not mem:/in-memory)
        if re.match(r"[/.]", path) or re.match(r"file:", path, re.IGNORECASE):
            url_components.add("database")
            tmpl_path = re.sub(r"^[^?#]+", "{database}", path)
            return None, f"{scheme}{tmpl_path}", url_components

    return None, "", url_components


# Known Spark built-in JdbcDialect implementations (package org.apache.spark.sql.jdbc).
#
# NO trailing '$' on these. Spark's built-in dialects are case CLASSES, so `PostgresDialect$`
# resolves to the companion object (a scala.runtime.AbstractFunction0 factory) which does NOT
# extend JdbcDialect — CatalogValidation.dialectClassErrors rejects it with "class does not
# extend org.apache.spark.sql.jdbc.JdbcDialect" and the whole driver catalog fails to load.
# Qualytics' own dialects (io.qualytics.dataplane.datastores.dialects.*) ARE Scala objects and
# do require the '$'; the two conventions are not interchangeable.
_SPARK_BUILTIN_DIALECTS: dict[str, str] = {
    "postgresql": "org.apache.spark.sql.jdbc.PostgresDialect",
    "mysql": "org.apache.spark.sql.jdbc.MySQLDialect",
    "mariadb": "org.apache.spark.sql.jdbc.MySQLDialect",
    "oracle": "org.apache.spark.sql.jdbc.OracleDialect",
    "sqlserver": "org.apache.spark.sql.jdbc.MsSqlServerDialect",
    "jtds": "org.apache.spark.sql.jdbc.MsSqlServerDialect",
    "db2": "org.apache.spark.sql.jdbc.DB2Dialect",
    "derby": "org.apache.spark.sql.jdbc.DerbyDialect",
    "teradata": "org.apache.spark.sql.jdbc.TeradataDialect",
}

# Mapping from a detected row-limit idiom to its sql.clauses closed-vocab token.
# The dataplane view-sampling renderer (SqlCapabilityRenderer.rowSampleSuffix) gates random
# sampling on BOTH a function (RANDOM/RAND/NEWID/DBMS_RANDOM_VALUE) AND the matching row-limit
# clause, so the idiom must be declared in sql.clauses in addition to the rowLimitStyle config
# field. Mirrors the built-in drivers: postgresql/redshift/mysql/snowflake → LIMIT, sqlserver →
# OFFSET_FETCH, oracle → ROWNUM, db2 → OFFSET_FETCH.
_ROW_LIMIT_CLAUSE_TOKEN: dict[str, str] = {
    "LIMIT": "LIMIT",
    "FETCH_FIRST": "OFFSET_FETCH",
    "TOP": "OFFSET_FETCH",
    "ROWNUM": "ROWNUM",
}

# Mapping from Java probe tableSampleTemplate strings to v2 closed-vocab clause tokens
_TABLESAMPLE_TOKEN_MAP: dict[str, str] = {
    "TABLESAMPLE SYSTEM ({pct})": "TABLESAMPLE_SYSTEM",
    "TABLESAMPLE BERNOULLI ({pct})": "TABLESAMPLE_BERNOULLI",
    "TABLESAMPLE SYSTEM ({pct} PERCENT)": "TABLESAMPLE_SYSTEM_PERCENT",
    "TABLESAMPLE ({pct})": "TABLESAMPLE_PERCENT",
    "SAMPLE ({pct})": "SAMPLE_PERCENT",
    "SAMPLE ({pct} PERCENT)": "SAMPLE_PERCENT",
}

# ---------------------------------------------------------------------------
# Dataplane v2 closed vocabularies — canonical case-sensitive enum values
# ---------------------------------------------------------------------------
VALID_TRANSACTION_ISOLATION: frozenset[str] = frozenset(
    {"NONE", "READ_UNCOMMITTED", "READ_COMMITTED", "REPEATABLE_READ", "SERIALIZABLE"}
)
VALID_TABLE_NAME_CASING: frozenset[str] = frozenset({"UPPER", "LOWER", "AS_IS"})
VALID_ROW_LIMIT_STYLE: frozenset[str] = frozenset(
    {"LIMIT", "TOP", "ROWNUM", "FETCH_FIRST"}
)
VALID_TIMESTAMP_LITERAL_STYLE: frozenset[str] = frozenset(
    {
        "PLAIN",
        "TIMESTAMP_PREFIX",
        "CAST_DATETIME2",
        "TO_TIMESTAMP",
        "CAST_AS_TIMESTAMP",
        "CAST_DATE_FORMAT",
    }
)
VALID_DATE_LITERAL_STYLE: frozenset[str] = frozenset(
    {"PLAIN", "DATE_PREFIX", "TO_DATE"}
)
VALID_SQL_FUNCTIONS: frozenset[str] = frozenset(
    {
        "APPROX_COUNT_DISTINCT",
        "APPROX_DISTINCT",
        "RANDOM",
        "RAND",
        "NEWID",
        "DBMS_RANDOM_VALUE",
    }
)
VALID_SQL_CLAUSES: frozenset[str] = frozenset(
    {
        "TABLESAMPLE_SYSTEM",
        "TABLESAMPLE_SYSTEM_PERCENT",
        "TABLESAMPLE_BERNOULLI",
        "TABLESAMPLE_PERCENT",
        "TABLESAMPLE_ROWS",
        "SAMPLE_PERCENT",
        "SAMPLE_ROWS",
        "LIMIT",
        "OFFSET_FETCH",
        "ROWNUM",
    }
)
VALID_SCHEMA_ONLY: frozenset[str] = frozenset(
    {
        "CTE",
        "PG_CTE",
        "SQLSERVER_TOP0",
        "WHERE_FALSE_QUERYA",
        "ORACLE_WHERE_FALSE",
        "HIVE_LIMIT0",
    }
)
VALID_ROW_COUNT: frozenset[str] = frozenset(
    {
        "COUNT_STAR",
        "BQ_TABLES",
        "INFORMATION_SCHEMA_ROW_COUNT",
        "INFORMATION_SCHEMA_TABLES_WITH_SIZE",
        "ALL_TABLES",
    }
)


def _detect_dialect_class(prefix: str, jar_path: str) -> str | None:
    """
    Return the fully-qualified JdbcDialect class name to use for dialectClass, or None.

    Priority:
      1. Driver JAR ServiceLoader registration:
         META-INF/services/org.apache.spark.sql.jdbc.JdbcDialect
      2. Known Spark built-in dialect for this JDBC prefix.
    """
    import zipfile as _zf

    # 1. Scan the JAR for a ServiceLoader registration file
    try:
        with _zf.ZipFile(jar_path, "r") as zf:
            service_entry = "META-INF/services/org.apache.spark.sql.jdbc.JdbcDialect"
            if service_entry in zf.namelist():
                content = (
                    zf.read(service_entry).decode("utf-8", errors="replace").strip()
                )
                # Take the first non-comment, non-blank line
                for line in content.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        return line
    except Exception:
        pass  # JAR unreadable or not a zip — fall through

    # 2. Static built-in lookup by prefix
    return _SPARK_BUILTIN_DIALECTS.get(prefix.lower())


def _build_yaml(
    prefix: str,
    probes: dict,
    jdbc_url: str,
    *,
    dialect_class: str | None = None,
) -> tuple[str, list[str], list[str]]:
    """
    Build the complete YAML content string from the probes dict.

    Follows canonical DriverDefinition key ordering.  Only emits keys that
    differ from their DriverDefinition defaults — plus required fields and
    any TODO fields that need manual/LLM review.

    Fields marked '# auto-detected' were probed from the live database.
    Fields marked '# TODO: ...' need manual review — the comment describes the
    field, its valid values, and what the LLM should consider when filling it in.
    """

    detected_fields: list[str] = []
    todo_fields: list[str] = []

    def _render(value) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return str(value).lower()
        if isinstance(value, int):
            return str(value)
        sv = str(value)
        if sv == "null":
            return "null"
        if any(
            c in sv
            for c in [
                ":",
                "#",
                "[",
                "]",
                "{",
                "}",
                ",",
                "&",
                "*",
                "?",
                "|",
                "-",
                "<",
                ">",
                "=",
                "!",
                "%",
                "@",
                "`",
                '"',
                "'",
                "\n",
            ]
        ):
            dumped = yaml.dump(sv, default_flow_style=True).strip()
            # yaml.dump may append a YAML document-end marker on a new line — strip it
            if "\n" in dumped:
                dumped = dumped.split("\n")[0]
            return dumped
        return sv

    _indent = [""]  # mutable — set to "  " inside config: section

    def field(name: str, value, comment: str = "") -> str:
        comment_str = f"  # {comment}" if comment else ""
        return f"{_indent[0]}{name}: {_render(value)}{comment_str}"

    def _sec(text: str) -> str:
        """Section comment with current indentation."""
        return f"{_indent[0]}{text}"

    lines: list[str] = []

    # ── Derive URL metadata ─────────────────────────────────────────────────
    default_port, jdbc_url_template, url_components = _derive_url_metadata(jdbc_url)
    # `config.url.template` is required and its placeholders must be backed by
    # connectionSpec fields. When the probe URL doesn't fit either recognised shape (e.g.
    # Oracle's `jdbc:oracle:thin:@host:port/service`), fall back to the conventional
    # host/port/database triple so the template and the form fields stay in agreement —
    # a TODO the operator corrects, rather than an unparseable file.
    if not jdbc_url_template:
        jdbc_url_template = f"jdbc:{prefix}://{{host}}:{{port}}/{{database}}"
        url_components |= {"host", "port", "database"}
        url_template_is_guess = True
    else:
        url_template_is_guess = False
    db_product_name = probes.get("dbProductName")
    display_name = (
        db_product_name
        if db_product_name and db_product_name not in (None, "null")
        else prefix.capitalize()
    )

    # ── Header ──────────────────────────────────────────────────────────────
    lines.append(
        textwrap.dedent(f"""\
        # Generated by: qualytics generate-driver
        #
        # "# auto-detected"  — probed from the live JDBC connection.
        # "# TODO: …"        — could not be auto-detected; fill in before deploying.
        #                       Comment describes the field, valid values, and intent.
        # "# LLM-suggested"  — filled in by the deployment LLM (review before use).
        #
        # Custom JDBC drivers in Qualytics support SOURCE datastores only (read access).
        # Excluded write-only field: insertBatchSize.
        # Optional keys equal to their DriverDefinition default are omitted to keep this file
        # concise; required keys are always emitted. An optional key is omitted (or shown
        # commented out) rather than set to null — an explicit null is a parse error.
        #
        # Deploy this file to:  META-INF/jdbc-drivers/{prefix}.yaml
        """)
    )

    # ── Spark JdbcDialect (top-level) ────────────────────────────────────────
    # Only `config`, `sql` and `dialectClass` are accepted at the top level, and
    # `dialectClass` must be a non-empty FQCN when present — an explicit null is a parse
    # error, so the undetected case emits a commented-out stub instead of `null`.
    lines.append(
        "# ── Spark JdbcDialect ────────────────────────────────────────────────"
    )
    if dialect_class is not None:
        lines.append(
            field(
                "dialectClass",
                dialect_class,
                "Auto-detected Spark JdbcDialect subclass",
            )
        )
        detected_fields.append("dialectClass")
    else:
        lines.append(
            "# TODO: dialectClass — fully-qualified Spark JdbcDialect implementation. A Scala"
        )
        lines.append(
            "# `object` needs the trailing '$' (com.example.MyDialect$); a class does NOT"
        )
        lines.append(
            "# (com.example.MyDialect). The wrong form fails catalog load with 'class does not"
        )
        lines.append(
            "# extend org.apache.spark.sql.jdbc.JdbcDialect'. Leave commented out if the driver"
        )
        lines.append("# needs no custom Spark dialect.")
        lines.append("# dialectClass: com.example.MyDialect$")
        todo_fields.append("dialectClass")
    lines.append("")

    # ══════════════════════════════════════════════════════════════════════════
    # config: section — all non-SQL configuration fields
    # ══════════════════════════════════════════════════════════════════════════
    lines.append("config:")
    _indent[0] = "  "

    # ── Identity ─────────────────────────────────────────────────────────────
    # prefix and className are config fields, not top-level keys.
    lines.append(
        _sec("# ── Identity ─────────────────────────────────────────────────────────")
    )
    lines.append(
        field(
            "prefix",
            prefix,
            "review — must match the jdbc:<prefix>: scheme in the JDBC URL, and the "
            "filename must be <prefix>.yaml",
        )
    )
    todo_fields.append("prefix")
    lines.append(
        field(
            "className",
            probes.get("className"),
            "auto-detected — fully-qualified JDBC Driver class name",
        )
    )
    detected_fields.append("className")

    # ── SQL dialect (config fields) ──────────────────────────────────────────
    lines.append(
        _sec("# ── SQL dialect ──────────────────────────────────────────────────────")
    )

    # displayName — always emit (default is raw prefix; capitalised form is user-friendly)
    lines.append(
        field(
            "displayName",
            display_name,
            "auto-detected from DB product name — human-readable name shown in the UI",
        )
    )
    detected_fields.append("displayName")

    # defaultPort — emit only when probe URL contained an explicit port number.
    # If the driver uses a portless URL scheme (e.g. jdbc:sqlite:, jdbc:h2:mem:),
    # leave as TODO so the user knows to set it (or omit if the driver truly has no port).
    if default_port is not None:
        lines.append(
            field(
                "defaultPort",
                default_port,
                "auto-detected from JDBC URL — default port shown in the connection form",
            )
        )
        detected_fields.append("defaultPort")
    else:
        # `defaultPort: null` is a parse error ("omit the key to use the default"), so the
        # undetected case is emitted commented out.
        lines.append(
            f"{_indent[0]}# defaultPort: 5432"
            "  # TODO: default TCP port (e.g. 5432 PostgreSQL, 3306 MySQL, "
            "1521 Oracle, 1433 SQL Server); leave commented out if this driver "
            "does not use TCP ports"
        )
        todo_fields.append("defaultPort")

    # transactionIsolation — REQUIRED by the parser, so always emit it even when it equals
    # the DriverConfig default.
    tx = probes.get("transactionIsolation") or "READ_UNCOMMITTED"
    lines.append(
        field(
            "transactionIsolation",
            tx,
            "auto-detected — valid: NONE, READ_UNCOMMITTED, READ_COMMITTED, "
            "REPEATABLE_READ, SERIALIZABLE",
        )
    )
    detected_fields.append("transactionIsolation")

    # identifierQuoteChar — omit if " (default)
    quote_char = probes.get("identifierQuoteChar")
    if quote_char and quote_char != '"':
        lines.append(
            field(
                "identifierQuoteChar",
                quote_char,
                'auto-detected — char used to quote identifiers; default " — MySQL/MariaDB use `',
            )
        )
        detected_fields.append("identifierQuoteChar")
    elif quote_char:
        detected_fields.append("identifierQuoteChar")  # default — omitted

    # tableNameCasing — REQUIRED by the parser, so always emit it even when it equals the
    # DriverConfig default.
    casing = probes.get("tableNameCasing", "AS_IS")
    lines.append(
        field(
            "tableNameCasing",
            casing,
            "auto-detected — valid: UPPER (DB2/Oracle), LOWER (PostgreSQL), "
            "AS_IS (most others)",
        )
    )
    detected_fields.append("tableNameCasing")

    # rowLimitStyle — omit if LIMIT (default); TODO if probe couldn't determine.
    # FETCH_FIRST is a rowLimitStyle arm in its own right; it additionally maps to the
    # OFFSET_FETCH sql.clauses token (see _ROW_LIMIT_CLAUSE_TOKEN below).
    row_limit = probes.get("rowLimitStyle")
    if row_limit and row_limit != "LIMIT":
        lines.append(
            field(
                "rowLimitStyle",
                row_limit,
                "auto-detected — valid: LIMIT (default), TOP (SQL Server), "
                "ROWNUM (Oracle), FETCH_FIRST (Db2)",
            )
        )
        detected_fields.append("rowLimitStyle")
    elif row_limit == "LIMIT":
        detected_fields.append("rowLimitStyle")  # default — omitted
    else:
        lines.append(
            field(
                "rowLimitStyle",
                "LIMIT",
                "TODO: valid: LIMIT (default, MySQL/PG/SQLite), TOP (SQL Server), "
                "ROWNUM (Oracle), FETCH_FIRST (Db2)",
            )
        )
        todo_fields.append("rowLimitStyle")

    # subqueryAlias — omit if true (default); emit false if probe confirmed no alias needed
    sub_alias = probes.get("subqueryAlias", True)
    if isinstance(sub_alias, str):
        sub_alias = sub_alias.lower() != "false"
    if not sub_alias:
        lines.append(
            field(
                "subqueryAlias",
                False,
                "auto-detected — false: subqueries do NOT need an AS alias "
                "(rare; historically Oracle)",
            )
        )
        detected_fields.append("subqueryAlias")
    else:
        detected_fields.append("subqueryAlias")  # default true — omitted

    # timestampLiteralStyle — omit if PLAIN (default)
    ts_style = probes.get("timestampLiteralStyle", "PLAIN")
    if ts_style != "PLAIN":
        lines.append(
            field(
                "timestampLiteralStyle",
                ts_style,
                "auto-detected — valid: PLAIN (default), TIMESTAMP_PREFIX (standard SQL), "
                "CAST_AS_TIMESTAMP (Hive), CAST_DATE_FORMAT (Databricks), "
                "TO_TIMESTAMP (Oracle), CAST_DATETIME2 (SQL Server)",
            )
        )
        detected_fields.append("timestampLiteralStyle")
    else:
        detected_fields.append("timestampLiteralStyle")  # default — omitted
    # timestampLiteralTemplate: escape hatch — omit unless enum styles are insufficient

    # dateLiteralStyle — omit if PLAIN (default)
    dt_style = probes.get("dateLiteralStyle", "PLAIN")
    if dt_style != "PLAIN":
        lines.append(
            field(
                "dateLiteralStyle",
                dt_style,
                "auto-detected — valid: PLAIN (default), DATE_PREFIX, TO_DATE (Oracle)",
            )
        )
        detected_fields.append("dateLiteralStyle")
    else:
        detected_fields.append("dateLiteralStyle")  # default — omitted
    # dateLiteralTemplate: escape hatch — omit unless enum styles are insufficient

    # connectionTest — omit if SELECT 1 (default)
    val_q = probes.get("connectionTest")
    if val_q and val_q != "SELECT 1":
        lines.append(
            field(
                "connectionTest",
                val_q,
                "auto-detected — minimal SQL to test a pooled connection is alive",
            )
        )
        detected_fields.append("connectionTest")
    elif val_q:
        detected_fields.append("connectionTest")  # default — omitted
    else:
        lines.append(
            field(
                "connectionTest",
                "SELECT 1",
                "TODO: SQL to verify a live connection; try SELECT 1 FROM DUAL (Oracle), "
                "VALUES 1 (DB2/H2)",
            )
        )
        todo_fields.append("connectionTest")

    lines.append("")

    # ── Schema / catalog filtering ────────────────────────────────────────────
    lines.append(
        _sec("# ── Schema / catalog filtering ───────────────────────────────────────")
    )
    lines.append(
        f"{_indent[0]}systemSchemaExclusions: []"
        "      # TODO: exact schema names to exclude from catalog scans "
        "(e.g. [information_schema, pg_catalog])"
    )
    lines.append(
        f"{_indent[0]}systemSchemaExclusionPrefixes: []"
        "  # TODO: schema name prefixes to exclude (e.g. [pg_temp_, pg_toast_temp_])"
    )
    lines.append(
        f"{_indent[0]}systemCatalogExclusions: []"
        "     # TODO: catalog names to exclude "
        "(e.g. [admin, local, config] for MongoDB; [information_schema, mysql] for MySQL)"
    )
    todo_fields += [
        "systemSchemaExclusions",
        "systemSchemaExclusionPrefixes",
        "systemCatalogExclusions",
    ]

    # getTablesUsesNullCatalog — omit if false (default); emit if true
    get_tables_null = probes.get("getTablesUsesNullCatalog", False)
    if isinstance(get_tables_null, str):
        get_tables_null = get_tables_null.lower() == "true"
    if get_tables_null:
        lines.append(
            field(
                "getTablesUsesNullCatalog",
                True,
                "auto-detected — pass null as catalog arg to DatabaseMetaData.getTables(); "
                "required for Db2",
            )
        )
        detected_fields.append("getTablesUsesNullCatalog")
    else:
        detected_fields.append("getTablesUsesNullCatalog")  # default false — omitted
    lines.append("")

    # ── Connectivity ──────────────────────────────────────────────────────────
    lines.append(
        _sec("# ── Connectivity ─────────────────────────────────────────────────────")
    )
    lines.append(
        field(
            "networkCapable",
            True,
            "default true — set false for embedded/file-based drivers "
            "(e.g. SQLite, H2 embedded) that need no network host",
        )
    )
    lines.append(
        field(
            "readOnly",
            False,
            "default false — set true if this driver cannot write "
            "(e.g. read-only replicas, analytical engines)",
        )
    )
    lines.append(
        field(
            "supportsLongLimit",
            False,
            "default false — set true if LIMIT/TOP accepts values > Integer.MAX_VALUE "
            "(2^31-1); needed for databases with very large tables",
        )
    )
    # An explicit `null` is a parse error ("omit the key to use the default"), so the
    # unset case is emitted commented out.
    lines.append(
        f"{_indent[0]}# defaultInsertBatchSize: 1000"
        "  # optional: override the default JDBC batch size for INSERT "
        "statements; omit the key entirely to use the platform default"
    )
    lines.append(
        f"{_indent[0]}connectionProperties: {{}}"
        "        # TODO: key-value pairs injected into JDBC pool and Spark "
        "(e.g. {ssl: 'true', charset: 'utf8'})"
    )
    lines.append(
        f"{_indent[0]}connectionPropertyMappings: {{}}"
        "  # optional: map connection form field names to JDBC property keys "
        "(e.g. {username: user, database: databaseName})"
    )
    lines.append(
        f"{_indent[0]}sessionInitStatements: []"
        "       # TODO: SQL statements run once after each new connection "
        '(e.g. ["SET SCHEMA mydb", "ALTER SESSION SET NLS_DATE_FORMAT=\'YYYY-MM-DD\'"])'
    )
    todo_fields += ["connectionProperties", "sessionInitStatements"]
    lines.append("")

    # ── URL construction ──────────────────────────────────────────────────────
    lines.append(
        _sec("# ── URL construction ─────────────────────────────────────────────────")
    )
    lines.append(
        _sec(
            "# Known placeholders: {host}, {port}, {database}, {schema}, {username}, {password}"
        )
    )
    ind = _indent[0]  # shorthand — currently "  " inside config:
    url_ind = ind + "  "  # one level deeper for url: sub-keys
    lines.append(f"{ind}url:")
    if url_template_is_guess:
        lines.append(
            f"{url_ind}template: {_render(jdbc_url_template)}"
            "  # TODO: could not derive a template from the probe URL — this is a "
            "conventional guess. Correct it to this driver's real URL shape "
            "(e.g. jdbc:oracle:thin:@{host}:{port}/{database}); every placeholder "
            "must match a connectionSpec field name"
        )
        todo_fields.append("template")
    else:
        lines.append(
            f"{url_ind}template: {_render(jdbc_url_template)}"
            "  # auto-detected from probe URL — verify all placeholders are correct"
        )
        detected_fields.append("template")
    lines.append(
        f"{url_ind}staticParams: []"
        "      # TODO: query params always appended to every URL "
        "(e.g. [tcpKeepAlive=true, sslmode=prefer])"
    )
    lines.append(
        f"{url_ind}conditionalParams: []"
        "  # TODO: params appended only when a form field is non-empty "
        "(e.g. [{key: schema, param: 'currentSchema={schema}'}])"
    )
    lines.append(
        f"{url_ind}authVariants: {{}}"
        "      # optional: auth_type -> full URL template override; leave empty if not needed"
    )
    # paramSeparator only accepts ';' or ','. Query style (`?` then `&`) is the default and
    # is NOT declarable — emitting '&' is a parse error, so the default case stays commented.
    lines.append(
        f"{url_ind}# paramSeparator: ';'"
        "  # optional: only ';' or ',' — omit for the default query style (?/&)"
    )
    todo_fields += ["staticParams", "conditionalParams"]
    lines.append("")

    # ── Connection spec ────────────────────────────────────────────────────────
    # Only mark a field required if the probe URL actually contained that component.
    # e.g. jdbc:sqlite:/path/to/db has no host or port → those fields are optional.
    ind = _indent[0]  # shorthand for current indentation
    lines.append(
        _sec("# ── Connection spec (frontend form) ──────────────────────────────────")
    )
    lines.append(f"{ind}# TODO: define the connection form fields shown in the UI.")
    lines.append(
        f"{ind}# Each field: name, label, fieldType (string/integer/boolean/password/enum/file),"
    )
    lines.append(
        f"{ind}#             required, defaultValue, hint, options (for enum),"
    )
    lines.append(f"{ind}#             aliases (list of alternate field names),")
    lines.append(
        f"{ind}#             dependsOn, dependsOnValues (list of values that activate this field)"
    )
    lines.append(f"{ind}connectionSpec:")
    lines.append(f"{ind}  supportsEnrichment: false  # custom drivers are source-only")
    lines.append(f"{ind}  fields:")
    if "host" in url_components:
        lines.append(f"{ind}    - name: host")
        lines.append(f'{ind}      label: "Host"')
        lines.append(f"{ind}      fieldType: string")
        lines.append(f"{ind}      required: true")
        lines.append(f"{ind}      aliases: []  # optional alternate field names")
    if "port" in url_components:
        lines.append(f"{ind}    - name: port")
        lines.append(f'{ind}      label: "Port"')
        lines.append(f"{ind}      fieldType: integer")
        lines.append(f"{ind}      required: true")
        if default_port is not None:
            lines.append(f'{ind}      defaultValue: "{default_port}"')
        lines.append(f"{ind}      aliases: []  # optional alternate field names")
    if "database" in url_components:
        lines.append(f"{ind}    - name: database")
        lines.append(f'{ind}      label: "Database"')
        lines.append(f"{ind}      fieldType: string")
        lines.append(f"{ind}      required: true")
        lines.append(f"{ind}      aliases: []  # optional alternate field names")
    # schema — optional form field, emitted when the DB organises tables into schemas
    # (probe: DatabaseMetaData.getSchemas). Required to back any {schema} URL placeholder /
    # conditionalParam: the dataplane catalog validator rejects a {schema} reference with no
    # matching connectionSpec field. Left as a conditional (required: false, no default) field.
    supports_schemas = probes.get("supportsSchemas", False)
    if isinstance(supports_schemas, str):
        supports_schemas = supports_schemas.lower() == "true"
    if supports_schemas:
        lines.append(f"{ind}    - name: schema")
        lines.append(f'{ind}      label: "Schema"')
        lines.append(f"{ind}      fieldType: string")
        lines.append(f"{ind}      required: false")
        lines.append(f"{ind}      aliases: []  # optional alternate field names")
    lines.append(f"{ind}    - name: username")
    lines.append(f'{ind}      label: "Username"')
    lines.append(f"{ind}      fieldType: string")
    lines.append(f"{ind}      required: true")
    lines.append(f"{ind}      aliases: []  # optional alternate field names")
    lines.append(f"{ind}    - name: password")
    lines.append(f'{ind}      label: "Password"')
    lines.append(f"{ind}      fieldType: password")
    lines.append(f"{ind}      required: true")
    lines.append(f"{ind}      aliases: []  # optional alternate field names")
    todo_fields.append("connectionSpec")

    # ══════════════════════════════════════════════════════════════════════════
    # End of config: section — reset indentation
    # ══════════════════════════════════════════════════════════════════════════
    _indent[0] = ""
    lines.append("")

    # ══════════════════════════════════════════════════════════════════════════
    # sql: section — SQL capabilities organized by type
    # ══════════════════════════════════════════════════════════════════════════
    lines.append("sql:")
    _indent[0] = "  "

    # ── sql.functions — capability tokens (list) ─────────────────────────
    lines.append(
        _sec("# ── SQL functions ────────────────────────────────────────────────")
    )
    lines.append(
        _sec(
            "# Closed vocab: APPROX_COUNT_DISTINCT, APPROX_DISTINCT, RANDOM, "
            "RAND, NEWID, DBMS_RANDOM_VALUE"
        )
    )

    func_entries: list[tuple[str, str]] = []  # (token, comment)

    # approxCountDistinctFunction → entry in sql.functions list
    approx = probes.get("approxCountDistinctFunction")
    if approx and approx != "null":
        func_entries.append((approx, "auto-detected — approximate COUNT DISTINCT"))
        detected_fields.append("approxCountDistinctFunction")
    else:
        detected_fields.append("approxCountDistinctFunction")  # null — omitted

    # viewSampleFallback → entry in sql.functions list. The dataplane view-sampling renderer pairs
    # this function with the row-limit clause (RANDOM/RAND + LIMIT, NEWID + OFFSET_FETCH,
    # DBMS_RANDOM_VALUE + ROWNUM), so it must always be emitted when the probe detected one — there
    # is no implicit default. RAND is a real detected value (MySQL/MariaDB), not a sentinel.
    vsf = probes.get("viewSampleFallback")
    if vsf and vsf != "null":
        func_entries.append((vsf, "auto-detected — random function for view sampling"))
        detected_fields.append("viewSampleFallback")
    else:
        detected_fields.append("viewSampleFallback")  # none detected — omitted

    ind_sql = _indent[0]  # "  " inside sql:
    if func_entries:
        lines.append(f"{ind_sql}functions:")
        for token, comment in func_entries:
            lines.append(f"{ind_sql}  - {token}  # {comment}")
    else:
        lines.append(f"{ind_sql}functions: []")

    # ── sql.clauses — capability tokens (list) ──────────────────────────────
    lines.append(
        _sec("# ── SQL clauses ──────────────────────────────────────────────────")
    )
    lines.append(
        _sec(
            "# Closed vocab: TABLESAMPLE_SYSTEM, TABLESAMPLE_SYSTEM_PERCENT, "
            "TABLESAMPLE_BERNOULLI, TABLESAMPLE_PERCENT, TABLESAMPLE_ROWS, "
            "SAMPLE_PERCENT, SAMPLE_ROWS, LIMIT, OFFSET_FETCH, ROWNUM"
        )
    )

    clause_entries: list[tuple[str, str]] = []  # (token, comment)

    # Row-limit idiom → sql.clauses token. The dataplane view-sampling renderer gates random
    # sampling on a (function, row-limit clause) pair, so the idiom is declared here in addition
    # to the rowLimitStyle config field. An undetected idiom defaults to LIMIT (the dataplane
    # default), matching the rowLimitStyle TODO fallback above.
    effective_row_limit = row_limit if (row_limit and row_limit != "null") else "LIMIT"
    row_limit_token = _ROW_LIMIT_CLAUSE_TOKEN.get(effective_row_limit)
    if row_limit_token:
        clause_entries.append(
            (
                row_limit_token,
                f"auto-detected — {effective_row_limit} row-limit idiom "
                "(declared so view-sampling can pair it with a random function)",
            )
        )

    # tableSampleTemplate → entry in sql.clauses list
    sample_tmpl = probes.get("tableSampleTemplate")
    if sample_tmpl and sample_tmpl != "null":
        token = _TABLESAMPLE_TOKEN_MAP.get(sample_tmpl, sample_tmpl)
        clause_entries.append((token, "auto-detected — table sampling strategy"))
        detected_fields.append("tableSampleTemplate")
    else:
        detected_fields.append("tableSampleTemplate")  # null/not supported — omitted

    if clause_entries:
        lines.append(f"{ind_sql}clauses:")
        for token, comment in clause_entries:
            lines.append(f"{ind_sql}  - {token}  # {comment}")
    else:
        lines.append(f"{ind_sql}clauses: []")

    # ── sql.queries — per-slot SQL overrides ────────────────────────────────
    # Every slot value is a FULL, single-statement, read-only SQL string using only that
    # slot's placeholders — not a strategy token. The parser validates placeholders and
    # rejects DML/DDL keywords and ';', but it cannot tell a token from SQL: emitting a
    # bare token like `schemaOnly: PG_CTE` parses cleanly and then ships that literal
    # string to the database at query time. So the probed style is carried as a comment
    # hint and every slot is emitted commented out — omitting a slot uses the dataplane's
    # composed default, which is correct for most drivers.
    schema_only = probes.get("schemaOnly", "CTE")
    row_count_style = probes.get("rowCount", "COUNT_STAR")
    detected_fields += ["schemaOnly", "rowCount"]

    lines.append(
        _sec("# ── SQL queries ──────────────────────────────────────────────────")
    )
    for line in (
        "# Optional per-slot overrides of the vendor metadata fast-paths. Each value is a",
        "# full read-only SQL statement (single statement, no ';'). Omit a slot to use the",
        "# dataplane's composed default. Allowed placeholders per slot:",
        "#   schemaOnly      {query}                        wrap a query to return 0 rows",
        "#   rowCount        {schema} {table}               -> one numeric column",
        "#   volume          {schema} {database} {table}    -> row_count, size_bytes",
        "#   freshness       {schema} {table} {qualifiedTable} -> one timestamp",
        "#   partitionColumn {schema} {table}               -> partitioning_column",
        "#   lineage         {schema}                       -> source/target edges",
        "#",
        f"# Probe hints (NOT valid SQL — do not paste verbatim): schemaOnly={schema_only},",
        f"# rowCount={row_count_style}. Translate these into real SQL for this engine, or",
        "# leave every slot out and take the defaults.",
        "#",
        "# schemaOnly: SELECT TOP 0 QUERYA.* FROM ({query}) AS QUERYA",
        "# rowCount: SELECT NUM_ROWS FROM ALL_TABLES WHERE OWNER = '{schema}' AND TABLE_NAME = '{table}'",
        "# volume: SELECT ROW_COUNT, BYTES FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = '{schema}' AND TABLE_NAME = '{table}'",
        "# freshness: SELECT LAST_ALTERED FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = '{schema}' AND TABLE_NAME = '{table}'",
    ):
        lines.append(_sec(line))
    lines.append(_sec("queries: {}"))
    _indent[0] = "    "

    # ══════════════════════════════════════════════════════════════════════════
    # End of sql: section — reset indentation
    # ══════════════════════════════════════════════════════════════════════════
    _indent[0] = ""
    lines.append("")

    return "\n".join(lines) + "\n", detected_fields, todo_fields


# ---------------------------------------------------------------------------
# LLM-assisted TODO resolution helpers
# ---------------------------------------------------------------------------


def _strip_jdbc_credentials(jdbc_url: str) -> str:
    """Remove user/password from a JDBC URL for safe inclusion in prompts."""
    cleaned = re.sub(r"(jdbc:[^:]+://)([^@/]+@)", r"\1", jdbc_url)
    cleaned = re.sub(
        r"[?&](password|passwd|pwd)=[^&]*", "", cleaned, flags=re.IGNORECASE
    )
    return cleaned


def _collect_todo_fields(yaml_content: str) -> list[tuple[str, str, str]]:
    """
    Scan YAML lines for remaining TODO comments.
    Returns list of (field_name, current_value, todo_description).
    Handles both top-level and indented (config:) fields.
    """
    todos = []
    for line in yaml_content.splitlines():
        m = re.match(r"^\s*(\w+):\s*(.+?)\s*#\s*TODO:\s*(.+)$", line)
        if m:
            todos.append((m.group(1), m.group(2).strip(), m.group(3).strip()))
    return todos


def _call_deployment_llm(client, prompt: str) -> str | None:
    """
    POST to agent/chat and collect the streamed SSE response.
    Returns the full concatenated text, or None if the call fails.
    """
    try:
        response = client.post(
            "agent/chat",
            json={"messages": [{"role": "user", "content": prompt}]},
            stream=True,
            timeout=120,
        )
        text_parts: list[str] = []
        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            if raw_line.startswith("data: "):
                data = raw_line[6:]
                if data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                    if isinstance(event, dict) and event.get("type") == "text-delta":
                        text_parts.append(
                            event.get("textDelta") or event.get("delta") or ""
                        )
                except json.JSONDecodeError:
                    # Vercel AI SDK compact format: 0:"chunk"
                    if re.match(r'^0:"', data):
                        try:
                            text_parts.append(json.loads(data[2:]))
                        except json.JSONDecodeError:
                            pass
        return "".join(text_parts) if text_parts else None
    except Exception:
        return None


def _apply_llm_suggestions(yaml_content: str, suggestions: dict) -> tuple[str, int]:
    """
    Substitute LLM-suggested values into YAML content, replacing TODO lines.
    suggestions: {field_name: {"value": ..., "rationale": "..."}}
    Returns (updated_content, count_applied).
    Handles both top-level and indented (config:) fields.
    """
    applied = 0
    result_lines: list[str] = []
    for line in yaml_content.splitlines(keepends=True):
        m = re.match(r"^(\s*)(\w+):\s*(.+?)\s*#\s*TODO:.*$", line)
        if m and m.group(2) in suggestions:
            leading_ws = m.group(1)
            field_name = m.group(2)
            suggestion = suggestions[field_name]
            value = suggestion.get("value")
            rationale = str(suggestion.get("rationale", "")).replace("\n", " ").strip()
            if value is not None:
                if isinstance(value, (list, dict)):
                    yaml_val = (
                        yaml.dump(value, default_flow_style=True).strip().rstrip("\n")
                    )
                elif isinstance(value, bool):
                    yaml_val = str(value).lower()
                elif isinstance(value, (int, float)):
                    yaml_val = str(value)
                else:
                    sv = str(value)
                    if any(c in sv for c in [":", "#", "[", "]", "{", "}", ","]):
                        yaml_val = yaml.dump(sv, default_flow_style=True).strip()
                    else:
                        yaml_val = sv
                result_lines.append(
                    f"{leading_ws}{field_name}: {yaml_val}  # LLM-suggested: {rationale}\n"
                )
                applied += 1
                continue
        result_lines.append(line)
    return "".join(result_lines), applied


# ---------------------------------------------------------------------------
# Index management helpers
# ---------------------------------------------------------------------------

_DEFAULT_DRIVERS_DIR = os.path.join("dist", "META-INF", "jdbc-drivers")


def _update_index(drivers_dir: str, yaml_filename: str) -> bool:
    """
    Create or update the ``index`` file in *drivers_dir*, adding *yaml_filename*
    if it is not already present.  Returns True if the index was modified.
    """
    index_path = os.path.join(drivers_dir, "index")
    existing: list[str] = []
    if os.path.isfile(index_path):
        with open(index_path) as fh:
            existing = [line.rstrip("\n") for line in fh if line.strip()]
    if yaml_filename in existing:
        return False
    existing.append(yaml_filename)
    with open(index_path, "w") as fh:
        fh.write("\n".join(existing) + "\n")
    return True


# ---------------------------------------------------------------------------
# CLI commands — drivers group
# ---------------------------------------------------------------------------

drivers_app = typer.Typer(
    name="drivers",
    help="Manage pluggable JDBC drivers for Qualytics.",
)
add_suggestion_callback(drivers_app, "drivers")


@drivers_app.command("generate")
def generate_driver(
    ctx: typer.Context,
    jar: Annotated[
        str,
        typer.Option(
            "--jar",
            help="Path to the JDBC driver JAR file.",
            show_default=False,
        ),
    ],
    url: Annotated[
        str,
        typer.Option(
            "--url",
            help="JDBC connection URL (e.g. jdbc:postgresql://host:5432/db).",
            show_default=False,
        ),
    ],
    user: Annotated[
        str | None,
        typer.Option(
            "--user",
            help="Database username.",
            show_default=False,
        ),
    ] = None,
    password: Annotated[
        str | None,
        typer.Option(
            "--password",
            help="Database password.",
            show_default=False,
        ),
    ] = None,
    properties: Annotated[
        list[str] | None,
        typer.Option(
            "--properties",
            help="Extra JDBC connection properties as key=value pairs (repeatable).",
            show_default=False,
        ),
    ] = None,
    output: Annotated[
        str | None,
        typer.Option(
            "--output",
            "-o",
            help="Output file path. Overrides --dist-dir when specified.",
            show_default=False,
        ),
    ] = None,
    dist_dir: Annotated[
        str,
        typer.Option(
            "--dist-dir",
            help="Root dist directory for generated files. "
            "YAML is written to <dist-dir>/META-INF/jdbc-drivers/<prefix>.yaml.",
            show_default=True,
        ),
    ] = "dist",
) -> None:
    """Generate a YAML driver definition by probing a JDBC driver JAR.

    Connects to the database using the provided JAR and URL, runs a series of
    introspection probes, and writes a best-effort YAML file you can review
    and edit before deploying.  The driver YAML is written to
    dist/META-INF/jdbc-drivers/<prefix>.yaml by default, and an index file is
    created or updated in the same directory.

    Run ``qualytics drivers package`` afterwards to bundle all generated YAMLs
    into a single deployable JAR.

    Requires a JDK (java + javac) on PATH.

    Examples:

    \\b
        qualytics drivers generate \\
            --jar ./postgresql-42.7.3.jar \\
            --url jdbc:postgresql://localhost:5432/mydb \\
            --user alice --password secret

        qualytics drivers generate \\
            --jar ./custom-driver.jar \\
            --url jdbc:customdb://host:1234/catalog \\
            --properties loginTimeout=30 \\
            --output custom.yaml
    """

    print_banner(subtitle="[bold]Generate Driver[/bold]")

    # ── Validate JAR path ────────────────────────────────────────────────
    jar_path = os.path.abspath(jar)
    if not os.path.isfile(jar_path):
        print(f"[red]JAR file not found: {jar_path}[/red]")
        raise typer.Exit(code=1)

    # ── Extract prefix from URL ──────────────────────────────────────────
    prefix = _extract_prefix(url)
    if prefix is None:
        print(
            f"[red]Could not parse a JDBC prefix from URL: {url}[/red]\n"
            "[yellow]Expected format: jdbc:<prefix>:...[/yellow]"
        )
        raise typer.Exit(code=1)

    # ── Determine output path ────────────────────────────────────────────
    if output:
        out_path = os.path.abspath(output)
    else:
        out_path = os.path.abspath(
            os.path.join(dist_dir, "META-INF", "jdbc-drivers", f"{prefix}.yaml")
        )

    print(f"  JAR:    [bold]{jar_path}[/bold]")
    print(f"  URL:    [bold]{url}[/bold]")
    print(f"  Output: [bold]{out_path}[/bold]")
    print()

    # ── Run probes ───────────────────────────────────────────────────────
    probes: dict = {}
    with status("[bold cyan]Probing JDBC driver capabilities...[/bold cyan]"):
        probes = _run_probe(
            jar_path=jar_path,
            jdbc_url=url,
            user=user,
            password=password,
            properties=list(properties or []),
        )

    # ── Build YAML ───────────────────────────────────────────────────────
    detected_dialect = _detect_dialect_class(prefix, jar_path)
    yaml_content, detected_fields, todo_fields = _build_yaml(
        prefix, probes, url, dialect_class=detected_dialect
    )

    # ── Write output ─────────────────────────────────────────────────────
    try:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w") as fh:
            fh.write(yaml_content)
    except OSError as e:
        print(f"[red]Failed to write output file: {e}[/red]")
        raise typer.Exit(code=1)

    # ── Update index ──────────────────────────────────────────────────────
    yaml_filename = os.path.basename(out_path)
    drivers_dir = os.path.dirname(out_path)
    try:
        index_updated = _update_index(drivers_dir, yaml_filename)
    except OSError as e:
        print(f"[yellow]  Warning: could not update index file: {e}[/yellow]")
        index_updated = False

    # ── LLM-assisted TODO resolution (optional — requires deployment login) ─
    todo_items = _collect_todo_fields(yaml_content)
    if todo_items:
        try:
            from ..config import load_config
            from ..api.client import QualyticsClient
            from ..utils import validate_and_format_url

            config = load_config()
            if config is None:
                print(
                    "[dim]  Not logged in to a Qualytics deployment — LLM TODO resolution skipped.[/dim]"
                )
            else:
                client = QualyticsClient(
                    base_url=validate_and_format_url(config["url"]),
                    token=config.get("token", ""),
                    ssl_verify=config.get("ssl_verify", True),
                )
                llm_status = client.get("agent/llm-config/status").json()
                if not llm_status.get("is_configured"):
                    print(
                        "[dim]  No LLM integration configured on this deployment — TODO fields left as-is.[/dim]"
                    )
                else:
                    db_product = probes.get("dbProductName") or "Unknown database"
                    db_version = probes.get("dbProductVersion") or ""
                    driver_class = probes.get("className") or "unknown"
                    clean_url = _strip_jdbc_credentials(url)
                    todo_block = "\n".join(
                        f"  {name}: {val}  # TODO: {desc}"
                        for name, val, desc in todo_items
                    )
                    prompt = textwrap.dedent(f"""\
                        I am generating a JDBC driver YAML configuration file for the Qualytics data quality platform.
                        Custom JDBC drivers in Qualytics support SOURCE datastores only (read-only access).

                        Database: {db_product} {db_version}
                        Driver class: {driver_class}
                        JDBC URL (credentials removed): {clean_url}

                        The following YAML fields could not be determined automatically.
                        For each field, recommend an appropriate value based on your knowledge of this database:

                        {todo_block}

                        Respond with a single JSON object. Each key is a field name from the list above.
                        Each value is an object with:
                          "value": the recommended YAML value (null if unknown, [] for empty lists, string otherwise)
                          "rationale": one concise sentence explaining the recommendation

                        Only include fields where you have reasonable confidence. Omit fields you are unsure about.
                        Return ONLY valid JSON — no markdown, no code fences, no preamble.
                    """)
                    with status(
                        f"[bold cyan]Asking LLM to resolve {len(todo_items)} TODO field(s)...[/bold cyan]"
                    ):
                        llm_text = _call_deployment_llm(client, prompt)
                    if not llm_text:
                        print(
                            "[yellow]  LLM call returned no usable output — TODO fields left as-is.[/yellow]"
                        )
                    else:
                        json_match = re.search(r"\{.*\}", llm_text, re.DOTALL)
                        if not json_match:
                            print(
                                "[yellow]  LLM response contained no JSON — TODO fields left as-is.[/yellow]"
                            )
                        else:
                            try:
                                suggestions = json.loads(json_match.group(0))
                                updated_yaml, applied = _apply_llm_suggestions(
                                    yaml_content, suggestions
                                )
                                if applied > 0:
                                    with open(out_path, "w") as fh:
                                        fh.write(updated_yaml)
                                    yaml_content = updated_yaml
                                    print(
                                        f"  [{BRAND}]LLM resolved {applied} TODO field(s).[/{BRAND}]"
                                    )
                                else:
                                    print(
                                        "[dim]  LLM returned suggestions but none matched TODO fields.[/dim]"
                                    )
                            except json.JSONDecodeError:
                                print(
                                    "[yellow]  LLM response could not be parsed as JSON — TODO fields left as-is.[/yellow]"
                                )
        except Exception as exc:
            print(
                f"[yellow]  LLM TODO resolution error ({exc}) — TODO fields left as-is.[/yellow]"
            )

    # ── Print summary ────────────────────────────────────────────────────
    console = Console()
    console.print()

    table = Table(title="Probe Results", show_header=True, header_style=f"bold {BRAND}")
    table.add_column("Field", style="bold", min_width=38)
    table.add_column("Result", min_width=20)
    table.add_column("Status", min_width=12)

    probe_display = [
        ("className", probes.get("className")),
        ("dbProductName", probes.get("dbProductName")),
        ("dbProductVersion", probes.get("dbProductVersion")),
        ("prefix (from URL)", prefix),
        ("identifierQuoteChar", probes.get("identifierQuoteChar")),
        ("transactionIsolation", probes.get("transactionIsolation")),
        ("tableNameCasing", probes.get("tableNameCasing")),
        ("connectionTest", probes.get("connectionTest")),
        (
            "subqueryAlias",
            str(probes.get("subqueryAlias", True)).lower(),
        ),
        (
            "getTablesUsesNullCatalog",
            str(probes.get("getTablesUsesNullCatalog", False)).lower(),
        ),
        ("supportsSchemas", str(probes.get("supportsSchemas", False)).lower()),
        ("approxCountDistinctFunction", probes.get("approxCountDistinctFunction")),
        ("rowCount", probes.get("rowCount")),
        ("schemaOnly", probes.get("schemaOnly")),
        ("rowLimitStyle", probes.get("rowLimitStyle")),
        ("tableSampleTemplate", probes.get("tableSampleTemplate")),
        ("viewSampleFallback", probes.get("viewSampleFallback")),
        ("timestampLiteralStyle", probes.get("timestampLiteralStyle")),
        ("dateLiteralStyle", probes.get("dateLiteralStyle")),
    ]

    for name, value in probe_display:
        if value is not None and value != "null":
            display_val = str(value)
            if len(display_val) > 50:
                display_val = display_val[:47] + "..."
            table.add_row(name, display_val, f"[{BRAND}]detected[/{BRAND}]")
        else:
            table.add_row(name, "—", "[yellow]needs review[/yellow]")

    console.print(table)
    console.print()

    todo_count = sum(1 for _, v in probe_display if v is None or v == "null")
    # Always-todo fields (not auto-detectable; need manual review or LLM assistance)
    always_todo = [
        "systemSchemaExclusions",
        "systemSchemaExclusionPrefixes",
        "systemCatalogExclusions",
        "connectionProperties",
        "sessionInitStatements",
        "dialectClass",
        "staticParams",
        "conditionalParams",
        "connectionSpec",
    ]
    total_todo = todo_count + len(always_todo)
    auto_detected = len(probe_display) - todo_count

    print(
        f"  [{BRAND}]{auto_detected} field(s) auto-detected[/{BRAND}]  "
        f"[yellow]{total_todo} field(s) need review[/yellow]\n"
    )
    print(f"  [bold]Written:[/bold] {out_path}")
    index_path = os.path.join(drivers_dir, "index")
    if index_updated:
        print(f"  [bold]Index:[/bold]   {index_path} (added {yaml_filename})")
    else:
        print(f"  [bold]Index:[/bold]   {index_path} (already present — no change)")
    print(
        "\n  [dim]Review the YAML, fill in the TODO fields, then run:[/dim]"
        "\n  [dim]  qualytics drivers package[/dim]"
        "\n  [dim]to bundle all drivers into custom-drivers.jar[/dim]\n"
    )


# ---------------------------------------------------------------------------
# drivers package command
# ---------------------------------------------------------------------------


@drivers_app.command("package")
def package_drivers(
    dist_dir: Annotated[
        str,
        typer.Option(
            "--dist-dir",
            help="Root dist directory produced by 'drivers generate'. "
            "Must contain META-INF/jdbc-drivers/.",
            show_default=True,
        ),
    ] = "dist",
    output: Annotated[
        str | None,
        typer.Option(
            "--output",
            "-o",
            help="Output JAR path. Defaults to custom-drivers.jar in the current directory.",
            show_default=False,
        ),
    ] = None,
) -> None:
    """Bundle all driver YAMLs in dist/META-INF/jdbc-drivers/ into a JAR.

    Reads the index file to enumerate drivers, then zips the entire
    dist/ tree into a JAR file that can be loaded by the Qualytics
    platform alongside the corresponding JDBC driver JARs.

    Examples:

    \\b
        # Default — reads dist/, writes custom-drivers.jar
        qualytics drivers package

        # Custom paths
        qualytics drivers package --dist-dir ./build --output my-drivers.jar
    """

    print_banner(subtitle="[bold]Package Drivers[/bold]")

    abs_dist = os.path.abspath(dist_dir)
    drivers_dir = os.path.join(abs_dist, "META-INF", "jdbc-drivers")

    # ── Validate dist dir ────────────────────────────────────────────────
    if not os.path.isdir(drivers_dir):
        print(
            f"[red]No jdbc-drivers directory found at: {drivers_dir}[/red]\n"
            "[yellow]Run [bold]qualytics drivers generate[/bold] first to populate it.[/yellow]"
        )
        raise typer.Exit(code=1)

    index_path = os.path.join(drivers_dir, "index")
    if not os.path.isfile(index_path):
        print(
            f"[red]No index file found at: {index_path}[/red]\n"
            "[yellow]Run [bold]qualytics drivers generate[/bold] first to create it.[/yellow]"
        )
        raise typer.Exit(code=1)

    with open(index_path) as fh:
        entries = [line.strip() for line in fh if line.strip()]

    if not entries:
        print("[yellow]Index file is empty — nothing to package.[/yellow]")
        raise typer.Exit(code=1)

    # ── Verify all indexed YAMLs exist ───────────────────────────────────
    missing = [e for e in entries if not os.path.isfile(os.path.join(drivers_dir, e))]
    if missing:
        print(f"[red]Index references files that do not exist: {missing}[/red]")
        raise typer.Exit(code=1)

    # ── Write JAR ────────────────────────────────────────────────────────
    jar_path = os.path.abspath(output or "custom-drivers.jar")
    print(f"  Dist dir: [bold]{abs_dist}[/bold]")
    print(f"  Drivers:  {', '.join(entries)}")
    print(f"  Output:   [bold]{jar_path}[/bold]")
    print()

    with status("[bold cyan]Packaging drivers...[/bold cyan]"):
        try:
            with zipfile.ZipFile(jar_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, _dirs, files in os.walk(abs_dist):
                    for fname in sorted(files):
                        fpath = os.path.join(root, fname)
                        arcname = os.path.relpath(fpath, abs_dist)
                        zf.write(fpath, arcname)
        except OSError as e:
            print(f"[red]Failed to write JAR: {e}[/red]")
            raise typer.Exit(code=1)

    print(f"  [{BRAND}]Packaged {len(entries)} driver(s) → {jar_path}[/{BRAND}]\n")
