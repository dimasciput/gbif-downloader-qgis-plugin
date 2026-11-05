"""
Thin wrapper around the GBIF Occurrence Download API.
https://techdocs.gbif.org/en/openapi/v1/occurrence#/Occurrence%20downloads
"""

import json
import logging
import urllib.request
import urllib.error
import urllib.parse
from base64 import b64encode

_BASE = "https://api.gbif.org/v1"
_BASE_V2 = "https://api.gbif.org/v2"
_AUTH_CFG_SETTINGS_KEY = "gbif_downloader/auth_config_id"

# The COL XR checklist key on GBIF ChecklistBank.
COL_CHECKLIST_KEY = "7ddf754f-d193-4cc9-b351-99906754a03b"

logger = logging.getLogger(__name__)


class CredentialsLockedError(RuntimeError):
    """Saved credentials exist but the QGIS auth database could not be read."""


def _urlopen(req, timeout: int):
    """Open only HTTPS URLs; raises ValueError for any other scheme."""
    url = req.full_url if isinstance(req, urllib.request.Request) else req
    if not url.lower().startswith("https://"):
        raise ValueError(f"Only HTTPS URLs are permitted, got: {url!r}")
    return urllib.request.urlopen(req, timeout=timeout)  # nosec B310


def _auth_header(username: str, password: str) -> dict:
    token = b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Accept": "application/json"}


def get_credentials(prompt: bool = True) -> tuple[str, str]:
    """Load username and password from the QGIS auth manager.

    Pass ``prompt=False`` from worker threads: a master-password dialog must
    only be shown from the GUI thread.
    """
    from qgis.core import QgsApplication, QgsAuthMethodConfig, QgsSettings

    settings = QgsSettings()
    cfg_id = settings.value(_AUTH_CFG_SETTINGS_KEY, "")
    if not cfg_id:
        return "", ""

    auth_mgr = QgsApplication.authManager()
    unlocked = auth_mgr.setMasterPassword(True) if prompt else auth_mgr.masterPasswordIsSet()
    if not unlocked:
        # Locked database: keep the saved ID, the user can retry
        raise CredentialsLockedError(
            "The QGIS authentication database is locked. "
            "Enter the master password to access the saved GBIF credentials."
        )

    config = QgsAuthMethodConfig()
    ok = auth_mgr.loadAuthenticationConfig(cfg_id, config, full=True)
    if not ok:
        if cfg_id in auth_mgr.configIds():
            # Config exists but could not be read (e.g. wrong master password)
            raise CredentialsLockedError(
                "The saved GBIF credentials could not be read from the QGIS "
                "authentication database."
            )
        # Stale ID — remove it so the user is prompted to re-enter credentials
        settings.remove(_AUTH_CFG_SETTINGS_KEY)
        return "", ""

    return config.config("username"), config.config("password")


def save_credentials(username: str, password: str) -> None:
    """Persist credentials in the QGIS auth manager (encrypted).

    Raises RuntimeError if the auth manager is unavailable (e.g. master
    password not set/entered) or refuses to store the configuration.
    """
    from qgis.core import QgsApplication, QgsAuthMethodConfig, QgsSettings

    auth_mgr = QgsApplication.authManager()
    if not auth_mgr.setMasterPassword(True):
        raise RuntimeError(
            "The QGIS authentication database is locked. Enter the master "
            "password (or set one under Settings > Options > Authentication) "
            "and try again."
        )

    settings = QgsSettings()
    cfg_id = settings.value(_AUTH_CFG_SETTINGS_KEY, "")

    config = QgsAuthMethodConfig()
    config.setName("GBIF Downloader")
    config.setMethod("Basic")
    config.setConfig("username", username)
    config.setConfig("password", password)

    if cfg_id and not auth_mgr.configIdUnique(cfg_id):
        # configIdUnique returns True when the ID is free (doesn't exist yet),
        # so False means it already exists — safe to update in place
        config.setId(cfg_id)
        ok = auth_mgr.updateAuthenticationConfig(config)
    else:
        # No existing config or stale ID — create a fresh entry
        config.setId("")
        ok = auth_mgr.storeAuthenticationConfig(config)
        # PyQGIS treats `mconfig` as an in/out parameter (SIP_INOUT), so the
        # call returns (bool, updated_config). The updated copy carries the
        # generated ID; the original object does not.
        if isinstance(ok, tuple):
            ok, config = ok

    if not ok or not config.id():
        raise RuntimeError("QGIS could not store the credentials in the authentication database.")
    settings.setValue(_AUTH_CFG_SETTINGS_KEY, config.id())


