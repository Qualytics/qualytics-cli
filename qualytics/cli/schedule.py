"""CLI commands for scheduling operations."""

import platform
import subprocess
import typer
from datetime import datetime
from croniter import croniter
from rich import print

from ..config import (
    BASE_PATH,
    CRONTAB_ERROR_PATH,
    CRONTAB_COMMANDS_PATH,
    load_config,
    is_token_valid,
)
from ..utils import validate_and_format_url


# Create Typer instance for schedule
schedule_app = typer.Typer(name="schedule", help="Commands for handling schedules")


@schedule_app.command("export-metadata")
def schedule(
    crontab_expression: str = typer.Option(
        ...,
        "--crontab",
        help="Crontab expression inside quotes, specifying when the task should run. Example: '0 * * * *' ",
    ),
    datastore: str = typer.Option(..., "--datastore", help="The datastore ID"),
    containers: str | None = typer.Option(
        None,
        "--containers",
        help='Comma-separated list of containers IDs or array-like format. Example: "1, 2, 3" or "[1,2,3]"',
    ),
    options: str = typer.Option(
        ...,
        "--options",
        help="Comma-separated list of op to export or all for everything. Example: anomalies, checks, field-profiles or all",
    ),
):
    # Validate the crontab expression
    try:
        croniter(crontab_expression)
    except ValueError:
        print(
            "[bold red] WARNING: Invalid crontab expression. Please provide a valid expression. [/bold red]"
        )
        return
    if containers:
        containers = [int(x.strip()) for x in containers.strip("[]").split(",")]

    if "all" in options:
        # If "all" is specified, include all metadata types
        options = ["anomalies", "checks", "field-profiles"]
    elif "," in options:
        options = [str(x.strip()) for x in options.strip("[]").split(",")]
    else:
        options = [options]

    config = load_config()
    base_url = validate_and_format_url(config["url"])
    token = is_token_valid(config["token"])

    # Determine the operating system
    operating_system = platform.system()

    if token:
        commands = []
        # Construct the appropriate command based on the operating system

        for option in options:
            log_file_path = f"{BASE_PATH}/schedule_{option}.txt"
            if operating_system == "Windows":
                if containers:
                    containers_string = "".join(
                        f"&containers={container}" for container in containers
                    )
                    powershell_script = (
                        f"Invoke-RestMethod -Method 'Post' "
                        f'-Uri "{base_url}export/{option}?datastore={datastore}{containers_string}" '
                        f"-Headers @{{'Authorization' = 'Bearer {token}'; 'Content-Type' = 'application/json'}} "
                    )

                else:
                    powershell_script = (
                        f"Invoke-RestMethod -Method 'Post' "
                        f"-Uri {base_url}export/{option}?datastore={datastore} "
                        f"-Headers @{{'Authorization' = 'Bearer {token}'; 'Content-Type' = 'application/json'}} "
                    )

                # powershell_script += f'$response | Out-File \'{log_file_path}\' -Append\''
                script_name = f"task_scheduler_script_{option}_{datastore}.ps1"
                # Save the PowerShell script to a file
                script_location = BASE_PATH + "/" + script_name
                with open(script_location, "w") as ps_script_file:
                    ps_script_file.write(powershell_script)

                # Print success message
                print(
                    f"[bold green]PowerShell script successfully created! Please check the script at: {script_location}[/bold green]"
                )

            elif operating_system == "Linux":
                if containers:
                    command = (
                        f"{crontab_expression} /usr/bin/curl --request POST --url '{base_url}export/{option}?datastore={datastore}'"
                        + "".join(
                            f"&containers={container}" for container in containers
                        )
                        + f" --header 'Authorization: Bearer {token}'  >> {log_file_path} 2>&1"
                    )
                else:
                    command = f"{crontab_expression} /usr/bin/curl --request POST --url '{base_url}export/{option}?datastore={datastore}' --header 'Authorization: Bearer {token}' >> {log_file_path} 2>&1"
                commands.append(command)

        if operating_system == "Linux":
            cron_commands = "\n".join(commands)

            with open(CRONTAB_COMMANDS_PATH, "a+") as file:
                file.write(cron_commands + "\n")

            # Run crontab command and add generated commands
            try:
                with open(CRONTAB_COMMANDS_PATH) as commands_file:
                    commands_content = commands_file.read()
                # Use input redirection to pass the content of the file to the crontab command
                subprocess.run(
                    f'crontab -l 2>{CRONTAB_ERROR_PATH} | echo "{commands_content}" | crontab -',
                    shell=True,
                    check=True,
                )
                # subprocess.run(f'(crontab -l 2>{CRONTAB_ERROR_PATH}; cat {CRONTAB_COMMANDS_PATH}) | crontab -', shell=True, check=True)
                print(
                    f"[bold green]Crontab successfully created! Please check the cronjobs in {CRONTAB_COMMANDS_PATH} or run `crontab -l` to list all cronjobs[/bold green]"
                )
            except subprocess.CalledProcessError as e:
                # Handle errors and write to the error file
                print(
                    f"[bold red] WARNING: There was an error in the crontab command. Please check the path: {CRONTAB_ERROR_PATH} [/bold red]"
                )
                with open(CRONTAB_ERROR_PATH, "a") as error_file:
                    current_datetime = datetime.now().strftime("[%m-%d-%Y %H:%M:%S]")
                    error_file.write(
                        f"{current_datetime} : Error executing crontab command: {e}\n"
                    )
                return


# ========================================== RUN_OPERATION_APP COMMANDS =================================================================
