"""CLI command to start the Qualytics MCP server."""

import httpx
import typer
from fastmcp.client import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server import create_proxy

from . import add_suggestion_callback
from ..config import load_config, CONFIG_PATH
from ..mcp.server import auth_status

mcp_app = typer.Typer(name="mcp", help="Start an MCP server for LLM integrations")
add_suggestion_callback(mcp_app, "mcp")


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

    Proxies the full Qualytics MCP tool set from the remote deployment over a
    local stdio transport, combining the platform's native tool surface with
    easy connectivity for desktop LLM clients.

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
    config = load_config()
    if config is None:
        raise typer.BadParameter(
            f"Not authenticated. Run 'qualytics auth login' or "
            f"'qualytics auth init'. Config expected at {CONFIG_PATH}",
            param_hint="authentication",
        )

    url = config.get("url", "").rstrip("/")
    token = config.get("token", "")
    ssl_verify = config.get("ssl_verify", True)

    remote_transport = StreamableHttpTransport(
        url=f"{url}/mcp",
        auth=token,
        httpx_client_factory=lambda **kwargs: httpx.AsyncClient(
            verify=ssl_verify, **kwargs
        ),
    )
    proxy = create_proxy(Client(remote_transport), name="Qualytics")
    proxy.add_tool(auth_status)

    if transport in ("streamable-http", "http", "sse"):
        proxy.run(transport="streamable-http", host=host, port=port)
    else:
        proxy.run(transport="stdio")
