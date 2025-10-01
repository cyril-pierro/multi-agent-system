from typing import Any
import json
import constants
import requests
import time
import random


def make_api_call(payload: dict[str, Any], retries: int = 5) -> dict[str, Any]:
    """Handles the API request with exponential backoff for reliability."""
    headers = {'Content-Type': 'application/json'}

    for i in range(retries):
        try:
            response = requests.post(
                constants.API_URL, headers=headers, data=json.dumps(payload))
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            if i < retries - 1 and (e.response.status_code == 429 or e.response.status_code >= 500):
                # Exponential backoff with jitter
                delay = 2 ** i + (random.random() * 1)
                print(
                    f"[SYSTEM] Rate limited or server error ({e.response.status_code}). Retrying in {delay:.2f}s...")
                time.sleep(delay)
            else:
                raise e
        except Exception as e:
            raise RuntimeError(f"API failed after {retries} attempts: {e}")
    raise RuntimeError("API call failed after all retries.")
