import os

from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QDialog

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

        self.test_btn.clicked.connect(self._test_connection)
        self.button_box.accepted.connect(self._save)
        self.button_box.rejected.connect(self.reject)

        self._load()

    def _load(self):
        from .gbif_api import get_credentials
        username, password = get_credentials()
        self.username_edit.setText(username)
        self.password_edit.setText(password)

    def _save(self):
        from .gbif_api import save_credentials
        save_credentials(
            self.username_edit.text().strip(),
            self.password_edit.text(),
        )
        self.accept()

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
        self.result_label.setText(message)
        self.result_label.setStyleSheet("color: green;" if ok else "color: red;")
        self.test_btn.setEnabled(True)
