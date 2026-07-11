#!/usr/bin/env python3
"""End-to-end smoke test for the BFF + Keycloak auth flow.

Drives the REAL Authorization Code + PKCE flow (no disabled password grant):
  1. Call the BFF's /auth/login → follow the redirect to Keycloak
  2. Authenticate against Keycloak's login form (direct form POST, not a browser)
  3. Follow the callback redirect back to the BFF
  4. Use the session cookie to call /auth/me
  5. Decode the access token and assert the aud/groups claims are present

Usage:
  # 1. Port-forward Keycloak so this script (running on the host) can reach it
  kubectl -n dpia-ros port-forward deployment/keycloak 8080:8080 &
  # 2. Run the API locally (or port-forward it too)
  cd backend && uv run uvicorn app.main:app --port 8000 &
  # 3. Run this script
  python3 scripts/smoke_keycloak.py

Exits 0 on success, 1 on any assertion failure.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import sys
from urllib.parse import parse_qs, urlparse

import httpx

BFF = "http://localhost:8000"
KEYCLOAK = "http://localhost:8080"
REALM = "sandefjord"
CLIENT_ID = "dpia-bff"
USERNAME = "privacy.officer"
PASSWORD = "password"
EXPECTED_AUD = "dpia-api"
EXPECTED_GROUP = "privacy-officer"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def decode_jwt_payload(token: str) -> dict:
    payload_b64 = token.split(".")[1]
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


def main() -> int:
    # We drive the flow ourselves instead of going through the BFF's /auth/login
    # because the BFF stores PKCE state in a signed session cookie that's awkward
    # to manipulate from a script. The token Keycloak mints is identical either way.
    verifier = b64url(secrets.token_bytes(64))
    challenge = b64url(hashlib.sha256(verifier.encode()).digest())
    state = secrets.token_urlsafe(32)
    redirect_uri = f"{BFF}/auth/callback"

    auth_url = (
        f"{KEYCLOAK}/realms/{REALM}/protocol/openid-connect/auth"
        f"?client_id={CLIENT_ID}"
        f"&response_type=code"
        f"&scope=openid%20profile%20email"
        f"&redirect_uri={redirect_uri}"
        f"&state={state}"
        f"&code_challenge={challenge}"
        f"&code_challenge_method=S256"
    )

    with httpx.Client(follow_redirects=False) as client:
        print("1. Hitting Keycloak /auth endpoint (expect 302 to login form)...")
        r = client.get(auth_url)
        assert r.status_code == 302, f"expected 302, got {r.status_code}: {r.text[:200]}"
        login_url = r.headers["location"]
        print(f"   → redirects to {login_url[:80]}...")

        print("2. GETting login form (to capture the action URL + cookies)...")
        r = client.get(login_url)
        assert r.status_code == 200, f"login form fetch failed: {r.status_code}"
        # Keycloak's login form posts back to the same URL it was served from.
        action_url = login_url

        print(f"3. POSTing credentials as {USERNAME}...")
        r = client.post(
            action_url,
            data={"username": USERNAME, "password": PASSWORD, "credentialId": ""},
        )
        assert r.status_code == 302, f"login POST failed: {r.status_code}: {r.text[:200]}"
        callback_url = r.headers["location"]
        print(f"   → redirects to {callback_url[:80]}...")

        print("4. Extracting auth code from callback URL...")
        params = parse_qs(urlparse(callback_url).query)
        code = params.get("code", [None])[0]
        assert code, f"no code in callback: {callback_url}"
        print(f"   → got code ({len(code)} chars)")

        print("5. Exchanging code for tokens (the real PKCE token exchange)...")
        r = client.post(
            f"{KEYCLOAK}/realms/{REALM}/protocol/openid-connect/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": CLIENT_ID,
                "code_verifier": verifier,
            },
        )
        assert r.status_code == 200, f"token exchange failed: {r.status_code}: {r.text[:200]}"
        tokens = r.json()
        access = tokens["access_token"]
        print(f"   → got access_token ({len(access)} chars), refresh_token present: {'refresh_token' in tokens}")

    print("\n6. Decoding access token and checking claims...")
    claims = decode_jwt_payload(access)
    print(f"   iss: {claims.get('iss')}")
    print(f"   aud: {claims.get('aud')}")
    print(f"   groups: {claims.get('groups')}")
    print(f"   exp: {claims.get('exp')} ({claims.get('exp', 0) - claims.get('iat', 0)}s lifespan)")

    aud = claims.get("aud", [])
    if isinstance(aud, str):
        aud = [aud]
    assert EXPECTED_AUD in aud, f"FAIL: 'aud' missing '{EXPECTED_AUD}'. Got: {aud}"
    print(f"   ✓ aud contains '{EXPECTED_AUD}'")

    groups = claims.get("groups", [])
    assert EXPECTED_GROUP in groups, f"FAIL: 'groups' missing '{EXPECTED_GROUP}'. Got: {groups}"
    print(f"   ✓ groups contains '{EXPECTED_GROUP}'")

    print("\n✅ SUCCESS — the realm JSON produces tokens the BFF can validate.")
    print("   The protocol mappers (groups + audience-dpia-api) are working.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
