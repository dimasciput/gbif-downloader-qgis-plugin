from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)


class CredentialsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("GBIF Credentials")
        self.setMinimumWidth(340)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)

        info = QLabel(
            "Enter your <a href='https://www.gbif.org/user/profile'>GBIF account</a> "
            "credentials. These are stored in the QGIS authentication manager (encrypted)."
        )
        info.setOpenExternalLinks(True)
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()
        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("GBIF username")
        form.addRow("Username:", self.username_edit)

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText("GBIF password")
        form.addRow("Password:", self.password_edit)
        layout.addLayout(form)

        self.test_btn = QPushButton("Test Connection")
        self.test_btn.clicked.connect(self._test_connection)
        layout.addWidget(self.test_btn)

        self.result_label = QLabel("")
        self.result_label.setAlignment(Qt.AlignCenter)
        self.result_label.setWordWrap(True)
        self.result_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )
        layout.addWidget(self.result_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

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
