#!/usr/bin/env python3
"""Generate a GOOGLE_HEALTH_REFRESH_TOKEN for the Fitbit sleep sync.

Fitbit data is read through the Google Health API, which uses Google OAuth.
Run this once on your own machine (no extra packages needed):

    PYTHONPATH=src python scripts/generate_google_health_token.py

It prints a consent URL. Open it, sign in with the Google account your Fitbit
is linked to, and approve. Google then redirects to the redirect URI you set
on the OAuth client (https://www.google.com by default); the page itself
doesn't matter. Copy the full URL from the address bar (or just the `code=`
value) and paste it back here. The script prints the refresh token to store
as the GOOGLE_HEALTH_REFRESH_TOKEN GitHub secret.
"""

import getpass
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from garmin_to_notion.google_health import (  # noqa: E402
    API_BASE,
    GoogleHealthClient,
    _request,
    build_auth_url,
    exchange_code,
)


def main() -> None:
    client_id = os.getenv("GOOGLE_HEALTH_CLIENT_ID") or input("OAuth client ID: ").strip()
    client_secret = os.getenv("GOOGLE_HEALTH_CLIENT_SECRET") or getpass.getpass(
        "OAuth client secret: "
    ).strip()
    redirect_uri = (
        input("Redirect URI [https://www.google.com]: ").strip()
        or "https://www.google.com"
    )

    print("\nOpen this URL, sign in, and approve access:\n")
    print(build_auth_url(client_id, redirect_uri))
    pasted = input("\nPaste the URL you were redirected to (or the code): ").strip()
    if pasted.startswith("http"):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(pasted).query)
        code = (query.get("code") or [""])[0]
    else:
        code = pasted
    if not code:
        sys.exit("No authorization code found.")

    tokens = exchange_code(client_id, client_secret, code, redirect_uri)
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        sys.exit(
            "Google didn't return a refresh token. Revoke the app at "
            "https://myaccount.google.com/permissions and run this again."
        )

    # Sanity check: the account must be linked in the Google Health app.
    try:
        _request(
            f"{API_BASE}/users/me/identity",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        print("\nGoogle Health account link verified.")
    except Exception as e:  # noqa: BLE001
        print(f"\nWarning: identity check failed ({e}).")
        print("Make sure your Fitbit is linked in the Google Health app.")

    # And confirm sleep data is readable.
    client = GoogleHealthClient(client_id, client_secret, refresh_token)
    try:
        first = next(iter(client.list_data_points("sleep", page_size=1)), None)
        print("Sleep data readable." if first else "Sleep endpoint works but returned no data yet.")
    except Exception as e:  # noqa: BLE001
        print(f"Warning: sleep read failed ({e}).")

    print("\nAdd these GitHub Actions secrets:")
    print("  GOOGLE_HEALTH_CLIENT_ID      =", client_id)
    print("  GOOGLE_HEALTH_CLIENT_SECRET  = (the client secret you entered)")
    print("  GOOGLE_HEALTH_REFRESH_TOKEN  =", refresh_token)


if __name__ == "__main__":
    main()
