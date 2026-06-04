"""
src/splunk_client.py
--------------------
Fires actual HTTP requests to Splunk Cloud REST API.
All Splunk credentials are read from environment variables.
"""

import os
import json
import time
import requests
from requests.auth import HTTPBasicAuth


class SplunkClient:
    """Thin wrapper around the Splunk REST API."""

    def __init__(self) -> None:
        self.base_url = os.getenv("SPLUNK_HOST", "https://your-instance.splunkcloud.com:8089")
        self.token = os.getenv("SPLUNK_TOKEN", "")
        self.username = os.getenv("SPLUNK_USERNAME", "")
        self.password = os.getenv("SPLUNK_PASSWORD", "")
        self.verify_ssl = os.getenv("SPLUNK_VERIFY_SSL", "true").lower() == "true"

    def _headers(self) -> dict:
        if self.token:
            return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        return {"Content-Type": "application/json"}

    def _auth(self):
        if not self.token and self.username:
            return HTTPBasicAuth(self.username, self.password)
        return None

    def run_search(self, query: str, earliest: str = "-1h", latest: str = "now") -> str:
        """Submit a blocking Splunk search and return results as a JSON string."""
        try:
            create_url = f"{self.base_url}/services/search/jobs"
            payload = {
                "search": f"search {query}" if not query.strip().startswith("search") else query,
                "earliest_time": earliest,
                "latest_time": latest,
                "output_mode": "json",
                "exec_mode": "normal",
            }
            r = requests.post(
                create_url, data=payload, headers=self._headers(),
                auth=self._auth(), verify=self.verify_ssl, timeout=15,
            )
            r.raise_for_status()
            sid = r.json()["sid"]

            status_url = f"{self.base_url}/services/search/jobs/{sid}"
            for _ in range(30):
                time.sleep(1)
                sr = requests.get(
                    status_url, params={"output_mode": "json"},
                    headers=self._headers(), auth=self._auth(),
                    verify=self.verify_ssl, timeout=10,
                )
                sr.raise_for_status()
                if sr.json()["entry"][0]["content"]["dispatchState"] == "DONE":
                    break

            results_url = f"{self.base_url}/services/search/jobs/{sid}/results"
            rr = requests.get(
                results_url, params={"output_mode": "json", "count": 50},
                headers=self._headers(), auth=self._auth(),
                verify=self.verify_ssl, timeout=10,
            )
            rr.raise_for_status()
            results = rr.json().get("results", [])
            return json.dumps(results, indent=2) if results else "No results found."

        except requests.RequestException as e:
            return f"[Splunk API Error] {e}"

    def get_alerts(self, limit: int = 10) -> str:
        """Fetch recently triggered alert actions."""
        try:
            url = f"{self.base_url}/services/alerts/fired_alerts"
            r = requests.get(
                url, params={"output_mode": "json", "count": limit},
                headers=self._headers(), auth=self._auth(),
                verify=self.verify_ssl, timeout=10,
            )
            r.raise_for_status()
            entries = r.json().get("entry", [])
            alerts = [{"name": e["name"], "published": e.get("published", "")} for e in entries]
            return json.dumps(alerts, indent=2) if alerts else "No fired alerts found."
        except requests.RequestException as e:
            return f"[Splunk API Error] {e}"
