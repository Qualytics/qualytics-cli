"""CLI command: generate-driver — probe a JDBC driver JAR and emit a YAML driver definition."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
from typing import Annotated, Optional

import typer
import yaml
from rich import print
from rich.console import Console
from rich.table import Table

from . import BRAND, print_banner
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

        // schemaExistenceQueryStyle
        String schemaStyle = "\"NONE\"";
        if (tryQuery(conn, "SELECT 1 FROM INFORMATION_SCHEMA.SCHEMATA WHERE 1=0", 5))
            schemaStyle = "\"INFORMATION_SCHEMA\"";
        else if (tryQuery(conn, "SHOW SCHEMAS", 5))
            schemaStyle = "\"SHOW_SCHEMAS\"";
        else if (tryQuery(conn, "SELECT 1 FROM SYSCAT.SCHEMATA WHERE 1=0", 5))
            schemaStyle = "\"SYSCAT\"";

        // dateArithmeticStyle + interval templates
        String dateArith = "\"STANDARD\"";
        String intervalTs = "null";
        String intervalDt = "null";
        String upperTs = "null";
        String upperDt = "null";

        if (tryQuery(conn, "SELECT TIMESTAMPADD(SECOND, 1, '2000-01-01')", 5)) {
            dateArith = "\"MYSQL\"";
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

        conn.close();

        // ── Emit JSON ─────────────────────────────────────────────────────
        StringBuilder out = new StringBuilder();
        out.append("{\n");
        out.append("  \"className\": ").append(jq(className)).append(",\n");
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
        out.append("  \"upperBoundDatetimeDateTemplate\": ").append(upperDt).append("\n");
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


def _build_yaml(
    prefix: str,
    probes: dict,
    jdbc_url: str,
) -> tuple[str, list[str], list[str]]:
    """
    Build the complete YAML content string from the probes dict.

    Fields that were auto-detected get a short '# auto-detected' comment;
    fields that need manual review get '# TODO: review' comments.
    """

    detected_fields: list[str] = []
    todo_fields: list[str] = []

    def field(name: str, value, comment: str = "") -> str:
        if value is None:
            rendered = "null"
        elif isinstance(value, bool):
            rendered = str(value).lower()
        elif isinstance(value, int):
            rendered = str(value)
        else:
            # string — quote only if it contains special YAML chars or spaces
            sv = str(value)
            if sv == "null":
                rendered = "null"
            elif any(c in sv for c in [':', '#', '[', ']', '{', '}', ',', '&', '*', '?', '|', '-', '<', '>', '=', '!', '%', '@', '`', '"', "'", '\n']):
                rendered = yaml.dump(sv, default_flow_style=True).strip()
            else:
                rendered = sv
        comment_str = f"  # {comment}" if comment else ""
        return f"{name}: {rendered}{comment_str}"

    lines: list[str] = []

    # ── Header comment ──────────────────────────────────────────────────────
    lines.append(
        textwrap.dedent(f"""\
        # Generated by: qualytics generate-driver
        # Source URL:   {jdbc_url}
        #
        # Fields marked  "# auto-detected"  were probed from JDBC metadata and live SQL.
        # Fields marked  "# TODO: review"   could not be detected automatically; verify
        # them against your database documentation before deploying.
        #
        # Deploy this file to:  META-INF/jdbc-drivers/{prefix}.yaml
        """)
    )

    # ── Auto-detected section ───────────────────────────────────────────────
    lines.append("# ── Auto-detected (verify before deploying) ──────────────────────")

    class_name = probes.get("className")
    lines.append(field("prefix", prefix, "review — extracted from JDBC URL"))
    lines.append(field("className", class_name, "auto-detected"))
    todo_fields.append("prefix")
    detected_fields.append("className")

    quote_char = probes.get("identifierQuoteChar")
    lines.append(field("identifierQuoteChar", quote_char, "auto-detected"))
    detected_fields.append("identifierQuoteChar")

    tx = probes.get("transactionIsolation")
    lines.append(field("transactionIsolation", tx, "auto-detected" if tx else "TODO: review"))
    (detected_fields if tx else todo_fields).append("transactionIsolation")

    casing = probes.get("tableNameCasing")
    lines.append(field("tableNameCasing", casing, "auto-detected"))
    detected_fields.append("tableNameCasing")

    row_limit = probes.get("rowLimitSyntax")
    lines.append(field("rowLimitSyntax", row_limit, "auto-detected" if row_limit else "TODO: review — try TOP, LIMIT, FETCH_FIRST, ROWNUM"))
    (detected_fields if row_limit else todo_fields).append("rowLimitSyntax")

    sub_alias = probes.get("subqueryRequiresAlias", False)
    lines.append(field("subqueryRequiresAlias", sub_alias, "auto-detected"))
    detected_fields.append("subqueryRequiresAlias")

    lines.append("")

    val_q = probes.get("validationQuery")
    lines.append(field("validationQuery", val_q, "auto-detected" if val_q else "TODO: review — try SELECT 1 or SELECT 1 FROM DUAL"))
    (detected_fields if val_q else todo_fields).append("validationQuery")

    lines.append("")

    sample_tmpl = probes.get("tableSampleTemplate")
    lines.append(field("tableSampleTemplate", sample_tmpl, "auto-detected" if sample_tmpl else "null — no TABLESAMPLE support detected"))
    detected_fields.append("tableSampleTemplate")

    approx = probes.get("approxCountDistinctFunction")
    lines.append(field(
        "approxCountDistinctFunction",
        approx,
        "auto-detected" if approx else "null — falls back to COUNT(DISTINCT col)",
    ))
    detected_fields.append("approxCountDistinctFunction")

    lines.append("")

    get_tables_null = probes.get("getTablesUsesNullCatalog", False)
    lines.append(field("getTablesUsesNullCatalog", get_tables_null, "auto-detected"))
    detected_fields.append("getTablesUsesNullCatalog")

    schema_style = probes.get("schemaExistenceQueryStyle", "NONE")
    lines.append(field("schemaExistenceQueryStyle", schema_style, "auto-detected"))
    detected_fields.append("schemaExistenceQueryStyle")

    date_arith = probes.get("dateArithmeticStyle", "STANDARD")
    lines.append(field("dateArithmeticStyle", date_arith, "auto-detected"))
    detected_fields.append("dateArithmeticStyle")

    lines.append("")

    # ── Performance tuning ──────────────────────────────────────────────────
    lines.append("# ── Performance tuning (adjust for your workload) ────────────────")
    lines.append(field("insertBatchSize", 10000, "TODO: tune for driver performance"))
    lines.append(field("maxPartitionParallelism", 10, "TODO: set to 1 for write-heavy databases"))
    lines.append(field("dataSizeLimit", "LONG_MAX", "TODO: use INT_MAX for SQL Server, Redshift, Db2"))
    todo_fields += ["insertBatchSize", "maxPartitionParallelism", "dataSizeLimit"]

    lines.append("")

    # ── Needs manual research ────────────────────────────────────────────────
    lines.append("# ── Needs manual research (database-specific) ────────────────────")
    lines.append(field("timestampLiteralStyle", "PLAIN", "TODO: check if CAST_DATETIME2, TO_TIMESTAMP, etc. applies"))
    lines.append(field("dateLiteralStyle", "PLAIN", "TODO: check if DATE_PREFIX or TO_DATE applies"))
    lines.append(field("schemaOnlyQueryStyle", "CTE", "TODO: check if SQLSERVER_TOP0, WHERE_FALSE_QUERYA, etc. applies"))
    lines.append(field("viewSampleFallback", "RAND", "TODO: verify RAND() is supported"))
    lines.append(field("rowCountQueryStyle", "COUNT_STAR", "TODO: check if INFORMATION_SCHEMA_TABLES_WITH_SIZE etc. applies"))
    todo_fields += ["timestampLiteralStyle", "dateLiteralStyle", "schemaOnlyQueryStyle",
                    "viewSampleFallback", "rowCountQueryStyle"]

    lines.append("")
    lines.append("systemSchemaExclusions: []      # TODO: add internal system schemas")
    lines.append("systemSchemaExclusionPrefixes: []  # TODO: add prefixes of temporary schemas")
    lines.append("systemCatalogExclusions: []     # TODO: add internal system catalogs")
    todo_fields += ["systemSchemaExclusions", "systemSchemaExclusionPrefixes", "systemCatalogExclusions"]

    lines.append("")

    # ── Advanced ────────────────────────────────────────────────────────────
    lines.append("# ── Advanced (leave null unless you know you need them) ──────────")
    lines.append("connectionProperties: {}        # TODO: add driver-specific properties if needed")
    lines.append("sessionInitStatements: []       # TODO: add session SQL if needed (NLS, SET DATEFORMAT, etc.)")
    lines.append(field("readOnly", False))
    lines.append(field("dialectClass", None, "TODO: set to JdbcDialect class if bundling Spark dialect"))
    todo_fields += ["connectionProperties", "sessionInitStatements", "dialectClass"]

    lines.append("")

    # ── Date arithmetic templates ────────────────────────────────────────────
    lines.append("# ── Date arithmetic templates ────────────────────────────────────")
    lines.append("# Placeholders: {col} = column name, {interval} = interval expression")
    lines.append("")
    lines.append(field("intervalCalcNumericTemplate", None, "use generic CASE/DECIMAL(38,0) fallback"))

    int_ts = probes.get("intervalCalcDatetimeTimestampTemplate")
    int_dt = probes.get("intervalCalcDatetimeDateTemplate")
    up_ts  = probes.get("upperBoundDatetimeTimestampTemplate")
    up_dt  = probes.get("upperBoundDatetimeDateTemplate")

    if int_ts:
        lines.append(field("intervalCalcDatetimeTimestampTemplate", int_ts, "auto-detected"))
        detected_fields.append("intervalCalcDatetimeTimestampTemplate")
    else:
        lines.append(field("intervalCalcDatetimeTimestampTemplate", None, "TODO: set timestamp midpoint expression"))
        todo_fields.append("intervalCalcDatetimeTimestampTemplate")

    if int_dt:
        lines.append(field("intervalCalcDatetimeDateTemplate", int_dt, "auto-detected"))
        detected_fields.append("intervalCalcDatetimeDateTemplate")
    else:
        lines.append(field("intervalCalcDatetimeDateTemplate", None, "TODO: set date midpoint expression"))
        todo_fields.append("intervalCalcDatetimeDateTemplate")

    lines.append("")
    lines.append(field("upperBoundNumericTemplate", None, "use code default"))

    if up_ts:
        lines.append(field("upperBoundDatetimeTimestampTemplate", up_ts, "auto-detected"))
        detected_fields.append("upperBoundDatetimeTimestampTemplate")
    else:
        lines.append(field("upperBoundDatetimeTimestampTemplate", None, "TODO: set timestamp upper-bound expression"))
        todo_fields.append("upperBoundDatetimeTimestampTemplate")

    if up_dt:
        lines.append(field("upperBoundDatetimeDateTemplate", up_dt, "auto-detected"))
        detected_fields.append("upperBoundDatetimeDateTemplate")
    else:
        lines.append(field("upperBoundDatetimeDateTemplate", None, "TODO: set date upper-bound expression"))
        todo_fields.append("upperBoundDatetimeDateTemplate")

    return "\n".join(lines) + "\n", detected_fields, todo_fields


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------

generate_driver_app = typer.Typer(
    name="generate-driver",
    help="Generate a YAML driver definition by probing a JDBC driver JAR.",
    invoke_without_command=True,
)


@generate_driver_app.callback(invoke_without_command=True)
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
            help="Output file path. Defaults to <prefix>.yaml in the current directory.",
            show_default=False,
        ),
    ] = None,
) -> None:
    """Generate a YAML driver definition by probing a JDBC driver JAR.

    Connects to the database using the provided JAR and URL, runs a series of
    introspection probes, and writes a best-effort YAML file you can review
    and edit before deploying to META-INF/jdbc-drivers/.

    Requires a JDK (java + javac) on PATH.

    Examples:

    \\b
        qualytics generate-driver \\
            --jar ./postgresql-42.7.3.jar \\
            --url jdbc:postgresql://localhost:5432/mydb \\
            --user alice --password secret

        qualytics generate-driver \\
            --jar ./custom-driver.jar \\
            --url jdbc:customdb://host:1234/catalog \\
            --properties loginTimeout=30 \\
            --output custom.yaml
    """
    # Skip if invoked as part of a help display
    if ctx.invoked_subcommand is not None:
        return

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
        out_path = os.path.join(os.getcwd(), f"{prefix}.yaml")

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
    yaml_content, detected_fields, todo_fields = _build_yaml(prefix, probes, url)

    # ── Write output ─────────────────────────────────────────────────────
    try:
        with open(out_path, "w") as fh:
            fh.write(yaml_content)
    except OSError as e:
        print(f"[red]Failed to write output file: {e}[/red]")
        raise typer.Exit(code=1)

    # ── Print summary ────────────────────────────────────────────────────
    console = Console()
    console.print()

    table = Table(title="Probe Results", show_header=True, header_style=f"bold {BRAND}")
    table.add_column("Field", style="bold", min_width=38)
    table.add_column("Result", min_width=20)
    table.add_column("Status", min_width=12)

    probe_display = [
        ("className",                           probes.get("className")),
        ("prefix (from URL)",                   prefix),
        ("identifierQuoteChar",                 probes.get("identifierQuoteChar")),
        ("transactionIsolation",                probes.get("transactionIsolation")),
        ("tableNameCasing",                     probes.get("tableNameCasing")),
        ("validationQuery",                     probes.get("validationQuery")),
        ("subqueryRequiresAlias",               str(probes.get("subqueryRequiresAlias", False)).lower()),
        ("getTablesUsesNullCatalog",            str(probes.get("getTablesUsesNullCatalog", False)).lower()),
        ("approxCountDistinctFunction",         probes.get("approxCountDistinctFunction")),
        ("schemaExistenceQueryStyle",           probes.get("schemaExistenceQueryStyle")),
        ("dateArithmeticStyle",                 probes.get("dateArithmeticStyle")),
        ("rowLimitSyntax",                      probes.get("rowLimitSyntax")),
        ("tableSampleTemplate",                 probes.get("tableSampleTemplate")),
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
    # Always-todo fields (performance tuning, manual research)
    always_todo = [
        "insertBatchSize", "maxPartitionParallelism", "dataSizeLimit",
        "timestampLiteralStyle", "dateLiteralStyle", "schemaOnlyQueryStyle",
        "viewSampleFallback", "rowCountQueryStyle",
        "systemSchemaExclusions", "systemSchemaExclusionPrefixes", "systemCatalogExclusions",
        "connectionProperties", "sessionInitStatements", "dialectClass",
    ]
    total_todo = todo_count + len(always_todo)
    auto_detected = len(probe_display) - todo_count

    print(
        f"  [{BRAND}]{auto_detected} field(s) auto-detected[/{BRAND}]  "
        f"[yellow]{total_todo} field(s) need review[/yellow]\n"
    )
    print(f"  [bold]Written:[/bold] {out_path}")
    print(
        "\n  [dim]Review the file, fill in the TODO comments, then deploy to:[/dim]"
        "\n  [dim]META-INF/jdbc-drivers/" + prefix + ".yaml[/dim]\n"
    )
