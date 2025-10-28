"""Container service functions."""
import time
import requests
import typer


def get_default_headers(token):
    """Get default authorization headers."""
    return {"Authorization": f"Bearer {token}"}


def get_table_ids(
    base_url: str, token: str, datastore_id: int, max_retries=5, retry_delay=5
):
    """Get table/container IDs for a datastore with retry logic."""
    for attempt in range(max_retries):
        try:
            response = requests.get(
                base_url + f"containers/listing?datastore={datastore_id}",
                headers=get_default_headers(token),
                verify=False,
            )

            if response.status_code == 200:
                items_array = response.json()
                table_ids = {}
                for item in items_array:
                    table_ids[item["name"]] = item["id"]

                return table_ids
            else:
                typer.secho(
                    f"Attempt {attempt + 1} failed with status code {response.status_code} - {response.text}. Retrying...",
                    fg=typer.colors.RED,
                )
                if attempt < max_retries - 1:  # Only sleep if it's not the last attempt
                    time.sleep(
                        retry_delay
                    )  # Wait for a specified delay before retrying
        except requests.RequestException as e:
            typer.secho(
                f"Request error during attempt {attempt + 1}: {e}. Retrying...",
                fg=typer.colors.RED,
            )
            print()
            if attempt < max_retries - 1:  # Only sleep if it's not the last attempt
                time.sleep(retry_delay)  # Wait for a specified delay before retrying
    typer.secho(
        f"Failed getting the table ids after {max_retries} attempts.",
        fg=typer.colors.RED,
    )
    return None
