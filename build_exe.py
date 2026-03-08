#!/usr/bin/env python3
"""
Build script to create SelfTrade Client .exe using Nuitka.

Nuitka compiles Python to native C code, so antivirus software does NOT
flag it as malware (unlike PyInstaller which bundles an interpreter).

Prerequisites (Windows):
    pip install nuitka ordered-set zstandard
    # Also need a C compiler - Nuitka will auto-download MinGW64 if needed

Usage:
    python build_exe.py

Output:
    dist/SelfTrade-Setup.exe

After building, push a tag to trigger GitHub Actions release:
    git tag v1.0.1 && git push origin v1.0.1
"""

import subprocess
import sys
import re
import os
import shutil
from pathlib import Path

ROOT_DIR = Path(__file__).parent
DIST_DIR = ROOT_DIR / "dist"
APP_NAME = "SelfTrade-Setup"
ENTRY_POINT = "client/main.py"

# Server static downloads path for self-hosted copy
SERVER_DOWNLOADS = Path("/opt/final_trading_with_client/static/downloads")


def get_version() -> str:
    """Read version from client/config.py"""
    # Allow env override (used by CI)
    env_ver = os.environ.get("BUILD_VERSION")
    if env_ver:
        return env_ver

    config_path = ROOT_DIR / "client" / "config.py"
    if config_path.exists():
        match = re.search(r'VERSION\s*=\s*["\']([^"\']+)["\']', config_path.read_text())
        if match:
            return match.group(1)
    return "1.0.0"


def check_nuitka():
    try:
        result = subprocess.run(
            [sys.executable, "-m", "nuitka", "--version"],
            capture_output=True, text=True
        )
        print(f"Nuitka found: {result.stdout.strip().splitlines()[0]}")
    except Exception:
        print("Nuitka not found. Installing...")
        subprocess.check_call([
            sys.executable, "-m", "pip", "install",
            "nuitka", "ordered-set", "zstandard"
        ])


def build():
    check_nuitka()
    version = get_version()

    DIST_DIR.mkdir(exist_ok=True)

    print(f"\nBuilding {APP_NAME}.exe v{version} with Nuitka (native C compilation)...")
    print("This will take several minutes on the first build.\n")

    cmd = [
        sys.executable, "-m", "nuitka",

        # Output settings
        "--standalone",
        "--onefile",
        f"--output-filename={APP_NAME}.exe",
        f"--output-dir={DIST_DIR}",

        # Windows GUI app (no console window)
        "--windows-disable-console",

        # Company/product info embedded in .exe properties
        "--company-name=SelfTrade",
        "--product-name=SelfTrade Client",
        f"--product-version={version}",
        "--file-description=SelfTrade Desktop Trading Client",
        "--copyright=SelfTrade 2024-2026",

        # Enable Nuitka plugins for Qt and anti-bloat
        "--enable-plugin=pyqt6",
        "--enable-plugin=anti-bloat",

        # Include packages that Nuitka might miss
        "--include-package=client",
        "--include-package=client.ui",
        "--include-package=client.services",
        "--include-package=client.trading",
        "--include-package=client.utils",
        "--include-package=ccxt",
        "--include-package=websockets",
        "--include-package=aiohttp",
        "--include-package=requests",
        "--include-package=qasync",
        "--include-package=ujson",

        # Follow imports within our code
        "--follow-imports",

        # Remove unnecessary modules to reduce size
        "--nofollow-import-to=tkinter",
        "--nofollow-import-to=unittest",
        "--nofollow-import-to=test",
        "--nofollow-import-to=setuptools",
        "--nofollow-import-to=pip",
        "--nofollow-import-to=distutils",
        "--nofollow-import-to=ccxt.pro",  # Exclude ccxt pro (async websocket exchanges, not used)

        # Entry point
        ENTRY_POINT,
    ]

    subprocess.check_call(cmd, cwd=str(ROOT_DIR))

    # Nuitka outputs to dist/ with onefile
    exe_path = DIST_DIR / f"{APP_NAME}.exe"

    if exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        print(f"\nBuild successful: {exe_path} ({size_mb:.1f} MB)")

        # Copy to server downloads directory if it exists
        if SERVER_DOWNLOADS.exists():
            dest = SERVER_DOWNLOADS / f"{APP_NAME}.exe"
            shutil.copy2(exe_path, dest)
            print(f"Copied to server: {dest}")

        print(f"\nTo release on GitHub:")
        print(f"  git tag v{version} && git push origin v{version}")
        print(f"  (GitHub Actions will build & publish automatically)")
    else:
        print("\nBuild failed - .exe not found in dist/")
        print("Check the Nuitka output above for errors.")
        sys.exit(1)


if __name__ == "__main__":
    build()
