#!/usr/bin/env python3
"""Entry point for Local Project Hub."""

import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from hub import store as store_mod
from hub.window import HubWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Local Project Hub")

    try:
        store = store_mod.Store()
    except store_mod.RegistryError as e:
        QMessageBox.critical(None, "Registry problem", str(e))
        return 2

    win = HubWindow(store)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
