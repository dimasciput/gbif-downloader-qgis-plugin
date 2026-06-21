import os
import shutil
import tempfile
import zipfile

from qgis.PyQt.QtCore import QThread, pyqtSignal

from .helpers import _find_tsv


class FetchPageWorker(QThread):
    finished = pyqtSignal(list, int, int, int)  # results, total, offset, limit
    error    = pyqtSignal(str)

    def __init__(self, offset: int, limit: int, statuses: list, from_date: str):
        super().__init__()
        self._offset    = offset
        self._limit     = limit
        self._statuses  = statuses
        self._from_date = from_date

    def run(self):
        from ..gbif_api import get_credentials, list_downloads
        username, password = get_credentials()
        if not username:
            self.error.emit(
                "No GBIF credentials configured.\n"
                "Use the dropdown → Configure GBIF Credentials."
            )
            return
        try:
            data = list_downloads(
                username, password,
                limit=self._limit, offset=self._offset,
                statuses=self._statuses, from_date=self._from_date,
            )
            self.finished.emit(
                data.get("results", []),
                data.get("count", 0),
                self._offset,
                self._limit,
            )
        except Exception as exc:
            self.error.emit(str(exc))


class PollWorker(QThread):
    updated = pyqtSignal(str, dict)

    def __init__(self, keys: list):
        super().__init__()
        self._keys = keys

    def run(self):
        from ..gbif_api import get_download
        for key in self._keys:
            try:
                self.updated.emit(key, get_download(key))
            except Exception:
                pass


class CancelWorker(QThread):
    finished = pyqtSignal(str)
    error    = pyqtSignal(str)

    def __init__(self, key: str):
        super().__init__()
        self._key = key

    def run(self):
        from ..gbif_api import get_credentials, cancel_download
        username, password = get_credentials()
        if not username:
            self.error.emit("No GBIF credentials configured.")
            return
        try:
            cancel_download(username, password, self._key)
            self.finished.emit(self._key)
        except Exception as exc:
            self.error.emit(str(exc))


class DownloadWorker(QThread):
    """
    fmt:
      "zip" – download the raw ZIP and save to dest
      "map" – download ZIP, extract TSV to dest

    source_zip: if set and the file exists, skip the download and use this zip directly.
    """
    progress = pyqtSignal(int)
    finished = pyqtSignal(str, str)  # (saved path, fmt)
    error    = pyqtSignal(str)

    def __init__(self, url: str, dest: str, fmt: str, source_zip: str = ""):
        super().__init__()
        self._url        = url
        self._dest       = dest
        self._fmt        = fmt
        self._source_zip = source_zip

    def run(self):
        import urllib.request

        if self._source_zip and os.path.exists(self._source_zip):
            try:
                if self._fmt == "map":
                    self._extract_tsv(self._source_zip, self._dest)
                self.progress.emit(100)
                self.finished.emit(self._dest, self._fmt)
            except Exception as exc:
                self.error.emit(str(exc))
            return

        tmp_zip  = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        tmp_path = tmp_zip.name
        tmp_zip.close()
        try:
            with urllib.request.urlopen(self._url) as resp:
                total    = int(resp.headers.get("Content-Length", 0))
                received = 0
                with open(tmp_path, "wb") as f:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)
                        received += len(chunk)
                        if total:
                            self.progress.emit(int(received * 100 / total))

            if self._fmt == "zip":
                shutil.move(tmp_path, self._dest)
                tmp_path = None
            elif self._fmt == "map":
                self._extract_tsv(tmp_path, self._dest)

            self.finished.emit(self._dest, self._fmt)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def _extract_tsv(self, zip_path: str, dest: str):
        with zipfile.ZipFile(zip_path) as zf:
            name = _find_tsv(zf)
            with zf.open(name) as src, open(dest, "wb") as dst:
                dst.write(src.read())
