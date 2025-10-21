import requests
import json

def create_datastore(payload: dict, url: str, headers: dict) -> dict:
    resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=30)
    # Raise for non-2xx so our caller can handle nicely
    try:
        resp.raise_for_status()
    except requests.HTTPError as e:
        # Attach body to the error for easier triage
        raise RuntimeError(f"HTTP {resp.status_code} from {url}: {resp.text}") from e
    return resp.json()

def list_datastores(url: str, headers: dict) -> dict:
    resp = requests.get(url, headers=headers, timeout=30)
    try:
        resp.raise_for_status()
    except requests.HTTPError as e:
        raise RuntimeError(f"HTTP {resp.status_code} from {url}: {resp.text}") from e
    return resp.json()

def get_datastore_by_id(url: str, headers: dict) -> dict:
    resp = requests.get(url,headers=headers, timeout=30)
    try:
        resp.raise_for_status()
    except requests.HTTPError as e:
        raise RuntimeError(f"HTTP {resp.status_code} from {url}: {resp.text}") from e
    return resp.json()

def remove_datastore(url: str, headers: dict) -> dict:
    resp = requests.delete(url,headers=headers, timeout=30)
    try:
        resp.raise_for_status()
    except requests.HTTPError as e:
        raise RuntimeError(f"HTTP {resp.status_code} from {url}: {resp.text}") from e
    return resp.json()