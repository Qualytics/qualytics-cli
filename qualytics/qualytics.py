import time

import typer
import os
import json
import requests
import urllib3
import re
import jwt
import platform
import subprocess

from datetime import datetime
from pathlib import Path
from rich import print
from rich.progress import track
from itertools import product
from typing import Optional
from typing_extensions import Annotated
from croniter import croniter

__version__ = "0.1.10"

app = typer.Typer()

# Create a new Typer instance for checks
checks_app = typer.Typer(name="checks", help="Commands for handling checks")

# Create a new Typer instance for operation
schedule_app = typer.Typer(name="schedule", help="Commands for handling schedules")

# Creates a new Typer instance for triggering operations for datastores (catalog, profile, scan)
run_operation_app = typer.Typer(name="run", help="Command to trigger a datastores operation. (catalog, profile, scan)")

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Get the home directory
home = Path.home()

# Define the new directory
folder_name = ".qualytics"
BASE_PATH = f"{home}/{folder_name}"

CONFIG_PATH = os.path.expanduser(f"{BASE_PATH}/config.json")
CRONTAB_ERROR_PATH = os.path.expanduser(f"{BASE_PATH}/schedule-operation-errors.txt")
CRONTAB_COMMANDS_PATH = os.path.expanduser(f"{BASE_PATH}/schedule-operation.txt")
OPERATION_ERROR_PATH = os.path.expanduser(f"{BASE_PATH}/operation-error.txt")


def validate_and_format_url(url: str) -> str:
    """Validates and formats the URL to the desired structure."""

    original_url = url  # Store the original URL for comparison later

    # Ensure the URL starts with 'https://'
    if not url.startswith('https://'):
        if url.startswith('http://'):
            url = url.replace('http://', 'https://', 1)
        else:
            url = 'https://' + url

    # Remove any trailing slashes or '/api' or '/api/'
    url = url.rstrip('/').rstrip('/api').rstrip('/')

    # Append '/api/' to the URL
    url += '/api/'

    return url


def save_config(data):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, 'w') as f:
        json.dump(data, f, indent=4)


def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'r') as f:
            return json.load(f)
    return None


def _get_default_headers(token):
    return {
        "Authorization": f"Bearer {token}"
    }


def distinct_file_content(file_path):
    # Check if the file exists before opening it
    if not os.path.exists(file_path):
        return  # Return early if the file doesn't exist

    with open(file_path, 'r') as file:
        # Using a set to automatically get distinct lines
        distinct_lines = set(file.readlines())

    with open(file_path, 'w') as file:
        for line in distinct_lines:
            file.write(line)


def log_error(message, file_path):
    # Check if the file exists before opening it
    if not os.path.exists(file_path):
        with open(file_path, 'w'):
            pass  # Create an empty file if it doesn't exist

    with open(file_path, 'a') as file:
        file.write(message + '\n')
        file.flush()


