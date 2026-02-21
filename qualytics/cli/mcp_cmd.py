"""CLI command to start the Qualytics MCP server."""

import typer

mcp_app = typer.Typer(
    name="mcp", help="Model Context Protocol (MCP) server for LLM integrations"
)


@mcp_app.command("serve")
def mcp_serve(
    transport: str = typer.Option(
        "stdio",
        "--transport",
        "-t",
        help="Transport protocol: stdio (default) or http",
    ),
    host: str = typer.Option(
        "127.0.0.1",
        "--host",
        help="Host for HTTP transport (default: 127.0.0.1)",
    ),
    port: int = typer.Option(
        8000,
        "--port",
        "-p",
        help="Port for HTTP transport (default: 8000)",
    ),
):
    """Start the Qualytics MCP server for Claude Code, Cursor, and other LLM tools.

    STDIO transport (default) is used by Claude Code and Cursor.
    HTTP transport is available for network-accessible deployments.

    Setup for Claude Code (~/.claude.json):

        {
          "mcpServers": {
            "qualytics": {
              "command": "qualytics",
              "args": ["mcp", "serve"]
            }
          }
        }
    """
    from ..mcp.server import mcp

    if transport == "http":
        mcp.run(transport="http", host=host, port=port)
    else:
        mcp.run()
