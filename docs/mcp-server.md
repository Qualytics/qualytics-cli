# MCP Server (LLM Integration)

The CLI includes a built-in [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) server, enabling Claude Code, Cursor, Windsurf, and other AI tools to call Qualytics operations directly as structured tool calls.

## Setup for Claude Code

Add to `~/.claude.json`:

```json
{
  "mcpServers": {
    "qualytics": {
      "command": "qualytics",
      "args": ["mcp", "serve"]
    }
  }
}
```

Then in Claude Code you can say things like:

> "List all datastores and show me which ones have failing quality checks"

> "Create a computed table that finds orders with negative totals"

> "Run a scan on datastore 42 and check for new anomalies"

Claude Code will call the appropriate tools directly and get structured JSON responses.

## Setup for Cursor

Add to your Cursor MCP settings:

```json
{
  "mcpServers": {
    "qualytics": {
      "command": "qualytics",
      "args": ["mcp", "serve"]
    }
  }
}
```

## Running the Server

```bash
# STDIO transport (default -- used by Claude Code and Cursor)
qualytics mcp serve

# Streamable-HTTP transport (network-accessible)
qualytics mcp serve --transport streamable-http --port 8000
```

## Available Tools

35 tools across 8 groups covering the full Qualytics API:

- **Auth**: `auth_status`
- **Datastores**: `list_datastores`, `get_datastore`, `create_datastore`, `update_datastore`, `delete_datastore`
- **Containers**: `list_containers`, `get_container`, `create_container`, `update_container`, `delete_container`, `get_field_profiles`
- **Connections**: `list_connections`, `get_connection`, `create_connection`, `update_connection`, `delete_connection`, `test_connection`
- **Quality Checks**: `list_checks`, `get_check`, `create_check`, `update_check`, `delete_check`
- **Anomalies**: `list_anomalies`, `get_anomaly`, `update_anomaly`, `archive_anomaly`, `delete_anomaly`
- **Operations**: `catalog`, `profile`, `scan`, `get_operation`, `list_operations`, `abort_operation`
- **Config**: `export_config`, `import_config`

Run `qualytics mcp serve --help` for details.
