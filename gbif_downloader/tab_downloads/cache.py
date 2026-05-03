import hashlib
import json
import pathlib

from qgis.core import QgsApplication


def cache_dir() -> pathlib.Path:
    base = pathlib.Path(QgsApplication.qgisSettingsDirPath()) / "gbif_downloader" / "downloads"
    base.mkdir(parents=True, exist_ok=True)
    return base


def save_cached(data: dict) -> None:
    key = data.get("key", "")
    if not key:
        return
    key_dir = cache_dir() / key
    key_dir.mkdir(exist_ok=True)
    (key_dir / "detail.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_all_cached() -> list[dict]:
    results = []
    cache = cache_dir()
    for key_dir in sorted(cache.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not key_dir.is_dir():
            continue
        detail_file = key_dir / "detail.json"
        if not detail_file.exists():
            continue
        try:
            results.append(json.loads(detail_file.read_text(encoding="utf-8")))
        except Exception:
            pass
    return results


def _filter_cache_key(statuses: list | None = None, from_date: str = "") -> str:
    payload = json.dumps(
        {"statuses": sorted(statuses or []), "from": from_date or ""},
        sort_keys=True,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def save_page_cache(
    offset: int,
    limit: int,
    count: int,
    keys: list,
    statuses: list | None = None,
    from_date: str = "",
) -> None:
    page_dir = cache_dir() / "_pages"
    page_dir.mkdir(exist_ok=True)
    path = page_dir / f"{_filter_cache_key(statuses, from_date)}_{offset}_{limit}.json"
    path.write_text(
        json.dumps({
            "count": count,
            "offset": offset,
            "limit": limit,
            "statuses": statuses or [],
            "from": from_date,
            "keys": keys,
        }),
        encoding="utf-8",
    )


def load_page_cache(
    offset: int,
    limit: int,
    statuses: list | None = None,
    from_date: str = "",
) -> dict | None:
    path = (
        cache_dir() / "_pages"
        / f"{_filter_cache_key(statuses, from_date)}_{offset}_{limit}.json"
    )
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_cached_keys(keys: list) -> list[dict]:
    results = []
    cache = cache_dir()
    for key in keys:
        detail = cache / key / "detail.json"
        if detail.exists():
            try:
                results.append(json.loads(detail.read_text(encoding="utf-8")))
            except Exception:
                pass
    return results
