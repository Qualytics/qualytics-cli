import typer
import os
import json
import requests
import urllib3
import re
import click


from pathlib import Path
from urllib.parse import urlparse
from rich import print
from rich.progress import track
from itertools import product
from typing import Optional
from typing_extensions import Annotated


__version__ = "0.1.1"

app = typer.Typer()

# Create a new Typer instance for checks
checks_app = typer.Typer(name="checks", help="Commands for handling checks")

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Get the home directory
home = Path.home()

# Define the new directory
folder_name = ".qualytics"
BASE_PATH = f"{home}/{folder_name}"

CONFIG_PATH = os.path.expanduser(f"{BASE_PATH}/config.json")


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
    with open(file_path, 'r') as file:
        # Using a set to automatically get distinct lines
        distinct_lines = set(file.readlines())

    with open(file_path, 'w') as file:
        for line in distinct_lines:
            file.write(line)


def log_error(message, file_path):
    with open(file_path, 'a') as file:
        file.write(message + '\n')
        file.flush() 


def get_quality_checks(base_url: str, token: str, datastore_id: int, output: str):
    endpoint = "quality-checks"
    url = f"{base_url}{endpoint}?datastore={datastore_id}"

    page = 1
    size = 100
    params = {"sort_created": "asc", "size": size, "page": page}

    response = requests.get(url, headers=_get_default_headers(token), params=params, verify=False)

    data = response.json()
    
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


def get_table_ids(base_url: str, token: str, datastore_id: int):
    response = requests.get(base_url + f"containers/listing?datastore={datastore_id}",
                        headers=_get_default_headers(token), verify=False)
    
    items_array = response.json()
    table_ids = {}
    for item in items_array:
        table_ids[item["name"]] = item["id"]
    
    return table_ids


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
        print(f"Config file located in: {CONFIG_PATH}")
        print(f"URL: {config['url']}")
        print(f"Token: {config['token']}")
    else:
        print("Configuration not found!")


@app.command()
def init(url: str = typer.Option(..., help="The URL to be set. Example: https://your-qualytics.qualytics.io/"), 
         token: str = typer.Option(..., help="The token to be set.")):
    """
    Initialize the configuration.
    """
    # Check if the URL starts with 'https://'
    if not url.startswith('https://'):
        url = 'https://' + url
    
    # Check if the URL ends with '/'
    if not url.endswith('/') or not url.endswith('/api'):
        url += '/api/'

    # Check if the URL contains 'your-qualytics.qualytics.io'
    parsed_url = urlparse(url)
    
    if not parsed_url.netloc.endswith('qualytics.io'):
        print("Invalid domain provided. The URL should be in the format: 'https://your-subdomain.qualytics.io/'")
        raise typer.Exit(code=1)
    
    config = {
        "url": url,
        "token": token
    }
    save_config(config)
    print("Configuration saved!")
    

@checks_app.command("export")
def checks_export(datastore: int = typer.Option(..., "--datastore", help="Datastore ID"), output: str = typer.Option(BASE_PATH + "/data_checks.json", "--output", help="Output file path")):
    """
    Export checks to a file.
    """    
    config = load_config()
    base_url = config['url']
    token = config['token']
    all_quality_checks = get_quality_checks(base_url=base_url, token=token, datastore_id=datastore, output=output)

    with open(output, 'w') as f:
        json.dump(all_quality_checks, f, indent=4)
    print(f"Data exported to {output}")
    
    
@checks_app.command("import")
def checks_import(datastore: str = typer.Option(..., "--datastore", help="Comma-separated list of Datastore IDs or array-like format"), input_file: str = typer.Option(BASE_PATH + "/data_checks.json", "--input", help="Input file path")):
    """
    Import checks from a file.
    """
    # Remove brackets if present and split by comma
    datastores = [int(x.strip()) for x in datastore.strip("[]").split(",")]
    config = load_config()
    base_url = config['url']
    token = config['token']
    
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
                try:
                    container_id = table_ids[quality_check['container']['name']]
                except:
                    print(f"[bold red] Profile `{quality_check['container']['name']}` was not found in datastore id: {datastore_id}[/bold red]")
                    log_error(f"Profile `{quality_check['container']['name']}` of quality check #{quality_check['id']} was not found in datastore id: {datastore_id}", BASE_PATH + "/errors.log")
                
                if container_id:
                    payload = {
                        "fields": [field['name'] for field in quality_check['fields']],
                        "description": f"{quality_check['description']} [from quality check id: {quality_check['id']} - main datastore id: {datastore_id}]",
                        "rule": quality_check['rule_type'],
                        "coverage": quality_check['coverage'],
                        "is_new": quality_check['is_new'],
                        "filter": quality_check['filter'],
                        "properties": quality_check['properties'],
                        "tags": [ global_tag['name'] for global_tag in quality_check['global_tags'] ],
                        "container_id": container_id
                    }
                    response = requests.post(base_url + f"quality-checks", headers=_get_default_headers(token), json=payload, verify=False)
                    if response.status_code == 409:
                        print(f"[bold yellow]Quality check for container: {quality_check['container']['name']} was already created on datastore id: {datastore_id}. Updating check...[/bold yellow]")
                        match = re.search(r"id: (\d+)", response.text)
                        response = requests.put(base_url + f"quality-checks/{match.group(1)}", headers=_get_default_headers(token), json=payload, verify=False)
                        if response.status_code == 200:
                            print(f"[bold green]Quality check id: {match.group(1)} updated successfully for datastore id: {datastore_id}[/bold green]")
                            total_updated_checks += 1
                        else:
                            print(f"[bold red]Error updating quality check id: {match.group(1)} [/bold red]")
                            log_error(f"Error updating quality check id: {match.group(1)} on datastore id: {datastore_id}. Details: {response.text}", BASE_PATH + "/errors.log")
                    elif response.status_code == 200:
                        print(f"[bold green]Quality check id: {response.json()['id']} for container: {quality_check['container']['name']} created successfully[/bold green]")
                        total_created_checks += 1
                    else:
                        log_error(f"Error creating quality check for datastore id: {datastore_id}. Details: {response.text}", BASE_PATH + "/errors.log")
                            
        print(f"Updated a total of {total_updated_checks} quality checks.")
        print(f"Created a tottal of {total_created_checks} quality checks.")
        distinct_file_content(BASE_PATH + "/errors.log")
      

# Add the checks_app as a subcommand to the main app
app.add_typer(checks_app, name="checks")


if __name__ == "__main__":
    app()