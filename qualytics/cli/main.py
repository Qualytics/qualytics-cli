"""Main CLI commands for Qualytics CLI."""
import os
import typer
from typing import Annotated
from rich import print

from ..setup import (
    __version__,
    load_config,
    save_local_env_config,
    is_token_valid,
    CONFIG_PATH,
    get_local_config_dir,
    get_local_assets_dir,
    get_local_qualytics_dir,
)
from ..utils import validate_and_format_url


app = typer.Typer()


@app.callback(invoke_without_command=True)
def version_callback(
    version: Annotated[bool | None, typer.Option("--version", is_eager=True)] = None,
):
    """Display version information."""
    if version:
        print(f"Qualytics CLI Version: {__version__}")
        raise typer.Exit()


@app.command()
def show_config():
    """Display the saved configuration."""
    config = load_config()
    if config:
        print(f"[bold yellow] Config file located in: {CONFIG_PATH} [/bold yellow]")
        print(f"[bold yellow] URL: {config['url']} [/bold yellow]")
        print(f"[bold yellow] Token: {config['token']} [/bold yellow]")

        # Verify token expiration using the separate function
        is_token_valid(config["token"])
    else:
        print("Configuration not found!")

@app.command()
def init():
    """Initialize Qualytics CLI configuration in local project directory."""
    # Create assets and config directories in the current working directory
    print("[bold cyan] Setting up project structure... [/bold cyan]")

    # Create assets subfolders
    local_assets_dir = get_local_assets_dir()
    os.makedirs(os.path.join(local_assets_dir, "anomalies"), exist_ok=True)
    os.makedirs(os.path.join(local_assets_dir, "check_templates"), exist_ok=True)
    os.makedirs(os.path.join(local_assets_dir, "checks"), exist_ok=True)
    print(f"[bold green] ✓ Created assets folder structure at: {local_assets_dir} [/bold green]")

    # Create config folder
    local_config_dir = get_local_config_dir()
    os.makedirs(local_config_dir, exist_ok=True)
    print(f"[bold green] ✓ Created config folder at: {local_config_dir} [/bold green]")

    # Create connections_example.yml
    connections_content = """# Example connections.yml file
# Then update with your actual connection credentials or use environment variables
#
#
# Security: Set file permissions to 600 to restrict access
#   chmod 600 ~/.qualytics/config/connections.yml

connections:
  # PostgreSQL Connection Example
  my_postgres:
    type: postgresql                      # Connection type
    name: production_postgres_db          # Required: Unique connection name
    parameters:
      host: postgres.example.com          # Database hostname
      port: 5432                          # Database port
      user: postgres_user                 # Database username
      password: your_secure_password      # Database password

  # Snowflake Connection Example (Username/Password)
  my_snowflake:
    type: snowflake
    name: prod_snowflake_connection
    parameters:
      host: account.snowflakecomputing.com
      role: DATA_ANALYST                  # Snowflake role
      warehouse: COMPUTE_WH               # Snowflake warehouse
      user: snowflake_user
      password: your_snowflake_password

  # Snowflake Connection Example (Key-Pair Authentication)
  my_snowflake_keypair:
    type: snowflake
    name: prod_snowflake_keypair
    parameters:
      host: account.snowflakecomputing.com
      role: DATA_ANALYST
      warehouse: COMPUTE_WH
      database: ANALYTICS_DB              # Optional: Default database
      schema: PUBLIC                      # Optional: Default schema
      authentication:
        method: keypair                   # Use key-pair authentication
        user: snowflake_user
        private_key_path: /path/to/private_key.pem  # Path to private key file

  # MySQL Connection Example
  my_mysql:
    type: mysql
    name: prod_mysql_db
    parameters:
      host: mysql.example.com
      port: 3306
      user: mysql_user
      password: mysql_password

  # BigQuery Connection Example
  my_bigquery:
    type: bigquery
    name: prod_bigquery
    parameters:
      project_id: my-gcp-project-id       # GCP project ID
      credentials_path: /path/to/service-account-key.json  # Path to service account JSON

  # Azure Blob File System (ABFS) Connection Example
  my_abfs:
    type: abfs
    name: azure_data_lake
    parameters:
      storage_account: mystorageaccount   # Azure storage account name
      container: mycontainer              # Container name
      access_key: your_access_key         # Storage account access key

  # Amazon Redshift Connection Example
  my_redshift:
    type: redshift
    name: prod_redshift
    parameters:
      host: redshift-cluster.example.com
      port: 5439
      user: redshift_user
      password: redshift_password
      database: analytics

  # Microsoft SQL Server Connection Example
  my_sqlserver:
    type: sqlserver
    name: prod_sqlserver
    parameters:
      host: sqlserver.example.com
      port: 1433
      user: sa
      password: sqlserver_password
      database: production_db

# Usage Examples:
#
# Create a datastore using an existing connection:
#   qualytics datastore new \\
#     --name "My Datastore" \\
#     --connection-name production_postgres_db \\
#     --database mydb \\
#     --schema public
#
# The CLI will:
#   1. Check if "production_postgres_db" exists in Qualytics
#   2. If yes: Use the existing connection ID
#   3. If no: Create a new connection using the config above
"""

    instance_content = """cli_version: 0.2.0

instances:
  - name: dev_qualytics
    url: ${QUALYTICS_URL}
    api_token: ${QUALYTICS_API_TOKEN}

    checks:
      import:
        location: qualytics/objects/checks/imports
      export:
        location: qualytics/objects/checks/exports    # Default output location
        file_format: json
        error_log: ${OPERATION_ERROR_PATH}

  - name: staging_qualytics
    url: ${QUALYTICS_STAGING_URL}
    api_token: ${QUALYTICS_STAGING_API_TOKEN}

    checks:
      import:
        location: qualytics/objects/checks/imports
      export:
        location: qualytics/objects/checks/exports
        file_format: json
        error_log: ${OPERATION_ERROR_PATH}
"""

    # Write YAML files
    with open(os.path.join(local_config_dir, "connections_example.yml"), "w") as f:
        f.write(connections_content)
    with open(os.path.join(local_config_dir, "instance.yml"), "w") as f:
        f.write(instance_content)
    print(f"[bold green] ✓ Created configuration files (connections_example.yml, instance.yml) [/bold green]")

    # Check if there's an existing JSON config file
    config = load_config()
    local_qualytics_dir = get_local_qualytics_dir()

    if config:
        # Migration path: User has existing JSON config
        print("[bold yellow] Found existing configuration file. Migrating to .env format... [/bold yellow]")
        url = config.get("url")
        token = config.get("token")

        # Verify token expiration
        token_valid = is_token_valid(token)

        if token_valid:
            save_local_env_config(url, token)
            print(f"[bold green] ✓ Created .qualytics folder at: {local_qualytics_dir} [/bold green]")
            print(f"[bold green] ✓ Configuration migrated to .env file at: {local_qualytics_dir}/.env [/bold green]")
    else:
        # New user path: No existing config, prompt for input
        # Prompt user for URL
        url = typer.prompt("Enter your Qualytics URL (e.g., https://your-qualytics.qualytics.io)")
        url = validate_and_format_url(url)

        # Prompt user for token
        token = typer.prompt("Enter your Qualytics API token", hide_input=True)

        # Verify token expiration using the separate function
        token_valid = is_token_valid(token)

        if token_valid:
            save_local_env_config(url, token)
            print(f"[bold green] ✓ Created .qualytics folder at: {local_qualytics_dir} [/bold green]")
            print(f"[bold green] ✓ Configuration saved to .env file at: {local_qualytics_dir}/.env [/bold green]")

    # Show final success message for both paths
    print("\n[bold green] Project initialized successfully! [/bold green]")
    print("[bold cyan] Your project structure: [/bold cyan]")
    print("  ├── .qualytics/")
    print("  │   └── .env")
    print("  ├── assets/")
    print("  │   ├── anomalies/")
    print("  │   ├── check_templates/")
    print("  │   └── checks/")
    print("  └── config/")
    print("      ├── connections_example.yml")
    print("      └── instance.yml")