def get_quality_checks(base_url: str, token: str, datastore_id: int, containers: list[int] | None):
    endpoint = "quality-checks"
    url = f"{base_url}{endpoint}?datastore={datastore_id}"

    if containers:
        containers_string = ''.join(f'&container={container}' for container in containers)
        url += containers_string

    page = 1
    size = 100
    params = {"sort_created": "asc", "size": size, "page": page}

    response = requests.get(url, headers=_get_default_headers(token), params=params, verify=False)

    # Check for non-success status codes
    if response.status_code != 200:
        typer.secho(
            f"Failed to retrieve quality checks. Server responded with: {response.status_code} - {response.text}. Please verify if your credentials are correct.",
            fg=typer.colors.RED)
        raise typer.Exit(code=1)

    data = response.json()

    # Check if "total" is in the response data
    if "total" not in data:
        typer.secho(
            f"Unexpected server response. 'total' field missing in: {data}. Please verify if your credentials are correct.",
            fg=typer.colors.RED)
        raise typer.Exit(code=1)

    total = data["total"]
    all_quality_checks = []

    total_pages = -(-total // size)

    # Loop through the pages based on total number and size
    for current_page in track(range(total_pages), description="Exporting quality checks..."):
        # Append the current page's data to the concatenated array
        all_quality_checks.extend(data["items"])

        total -= size
        page += 1

        params["page"] = page
        response = requests.get(url, headers=_get_default_headers(token), params=params, verify=False)
        data = response.json()

    print(f"[bold green] Total of Quality Checks = {data['total']} [/bold green]")
    print(f"[bold green] Total pages = {total_pages} [/bold green]")
    return all_quality_checks


def get_quality_check_by_description(base_url: str, token: str, description: str):
    endpoint = "quality-checks"
    params = {
        "search": description
    }
    url = f"{base_url}{endpoint}"

    response = requests.get(url, headers=_get_default_headers(token), params=params, verify=False)

    if response.status_code == 200:

        quality_check = response.json()['items']

        if len(quality_check) == 1:
            return response.json()['items'][0]['id']

    return None


def get_table_ids(base_url: str, token: str, datastore_id: int, max_retries=5, retry_delay=5):
    for attempt in range(max_retries):
        try:
            response = requests.get(base_url + f"containers/listing?datastore={datastore_id}",
                                    headers=_get_default_headers(token), verify=False)

            if response.status_code == 200:
                items_array = response.json()
                table_ids = {}
                for item in items_array:
                    table_ids[item["name"]] = item["id"]

                return table_ids
            else:
                typer.secho(
                    f"Attempt {attempt + 1} failed with status code {response.status_code} - {response.text}. Retrying...",
                    fg=typer.colors.RED)
                if attempt < max_retries - 1:  # Only sleep if it's not the last attempt
                    time.sleep(retry_delay)  # Wait for a specified delay before retrying
        except requests.RequestException as e:
            typer.secho(f"Request error during attempt {attempt + 1}: {e}. Retrying...", fg=typer.colors.RED)
            print()
            if attempt < max_retries - 1:  # Only sleep if it's not the last attempt
                time.sleep(retry_delay)  # Wait for a specified delay before retrying
    typer.secho(f"Failed getting the table ids after {max_retries} attempts.", fg=typer.colors.RED)
    return None


def is_token_valid(token: str):
   # Decode the JWT token
    try:
        decoded_token = jwt.decode(token, algorithms=['none'], options={"verify_signature": False})
        expiration_time = decoded_token.get('exp')

        if expiration_time is not None:
            current_time = datetime.utcnow().timestamp()
            if not expiration_time >= current_time:
                print('[bold red] WARNING: Your token is expired, please setup with a new token by running: qualytics init --url "your-qualytics.io/api" --token "my-token" [/bold red]')
                return None
            else:
                return token
    except Exception as e:
        print("[bold red] WARNING: Your token is not valid [/bold red]")


def run_catalog(datastore_ids: [int], include: [str], prune: bool, recreate: bool, token: str):
    config = load_config()
    base_url = base_url = validate_and_format_url(config['url'])
    endpoint = "operations/run"
    url = f"{base_url}{endpoint}"
    for datastore_id in track(datastore_ids, description="Processing..."):
        try:
            response = requests.post(f'{url}', headers=_get_default_headers(token), json={
                "datastore_id": datastore_id,
                "type": "catalog",
                "include": include,
                "prune": prune,
                "recreate": recreate
            })
            if 200 <= response.status_code <= 299:
                print(f"[bold green] Successfully started Catalog operation "
                      f"for datastore: {datastore_id} [/bold green]")
                wait_for_operation_finishes(response.json()["id"], token)
                print(f"[bold green] Successfully finished Catalog operation "
                      f"for datastore: {datastore_id} [/bold green]")
        except Exception:
            print(f"[bold red] Failed Catalog for datastore: {datastore_id}, Please check the path: "
                  f"{OPERATION_ERROR_PATH}[/bold red]")
            with open(OPERATION_ERROR_PATH, "a") as error_file:
                message = response.json()["detail"]
                current_datetime = datetime.now().strftime("[%m-%d-%Y %H:%M:%S]")
                error_file.write(f"{current_datetime} : Error executing catalog operation: {message}\n\n")


def run_profile(datastore_ids: [int], container_names: list[str] | None, container_tags: list[str] | None,
                infer_constraints: bool | None, max_records_analyzed_per_partition: int | None, max_count_testing_sample: int | None,
                percent_testing_threshold: float | None, high_correlation_threshold: float | None, greater_than_time: datetime | None,
                greater_than_batch: float | None, histogram_max_distinct_values: int | None, token: str):
    config = load_config()
    base_url = base_url = validate_and_format_url(config['url'])
    endpoint = "operations/run"
    url = f"{base_url}{endpoint}"

    for datastore_id in track(datastore_ids, description="Processing..."):
        try:
            response = requests.post(f'{url}',headers=_get_default_headers(token), json={
                "datastore_id": datastore_id,
                "type": "profile",
                "container_names": container_names,
                "container_tags": container_tags,
                "infer_constraints": infer_constraints,
                "max_records_analyzed_per_partition": max_records_analyzed_per_partition,
                "max_count_testing_sample": max_count_testing_sample,
                "percent_testing_threshold": percent_testing_threshold,
                "high_correlation_threshold": high_correlation_threshold,
                "greater_than_time": greater_than_time,
                "greater_than_batch": greater_than_batch,
                "histogram_max_distinct_values": histogram_max_distinct_values
            })
            if 200 <= response.status_code <= 299:
                print(f"[bold green] Successful Profile for datastore: {datastore_id} [/bold green]")
                break
        except Exception:
            print(f"[bold red] Failed Profile for datastore: {datastore_id}, Please check the path: "
                  f"{OPERATION_ERROR_PATH}[/bold red]")
            with open(OPERATION_ERROR_PATH, "a") as error_file:
                message = response.json()["detail"]
                current_datetime = datetime.now().strftime("[%m-%d-%Y %H:%M:%S]")
                error_file.write(f"{current_datetime} : Error executing catalog operation: {message}\n\n")
                break


def wait_for_operation_finishes(operation: int, token: str):
    """
    Wait for an operation to finish executing.

    Parameters:
    - operation (int): The operation ID.
    - headers (dict): Optional headers to pass to the requests request.

    Returns:
    - The operation response object.
    """
    config = load_config()
    base_url = base_url = validate_and_format_url(config['url'])
    headers = _get_default_headers(token)
    max_retries = 10
    wait_time = 50
    for attempt in range(max_retries):
        end_scan = None
        response = None
        while not end_scan:
            print(" Waiting for operation to finish")
            response = requests.get(base_url + f'operations/{operation}', headers=headers).json()
            time.sleep(5)
            if response['end_time']:
                end_scan = True
        time.sleep(10)
        if response['result'] == 'success':

            return response
        if attempt == max_retries - 1:
            return response
        print(f"Attempt {attempt + 1} failed. Retrying in {wait_time} seconds...")
        time.sleep(wait_time)



@app.callback(invoke_without_command=True)
def version_callback(version: Annotated[Optional[bool], typer.Option("--version", is_eager=True)] = None):
    if version:
        print(f"Qualytics CLI Version: {__version__}")
        raise typer.Exit()


@app.command()
def show_config():
    """
    Display the saved configuration.
    """
    config = load_config()
    if config:
        print(f"[bold yellow] Config file located in: {CONFIG_PATH} [/bold yellow]")
        print(f"[bold yellow] URL: {config['url']} [/bold yellow]")
        print(f"[bold yellow] Token: {config['token']} [/bold yellow]")
        
        # Verify token expiration using the separate function
        valid_token = is_token_valid(config['token'])
    else:
        print("Configuration not found!")


@app.command()
def init(url: str = typer.Option(..., help="The URL to be set. Example: https://your-qualytics.qualytics.io/"),
         token: str = typer.Option(..., help="The token to be set.")):
    url = validate_and_format_url(url)

    config = {
        "url": url,
        "token": token
    }

    # Verify token expiration using the separate function
    token_valid = is_token_valid(token)

    if token_valid:
        save_config(config)
        print("[bold green] Configuration saved! [/bold green]")


@checks_app.command("export")
def checks_export(datastore: int = typer.Option(..., "--datastore", help="Datastore ID"),
                  containers: Optional[str] = typer.Option(None, "--containers", help="Comma-separated list of containers IDs or array-like format. Example: \"1, 2, 3\" or \"[1,2,3]\""),
                  output: str = typer.Option(BASE_PATH + "/data_checks.json", "--output", help="Output file path")):
    """
    Export checks to a file.
    """
    config = load_config()
    base_url = validate_and_format_url(config['url'])
    token = is_token_valid(config['token'])
    
    if token:
        if containers:
            containers = [int(x.strip()) for x in containers.strip("[]").split(",")]

        all_quality_checks = get_quality_checks(base_url=base_url,
                                                token=token,
                                                datastore_id=datastore,
                                                containers=containers)

        with open(output, 'w') as f:
            json.dump(all_quality_checks, f, indent=4)
        print(f"[bold green]Data exported to {output}[/bold green]")


@checks_app.command("export-templates")
def check_templates_export(enrich_datastore_id: int = typer.Option(..., "--enrichment_datastore_id", help="Enrichment Datastore ID"),
                  check_templates: Optional[str] = typer.Option(None, "--check_templates",
                                                           help="Comma-separated list of check templates IDs or array-like format. Example: \"1, 2, 3\" or \"[1,2,3]\"")):
    """
    Export checks to a file.
    """
    config = load_config()
    base_url = validate_and_format_url(config['url'])
    token = is_token_valid(config['token'])

    if token:
        if check_templates:
            check_templates = [int(x.strip()) for x in check_templates.strip("[]").split(",")]

        endpoint = "export/check-templates"
        url = f"{base_url}{endpoint}?enrich_datastore_id={enrich_datastore_id}"

        if check_templates:
            containers_string = ''.join(f'&template_ids={check_template}' for check_template in check_templates)
            url += containers_string

        response = requests.post(url, headers=_get_default_headers(token), verify=False)

        # Check for non-success status codes
        if response.status_code != 204:
            typer.secho(
                f"Failed to export check templates. Server responded with: {response.status_code} - {response.text}.",
                fg=typer.colors.RED)
            raise typer.Exit(code=1)

        print(f"[bold green]The check templates were exported to the table `_export_check_templates` to enrichment id: {enrich_datastore_id}.[/bold green]")


@checks_app.command("import")
def checks_import(datastore: str = typer.Option(..., "--datastore",
                                                help="Comma-separated list of Datastore IDs or array-like format"),
                  input_file: str = typer.Option(BASE_PATH + "/data_checks.json", "--input", help="Input file path")):
    """
    Import checks from a file.
    """
    # Remove brackets if present and split by comma
    datastores = [int(x.strip()) for x in datastore.strip("[]").split(",")]
    config = load_config()
    base_url = validate_and_format_url(config['url'])
    token = is_token_valid(config['token'])
    error_log_path = f"/errors-{datetime.now().strftime('%Y-%m-%d')}.log"
    if token:
        with open(input_file, 'r') as f:
            all_quality_checks = json.load(f)
            total_created_checks = 0
            total_updated_checks = 0

            # Create pairs of datastore and quality_check to process
            pairs_to_process = list(product(datastores, all_quality_checks))

            # Now use the track function to show the progress bar
            for datastore_id, quality_check in track(pairs_to_process, description="Processing..."):
                # for datastore_id in datastores:
                table_ids = get_table_ids(base_url=base_url, token=token, datastore_id=datastore_id)

                # for quality_check in all_quality_checks:
                container_id = None
                if table_ids:
                    try:
                        container_id = table_ids[quality_check['container']['name']]
                    except:
                        print(
                            f"[bold red] Profile `{quality_check['container']['name']}` was not found in datastore id: {datastore_id}[/bold red]")
                        log_error(
                            f"Profile `{quality_check['container']['name']}` of quality check {quality_check['id']} was not found in datastore id: {datastore_id}",
                            BASE_PATH + error_log_path)
                    
                    if container_id:
                        description = f"[from quality check id: {quality_check['id']} - main datastore id: {datastore_id}]"
                        additional_metadata = {
                                "from quality check id": f"{quality_check['id']}",
                                "main datastore id": f"{datastore_id}"
                        }

                        if quality_check['additional_metadata'] is None:
                            quality_check['additional_metadata'] = additional_metadata
                        else:
                            quality_check['additional_metadata'].update(additional_metadata)

                        payload = {
                            "fields": [field['name'] for field in quality_check['fields']],
                            "description": f"{quality_check['description']} {description}",
                            "rule": quality_check['rule_type'],
                            "coverage": quality_check['coverage'],
                            "is_new": quality_check['is_new'],
                            "filter": quality_check['filter'],
                            "properties": quality_check['properties'],
                            "tags": [global_tag['name'] for global_tag in quality_check['global_tags']],
                            "container_id": container_id,
                            "additional_metadata": quality_check['additional_metadata']
                        }
                        # gets the quality_check by the description
                        quality_check_id = get_quality_check_by_description(base_url=base_url, token=token,
                                                                            description=description)

                        # If a quality check contains the description, we sync
                        if quality_check_id:
                            print(
                                f"[bold yellow]Quality check for container: {quality_check['container']['name']} was already created on datastore id: {datastore_id}. Updating quality check id: {quality_check_id}[/bold yellow]")
                            response = requests.put(base_url + f"quality-checks/{quality_check_id}",
                                                    headers=_get_default_headers(token), json=payload, verify=False)
                            if response.status_code == 200:
                                print(
                                    f"[bold green]Quality check id: {quality_check_id} updated successfully for datastore id: {datastore_id}[/bold green]")
                                total_updated_checks += 1
                            else:
                                print(f"[bold red]Error updating quality check id: {quality_check_id} [/bold red]")
                                log_error(
                                    f"Error updating quality check id: {quality_check_id} on datastore id: {datastore_id}. Details: {response.text}",
                                    BASE_PATH + error_log_path)
                        # If a quality check does not contain the description:
                        # 1. We try to create quality check and verify for conflict
                        #    a. If we notify a conflict, it will  update the check
                        #    b. If there's no conflict, it will create a new one
                        else:
                            response = requests.post(base_url + f"quality-checks", headers=_get_default_headers(token),
                                                    json=payload, verify=False)
                            if response.status_code == 409:
                                match = re.search(r"id: (\d+)", response.text)
                                print(
                                    f"[bold yellow]Quality check for container: {quality_check['container']['name']} was already created on datastore id: {datastore_id}. Updating check id: {match.group(1)}.[/bold yellow]")
                                response = requests.put(base_url + f"quality-checks/{match.group(1)}",
                                                        headers=_get_default_headers(token), json=payload, verify=False)
                                if response.status_code == 200:
                                    print(
                                        f"[bold green]Quality check id: {match.group(1)} updated successfully for datastore id: {datastore_id}[/bold green]")
                                    total_updated_checks += 1
                                else:
                                    print(f"[bold red]Error updating quality check id: {match.group(1)} [/bold red]")
                                    log_error(
                                        f"Error updating quality check id: {match.group(1)} on datastore id: {datastore_id}. Details: {response.text}",
                                        BASE_PATH + error_log_path)
                            elif response.status_code == 200:
                                print(
                                    f"[bold green]Quality check id: {response.json()['id']} for container: {quality_check['container']['name']} created successfully[/bold green]")
                                total_created_checks += 1
                            else:
                                log_error(
                                    f"Error creating quality check for datastore id: {datastore_id}. Details: {response.text}",
                                    BASE_PATH + error_log_path)

            print(f"Updated a total of {total_updated_checks} quality checks.")
            print(f"Created a tottal of {total_created_checks} quality checks.")
            distinct_file_content(BASE_PATH + error_log_path)


@schedule_app.command("export-metadata")
def schedule(
    crontab_expression: str = typer.Option(..., "--crontab", help="Crontab expression inside quotes, specifying when the task should run. Example: '0 * * * *' "),
    datastore: str = typer.Option(..., "--datastore",help="The datastore ID"),
    containers: Optional[str] = typer.Option(None, "--containers",help="Comma-separated list of containers IDs or array-like format. Example: \"1, 2, 3\" or \"[1,2,3]\""),
    options: str = typer.Option(..., "--options", help="Comma-separated list of op to export or all for everything. Example: anomalies, checks, field-profiles or all"),
):
    
    # Validate the crontab expression
    try:
        croniter(crontab_expression)
    except ValueError:
        print("[bold red] WARNING: Invalid crontab expression. Please provide a valid expression. [/bold red]")
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
    base_url = validate_and_format_url(config['url'])
    token = is_token_valid(config['token'])
    
    # Determine the operating system
    operating_system = platform.system()
    
    if token:
        commands = []
        # Construct the appropriate command based on the operating system
        
        for option in options:
            log_file_path = f'{BASE_PATH}/schedule_{option}.txt'
            if operating_system == "Windows":
                if containers:
                    containers_string = ''.join(f'&containers={container}' for container in containers)
                    powershell_script = (
                        f'Invoke-RestMethod -Method \'Post\' '
                        f'-Uri \"{base_url}export/{option}?datastore={datastore}{containers_string}\" '
                        f'-Headers @{{\'Authorization\' = \'Bearer {token}\'; \'Content-Type\' = \'application/json\'}} '
                    )
                    
                else:
                    powershell_script = (
                        f'Invoke-RestMethod -Method \'Post\' '
                        f'-Uri {base_url}export/{option}?datastore={datastore} '
                        f'-Headers @{{\'Authorization\' = \'Bearer {token}\'; \'Content-Type\' = \'application/json\'}} '
                    )
                    
                # powershell_script += f'$response | Out-File \'{log_file_path}\' -Append\''
                script_name = f"task_scheduler_script_{option}_{datastore}.ps1"
                # Save the PowerShell script to a file
                script_location = BASE_PATH+"/"+script_name
                with open(script_location, 'w') as ps_script_file:
                    ps_script_file.write(powershell_script)
                
                # Print success message
                print(f"[bold green]PowerShell script successfully created! Please check the script at: {script_location}[/bold green]")
                    
            elif operating_system == "Linux":
                
                if containers:
                    command = f'{crontab_expression} /usr/bin/curl --request POST --url \'{base_url}export/{option}?datastore={datastore}\'' + ''.join(f'&containers={container}' for container in containers) + f' --header \'Authorization: Bearer {token}\'  >> {log_file_path} 2>&1'
                else:
                    command = f'{crontab_expression} /usr/bin/curl --request POST --url \'{base_url}export/{option}?datastore={datastore}\' --header \'Authorization: Bearer {token}\' >> {log_file_path} 2>&1'
                commands.append(command)
        
        if operating_system == "Linux":
            cron_commands = "\n".join(commands)
            
            with open(CRONTAB_COMMANDS_PATH, "a+") as file:
                file.write(cron_commands + "\n")
            
            # Run crontab command and add generated commands
            try:
                with open(CRONTAB_COMMANDS_PATH, 'r') as commands_file:
                    commands_content = commands_file.read()
                # Use input redirection to pass the content of the file to the crontab command
                subprocess.run(f'crontab -l 2>{CRONTAB_ERROR_PATH} | echo "{commands_content}" | crontab -', shell=True, check=True)
                # subprocess.run(f'(crontab -l 2>{CRONTAB_ERROR_PATH}; cat {CRONTAB_COMMANDS_PATH}) | crontab -', shell=True, check=True)
                print(f"[bold green]Crontab successfully created! Please check the cronjobs in {CRONTAB_COMMANDS_PATH} or run `crontab -l` to list all cronjobs[/bold green]")
            except subprocess.CalledProcessError as e:
                # Handle errors and write to the error file
                print(f"[bold red] WARNING: There was an error in the crontab command. Please check the path: {CRONTAB_ERROR_PATH} [/bold red]")
                with open(CRONTAB_ERROR_PATH, "a") as error_file:
                    current_datetime = datetime.now().strftime("[%m-%d-%Y %H:%M:%S]")
                    error_file.write(f"{current_datetime} : Error executing crontab command: {e}\n")
                return 


@run_operation_app.command("catalog", help="Triggers a catalog operation for the specified datastores")
def catalog_operation(datastores: str = typer.Option(..., "--datastore",
                                                help="Comma-separated list of Datastore IDs or array-like format"),
                      include: Optional[str] = typer.Option(None,"--include",
                                                            help="Comma-separated list of include types or array-like format. Example: \"table,view\" or \"[table,view]\""),
                      prune: Optional[bool] = typer.Option(None, "--prune",
                                                           help="Prune the operation. Do not include if you want prune == false"),
                      recreate: Optional[bool] = typer.Option(None, "--recreate",
                                                              help="Recreate the operation. Do not include if you want recreate == false")
                      ):
    # Remove brackets if present and split by comma
    datastores = [int(x.strip()) for x in datastores.strip("[]").split(",")]
    config = load_config()
    base_url = validate_and_format_url(config['url'])
    token = is_token_valid(config['token'])
    if token:
        if include:
            include = [(x.strip()) for x in include.strip("[]").split(",")]
        if prune is None:
            prune = False
        if recreate is None:
            recreate = False
        run_catalog(datastores, include, prune, recreate, token)


@run_operation_app.command("profile",help="Triggers a profile operation for the specified datastores" )
def profile_operation(datastores: str = typer.Option(..., "--datastore",
                                                help="Comma-separated list of Datastore IDs or array-like format"),
                      container_names: Optional[str] = typer.Option(None,"--container_names",
                                                            help="Comma-separated list of include types or array-like format. Example: \"table,view\" or \"[table,view]\""),
                      container_tags: Optional[str] = typer.Option(None,"--container_tags",
                                                            help="Comma-separated list of include types or array-like format. Example: \"table,view\" or \"[table,view]\""),
                      infer_constraints: Optional[bool] = typer.Option(None, "--infer_constraints",
                                                           help="Infer quality checks in profile. Do not include if you want infer_constraints == false"),
                      max_records_analyzed_per_partition: Optional[int] = typer.Option(None, "--max_records_analyzed_per_partition",
                                                                                       help="Number of max records analyzed per partition"),
                      max_count_testing_sample: Optional[int] = typer.Option(None, "--max_count_testing_sample",
                                                                                       help="The number of records accumulated during profiling for validation of inferred checks. Capped at 100,000"),
                      percent_testing_threshold: Optional[float] = typer.Option(None, "--percent_testing_threshold",
                                                                                help=" Percent of Testing Threshold" ),
                      high_correlation_threshold: Optional[float] = typer.Option(None, "--high_correlation_threshold",
                                                                                 help="Number of Correlation Threshold"),
                      greater_than_time: Optional[datetime] = typer.Option(None, "--greater_than_date",
                                                                           help="Only include rows where the incremental field's value is greater than this time. Use one of these formats %Y-%m-%dT%H:%M:%S or %Y-%m-%d %H:%M:%S"),
                      greater_than_batch: Optional[float] = typer.Option(None, "--greater_than_batch",
                                                                         help="Only include rows where the incremental field's value is greater than this number"),
                      histogram_max_distinct_values: Optional[int] = typer.Option(None, "--histogram_max_distinct_values",
                                                                                  help="Number of max distinct values of the histogram")
                      ):
    # Remove brackets if present and split by comma
    datastores = [int(x.strip()) for x in datastores.strip("[]").split(",")]
    config = load_config()
    base_url = validate_and_format_url(config['url'])
    token = is_token_valid(config['token'])
    if token:
        if container_names:
            container_names = [(x.strip()) for x in container_names.strip("[]").split(",")]
            print(container_names)
        if container_tags:
            container_tags = [(x.strip()) for x in container_tags.strip("[]").split(",")]
        if greater_than_time:
            greater_than_time = greater_than_time.strftime("%Y-%m-%dT%H:%M:%S.000Z")

        run_profile(datastore_ids=datastores, container_names=container_names,container_tags=container_tags,
                    infer_constraints=infer_constraints,max_records_analyzed_per_partition=max_records_analyzed_per_partition,
                    max_count_testing_sample=max_count_testing_sample,percent_testing_threshold=percent_testing_threshold,
                    high_correlation_threshold=high_correlation_threshold,greater_than_time=greater_than_time,
                    greater_than_batch=greater_than_batch,histogram_max_distinct_values=histogram_max_distinct_values , token=token)


# TODO: Update to wait for operation to finish to make sure it is completed.

# Add the checks_app as a subcommand to the main app
app.add_typer(checks_app, name="checks")

# Add the schedule_app as a subcommand to the main app
app.add_typer(schedule_app, name="schedule")

# Add the trigger operation as a subcommand to the main app
app.add_typer(run_operation_app, name="run")

if __name__ == "__main__":
    app()
