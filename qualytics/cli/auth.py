"""CLI commands for authentication and configuration."""

import platform
import secrets
import threading
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, quote, urlparse

import jwt
import typer
from rich import print

from ..config import is_token_valid, load_config, save_config, CONFIG_PATH
from ..utils import validate_and_format_url

auth_app = typer.Typer(
    name="auth", help="Authenticate the CLI with a Qualytics instance"
)

_DEFAULT_TIMEOUT = 120


@auth_app.command("login")
def auth_login(
    url: str = typer.Option(
        ...,
        "--url",
        "-u",
        help="Qualytics deployment URL (e.g. https://your-instance.qualytics.io)",
    ),
    timeout: int = typer.Option(
        _DEFAULT_TIMEOUT,
        "--timeout",
        help="Seconds to wait for browser callback",
    ),
    no_verify_ssl: bool = typer.Option(
        False,
        "--no-verify-ssl",
        help="Disable SSL certificate verification for API requests",
    ),
):
    """Authenticate via browser (opens a login page, receives a token callback)."""
    base_url = validate_and_format_url(url)
    state = secrets.token_urlsafe(32)

    # Start local callback server on an OS-assigned port
    try:
        result: dict = {}
        server = _create_callback_server(state, result)
    except OSError as e:
        print(f"[red]Failed to start local callback server: {e}[/red]")
        raise typer.Exit(code=1)

    _, port = server.server_address
    redirect_uri = f"http://127.0.0.1:{port}/callback"

    hostname = platform.node() or "unknown"
    # Strip macOS mDNS/Bonjour ".local" suffix — it's noise in a token name
    hostname = hostname.removesuffix(".local")
    hostname = quote(hostname)

    authorize_url = (
        f"{base_url}cli/authorize"
        f"?redirect_uri={redirect_uri}"
        f"&state={state}"
        f"&hostname={hostname}"
    )

    # Start listening before opening the browser so the server is ready
    server.timeout = timeout
    server_thread = threading.Thread(target=server.handle_request, daemon=True)
    server_thread.start()

    print(f"[cyan]Opening browser for authentication...[/cyan]")
    print(f"[dim]If the browser doesn't open, visit:[/dim]")
    print(f"[dim]{authorize_url}[/dim]")

    webbrowser.open(authorize_url)

    # Wait for the callback (single request, then shut down)
    server_thread.join(timeout=timeout + 1)

    server.server_close()

    # Process result
    if not result:
        print("[red]Authentication timed out. No callback received.[/red]")
        print(
            "[yellow]Try again or use 'qualytics auth init' to configure manually.[/yellow]"
        )
        raise typer.Exit(code=1)

    if result.get("error"):
        print(f"[red]Authentication failed: {result['error']}[/red]")
        raise typer.Exit(code=1)

    token = result.get("token")
    if not token:
        print("[red]No token received in callback.[/red]")
        raise typer.Exit(code=1)

    # Validate the token
    if is_token_valid(token) is None:
        print("[red]Received token is invalid or expired.[/red]")
        raise typer.Exit(code=1)

    # Save configuration
    config = {"url": base_url, "token": token, "ssl_verify": not no_verify_ssl}
    save_config(config)

    print("[bold green]Authentication successful! Configuration saved.[/bold green]")
    if no_verify_ssl:
        print(
            "[bold yellow]SSL verification is disabled. Use with caution.[/bold yellow]"
        )


