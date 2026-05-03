from qgis.PyQt.QtCore import QThread, pyqtSignal


class SubmitWorker(QThread):
    submitted = pyqtSignal(str)
    error     = pyqtSignal(str)

    def __init__(self, predicate: dict, fmt: str, send_notification: bool):
        super().__init__()
        self._predicate = predicate
        self._fmt       = fmt
        self._notify    = send_notification

    def run(self):
        from ..gbif_api import get_credentials, submit_predicate_download
        username, password = get_credentials()
        if not username:
            self.error.emit(
                "No GBIF credentials configured. "
                "Use the dropdown → Configure GBIF Credentials."
            )
            return
        try:
            key = submit_predicate_download(
                username, password, self._predicate, self._fmt, self._notify
            )
            self.submitted.emit(key)
        except Exception as exc:
            self.error.emit(str(exc))
