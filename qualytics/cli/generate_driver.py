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
from typing import Annotated, Optional

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
        String casing = "\"asis\"";
        try {
            if (meta.storesUpperCaseIdentifiers()) casing = "\"upper\"";
            else if (meta.storesLowerCaseIdentifiers()) casing = "\"lower\"";
        } catch (Exception e) { System.err.println("tableNameCasing err: " + e.getMessage()); }

        // ── Phase 2: SQL probes (5s timeout each) ────────────────────────

        // validationQuery
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

        // subqueryRequiresAlias
        String subAlias = "false";
        try {
            tryQuery(conn, "SELECT * FROM (SELECT 1 AS x) WHERE 1=0", 5);
            subAlias = "false";
        } catch (Exception e) { subAlias = "false"; }
        if (!tryQuery(conn, "SELECT * FROM (SELECT 1 AS x) WHERE 1=0", 5)) {
            subAlias = "true";
        }

        // approxCountDistinctFunction
        String approxFn = "null";
        if (tryQuery(conn, "SELECT APPROX_COUNT_DISTINCT(1)", 5)) approxFn = "\"APPROX_COUNT_DISTINCT\"";
        else if (tryQuery(conn, "SELECT APPROX_DISTINCT(1)", 5)) approxFn = "\"APPROX_DISTINCT\"";
        else if (tryQuery(conn, "SELECT NDV(1)", 5)) approxFn = "\"NDV\"";

        // schemaExistenceQueryStyle
        String schemaStyle = "\"NONE\"";
        if (tryQuery(conn, "SELECT 1 FROM INFORMATION_SCHEMA.SCHEMATA WHERE 1=0", 5))
            schemaStyle = "\"INFORMATION_SCHEMA\"";
        else if (tryQuery(conn, "SHOW SCHEMAS", 5))
            schemaStyle = "\"SHOW_SCHEMAS_ITERATE\"";
        else if (tryQuery(conn, "SELECT 1 FROM SYSCAT.SCHEMATA WHERE 1=0", 5))
            schemaStyle = "\"SYSCAT\"";
        else if (tryQuery(conn, "SELECT 1 FROM sys.schemas WHERE 1=0", 5))
            schemaStyle = "\"SYS_SCHEMAS\"";

        // dateArithmeticStyle + interval templates
        String dateArith = "\"STANDARD\"";
        String intervalTs = "null";
        String intervalDt = "null";
        String upperTs = "null";
        String upperDt = "null";

        if (tryQuery(conn, "SELECT TIMESTAMPADD(SECOND, 1, '2000-01-01')", 5)) {
            dateArith = "\"STANDARD\"";
            intervalTs = jq("TIMESTAMPADD(SECOND, TIMESTAMPDIFF(SECOND, MIN_{col}, MAX_{col}) / 3, MIN_{col})");
            intervalDt = jq("TIMESTAMPADD(DAY, TIMESTAMPDIFF(DAY, MIN_{col}, MAX_{col}) / 3, MIN_{col})");
            upperTs = jq("TIMESTAMPADD(SECOND, TIMESTAMPDIFF(SECOND, MIN_{col}, {interval}), {interval})");
            upperDt = jq("TIMESTAMPADD(DAY, TIMESTAMPDIFF(DAY, MIN_{col}, {interval}), {interval})");
        } else if (tryQuery(conn, "SELECT DATEADD(second, 1, '2000-01-01')", 5)) {
            dateArith = "\"DATEADD_DATEDIFF\"";
            intervalTs = jq("DATEADD(second, DATEDIFF(second, MIN_{col}, MAX_{col}) / 3, MIN_{col})");
            intervalDt = jq("DATEADD(day, DATEDIFF(day, MIN_{col}, MAX_{col}) / 3, MIN_{col})");
            upperTs = jq("DATEADD(second, DATEDIFF(second, MIN_{col}, {interval}), {interval})");
            upperDt = jq("DATEADD(day, DATEDIFF(day, MIN_{col}, {interval}), {interval})");
        } else if (tryQuery(conn, "SELECT NUMTODSINTERVAL(1, 'SECOND') FROM DUAL", 5)) {
            dateArith = "\"NUMTODSINTERVAL\"";
            intervalTs = jq("MIN_{col} + NUMTODSINTERVAL(EXTRACT(SECOND FROM (MAX_{col} - MIN_{col}))/3, 'SECOND')");
            intervalDt = jq("MIN_{col} + NUMTODSINTERVAL((MAX_{col} - MIN_{col})/3, 'DAY')");
            upperTs = jq("MIN_{col} + NUMTODSINTERVAL(EXTRACT(SECOND FROM ({interval} - MIN_{col})), 'SECOND')");
            upperDt = jq("MIN_{col} + NUMTODSINTERVAL({interval} - MIN_{col}, 'DAY')");
        } else if (tryQuery(conn, "SELECT TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL 1 SECOND)", 5)) {
            dateArith = "\"TIMESTAMP_ADD\"";
            intervalTs = jq("TIMESTAMP_ADD(MIN_{col}, INTERVAL TIMESTAMP_DIFF(MAX_{col}, MIN_{col}, SECOND)/3 SECOND)");
            intervalDt = jq("DATE_ADD(MIN_{col}, INTERVAL DATE_DIFF(MAX_{col}, MIN_{col}, DAY)/3 DAY)");
            upperTs = jq("TIMESTAMP_ADD({interval}, INTERVAL TIMESTAMP_DIFF({interval}, MIN_{col}, SECOND) SECOND)");
            upperDt = jq("DATE_ADD({interval}, INTERVAL DATE_DIFF({interval}, MIN_{col}, DAY) DAY)");
        }

        // rowLimitSyntax — find a real accessible table first
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

        if (sampleTable != null) {
            if (tryQuery(conn, "SELECT TOP 1 1 FROM " + sampleTable, 5))
                rowLimit = "\"TOP\"";
            else if (tryQuery(conn, "SELECT 1 FROM " + sampleTable + " FETCH FIRST 1 ROWS ONLY", 5))
                rowLimit = "\"FETCH_FIRST\"";
            else if (tryQuery(conn, "SELECT 1 FROM " + sampleTable + " WHERE ROWNUM <= 1", 5))
                rowLimit = "\"ROWNUM\"";
            else if (tryQuery(conn, "SELECT 1 FROM " + sampleTable + " LIMIT 1", 5))
                rowLimit = "\"LIMIT\"";
        } else {
            // no tables — try without a table
            if (tryQuery(conn, "SELECT TOP 1 1", 5))         rowLimit = "\"TOP\"";
            else if (tryQuery(conn, "VALUES 1 FETCH FIRST 1 ROWS ONLY", 5)) rowLimit = "\"FETCH_FIRST\"";
            else if (tryQuery(conn, "SELECT 1 LIMIT 1", 5))  rowLimit = "\"LIMIT\"";
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

        // viewSampleFallback — probe which random function is supported for view sampling
        String viewSampleFallback = "\"RAND\"";
        if (!tryQuery(conn, "SELECT RAND()", 5)) {
            if (tryQuery(conn, "SELECT RANDOM()", 5))
                viewSampleFallback = "\"RANDOM\"";
            else if (tryQuery(conn, "SELECT NEWID()", 5))
                viewSampleFallback = "\"NEWID\"";
        }

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

        // schemaOnlyQueryStyle — how to wrap a query to return 0 rows (for schema inspection)
        String schemaOnlyStyle = "\"CTE\"";
        if (sampleTable != null) {
            if (tryQuery(conn, "SELECT TOP 0 * FROM " + sampleTable, 5))
                schemaOnlyStyle = "\"SQLSERVER_TOP0\"";
            else if (tryQuery(conn, "SELECT * FROM " + sampleTable + " WHERE 1=0", 5)
                     && dateLiteralStyle.equals("\"TO_DATE\""))
                // Oracle: WHERE 1=0 works but no alias required
                schemaOnlyStyle = "\"ORACLE_WHERE_FALSE\"";
        }

        // rowCountQueryStyle — probe metadata tables for optimized row count access
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
        out.append("  \"validationQuery\": ").append(validationQuery).append(",\n");
        out.append("  \"getTablesUsesNullCatalog\": ").append(nullCatalog).append(",\n");
        out.append("  \"subqueryRequiresAlias\": ").append(subAlias).append(",\n");
        out.append("  \"approxCountDistinctFunction\": ").append(approxFn).append(",\n");
        out.append("  \"schemaExistenceQueryStyle\": ").append(schemaStyle).append(",\n");
        out.append("  \"dateArithmeticStyle\": ").append(dateArith).append(",\n");
        out.append("  \"rowLimitSyntax\": ").append(rowLimit).append(",\n");
        out.append("  \"tableSampleTemplate\": ").append(sampleTemplate).append(",\n");
        out.append("  \"intervalCalcDatetimeTimestampTemplate\": ").append(intervalTs).append(",\n");
        out.append("  \"intervalCalcDatetimeDateTemplate\": ").append(intervalDt).append(",\n");
        out.append("  \"upperBoundDatetimeTimestampTemplate\": ").append(upperTs).append(",\n");
        out.append("  \"upperBoundDatetimeDateTemplate\": ").append(upperDt).append(",\n");
        out.append("  \"viewSampleFallback\": ").append(viewSampleFallback).append(",\n");
        out.append("  \"timestampLiteralStyle\": ").append(timestampLiteralStyle).append(",\n");
        out.append("  \"dateLiteralStyle\": ").append(dateLiteralStyle).append(",\n");
        out.append("  \"schemaOnlyQueryStyle\": ").append(schemaOnlyStyle).append(",\n");
        out.append("  \"rowCountQueryStyle\": ").append(rowCountStyle).append("\n");
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
        print(
            f"[red]Failed to compile Java probe:[/red]\n{result.stderr}"
        )
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
                    print(f"[red]JDBC connection failed: {line[len('CONNECTION_ERROR:'):].strip()}[/red]")
                    raise typer.Exit(code=1)
                if line.startswith("ERROR:"):
                    print(f"[red]{line[len('ERROR:'):].strip()}[/red]")
                    raise typer.Exit(code=1)

        if result.returncode == 4:
            print("[red]Could not connect to the database. Check --url, --user, and --password.[/red]")
            raise typer.Exit(code=1)
        if result.returncode == 3:
            print("[red]No compatible JDBC driver found in the provided JAR for the given URL.[/red]")
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
        host_part = re.sub(r"^[^@]+@", "", authority)   # strip user:pass@
        host_part = re.sub(r":\d+(?:$|;)", "", host_part)  # strip :port
        host_part = re.sub(r";.*$", "", host_part)       # strip ;params (SQL Server style)
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


# Known Spark built-in JdbcDialect implementations (Spark 3.x, package org.apache.spark.sql.jdbc)
_SPARK_BUILTIN_DIALECTS: dict[str, str] = {
    "postgresql": "org.apache.spark.sql.jdbc.PostgresDialect$",
    "mysql":      "org.apache.spark.sql.jdbc.MySQLDialect$",
    "mariadb":    "org.apache.spark.sql.jdbc.MySQLDialect$",
    "oracle":     "org.apache.spark.sql.jdbc.OracleDialect$",
    "sqlserver":  "org.apache.spark.sql.jdbc.MsSqlServerDialect$",
    "jtds":       "org.apache.spark.sql.jdbc.MsSqlServerDialect$",
    "db2":        "org.apache.spark.sql.jdbc.DB2Dialect$",
    "derby":      "org.apache.spark.sql.jdbc.DerbyDialect$",
    "teradata":   "org.apache.spark.sql.jdbc.TeradataDialect$",
}


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
                content = zf.read(service_entry).decode("utf-8", errors="replace").strip()
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
        if any(c in sv for c in [':', '#', '[', ']', '{', '}', ',', '&', '*', '?', '|',
                                   '-', '<', '>', '=', '!', '%', '@', '`', '"', "'", '\n']):
            dumped = yaml.dump(sv, default_flow_style=True).strip()
            # yaml.dump may append a YAML document-end marker on a new line — strip it
            if '\n' in dumped:
                dumped = dumped.split('\n')[0]
            return dumped
        return sv

    def field(name: str, value, comment: str = "") -> str:
        comment_str = f"  # {comment}" if comment else ""
        return f"{name}: {_render(value)}{comment_str}"

    lines: list[str] = []

    # ── Derive URL metadata ─────────────────────────────────────────────────
    default_port, jdbc_url_template, url_components = _derive_url_metadata(jdbc_url)
    db_product_name = probes.get("dbProductName")
    display_name = (
        db_product_name
        if db_product_name and db_product_name not in (None, "null")
        else prefix.capitalize()
    )

    # ── Header ──────────────────────────────────────────────────────────────
    lines.append(textwrap.dedent(f"""\
        # Generated by: qualytics generate-driver
        #
        # "# auto-detected"  — probed from the live JDBC connection.
        # "# TODO: …"        — could not be auto-detected; fill in before deploying.
        #                       Comment describes the field, valid values, and intent.
        # "# LLM-suggested"  — filled in by the deployment LLM (review before use).
        #
        # Custom JDBC drivers in Qualytics support SOURCE datastores only (read access).
        # Excluded write-only field: insertBatchSize.
        # Keys equal to their DriverDefinition default are omitted to keep this file concise.
        #
        # Deploy this file to:  META-INF/jdbc-drivers/{prefix}.yaml
        """))

    # ── Identity ─────────────────────────────────────────────────────────────
    lines.append(field("prefix", prefix,
                       "review — must match the jdbc:<prefix>: scheme in the JDBC URL"))
    todo_fields.append("prefix")
    lines.append(field("className", probes.get("className"),
                       "auto-detected — fully-qualified JDBC Driver class name"))
    detected_fields.append("className")
    lines.append("")

    # ── SQL dialect ───────────────────────────────────────────────────────────
    lines.append("# ── SQL dialect ──────────────────────────────────────────────────────")

    # displayName — always emit (default is raw prefix; capitalised form is user-friendly)
    lines.append(field("displayName", display_name,
                       "auto-detected from DB product name — human-readable name shown in the UI"))
    detected_fields.append("displayName")

    # defaultPort — emit only when probe URL contained an explicit port number.
    # If the driver uses a portless URL scheme (e.g. jdbc:sqlite:, jdbc:h2:mem:),
    # leave as TODO so the user knows to set it (or omit if the driver truly has no port).
    if default_port is not None:
        lines.append(field("defaultPort", default_port,
                           "auto-detected from JDBC URL — default port shown in the connection form"))
        detected_fields.append("defaultPort")
    else:
        lines.append(field("defaultPort", None,
                           "TODO: default TCP port for this driver "
                           "(e.g. 5432 PostgreSQL, 3306 MySQL, 1521 Oracle, 1433 SQL Server). "
                           "Omit this key entirely if the driver does not use TCP ports."))
        todo_fields.append("defaultPort")

    # transactionIsolation — omit if READ_UNCOMMITTED (default)
    tx = probes.get("transactionIsolation")
    if tx and tx != "READ_UNCOMMITTED":
        lines.append(field("transactionIsolation", tx,
                           "auto-detected — valid: NONE, READ_UNCOMMITTED (default), "
                           "READ_COMMITTED, SERIALIZABLE"))
        detected_fields.append("transactionIsolation")
    elif tx:
        detected_fields.append("transactionIsolation")   # default — omitted

    # identifierQuoteChar — omit if " (default)
    quote_char = probes.get("identifierQuoteChar")
    if quote_char and quote_char != '"':
        lines.append(field("identifierQuoteChar", quote_char,
                           'auto-detected — char used to quote identifiers; default " — MySQL/MariaDB use `'))
        detected_fields.append("identifierQuoteChar")
    elif quote_char:
        detected_fields.append("identifierQuoteChar")    # default — omitted

    # tableNameCasing — omit if asis (default)
    casing = probes.get("tableNameCasing", "asis")
    if casing != "asis":
        lines.append(field("tableNameCasing", casing,
                           "auto-detected — valid: upper (DB2/Oracle), lower (PostgreSQL), "
                           "asis (default, most others)"))
        detected_fields.append("tableNameCasing")
    else:
        detected_fields.append("tableNameCasing")        # default — omitted

    # rowLimitSyntax — omit if LIMIT (default); TODO if probe couldn't determine
    row_limit = probes.get("rowLimitSyntax")
    if row_limit and row_limit != "LIMIT":
        lines.append(field("rowLimitSyntax", row_limit,
                           "auto-detected — valid: LIMIT (default), TOP (SQL Server), "
                           "ROWNUM (Oracle), FETCH_FIRST (DB2/Informix)"))
        detected_fields.append("rowLimitSyntax")
    elif row_limit == "LIMIT":
        detected_fields.append("rowLimitSyntax")         # default — omitted
    else:
        lines.append(field("rowLimitSyntax", "LIMIT",
                           "TODO: valid: LIMIT (default, MySQL/PG/SQLite), TOP (SQL Server), "
                           "ROWNUM (Oracle), FETCH_FIRST (DB2/Informix/Spark)"))
        todo_fields.append("rowLimitSyntax")

    # subqueryRequiresAlias — omit if true (default); emit false if probe confirmed no alias needed
    sub_alias = probes.get("subqueryRequiresAlias", True)
    if isinstance(sub_alias, str):
        sub_alias = sub_alias.lower() != "false"
    if not sub_alias:
        lines.append(field("subqueryRequiresAlias", False,
                           "auto-detected — false: subqueries do NOT need an AS alias "
                           "(rare; historically Oracle)"))
        detected_fields.append("subqueryRequiresAlias")
    else:
        detected_fields.append("subqueryRequiresAlias")  # default true — omitted

    # timestampLiteralStyle — omit if PLAIN (default)
    ts_style = probes.get("timestampLiteralStyle", "PLAIN")
    if ts_style != "PLAIN":
        lines.append(field("timestampLiteralStyle", ts_style,
                           "auto-detected — valid: PLAIN (default), TIMESTAMP_PREFIX (standard SQL), "
                           "CAST_AS_TIMESTAMP (Hive), CAST_DATE_FORMAT (Databricks), "
                           "TO_TIMESTAMP (Oracle), CAST_DATETIME2 (SQL Server)"))
        detected_fields.append("timestampLiteralStyle")
    else:
        detected_fields.append("timestampLiteralStyle")  # default — omitted
    # timestampLiteralTemplate: escape hatch — omit unless enum styles are insufficient

    # dateLiteralStyle — omit if PLAIN (default)
    dt_style = probes.get("dateLiteralStyle", "PLAIN")
    if dt_style != "PLAIN":
        lines.append(field("dateLiteralStyle", dt_style,
                           "auto-detected — valid: PLAIN (default), DATE_PREFIX, TO_DATE (Oracle)"))
        detected_fields.append("dateLiteralStyle")
    else:
        detected_fields.append("dateLiteralStyle")       # default — omitted
    # dateLiteralTemplate: escape hatch — omit unless enum styles are insufficient

    # schemaOnlyQueryStyle — if CTE (probe fallback, unconfirmed) → TODO; else emit as detected
    schema_only = probes.get("schemaOnlyQueryStyle", "CTE")
    if schema_only != "CTE":
        lines.append(field("schemaOnlyQueryStyle", schema_only,
                           "auto-detected — how to wrap a query to return 0 rows for schema inspection. "
                           "Valid: CTE (default), PG_CTE (PostgreSQL), SQLSERVER_TOP0 (SQL Server), "
                           "WHERE_FALSE_QUERYA (generic WHERE 1=0), ORACLE_WHERE_FALSE (Oracle), "
                           "HIVE_LIMIT0 (Hive/Spark)"))
        detected_fields.append("schemaOnlyQueryStyle")
    else:
        lines.append(field("schemaOnlyQueryStyle", "CTE",
                           "TODO: how to wrap a query to return 0 rows for schema inspection. "
                           "Valid: CTE (default, most modern DBs with WITH support), PG_CTE (PostgreSQL), "
                           "SQLSERVER_TOP0 (SQL Server/Synapse), WHERE_FALSE_QUERYA (generic WHERE 1=0), "
                           "ORACLE_WHERE_FALSE (Oracle), HIVE_LIMIT0 (Hive/Spark)"))
        todo_fields.append("schemaOnlyQueryStyle")

    # tableSampleTemplate — omit if null (not supported = default "no template")
    sample_tmpl = probes.get("tableSampleTemplate")
    if sample_tmpl and sample_tmpl != "null":
        lines.append(field("tableSampleTemplate", sample_tmpl,
                           "auto-detected — TABLESAMPLE syntax; {pct} = percent, {rows} = row count"))
        detected_fields.append("tableSampleTemplate")
    else:
        detected_fields.append("tableSampleTemplate")    # null/not supported — omitted

    # viewSampleFallback — omit if RAND (default)
    vsf = probes.get("viewSampleFallback", "RAND")
    if vsf != "RAND":
        lines.append(field("viewSampleFallback", vsf,
                           "auto-detected — random fn for view sampling. "
                           "Valid: RAND (default), RANDOM (PostgreSQL/Redshift), "
                           "NEWID (SQL Server), DBMS_RANDOM (Oracle), SAMPLE_N (Teradata), "
                           "NONE (BigQuery)"))
        detected_fields.append("viewSampleFallback")
    else:
        detected_fields.append("viewSampleFallback")     # default — omitted
    # viewSampleFallbackSql: escape hatch — omit unless enum styles are insufficient

    # approxCountDistinctFunction — omit if null (not supported, falls back to COUNT DISTINCT)
    approx = probes.get("approxCountDistinctFunction")
    if approx and approx != "null":
        lines.append(field("approxCountDistinctFunction", approx,
                           "auto-detected — SQL function name for approximate COUNT DISTINCT"))
        detected_fields.append("approxCountDistinctFunction")
    else:
        detected_fields.append("approxCountDistinctFunction")  # null — omitted

    # validationQuery — omit if SELECT 1 (default)
    val_q = probes.get("validationQuery")
    if val_q and val_q != "SELECT 1":
        lines.append(field("validationQuery", val_q,
                           "auto-detected — minimal SQL to test a pooled connection is alive"))
        detected_fields.append("validationQuery")
    elif val_q:
        detected_fields.append("validationQuery")        # default — omitted
    else:
        lines.append(field("validationQuery", "SELECT 1",
                           "TODO: SQL to verify a live connection; try SELECT 1 FROM DUAL (Oracle), "
                           "VALUES 1 (DB2/H2)"))
        todo_fields.append("validationQuery")

    lines.append("")

    # ── Performance ───────────────────────────────────────────────────────────
    lines.append("# ── Performance ──────────────────────────────────────────────────────")
    lines.append(field("maxPartitionParallelism", 10,
                       "TODO: max parallel partitions for scan operations; default 10. "
                       "Set 1 for DBs that struggle with concurrent connections (e.g. BigQuery, "
                       "single-threaded embedded drivers)"))
    todo_fields.append("maxPartitionParallelism")
    _int_max_prefixes = ("redshift", "sqlserver", "db2")
    _data_size_default = "INT_MAX" if any(p in prefix.lower() for p in _int_max_prefixes) else "LONG_MAX"
    _data_size_comment = (
        "INT_MAX: older 32-bit driver (SQL Server, Redshift, Db2)"
        if _data_size_default == "INT_MAX"
        else "TODO: max data the driver can handle. LONG_MAX (default, most DBs) or "
             "INT_MAX for older 32-bit drivers (SQL Server, Redshift, Db2)"
    )
    lines.append(field("dataSizeLimit", _data_size_default, _data_size_comment))
    if _data_size_default == "INT_MAX":
        detected_fields.append("dataSizeLimit")
    else:
        todo_fields.append("dataSizeLimit")
    lines.append("")

    # ── Schema / catalog filtering ────────────────────────────────────────────
    lines.append("# ── Schema / catalog filtering ───────────────────────────────────────")
    lines.append("systemSchemaExclusions: []"
                 "      # TODO: exact schema names to exclude from catalog scans "
                 "(e.g. [information_schema, pg_catalog])")
    lines.append("systemSchemaExclusionPrefixes: []"
                 "  # TODO: schema name prefixes to exclude (e.g. [pg_temp_, pg_toast_temp_])")
    lines.append("systemCatalogExclusions: []"
                 "     # TODO: catalog names to exclude "
                 "(e.g. [admin, local, config] for MongoDB; [information_schema, mysql] for MySQL)")
    todo_fields += ["systemSchemaExclusions", "systemSchemaExclusionPrefixes", "systemCatalogExclusions"]

    # getTablesUsesNullCatalog — omit if false (default); emit if true
    get_tables_null = probes.get("getTablesUsesNullCatalog", False)
    if isinstance(get_tables_null, str):
        get_tables_null = get_tables_null.lower() == "true"
    if get_tables_null:
        lines.append(field("getTablesUsesNullCatalog", True,
                           "auto-detected — pass null as catalog arg to DatabaseMetaData.getTables(); "
                           "required for Db2"))
        detected_fields.append("getTablesUsesNullCatalog")
    else:
        detected_fields.append("getTablesUsesNullCatalog")  # default false — omitted
    lines.append("")

    # ── Style selectors ────────────────────────────────────────────────────────
    lines.append("# ── Style selectors ──────────────────────────────────────────────────")

    # rowCountQueryStyle — emit as TODO if COUNT_STAR (default/unconfirmed), else auto-detected
    row_count_style = probes.get("rowCountQueryStyle", "COUNT_STAR")
    if row_count_style and row_count_style != "COUNT_STAR":
        lines.append(field("rowCountQueryStyle", row_count_style,
                           "auto-detected — row count strategy"))
        detected_fields.append("rowCountQueryStyle")
    else:
        lines.append(field("rowCountQueryStyle", "COUNT_STAR",
                           "TODO: row count strategy. Valid: COUNT_STAR (default, always works), "
                           "BQ_TABLES (BigQuery), INFORMATION_SCHEMA_ROW_COUNT (MySQL/MariaDB), "
                           "ALL_TABLES (Oracle), INFORMATION_SCHEMA_TABLES_WITH_SIZE (MySQL/MariaDB)"))
        todo_fields.append("rowCountQueryStyle")
    # countStarNullSizeBytesExpr — almost always null (default); omit; user adds manually for Dremio

    # schemaExistenceQueryStyle — omit if NONE (default)
    schema_style = probes.get("schemaExistenceQueryStyle", "NONE")
    if schema_style != "NONE":
        lines.append(field("schemaExistenceQueryStyle", schema_style,
                           "auto-detected — schema enumeration style. "
                           "Valid: NONE (default), INFORMATION_SCHEMA, SHOW_SCHEMAS_LIKE, "
                           "SHOW_SCHEMAS_ITERATE (Hive/Trino), SYSCAT (DB2), "
                           "ALTER_SESSION (Oracle), SYS_SCHEMAS (SQL Server)"))
        detected_fields.append("schemaExistenceQueryStyle")
    else:
        detected_fields.append("schemaExistenceQueryStyle")  # default — omitted

    # dateArithmeticStyle — omit if STANDARD (default)
    date_arith = probes.get("dateArithmeticStyle", "STANDARD")
    if date_arith != "STANDARD":
        lines.append(field("dateArithmeticStyle", date_arith,
                           "auto-detected — date arithmetic strategy. "
                           "Valid: STANDARD (default, ANSI fallback), DATEADD_DATEDIFF (SQL Server), "
                           "NUMTODSINTERVAL (Oracle), TIMESTAMP_ADD (BigQuery), TIMESTAMPDIFF_DB2 (Db2)"))
        detected_fields.append("dateArithmeticStyle")
    else:
        detected_fields.append("dateArithmeticStyle")       # default — omitted
    lines.append("")

    # ── Date arithmetic templates (only when non-null) ────────────────────────
    int_ts = probes.get("intervalCalcDatetimeTimestampTemplate")
    int_dt = probes.get("intervalCalcDatetimeDateTemplate")
    up_ts  = probes.get("upperBoundDatetimeTimestampTemplate")
    up_dt  = probes.get("upperBoundDatetimeDateTemplate")

    has_templates = any(v and v != "null" for v in [int_ts, int_dt, up_ts, up_dt])
    if has_templates:
        lines.append("# ── Date arithmetic templates ─────────────────────────────────────────")
        lines.append("# Placeholders: {col} = column name, MIN_{col} = min value, "
                     "MAX_{col} = max value, {interval} = midpoint expression")
        if int_ts and int_ts != "null":
            lines.append(field("intervalCalcDatetimeTimestampTemplate", int_ts, "auto-detected"))
            detected_fields.append("intervalCalcDatetimeTimestampTemplate")
        if int_dt and int_dt != "null":
            lines.append(field("intervalCalcDatetimeDateTemplate", int_dt, "auto-detected"))
            detected_fields.append("intervalCalcDatetimeDateTemplate")
        if up_ts and up_ts != "null":
            lines.append(field("upperBoundDatetimeTimestampTemplate", up_ts, "auto-detected"))
            detected_fields.append("upperBoundDatetimeTimestampTemplate")
        if up_dt and up_dt != "null":
            lines.append(field("upperBoundDatetimeDateTemplate", up_dt, "auto-detected"))
            detected_fields.append("upperBoundDatetimeDateTemplate")
        lines.append("")

    # ── Connectivity ──────────────────────────────────────────────────────────
    lines.append("# ── Connectivity ─────────────────────────────────────────────────────")
    # networkCapable: true (default) — omitted; readOnly: false (default) — omitted
    lines.append("connectionProperties: {}"
                 "        # TODO: key-value pairs injected into JDBC pool and Spark "
                 "(e.g. {ssl: 'true', charset: 'utf8'})")
    lines.append("sessionInitStatements: []"
                 "       # TODO: SQL statements run once after each new connection "
                 "(e.g. [\"SET SCHEMA mydb\", \"ALTER SESSION SET NLS_DATE_FORMAT='YYYY-MM-DD'\"])")
    todo_fields += ["connectionProperties", "sessionInitStatements"]
    lines.append("")

    # ── Spark JdbcDialect ─────────────────────────────────────────────────────
    lines.append("# ── Spark JdbcDialect ────────────────────────────────────────────────")
    if dialect_class is not None:
        lines.append(field("dialectClass", dialect_class,
                           "Auto-detected Spark JdbcDialect subclass"))
        detected_fields.append("dialectClass")
    else:
        lines.append(field("dialectClass", None,
                           "TODO: fully-qualified JdbcDialect Scala object class to register with Spark "
                           "(e.g. com.example.MyDialect$); null if no custom Spark dialect is needed"))
        todo_fields.append("dialectClass")
    lines.append("")

    # ── URL construction ──────────────────────────────────────────────────────
    lines.append("# ── URL construction ─────────────────────────────────────────────────")
    lines.append("# Known placeholders: {host}, {port}, {database}, {schema}, {username}, {password}")
    if jdbc_url_template:
        lines.append(field("jdbcUrlTemplate", jdbc_url_template,
                           "auto-detected from probe URL — verify all placeholders are correct"))
        detected_fields.append("jdbcUrlTemplate")
    else:
        lines.append(field("jdbcUrlTemplate", "",
                           "TODO: URL template with {host}, {port}, {database} substitution tokens. "
                           "Example: jdbc:mydb://{host}:{port}/{database}"))
        todo_fields.append("jdbcUrlTemplate")
    lines.append("jdbcUrlStaticParams: []"
                 "      # TODO: query params always appended to every URL "
                 "(e.g. [tcpKeepAlive=true, sslmode=prefer])")
    lines.append("jdbcUrlConditionalParams: []"
                 "  # TODO: params appended only when a form field is non-empty "
                 "(e.g. [{key: schema, param: 'currentSchema={schema}'}])")
    lines.append("jdbcUrlAuthVariants: {}"
                 "      # optional: auth_type -> full URL template override; leave empty if not needed")
    todo_fields += ["jdbcUrlStaticParams", "jdbcUrlConditionalParams"]
    lines.append("")

    # ── Connection spec ────────────────────────────────────────────────────────
    # Only mark a field required if the probe URL actually contained that component.
    # e.g. jdbc:sqlite:/path/to/db has no host or port → those fields are optional.
    lines.append("# ── Connection spec (frontend form) ──────────────────────────────────")
    lines.append("# TODO: define the connection form fields shown in the UI.")
    lines.append("# Each field: name, label, fieldType (string/integer/boolean/password/enum/file),")
    lines.append("#             required, defaultValue, hint, options (for enum), dependsOn, dependsOnValue")
    lines.append("connectionSpec:")
    lines.append("  supportsEnrichment: false  # custom drivers are source-only")
    lines.append("  fields:")
    if "host" in url_components:
        lines.append("    - name: host")
        lines.append('      label: "Host"')
        lines.append("      fieldType: string")
        lines.append("      required: true")
    if "port" in url_components:
        lines.append("    - name: port")
        lines.append('      label: "Port"')
        lines.append("      fieldType: integer")
        lines.append("      required: true")
        if default_port is not None:
            lines.append(f'      defaultValue: "{default_port}"')
    if "database" in url_components:
        lines.append("    - name: database")
        lines.append('      label: "Database"')
        lines.append("      fieldType: string")
        lines.append("      required: true")
    lines.append("    - name: username")
    lines.append('      label: "Username"')
    lines.append("      fieldType: string")
    lines.append("      required: true")
    lines.append("    - name: password")
    lines.append('      label: "Password"')
    lines.append("      fieldType: password")
    lines.append("      required: true")
    todo_fields.append("connectionSpec")

    return "\n".join(lines) + "\n", detected_fields, todo_fields


# ---------------------------------------------------------------------------
# LLM-assisted TODO resolution helpers
# ---------------------------------------------------------------------------


def _strip_jdbc_credentials(jdbc_url: str) -> str:
    """Remove user/password from a JDBC URL for safe inclusion in prompts."""
    cleaned = re.sub(r"(jdbc:[^:]+://)([^@/]+@)", r"\1", jdbc_url)
    cleaned = re.sub(r"[?&](password|passwd|pwd)=[^&]*", "", cleaned, flags=re.IGNORECASE)
    return cleaned


def _collect_todo_fields(yaml_content: str) -> list[tuple[str, str, str]]:
    """
    Scan YAML lines for remaining TODO comments.
    Returns list of (field_name, current_value, todo_description).
    """
    todos = []
    for line in yaml_content.splitlines():
        m = re.match(r"^(\w+):\s*(.+?)\s*#\s*TODO:\s*(.+)$", line)
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
                        text_parts.append(event.get("textDelta") or event.get("delta") or "")
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
    """
    applied = 0
    result_lines: list[str] = []
    for line in yaml_content.splitlines(keepends=True):
        m = re.match(r"^(\w+):\s*(.+?)\s*#\s*TODO:.*$", line)
        if m and m.group(1) in suggestions:
            field_name = m.group(1)
            suggestion = suggestions[field_name]
            value = suggestion.get("value")
            rationale = str(suggestion.get("rationale", "")).replace("\n", " ").strip()
            if value is not None:
                if isinstance(value, (list, dict)):
                    yaml_val = yaml.dump(value, default_flow_style=True).strip().rstrip("\n")
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
                result_lines.append(f"{field_name}: {yaml_val}  # LLM-suggested: {rationale}\n")
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
        Optional[str],
        typer.Option(
            "--user",
            help="Database username.",
            show_default=False,
        ),
    ] = None,
    password: Annotated[
        Optional[str],
        typer.Option(
            "--password",
            help="Database password.",
            show_default=False,
        ),
    ] = None,
    properties: Annotated[
        Optional[list[str]],
        typer.Option(
            "--properties",
            help="Extra JDBC connection properties as key=value pairs (repeatable).",
            show_default=False,
        ),
    ] = None,
    output: Annotated[
        Optional[str],
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
    yaml_content, detected_fields, todo_fields = _build_yaml(prefix, probes, url, dialect_class=detected_dialect)

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
                print("[dim]  Not logged in to a Qualytics deployment — LLM TODO resolution skipped.[/dim]")
            else:
                client = QualyticsClient(
                    base_url=validate_and_format_url(config["url"]),
                    token=config.get("token", ""),
                    ssl_verify=config.get("ssl_verify", True),
                )
                llm_status = client.get("agent/llm-config/status").json()
                if not llm_status.get("is_configured"):
                    print("[dim]  No LLM integration configured on this deployment — TODO fields left as-is.[/dim]")
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
                    with status(f"[bold cyan]Asking LLM to resolve {len(todo_items)} TODO field(s)...[/bold cyan]"):
                        llm_text = _call_deployment_llm(client, prompt)
                    if not llm_text:
                        print("[yellow]  LLM call returned no usable output — TODO fields left as-is.[/yellow]")
                    else:
                        json_match = re.search(r"\{.*\}", llm_text, re.DOTALL)
                        if not json_match:
                            print("[yellow]  LLM response contained no JSON — TODO fields left as-is.[/yellow]")
                        else:
                            try:
                                suggestions = json.loads(json_match.group(0))
                                updated_yaml, applied = _apply_llm_suggestions(yaml_content, suggestions)
                                if applied > 0:
                                    with open(out_path, "w") as fh:
                                        fh.write(updated_yaml)
                                    yaml_content = updated_yaml
                                    print(f"  [{BRAND}]LLM resolved {applied} TODO field(s).[/{BRAND}]")
                                else:
                                    print("[dim]  LLM returned suggestions but none matched TODO fields.[/dim]")
                            except json.JSONDecodeError:
                                print("[yellow]  LLM response could not be parsed as JSON — TODO fields left as-is.[/yellow]")
        except Exception as exc:
            print(f"[yellow]  LLM TODO resolution error ({exc}) — TODO fields left as-is.[/yellow]")

    # ── Print summary ────────────────────────────────────────────────────
    console = Console()
    console.print()

    table = Table(title="Probe Results", show_header=True, header_style=f"bold {BRAND}")
    table.add_column("Field", style="bold", min_width=38)
    table.add_column("Result", min_width=20)
    table.add_column("Status", min_width=12)

    probe_display = [
        ("className",                           probes.get("className")),
        ("dbProductName",                       probes.get("dbProductName")),
        ("dbProductVersion",                    probes.get("dbProductVersion")),
        ("prefix (from URL)",                   prefix),
        ("identifierQuoteChar",                 probes.get("identifierQuoteChar")),
        ("transactionIsolation",                probes.get("transactionIsolation")),
        ("tableNameCasing",                     probes.get("tableNameCasing")),
        ("validationQuery",                     probes.get("validationQuery")),
        ("subqueryRequiresAlias",               str(probes.get("subqueryRequiresAlias", True)).lower()),
        ("getTablesUsesNullCatalog",            str(probes.get("getTablesUsesNullCatalog", False)).lower()),
        ("approxCountDistinctFunction",         probes.get("approxCountDistinctFunction")),
        ("rowCountQueryStyle",                  probes.get("rowCountQueryStyle")),
        ("schemaExistenceQueryStyle",           probes.get("schemaExistenceQueryStyle")),
        ("schemaOnlyQueryStyle",                probes.get("schemaOnlyQueryStyle")),
        ("dateArithmeticStyle",                 probes.get("dateArithmeticStyle")),
        ("rowLimitSyntax",                      probes.get("rowLimitSyntax")),
        ("tableSampleTemplate",                 probes.get("tableSampleTemplate")),
        ("viewSampleFallback",                  probes.get("viewSampleFallback")),
        ("timestampLiteralStyle",               probes.get("timestampLiteralStyle")),
        ("dateLiteralStyle",                    probes.get("dateLiteralStyle")),
        ("intervalCalcDatetimeTimestampTemplate", probes.get("intervalCalcDatetimeTimestampTemplate")),
        ("intervalCalcDatetimeDateTemplate",    probes.get("intervalCalcDatetimeDateTemplate")),
        ("upperBoundDatetimeTimestampTemplate", probes.get("upperBoundDatetimeTimestampTemplate")),
        ("upperBoundDatetimeDateTemplate",      probes.get("upperBoundDatetimeDateTemplate")),
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

    todo_count = sum(
        1 for _, v in probe_display if v is None or v == "null"
    )
    # Always-todo fields (not auto-detectable; need manual review or LLM assistance)
    always_todo = [
        "maxPartitionParallelism", "dataSizeLimit",
        "systemSchemaExclusions", "systemSchemaExclusionPrefixes", "systemCatalogExclusions",
        "connectionProperties", "sessionInitStatements", "dialectClass",
        "jdbcUrlStaticParams", "jdbcUrlConditionalParams", "connectionSpec",
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
        Optional[str],
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