def delete_credentials() -> None:
    """Remove stored credentials from the QGIS auth manager and settings."""
    from qgis.core import QgsApplication, QgsSettings

    settings = QgsSettings()
    cfg_id = settings.value(_AUTH_CFG_SETTINGS_KEY, "")
    if cfg_id:
        QgsApplication.authManager().removeAuthenticationConfig(cfg_id)
        settings.remove(_AUTH_CFG_SETTINGS_KEY)


def test_credentials(username: str, password: str) -> tuple[bool, str]:
    """Return (ok, message). Hits the GBIF login endpoint."""
    url = f"{_BASE}/user/login"
    req = urllib.request.Request(url, headers=_auth_header(username, password))
    try:
        with _urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                return True, "Connected successfully."
            return False, f"Unexpected status: {resp.status}"
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            return False, "Invalid username or password."
        return False, f"HTTP {exc.code}: {exc.reason}"
    except Exception as exc:  # noqa: BLE001 - surfaced to the user as a message
        logger.exception("Credential test failed")
        return False, str(exc)


def find_species(original_species_name: str, rank: str | None = None) -> dict | None:
    """COL-based species lookup using the GBIF v2 species/match endpoint.

    Returns the full COL match response dict (containing a ``usage`` key) or None.
    """
    logger.info("Find species (COL): %s", original_species_name)
    params: dict = {
        "checklistKey": COL_CHECKLIST_KEY,
        "scientificName": original_species_name,
    }
    if rank:
        params["rank"] = rank.upper()

    url = f"{_BASE_V2}/species/match?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with _urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, ValueError, OSError) as exc:
        logger.warning("COL match error for %s: %s", original_species_name, exc)
        return None

    if not data or (data.get("diagnostics") or {}).get("matchType") == "NONE":
        logger.info("No COL match for %s", original_species_name)
        return None
    if "usage" not in data:
        return None

    return data


def submit_predicate_download(
    username: str,
    password: str,
    predicate: dict,
    fmt: str = "SIMPLE_CSV",
    send_notification: bool = True,
    checklist_key: str | None = COL_CHECKLIST_KEY,
) -> str:
    """Submit a predicate-based download request. Returns the download key."""
    url = f"{_BASE}/occurrence/download/request"
    payload: dict = {
        "creator": username,
        "sendNotification": send_notification,
        "format": fmt,
        "predicate": predicate,
    }
    if checklist_key:
        payload["checklistKey"] = checklist_key
    body = json.dumps(payload).encode()
    headers = {
        **_auth_header(username, password),
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with _urlopen(req, timeout=30) as resp:
            return resp.read().decode().strip().strip('"')
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def get_download(key: str) -> dict:
    """Fetch metadata for a single download key (public endpoint)."""
    url = f"{_BASE}/occurrence/download/{key}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with _urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def cancel_download(username: str, password: str, key: str) -> None:
    """Cancel a running download by key. Raises RuntimeError on failure."""
    url = f"{_BASE}/occurrence/download/request/{urllib.parse.quote(key)}"
    req = urllib.request.Request(url, headers=_auth_header(username, password), method="DELETE")
    try:
        with _urlopen(req, timeout=10):
            pass
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def list_downloads(
    username: str,
    password: str,
    limit: int = 50,
    offset: int = 0,
    statuses: list | None = None,
    from_date: str = "",
) -> dict:
    """Return one page of the user's downloads (most recent first).

    Returns the raw API dict: {results, count, offset, limit, endOfRecords}.
    """
    params = [("limit", limit), ("offset", offset)]
    params.extend(("status", s) for s in (statuses or []))
    if from_date:
        params.append(("from", from_date))
    query = urllib.parse.urlencode(params, doseq=True)
    url = f"{_BASE}/occurrence/download/user/{urllib.parse.quote(username)}?{query}"
    req = urllib.request.Request(url, headers=_auth_header(username, password))
    with _urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())
