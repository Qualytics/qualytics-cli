"""Container service functions."""

import time
import typer

from ..api.client import QualyticsClient, QualyticsAPIError


def get_table_ids(
    client: QualyticsClient, datastore_id: int, max_retries=5, retry_delay=5
):
    """Get table/container IDs for a datastore with retry logic."""
    for attempt in range(max_retries):
        try:
            response = client.get(
                f"containers/listing?datastore={datastore_id}",
            )
            items_array = response.json()
            table_ids = {}
            for item in items_array:
                table_ids[item["name"]] = item["id"]
            return table_ids
        except QualyticsAPIError as e:
            typer.secho(
                f"Attempt {attempt + 1} failed with status code {e.status_code}. Retrying...",
                fg=typer.colors.RED,
            )
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
        except Exception as e:
            typer.secho(
                f"Request error during attempt {attempt + 1}: {e}. Retrying...",
                fg=typer.colors.RED,
            )
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
    typer.secho(
        f"Failed getting the table ids after {max_retries} attempts.",
        fg=typer.colors.RED,
    )
    return None
