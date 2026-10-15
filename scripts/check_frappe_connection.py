"""Local development-only Frappe API smoke test. Reads .env; never prints secrets."""

import sys
from urllib.parse import urlparse

import httpx
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    frappe_url: str
    frappe_api_key: str
    frappe_api_secret: str


def main() -> int:
    cfg = Settings()
    url = cfg.frappe_url.rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        print("ERROR: Invalid FRAPPE_URL; expected http(s) site URL.")
        return 1
    if parsed.scheme == "http" and parsed.hostname not in {
        "localhost", "127.0.0.1", "::1"
    } and not parsed.hostname.endswith(".localhost"):
        print("ERROR: Plain HTTP is allowed only on loopback/local development hosts.")
        return 1
    if not cfg.frappe_api_key or not cfg.frappe_api_secret:
        print("ERROR: API credentials missing.")
        return 1
    header = {"Authorization": f"token {cfg.frappe_api_key}:{cfg.frappe_api_secret}"}
    try:
        with httpx.Client(timeout=10.0, follow_redirects=False, verify=True) as client:
            r = client.get(f"{url}/api/method/frappe.auth.get_logged_user", headers=header)
            print("GET current user status:", r.status_code)
            r.raise_for_status()
            user = r.json().get("message")
            if not user or user == "Guest":
                print("ERROR: API authentication did not establish a user.")
                return 1
            if user == "Administrator":
                print("ERROR: Refusing to test with Administrator credentials.")
                return 1
            print("Authenticated Frappe user:", user)
            r2 = client.get(f"{url}/api/resource/ToDo", headers=header,
                            params={"fields": '["name"]', "limit_page_length": 1})
            print("GET ToDo list status:", r2.status_code)
            if r2.status_code == 403:
                print(
                    "User lacks ToDo read permission; set restricted test permissions"
                    " or choose an allowed test DocType."
                )
                return 1
            r2.raise_for_status()
            print("PASS: Frappe API connection works using a restricted user.")
            return 0
    except httpx.HTTPError as e:
        print("ERROR: Connection or HTTP failure:", type(e).__name__)
        return 1
    except (ValueError, KeyError) as e:
        print("ERROR: Unexpected response or configuration:", type(e).__name__)
        return 1


if __name__ == "__main__":
    sys.exit(main())
