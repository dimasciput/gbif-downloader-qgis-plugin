"""
Thin wrapper around the GBIF Occurrence Download API.
https://techdocs.gbif.org/en/openapi/v1/occurrence#/Occurrence%20downloads
"""

import json
import urllib.request
import urllib.error
import urllib.parse
from base64 import b64encode

_BASE = "https://api.gbif.org/v1"
_AUTH_CFG_SETTINGS_KEY = "gbif_downloader/auth_config_id"


def _urlopen(req, timeout: int):
    """Open only HTTPS URLs; raises ValueError for any other scheme."""
    url = req.full_url if isinstance(req, urllib.request.Request) else req
    if not url.lower().startswith("https://"):
        raise ValueError(f"Only HTTPS URLs are permitted, got: {url!r}")
    return urllib.request.urlopen(req, timeout=timeout)  # nosec B310


def _auth_header(username: str, password: str) -> dict:
    token = b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Accept": "application/json"}


def get_credentials() -> tuple[str, str]:
    """Load username and password from the QGIS auth manager."""
    from qgis.core import QgsApplication, QgsAuthMethodConfig, QgsSettings

    settings = QgsSettings()
    cfg_id = settings.value(_AUTH_CFG_SETTINGS_KEY, "")
    if not cfg_id:
        return "", ""

    config = QgsAuthMethodConfig()
    ok = QgsApplication.authManager().loadAuthenticationConfig(cfg_id, config, full=True)
    if not ok:
        # Stale ID — remove it so the user is prompted to re-enter credentials
        settings.remove(_AUTH_CFG_SETTINGS_KEY)
        return "", ""

    return config.config("username"), config.config("password")


def save_credentials(username: str, password: str) -> None:
    """Persist credentials in the QGIS auth manager (encrypted)."""
    from qgis.core import QgsApplication, QgsAuthMethodConfig, QgsSettings

    auth_mgr = QgsApplication.authManager()
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
        auth_mgr.updateAuthenticationConfig(config)
    else:
        # No existing config or stale ID — create a fresh entry
        config.setId("")
        auth_mgr.storeAuthenticationConfig(config)
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
    except Exception as exc:
        return False, str(exc)


def submit_predicate_download(
    username: str,
    password: str,
    predicate: dict,
    fmt: str = "SIMPLE_CSV",
    send_notification: bool = True,
) -> str:
    """Submit a predicate-based download request. Returns the download key."""
    url = f"{_BASE}/occurrence/download/request"
    body = json.dumps({
        "creator": username,
        "sendNotification": send_notification,
        "format": fmt,
        "predicate": predicate,
    }).encode()
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
