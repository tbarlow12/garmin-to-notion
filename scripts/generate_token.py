#!/usr/bin/env python3
"""Generate a GARMIN_TOKENS secret value via an interactive Garmin login.

Logs in with your Garmin email/password (prompting for an MFA code if your
account requires one), then prints the token as base64 to paste into the
GARMIN_TOKENS GitHub secret. The sync workflow refreshes this token in place
on every run and never needs to repeat an interactive login unless Garmin
invalidates the session (e.g. a changed password).

Usage:
    python scripts/generate_token.py
"""

import base64
import getpass

from garminconnect import Garmin


def main() -> None:
    email = input("Garmin email: ")
    password = getpass.getpass("Garmin password: ")

    client = Garmin(email, password, prompt_mfa=lambda: input("MFA code: "))
    client.login()

    token_json = client.client.dumps()
    b64 = base64.b64encode(token_json.encode()).decode()

    print()
    print("=" * 60)
    print(f"Authenticated as: {client.display_name}")
    print("GARMIN_TOKENS for GitHub secret (copy the line below):")
    print("=" * 60)
    print(b64)
    print("=" * 60)


if __name__ == "__main__":
    main()
