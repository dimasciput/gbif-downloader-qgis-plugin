import os
import shutil

from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox, QMessageBox

FORM_CLASS, _ = uic.loadUiType(
    os.path.join(os.path.dirname(__file__), "gui", "credentials_dialog.ui")
)


class CredentialsDialog(QDialog, FORM_CLASS):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.result_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )

        self._test_passed = False
        self._save_btn = self.button_box.button(QDialogButtonBox.Save)
        self._save_btn.setEnabled(False)

        self.test_btn.clicked.connect(self._test_connection)
        self.logout_btn.clicked.connect(self._logout)
        self.button_box.accepted.connect(self._save)
        self.button_box.rejected.connect(self.reject)
        self.username_edit.textChanged.connect(self._on_credentials_changed)
        self.password_edit.textChanged.connect(self._on_credentials_changed)

        self._load()

    def _load(self):
        from .gbif_api import get_credentials
        username, password = get_credentials()
        self.username_edit.setText(username)
        self.password_edit.setText(password)
        self.logout_btn.setVisible(bool(username))

    def _on_credentials_changed(self):
        self._test_passed = False
        self._save_btn.setEnabled(False)

    def _save(self):
        if not self._test_passed:
            return
        from .gbif_api import save_credentials
        save_credentials(
            self.username_edit.text().strip(),
            self.password_edit.text(),
        )
        self.accept()

    def _logout(self):
        from .gbif_api import delete_credentials
        from .tab_downloads.cache import cache_dir

        reply = QMessageBox.warning(
            self,
            "Logout & Delete Downloaded Data",
            "This will remove your saved GBIF credentials and permanently delete all "
            "locally cached download data.\n\nThis action cannot be undone. Continue?",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if reply != QMessageBox.Yes:
            return

        delete_credentials()

        cache = cache_dir().parent
        if cache.exists():
            shutil.rmtree(cache, ignore_errors=True)

        self.username_edit.clear()
        self.password_edit.clear()
        self.logout_btn.setVisible(False)
        self.result_label.setText("Logged out and data deleted.")
        self.result_label.setStyleSheet("color: green;")

    def _test_connection(self):
        from .gbif_api import test_credentials
        self.test_btn.setEnabled(False)
        self.result_label.setText("Testing…")
        self.result_label.setStyleSheet("color: grey;")

        username = self.username_edit.text().strip()
        password = self.password_edit.text()
        if not username or not password:
            self.result_label.setText("Enter username and password first.")
            self.result_label.setStyleSheet("color: red;")
            self.test_btn.setEnabled(True)
            return

        ok, message = test_credentials(username, password)
        self._test_passed = ok
        self._save_btn.setEnabled(ok)
        self.result_label.setText(message)
        self.result_label.setStyleSheet("color: green;" if ok else "color: red;")
        self.test_btn.setEnabled(True)
