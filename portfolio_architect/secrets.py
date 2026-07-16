"""Optional runtime config loading from Nebius MysteryBox.

If `NEBIUS_SECRET_ID` is set, the backend pulls that secret's primary-version
payload from MysteryBox and injects each key/value into the process environment
*before* `Settings` is constructed, so pydantic reads them like any other env
var. If it is unset, this module is a no-op and the app uses `.env` / real env
vars exactly as before — so local SQLite dev is unaffected.

The secret payload is the shape MysteryBox returns:
    {"version_id": "...", "data": [{"key": "NEBIUS_KEY", "string_value": "..."}, ...]}

Fetch strategy: shell out to the `nebius` CLI
    nebius mysterybox payload get --secret-id <id> --format json
which works locally (your CLI credentials) and in any runtime that bundles the
CLI + a service-account profile (e.g. the deployed container / VM). This keeps
the dependency to the already-present CLI rather than adding an SDK; swap in the
Nebius Python SDK here later without touching call sites.

Precedence: by default a value already present in the environment WINS over the
secret (so an explicit `-e VAR=...` at run time still overrides). Set
`NEBIUS_SECRET_OVERRIDE=1` to make the secret authoritative instead.
"""

import json
import os
import shutil
import subprocess
import sys

_TRUTHY = {"1", "true", "yes", "on"}


def load_secrets_into_env() -> bool:
    """Inject the MysteryBox secret's keys into os.environ. Returns True if a
    secret was loaded, False if disabled or unavailable (never raises)."""
    secret_id = os.environ.get("NEBIUS_SECRET_ID", "").strip()
    if not secret_id:
        return False

    entries = _fetch_payload(secret_id)
    if not entries:
        return False

    override = os.environ.get("NEBIUS_SECRET_OVERRIDE", "").strip().lower() in _TRUTHY
    loaded = 0
    for item in entries:
        key = item.get("key")
        val = item.get("string_value")
        if not key or val is None:
            continue  # skip empty keys and binary_value entries
        if override or key not in os.environ:
            os.environ[key] = val
            loaded += 1
    if loaded:
        print(f"[secrets] loaded {loaded} keys from MysteryBox {secret_id}", file=sys.stderr)
    return loaded > 0


def _fetch_payload(secret_id: str) -> list[dict]:
    """Return the payload `data` list via the nebius CLI, or [] on any failure."""
    exe = shutil.which("nebius")
    if not exe:
        print("[secrets] NEBIUS_SECRET_ID set but `nebius` CLI not found — "
              "falling back to env/.env", file=sys.stderr)
        return []
    version_id = os.environ.get("NEBIUS_SECRET_VERSION_ID", "").strip()
    cmd = [exe, "mysterybox", "payload", "get", "--secret-id", secret_id, "--format", "json"]
    if version_id:
        cmd += ["--version-id", version_id]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=True).stdout
    except Exception as e:  # noqa: BLE001 — any failure degrades to env/.env, never crash boot
        print(f"[secrets] MysteryBox fetch failed ({type(e).__name__}) — "
              f"falling back to env/.env", file=sys.stderr)
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        for key in ("data", "payload", "entries", "items"):
            if isinstance(data.get(key), list):
                return data[key]
        return []
    return data if isinstance(data, list) else []
