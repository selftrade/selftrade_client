# client/main.py - SelfTrade Desktop Client Entry Point
import sys
import os
import logging
import signal

# Add parent directory to path for direct execution
if __name__ == "__main__" and __package__ is None:
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, parent_dir)
    __package__ = "client"

# Check for display availability on Linux
# If no display, use offscreen platform (for headless/monitor-off scenarios)
if sys.platform.startswith('linux'):
    display = os.environ.get('DISPLAY')
    if not display:
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
        print("No DISPLAY detected, running in offscreen mode")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

from client.utils.logging import setup_logging
from client.ui import MainWindow
from client.config import WINDOW_TITLE, VERSION


def main():
    """Main entry point for the SelfTrade desktop client"""
    # Setup logging
    logger = setup_logging()
    logger.info(f"Starting SelfTrade Desktop Client v{VERSION}")

    # Handle Ctrl+C gracefully
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    # Create application with crash protection
    try:
        app = QApplication(sys.argv)
    except Exception as e:
        logger.error(f"Failed to create QApplication: {e}")
        logger.info("Trying offscreen mode...")
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
        app = QApplication(sys.argv)

    app.setApplicationName(WINDOW_TITLE)
    app.setOrganizationName("SelfTrade")

    # Set style
    app.setStyle("Fusion")

    # Global exception handler for Qt
    def exception_hook(exctype, value, traceback):
        logger.error(f"Uncaught exception: {exctype.__name__}: {value}")
        # Don't crash on display errors - just log
        if 'display' in str(value).lower() or 'xcb' in str(value).lower():
            logger.warning("Display error detected - continuing...")
            return
        sys.__excepthook__(exctype, value, traceback)

    sys.excepthook = exception_hook

    # Create and show main window
    window = MainWindow()
    window.show()

    logger.info("Application window created")

    # Periodic keepalive to prevent sleep-related crashes
    def keepalive():
        pass  # Just keeps event loop active

    keepalive_timer = QTimer()
    keepalive_timer.timeout.connect(keepalive)
    keepalive_timer.start(30000)  # Every 30 seconds

    # Run application
    try:
        exit_code = app.exec()
    except Exception as e:
        logger.error(f"Application crashed: {e}")
        exit_code = 1

    logger.info(f"Application exited with code {exit_code}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
