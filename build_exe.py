#!/usr/bin/env python3
"""
Build script to create SelfTrade Client .exe using PyInstaller.

Usage:
    python build_exe.py

Output:
    dist/SelfTrade-Setup.exe

After building, upload to:
1. GitHub Releases: gh release create v1.0.0 dist/SelfTrade-Setup.exe --repo selftrade/selftrade_client
2. Self-hosted: cp dist/SelfTrade-Setup.exe /opt/final_trading_with_client/static/downloads/
"""

import subprocess
import sys
import shutil
from pathlib import Path

ROOT_DIR = Path(__file__).parent
DIST_DIR = ROOT_DIR / "dist"
BUILD_DIR = ROOT_DIR / "build"
APP_NAME = "SelfTrade-Setup"
ENTRY_POINT = "client/main.py"

# Server static downloads path for self-hosted copy
SERVER_DOWNLOADS = Path("/opt/final_trading_with_client/static/downloads")


def check_pyinstaller():
    try:
        import PyInstaller
        print(f"PyInstaller {PyInstaller.__version__} found")
    except ImportError:
        print("PyInstaller not found. Installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])


def build():
    check_pyinstaller()

    print(f"\nBuilding {APP_NAME}.exe from {ENTRY_POINT}...")

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", APP_NAME,
        "--clean",
        # Include all client subpackages
        "--hidden-import", "client.ui",
        "--hidden-import", "client.ui.main_window",
        "--hidden-import", "client.services",
        "--hidden-import", "client.services.server_client",
        "--hidden-import", "client.services.websocket_client",
        "--hidden-import", "client.services.exchange_client",
        "--hidden-import", "client.trading",
        "--hidden-import", "client.trading.order_executor",
        "--hidden-import", "client.trading.position_sizer",
        "--hidden-import", "client.trading.position_manager",
        "--hidden-import", "client.trading.signal_handler",
        "--hidden-import", "client.trading.sl_tp_monitor",
        "--hidden-import", "client.utils",
        # PyQt6 hidden imports
        "--hidden-import", "PyQt6.QtCore",
        "--hidden-import", "PyQt6.QtWidgets",
        "--hidden-import", "PyQt6.QtGui",
        # CCXT for exchange connectivity
        "--hidden-import", "ccxt",
        "--hidden-import", "ccxt.binance",
        "--hidden-import", "ccxt.mexc",
        "--hidden-import", "ccxt.bybit",
        # Other deps
        "--hidden-import", "websockets",
        "--hidden-import", "aiohttp",
        "--hidden-import", "requests",
        ENTRY_POINT,
    ]

    subprocess.check_call(cmd, cwd=str(ROOT_DIR))

    exe_path = DIST_DIR / f"{APP_NAME}.exe"

    if exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        print(f"\nBuild successful: {exe_path} ({size_mb:.1f} MB)")

        # Copy to server downloads directory if it exists
        if SERVER_DOWNLOADS.exists():
            dest = SERVER_DOWNLOADS / f"{APP_NAME}.exe"
            shutil.copy2(exe_path, dest)
            print(f"Copied to server: {dest}")

        print(f"\nTo upload to GitHub Releases:")
        print(f"  gh release create v1.0.0 {exe_path} --repo selftrade/selftrade_client --title 'SelfTrade Client v1.0.0' --notes 'Desktop trading client'")
    else:
        print("\nBuild failed - .exe not found")
        sys.exit(1)


if __name__ == "__main__":
    build()