@auth_app.command("status")
def auth_status():
    """Show current authentication status."""
    config = load_config()
    if config is None:
        print("[bold red]Not logged in.[/bold red]")
        print(
            "[yellow]Run 'qualytics auth login --url <your-url>' "
            "or 'qualytics auth init --url <url> --token <token>' to authenticate.[/yellow]"
        )
        raise typer.Exit(code=1)

    url = config.get("url", "(unknown)")
    token = config.get("token", "")
    ssl_verify = config.get("ssl_verify", True)

    # Extract hostname from URL for display
    try:
        parsed = urlparse(url)
        host = parsed.hostname or url
    except Exception:
        host = url

    # Mask the token: show first 4 chars + asterisks
    if len(token) > 4:
        masked_token = token[:4] + "*" * 16
    else:
        masked_token = "****"

    # Decode JWT to get expiry
    expiry_line = ""
    token_valid = True
    try:
        decoded = jwt.decode(
            token, algorithms=["none"], options={"verify_signature": False}
        )
        exp = decoded.get("exp")
        if exp is not None:
            exp_dt = datetime.fromtimestamp(exp, tz=timezone.utc)
            now = datetime.now(timezone.utc)
            delta = exp_dt - now

            if delta.total_seconds() <= 0:
                token_valid = False
                days_ago = abs(delta.days)
                expiry_line = f"[red]Token expired {days_ago} day(s) ago ({exp_dt.strftime('%Y-%m-%d %H:%M UTC')})[/red]"
            else:
                days_left = delta.days
                if days_left > 0:
                    relative = f"in {days_left} day(s)"
                else:
                    hours_left = int(delta.total_seconds() // 3600)
                    relative = f"in {hours_left} hour(s)"
                expiry_line = f"[green]Token expires {relative} ({exp_dt.strftime('%Y-%m-%d %H:%M UTC')})[/green]"
    except Exception:
        expiry_line = "[yellow]Could not decode token expiry[/yellow]"

    # Print status
    status_icon = (
        "[green]Logged in[/green]" if token_valid else "[red]Token expired[/red]"
    )
    ssl_label = "[green]enabled[/green]" if ssl_verify else "[yellow]disabled[/yellow]"

    print(f"[bold]{host}[/bold]")
    print(f"  Status:           {status_icon}")
    print(f"  Token:            {masked_token}")
    if expiry_line:
        print(f"  Expiry:           {expiry_line}")
    print(f"  SSL Verification: {ssl_label}")
    print(f"  Config file:      {CONFIG_PATH}")

    if not token_valid:
        print(
            "\n[yellow]Run 'qualytics auth login --url <your-url>' to re-authenticate.[/yellow]"
        )
        raise typer.Exit(code=1)


@auth_app.command("init")
def auth_init(
    url: str = typer.Option(
        ..., help="The URL to be set. Example: https://your-qualytics.qualytics.io/"
    ),
    token: str = typer.Option(..., help="The token to be set."),
    no_verify_ssl: bool = typer.Option(
        False,
        "--no-verify-ssl",
        help="Disable SSL certificate verification for API requests.",
    ),
):
    """Initialize Qualytics CLI configuration with a URL and token."""
    url = validate_and_format_url(url)

    config = {"url": url, "token": token, "ssl_verify": not no_verify_ssl}

    token_valid = is_token_valid(token)

    if token_valid:
        save_config(config)
        print("[bold green]Configuration saved![/bold green]")
        if no_verify_ssl:
            print(
                "[bold yellow]SSL verification is disabled. Use with caution.[/bold yellow]"
            )


def _create_callback_server(state: str, result: dict) -> HTTPServer:
    """Create an HTTP server that handles the OAuth-style callback."""

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)

            # Verify state parameter
            received_state = params.get("state", [None])[0]
            if received_state != state:
                result["error"] = "State mismatch — possible CSRF attack"
                self._respond(400, "Authentication failed: state mismatch.")
                return

            # Check for error from server
            error = params.get("error", [None])[0]
            if error:
                result["error"] = error
                self._respond(400, f"Authentication failed: {error}")
                return

            # Extract token
            token = params.get("token", [None])[0]
            if not token:
                result["error"] = "No token in callback"
                self._respond(400, "Authentication failed: no token received.")
                return

            result["token"] = token
            self._respond(200, "Authentication successful! You can close this tab.")

        def _respond(self, status: int, message: str):
            self.send_response(status)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            # Use history.replaceState to strip token from URL bar
            html = (
                f"<html><body><p>{message}</p>"
                "<script>history.replaceState(null, '', '/callback?done=1');</script>"
                "</body></html>"
            )
            self.wfile.write(html.encode())

        def log_message(self, format, *args):
            # Suppress HTTP logs to avoid printing token to terminal
            pass

    server = HTTPServer(("127.0.0.1", 0), CallbackHandler)
    return server
