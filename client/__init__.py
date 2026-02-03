# client/__init__.py - SelfTrade Desktop Client Package
"""
SelfTrade Desktop Client - PyQt6 trading interface

This package provides:
- Server connection and authentication
- Exchange connection (Binance, MEXC, Bybit)
- Real-time signal reception via WebSocket
- Order execution and position management

Usage:
    cd client && python -m client.main

    or:

    from client.ui import MainWindow
    from PyQt6.QtWidgets import QApplication
    import sys

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
"""

from .main import main
from .config import VERSION

__all__ = ["main", "VERSION"]
__version__ = VERSION
