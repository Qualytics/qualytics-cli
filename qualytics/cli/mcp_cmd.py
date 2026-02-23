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
        help="Transport protocol: stdio (default) or streamable-http",
    ),
    host: str = typer.Option(
        "127.0.0.1",
        "--host",
        help="Host for streamable-http transport (default: 127.0.0.1)",
    ),
    port: int = typer.Option(
        8000,
        "--port",
        "-p",
        help="Port for streamable-http transport (default: 8000)",
    ),
):
    """Start the Qualytics MCP server for Claude Code, Cursor, and other LLM tools.

    STDIO transport (default) is used by Claude Code and Cursor.
    Streamable-HTTP transport is available for network-accessible deployments.

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

    if transport in ("streamable-http", "http", "sse"):
        mcp.run(transport="streamable-http", host=host, port=port)
    else:
        mcp.run(transport="stdio")
