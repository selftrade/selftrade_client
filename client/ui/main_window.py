# client/ui/main_window.py - Professional PyQt6 Trading Client UI
import logging
from typing import Optional, Dict
import time
from datetime import datetime

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QLabel, QLineEdit, QPushButton, QTextEdit, QComboBox,
    QSpinBox, QDoubleSpinBox, QGroupBox, QGridLayout, QMessageBox,
    QStatusBar, QCheckBox, QFrame, QProgressBar, QScrollArea,
    QSizePolicy, QSpacerItem
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QSize, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QFont, QIcon, QPixmap

import json
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from client.config import (
    WINDOW_TITLE, WINDOW_SIZE, SUPPORTED_PAIRS, SUPPORTED_EXCHANGES,
    DEFAULT_RISK_PERCENT, MIN_CONFIDENCE, SERVER_URL
)
from client.services import ServerClient, ExchangeClient, WebSocketClient
from client.services.server_client import SubscriptionExpiredError
from client.trading import (
    OrderExecutor, PositionSizer, PositionManager, SignalHandler,
    SLTPMonitor, TrailingStopConfig, ExitReason
)

# Config file path for saving credentials
CONFIG_FILE = Path.home() / ".selftrade_config.json"

# Thread pool for background network operations (prevents UI freezing)
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="network")

logger = logging.getLogger(__name__)

# Modern Professional Stylesheet - Enhanced v2.1
STYLESHEET = """
/* ========== GLOBAL STYLES ========== */
QMainWindow {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #0d0d18, stop:0.5 #080810, stop:1 #040406);
}

QWidget {
    color: #c8c8d0;
    font-family: 'Segoe UI', 'SF Pro Display', -apple-system, sans-serif;
    font-size: 13px;
    background: transparent;
}

QLabel {
    color: #c8c8d0;
    background: transparent;
}

QScrollArea {
    border: none;
    background: transparent;
}

QScrollBar:vertical {
    background: #1a1a2e;
    width: 10px;
    border-radius: 5px;
}

QScrollBar::handle:vertical {
    background: #3a3a5e;
    border-radius: 5px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background: #4a4a7e;
}

/* ========== TAB WIDGET ========== */
QTabWidget::pane {
    border: none;
    background: transparent;
    padding: 15px;
}

QTabBar::tab {
    background: rgba(30, 30, 50, 0.6);
    color: #808090;
    padding: 14px 28px;
    margin-right: 8px;
    border-radius: 12px 12px 0 0;
    font-weight: 600;
    font-size: 14px;
    min-width: 120px;
}

QTabBar::tab:selected {
    background: linear-gradient(180deg, #1e1e3a 0%, #15152a 100%);
    color: #00d4aa;
    border-bottom: 3px solid #00d4aa;
}

QTabBar::tab:hover:!selected {
    background: rgba(40, 40, 70, 0.8);
    color: #b0b0c0;
}

/* ========== CARDS & FRAMES ========== */
QFrame#card {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(35, 35, 60, 0.95), stop:1 rgba(25, 25, 45, 0.95));
    border: 1px solid rgba(100, 100, 150, 0.3);
    border-radius: 16px;
    padding: 18px;
}

QFrame#card:hover {
    border: 1px solid rgba(0, 212, 170, 0.3);
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(40, 40, 70, 0.95), stop:1 rgba(30, 30, 55, 0.95));
}

QFrame#headerCard {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(0, 100, 80, 0.3), stop:1 rgba(0, 50, 100, 0.3));
    border: 1px solid rgba(0, 212, 170, 0.3);
    border-radius: 10px;
    padding: 8px;
}

QFrame#warningCard {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(255, 180, 0, 0.2), stop:1 rgba(255, 100, 0, 0.2));
    border: 1px solid rgba(255, 180, 0, 0.5);
    border-radius: 12px;
    padding: 15px;
}

QFrame#signalCardLong {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(0, 180, 120, 0.15), stop:1 rgba(0, 100, 80, 0.1));
    border: 2px solid #00d4aa;
    border-radius: 16px;
    padding: 20px;
}

QFrame#signalCardShort {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(255, 80, 80, 0.15), stop:1 rgba(150, 40, 40, 0.1));
    border: 2px solid #ff6b6b;
    border-radius: 16px;
    padding: 20px;
}

QFrame#signalCardNeutral {
    background: rgba(40, 40, 70, 0.6);
    border: 2px solid rgba(100, 100, 150, 0.4);
    border-radius: 16px;
    padding: 20px;
}

/* ========== INPUT FIELDS ========== */
QLineEdit {
    background: rgba(20, 20, 40, 0.8);
    border: 2px solid rgba(80, 80, 120, 0.5);
    border-radius: 10px;
    padding: 14px 18px;
    color: #ffffff;
    font-size: 14px;
    selection-background-color: #00d4aa;
}

QLineEdit:focus {
    border: 2px solid #00d4aa;
    background: rgba(25, 25, 50, 0.9);
}

QLineEdit:hover:!focus {
    border: 2px solid rgba(100, 100, 150, 0.7);
}

QLineEdit::placeholder {
    color: #707090;
}

QLineEdit#apiInput {
    font-family: 'Consolas', 'Monaco', monospace;
    font-size: 13px;
    letter-spacing: 1px;
}

/* ========== BUTTONS ========== */
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #00d4aa, stop:1 #00a888);
    color: #0a0a12;
    border: none;
    border-radius: 10px;
    padding: 12px 24px;
    font-weight: 700;
    font-size: 13px;
    min-height: 18px;
}

QPushButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #00e8bb, stop:1 #00b899);
}

QPushButton:pressed {
    background: #008866;
    padding-top: 14px;
    padding-bottom: 10px;
}

QPushButton:disabled {
    background: rgba(60, 60, 80, 0.6);
    color: #505060;
}

QPushButton#secondaryBtn {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #4080ff, stop:1 #3060dd);
    color: #ffffff;
}

QPushButton#secondaryBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #5090ff, stop:1 #4070ee);
}

QPushButton#dangerBtn {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #ff6b6b, stop:1 #dd4444);
    color: #ffffff;
}

QPushButton#dangerBtn:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #ff8080, stop:1 #ee5555);
}

QPushButton#outlineBtn {
    background: transparent;
    border: 2px solid #00d4aa;
    color: #00d4aa;
}

QPushButton#outlineBtn:hover {
    background: rgba(0, 212, 170, 0.1);
}

QPushButton#iconBtn {
    background: rgba(60, 60, 100, 0.5);
    padding: 10px;
    min-width: 40px;
    max-width: 40px;
}

QPushButton#iconBtn:hover {
    background: rgba(80, 80, 130, 0.7);
}

/* ========== COMBO BOX ========== */
QComboBox {
    background: rgba(20, 20, 40, 0.8);
    border: 2px solid rgba(80, 80, 120, 0.5);
    border-radius: 10px;
    padding: 12px 18px;
    color: #ffffff;
    font-size: 14px;
    min-width: 150px;
}

QComboBox:hover {
    border: 2px solid rgba(100, 100, 150, 0.7);
}

QComboBox:focus {
    border: 2px solid #00d4aa;
}

QComboBox::drop-down {
    border: none;
    padding-right: 12px;
    width: 20px;
}

QComboBox::down-arrow {
    width: 0;
    height: 0;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid #808090;
}

QComboBox::down-arrow:hover {
    border-top: 6px solid #00d4aa;
}

QComboBox QAbstractItemView {
    background: #1a1a2e;
    border: 1px solid rgba(80, 80, 120, 0.5);
    border-radius: 8px;
    selection-background-color: #00d4aa;
    selection-color: #0a0a12;
    padding: 5px;
}

/* ========== SPINBOX ========== */
QDoubleSpinBox, QSpinBox {
    background: rgba(20, 20, 40, 0.8);
    border: 2px solid rgba(80, 80, 120, 0.5);
    border-radius: 10px;
    padding: 10px 14px;
    color: #ffffff;
    font-size: 14px;
    min-height: 20px;
}

QDoubleSpinBox:focus, QSpinBox:focus {
    border: 2px solid #00d4aa;
    background: rgba(25, 25, 50, 0.9);
}

QDoubleSpinBox:hover:!focus, QSpinBox:hover:!focus {
    border: 2px solid rgba(100, 100, 150, 0.7);
}

QDoubleSpinBox::up-button, QSpinBox::up-button,
QDoubleSpinBox::down-button, QSpinBox::down-button {
    width: 20px;
    border: none;
    background: rgba(60, 60, 100, 0.5);
}

QDoubleSpinBox::up-button:hover, QSpinBox::up-button:hover,
QDoubleSpinBox::down-button:hover, QSpinBox::down-button:hover {
    background: rgba(80, 80, 130, 0.7);
}

/* ========== CHECKBOX ========== */
QCheckBox {
    color: #e0e0e0;
    spacing: 12px;
    font-size: 14px;
}

QCheckBox::indicator {
    width: 24px;
    height: 24px;
    border-radius: 6px;
    border: 2px solid rgba(80, 80, 120, 0.5);
    background: rgba(20, 20, 40, 0.8);
}

QCheckBox::indicator:checked {
    background: #00d4aa;
    border-color: #00d4aa;
}

QCheckBox::indicator:hover {
    border-color: #00d4aa;
}

/* ========== TEXT EDIT ========== */
QTextEdit {
    background: rgba(10, 10, 20, 0.9);
    border: 1px solid rgba(60, 60, 100, 0.5);
    border-radius: 12px;
    color: #00d4aa;
    font-family: 'JetBrains Mono', 'Consolas', 'Monaco', monospace;
    font-size: 12px;
    padding: 15px;
    selection-background-color: #00d4aa;
    selection-color: #0a0a12;
}

/* ========== PROGRESS BAR ========== */
QProgressBar {
    background: rgba(30, 30, 50, 0.8);
    border: none;
    border-radius: 8px;
    height: 16px;
    text-align: center;
    font-size: 11px;
    color: #ffffff;
}

QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #00d4aa, stop:1 #4080ff);
    border-radius: 8px;
}

/* ========== STATUS BAR ========== */
QStatusBar {
    background: rgba(15, 15, 25, 0.95);
    border-top: 1px solid rgba(60, 60, 100, 0.3);
    color: #808090;
    font-size: 12px;
    padding: 8px 15px;
}

/* ========== LABELS ========== */
QLabel#sectionTitle {
    font-size: 20px;
    font-weight: 700;
    color: #ffffff;
}

QLabel#sectionSubtitle {
    font-size: 13px;
    color: #808090;
}

QLabel#fieldLabel {
    font-size: 13px;
    font-weight: 600;
    color: #b0b0c0;
    margin-bottom: 4px;
}

QLabel#helperText {
    font-size: 11px;
    color: #808090;
}

QLabel#valueLabel {
    font-size: 28px;
    font-weight: 700;
    color: #00d4aa;
}

QLabel#statusConnected {
    color: #00d4aa;
    font-weight: 600;
}

QLabel#statusDisconnected {
    color: #ff6b6b;
    font-weight: 600;
}

/* ========== STATS CARDS ========== */
QFrame#statsCard {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(25, 30, 45, 0.95), stop:1 rgba(18, 22, 35, 0.95));
    border: 1px solid rgba(80, 100, 140, 0.25);
    border-radius: 14px;
    padding: 16px;
}

QFrame#statsCardProfit {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(0, 80, 60, 0.25), stop:1 rgba(0, 60, 45, 0.2));
    border: 1px solid rgba(0, 212, 170, 0.35);
    border-radius: 14px;
    padding: 16px;
}

QFrame#statsCardLoss {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(80, 30, 30, 0.25), stop:1 rgba(60, 20, 20, 0.2));
    border: 1px solid rgba(255, 107, 107, 0.35);
    border-radius: 14px;
    padding: 16px;
}

QLabel#statValue {
    font-size: 26px;
    font-weight: 800;
    color: #ffffff;
}

QLabel#statValueProfit {
    font-size: 26px;
    font-weight: 800;
    color: #00d4aa;
}

QLabel#statValueLoss {
    font-size: 26px;
    font-weight: 800;
    color: #ff6b6b;
}

QLabel#statLabel {
    font-size: 11px;
    font-weight: 600;
    color: #707090;
    text-transform: uppercase;
    letter-spacing: 1px;
}

/* ========== COLLAPSIBLE SECTIONS ========== */
QPushButton#collapseBtn {
    background: rgba(40, 45, 65, 0.6);
    border: 1px solid rgba(80, 90, 120, 0.3);
    border-radius: 8px;
    color: #a0a8c0;
    font-size: 12px;
    font-weight: 600;
    padding: 10px 15px;
    text-align: left;
}

QPushButton#collapseBtn:hover {
    background: rgba(50, 55, 80, 0.8);
    border-color: rgba(100, 110, 140, 0.4);
    color: #c0c8e0;
}

QPushButton#collapseBtn:checked {
    background: rgba(0, 100, 80, 0.2);
    border-color: rgba(0, 180, 140, 0.3);
    color: #00d4aa;
}

/* ========== LIVE INDICATOR ========== */
QLabel#liveIndicator {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(0, 200, 100, 0.9), stop:1 rgba(0, 180, 90, 0.9));
    color: #ffffff;
    font-size: 10px;
    font-weight: 700;
    padding: 4px 10px;
    border-radius: 10px;
    letter-spacing: 1px;
}

/* ========== TOOLTIP STYLING ========== */
QToolTip {
    background: #1a1a30;
    color: #e0e0f0;
    border: 1px solid #3a3a60;
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 12px;
}

/* ========== SEPARATOR LINE ========== */
QFrame#separator {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 transparent, stop:0.5 rgba(100, 110, 140, 0.4), stop:1 transparent);
    max-height: 1px;
    margin: 10px 0;
}
"""


class MainWindow(QMainWindow):
    """Professional Trading Client Main Window"""

    signal_received = pyqtSignal(dict)
    # Thread-safe signals for UI updates from background threads
    log_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str)
    balance_signal = pyqtSignal(float)
    portfolio_signal = pyqtSignal(str)
    trade_result_signal = pyqtSignal(dict)
    connect_result_signal = pyqtSignal(dict)
    login_result_signal = pyqtSignal(dict)
    subscription_expired_signal = pyqtSignal(str)  # Emitted when API key expires

    def __init__(self):
        super().__init__()

        # Services
        self.server_client = ServerClient()
        self.exchange_client = ExchangeClient()
        self.ws_client = WebSocketClient()
        self.position_manager = PositionManager()
        self.position_sizer = PositionSizer()
        self.signal_handler = SignalHandler()
        self.order_executor: Optional[OrderExecutor] = None
        self.sl_tp_monitor: Optional[SLTPMonitor] = None

        # CLEAR positions.json on startup - exchange is source of truth
        # Positions will be synced from exchange when connected
        cleared = self.position_manager.clear_all_positions()
        if cleared > 0:
            logger.info(f"Startup: Cleared {cleared} stale position(s) - will sync from exchange")

        # Trailing stop configuration (FIXED - less aggressive for crypto volatility)
        # Previous settings were too tight, causing early exits before TP
        self.trailing_config = TrailingStopConfig(
            enabled=True,
            activation_pct=2.5,      # Activate trailing after 2.5% profit (was 1%)
            trail_pct=1.5,           # Trail 1.5% behind peak (was 0.5%)
            breakeven_pct=1.5,       # Move SL to breakeven after 1.5% profit (was 0.5%)
            breakeven_buffer_pct=0.3 # Add 0.3% buffer above entry for fees (was 0.1%)
        )

        # State
        self.connected_server = False
        self.connected_exchange = False
        self.auto_trade = False
        self._subscription_expired_shown = False  # Prevent multiple dialogs
        self.user_data = {}
        self.signals_remaining = 0
        self.signals_used = 0
        self._current_signal = None

        # Cache for prices (reduces API calls and UI freezing)
        self._price_cache = {}
        self._price_cache_time = {}
        self._cache_ttl = 5  # seconds (increased from 3)
        self._total_balance = 0.0
        self._last_balance_update = 0

        # Flags to prevent overlapping background tasks
        self._sl_tp_check_running = False
        self._position_update_running = False
        self._balance_update_running = False

        # Track skipped SHORT signals for user info
        self._short_skip_count = 0
        self._last_short_skip_log = 0

        # Track insufficient balance signals to avoid log spam
        # Maps pair -> timestamp of last "insufficient" log
        self._insufficient_balance_logged: Dict[str, float] = {}
        self._insufficient_log_cooldown = 120  # Only log once per 2 minutes per pair

        # Stop-loss cooldown: prevent re-entering same pair after SL hit
        # Maps pair -> timestamp of last SL exit
        self._sl_cooldown: Dict[str, float] = {}
        self._sl_cooldown_seconds = 300  # 5 minute cooldown after stop loss

        # EMERGENCY STOP: Consecutive loss protection
        self._consecutive_losses = 0
        self._max_consecutive_losses = 3  # Stop trading after 3 consecutive losses
        self._trading_halted = False
        self._halt_reason = ""

        # Saved credentials
        self._saved_config = self._load_config()

        # Setup UI
        self._setup_ui()

        # Pre-fill saved credentials after UI is created
        self._apply_saved_credentials()
        self._setup_timers()
        self._connect_signals()

        logger.info("SelfTrade Pro initialized")

    def _setup_ui(self):
        """Setup the main user interface"""
        self.setWindowTitle("SelfTrade Pro - Trading Signals")
        self.setMinimumSize(1400, 900)
        self.setStyleSheet(STYLESHEET)

        # Central widget with main scroll area for entire content
        central = QWidget()
        self.setCentralWidget(central)

        # Use a scroll area for the entire main content
        main_scroll = QScrollArea()
        main_scroll.setWidgetResizable(True)
        main_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        main_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        main_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        # Content widget inside scroll
        content_widget = QWidget()
        main_layout = QVBoxLayout(content_widget)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # Header (fixed height)
        header = self._create_header()
        header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        main_layout.addWidget(header)

        # Warning banner (collapsible, fixed height when visible)
        self.warning_banner = self._create_warning_banner()
        self.warning_banner.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.warning_banner.setMaximumHeight(80)
        main_layout.addWidget(self.warning_banner)

        # Tab widget (expands to fill space)
        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        main_layout.addWidget(tabs, 1)

        # Create tabs
        tabs.addTab(self._create_connection_tab(), "🔌  Connection")
        tabs.addTab(self._create_trading_tab(), "📈  Trading")
        tabs.addTab(self._create_logs_tab(), "📋  Activity Log")

        main_scroll.setWidget(content_widget)

        # Layout for central widget
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.addWidget(main_scroll)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self._update_status()

    def _create_header(self) -> QWidget:
        """Create the header section"""
        header = QFrame()
        header.setObjectName("headerCard")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(15, 8, 15, 8)

        # Logo and branding
        brand_layout = QVBoxLayout()
        brand_layout.setSpacing(2)

        title = QLabel("⚡ SelfTrade Pro")
        title.setStyleSheet("font-size: 18px; font-weight: 800; color: #00d4aa;")
        brand_layout.addWidget(title)

        subtitle = QLabel("AI-Powered Crypto Trading")
        subtitle.setStyleSheet("font-size: 11px; color: rgba(255,255,255,0.6);")
        brand_layout.addWidget(subtitle)

        layout.addLayout(brand_layout)
        layout.addStretch()

        # User info card (hidden until logged in)
        self.user_card = QFrame()
        self.user_card.setStyleSheet("""
            background: rgba(0, 0, 0, 0.3);
            border-radius: 8px;
            padding: 6px 12px;
        """)
        self.user_card.setVisible(False)
        user_layout = QVBoxLayout(self.user_card)
        user_layout.setSpacing(4)
        user_layout.setContentsMargins(4, 4, 4, 4)

        user_header = QHBoxLayout()
        self.user_label = QLabel("👤 Username")
        self.user_label.setStyleSheet("font-size: 13px; font-weight: 600; color: #ffffff;")
        user_header.addWidget(self.user_label)

        self.plan_badge = QLabel("FREE")
        self.plan_badge.setStyleSheet("""
            background: rgba(100, 100, 150, 0.4);
            color: #a0a0b0;
            padding: 4px 12px;
            border-radius: 6px;
            font-size: 11px;
            font-weight: 700;
        """)
        user_header.addWidget(self.plan_badge)
        user_layout.addLayout(user_header)

        # Signal counter
        signal_row = QHBoxLayout()
        self.signal_icon = QLabel("🎯")
        self.signal_icon.setStyleSheet("font-size: 11px;")
        signal_row.addWidget(self.signal_icon)

        self.signal_count_label = QLabel("0 / 200 signals used")
        self.signal_count_label.setStyleSheet("font-size: 11px; color: #ffd93d;")
        signal_row.addWidget(self.signal_count_label)
        signal_row.addStretch()
        user_layout.addLayout(signal_row)

        self.signal_progress = QProgressBar()
        self.signal_progress.setMaximum(200)
        self.signal_progress.setValue(0)
        self.signal_progress.setFixedHeight(6)
        self.signal_progress.setTextVisible(False)
        user_layout.addWidget(self.signal_progress)

        layout.addWidget(self.user_card)

        return header

    def _create_warning_banner(self) -> QWidget:
        """Create IP whitelist warning banner with smooth collapse"""
        banner = QFrame()
        banner.setObjectName("warningCard")
        banner.setMinimumHeight(60)
        layout = QHBoxLayout(banner)
        layout.setContentsMargins(15, 10, 15, 10)
        layout.setSpacing(12)

        icon = QLabel("⚠️")
        icon.setStyleSheet("font-size: 20px;")
        icon.setFixedWidth(30)
        layout.addWidget(icon)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        text_layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("IP Whitelist Required")
        title.setStyleSheet("font-size: 13px; font-weight: 700; color: #ffb400;")
        text_layout.addWidget(title)

        desc = QLabel("Whitelist your IP in exchange API settings to avoid auth errors.")
        desc.setStyleSheet("font-size: 11px; color: rgba(255, 180, 0, 0.8);")
        desc.setWordWrap(True)
        text_layout.addWidget(desc)

        layout.addLayout(text_layout, 1)

        close_btn = QPushButton("✕")
        close_btn.setObjectName("iconBtn")
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255, 180, 0, 0.3);
                border: none;
                border-radius: 14px;
                color: #ffb400;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: rgba(255, 180, 0, 0.5);
            }
        """)
        close_btn.clicked.connect(self._hide_warning_banner)
        layout.addWidget(close_btn)

        return banner

    def _hide_warning_banner(self):
        """Hide warning banner with smooth animation"""
        # Create animation for smooth collapse
        self._banner_animation = QPropertyAnimation(self.warning_banner, b"maximumHeight")
        self._banner_animation.setDuration(200)
        self._banner_animation.setStartValue(self.warning_banner.height())
        self._banner_animation.setEndValue(0)
        self._banner_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._banner_animation.finished.connect(lambda: self.warning_banner.setVisible(False))
        self._banner_animation.start()

    def _create_connection_tab(self) -> QWidget:
        """Create the connection settings tab with scroll support"""
        # Create scroll area for the tab content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        # Content widget
        content = QWidget()
        main_layout = QVBoxLayout(content)
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # Two column layout
        columns = QHBoxLayout()
        columns.setSpacing(20)

        # ========== LEFT: SERVER CONNECTION ==========
        server_card = QFrame()
        server_card.setStyleSheet("""
            QFrame {
                background-color: #1a1a2e;
                border: 1px solid #2a2a4e;
                border-radius: 12px;
                padding: 20px;
            }
        """)
        server_layout = QVBoxLayout(server_card)
        server_layout.setSpacing(15)

        # Title
        server_title = QLabel("🌐  SelfTrade Server Login")
        server_title.setStyleSheet("font-size: 18px; font-weight: bold; color: #00d4aa; padding: 5px 0;")
        server_layout.addWidget(server_title)

        server_desc = QLabel("Login to receive trading signals")
        server_desc.setStyleSheet("font-size: 12px; color: #808090; margin-bottom: 10px;")
        server_layout.addWidget(server_desc)

        # Username
        username_lbl = QLabel("Username:")
        username_lbl.setStyleSheet("font-size: 13px; color: #b0b0c0; font-weight: 500;")
        server_layout.addWidget(username_lbl)
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Enter username")
        self.username_input.setStyleSheet("""
            QLineEdit {
                background-color: #252540;
                border: 2px solid #3a3a5e;
                border-radius: 8px;
                padding: 12px;
                color: white;
                font-size: 14px;
            }
            QLineEdit:focus { border-color: #00d4aa; }
        """)
        self.username_input.setMinimumHeight(45)
        server_layout.addWidget(self.username_input)

        # Password
        password_lbl = QLabel("Password:")
        password_lbl.setStyleSheet("font-size: 13px; color: #b0b0c0; font-weight: 500;")
        server_layout.addWidget(password_lbl)
        password_row = QHBoxLayout()
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Enter password")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setStyleSheet("""
            QLineEdit {
                background-color: #252540;
                border: 2px solid #3a3a5e;
                border-radius: 8px;
                padding: 12px;
                color: white;
                font-size: 14px;
            }
            QLineEdit:focus { border-color: #00d4aa; }
        """)
        self.password_input.setMinimumHeight(45)
        password_row.addWidget(self.password_input)

        self.show_password_btn = QPushButton("👁")
        self.show_password_btn.setFixedSize(45, 45)
        self.show_password_btn.setCheckable(True)
        self.show_password_btn.setStyleSheet("""
            QPushButton {
                background-color: #3a3a5e;
                border: none;
                border-radius: 8px;
                font-size: 16px;
            }
            QPushButton:hover { background-color: #4a4a7e; }
        """)
        self.show_password_btn.clicked.connect(self._toggle_password_visibility)
        password_row.addWidget(self.show_password_btn)
        server_layout.addLayout(password_row)

        # Login button
        self.login_btn = QPushButton("🔐  Login to Server")
        self.login_btn.setStyleSheet("""
            QPushButton {
                background-color: #00d4aa;
                color: #0a0a12;
                border: none;
                border-radius: 8px;
                padding: 15px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #00e8bb; }
        """)
        self.login_btn.setMinimumHeight(50)
        self.login_btn.clicked.connect(self._on_login)
        server_layout.addWidget(self.login_btn)

        # Status
        self.server_status = QLabel("○  Not Connected")
        self.server_status.setStyleSheet("font-size: 13px; color: #ff6b6b; padding: 8px 0;")
        server_layout.addWidget(self.server_status)

        # API Key display (hidden initially)
        self.api_key_frame = QFrame()
        self.api_key_frame.setStyleSheet("""
            QFrame {
                background-color: rgba(0, 212, 170, 0.15);
                border: 1px solid #00d4aa;
                border-radius: 8px;
                padding: 10px;
            }
        """)
        self.api_key_frame.setVisible(False)
        api_key_layout = QVBoxLayout(self.api_key_frame)
        self.api_key_label = QLabel("")
        self.api_key_label.setStyleSheet("font-size: 11px; color: #00d4aa; font-family: monospace;")
        self.api_key_label.setWordWrap(True)
        api_key_layout.addWidget(self.api_key_label)
        server_layout.addWidget(self.api_key_frame)

        server_layout.addStretch()
        columns.addWidget(server_card)

        # ========== RIGHT: EXCHANGE CONNECTION ==========
        exchange_card = QFrame()
        exchange_card.setStyleSheet("""
            QFrame {
                background-color: #1a1a2e;
                border: 1px solid #2a2a4e;
                border-radius: 12px;
                padding: 20px;
            }
        """)
        exchange_layout = QVBoxLayout(exchange_card)
        exchange_layout.setSpacing(15)

        # Title
        exchange_title = QLabel("💱  Exchange Connection")
        exchange_title.setStyleSheet("font-size: 18px; font-weight: bold; color: #4080ff; padding: 5px 0;")
        exchange_layout.addWidget(exchange_title)

        exchange_desc = QLabel("Connect your exchange to execute trades")
        exchange_desc.setStyleSheet("font-size: 12px; color: #808090; margin-bottom: 10px;")
        exchange_layout.addWidget(exchange_desc)

        # Exchange selector
        exchange_lbl = QLabel("Select Exchange:")
        exchange_lbl.setStyleSheet("font-size: 13px; color: #b0b0c0; font-weight: 500;")
        exchange_layout.addWidget(exchange_lbl)
        self.exchange_combo = QComboBox()
        self.exchange_combo.setStyleSheet("""
            QComboBox {
                background-color: #252540;
                border: 2px solid #3a3a5e;
                border-radius: 8px;
                padding: 12px;
                color: white;
                font-size: 14px;
            }
            QComboBox:focus { border-color: #4080ff; }
            QComboBox QAbstractItemView {
                background-color: #252540;
                selection-background-color: #4080ff;
            }
        """)
        self.exchange_combo.setMinimumHeight(45)
        for ex in SUPPORTED_EXCHANGES:
            self.exchange_combo.addItem(f"  {ex.upper()}")
        exchange_layout.addWidget(self.exchange_combo)

        # ===== API CREDENTIALS SECTION (HIGHLIGHTED) =====
        api_box = QFrame()
        api_box.setStyleSheet("""
            QFrame {
                background-color: #252550;
                border: 2px solid #4080ff;
                border-radius: 10px;
                padding: 15px;
            }
        """)
        api_box_layout = QVBoxLayout(api_box)
        api_box_layout.setSpacing(12)

        api_title = QLabel("🔑  API CREDENTIALS")
        api_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #4080ff;")
        api_box_layout.addWidget(api_title)

        # API Key input
        api_key_lbl = QLabel("API Key:")
        api_key_lbl.setStyleSheet("font-size: 13px; color: #b0b0c0;")
        api_box_layout.addWidget(api_key_lbl)

        self.exchange_api_key = QLineEdit()
        self.exchange_api_key.setPlaceholderText("Paste your API key here...")
        self.exchange_api_key.setStyleSheet("""
            QLineEdit {
                background-color: #1a1a30;
                border: 2px solid #4a4a7e;
                border-radius: 8px;
                padding: 14px;
                color: #ffffff;
                font-size: 14px;
                font-family: 'Consolas', monospace;
            }
            QLineEdit:focus { border-color: #4080ff; background-color: #202045; }
        """)
        self.exchange_api_key.setMinimumHeight(50)
        api_box_layout.addWidget(self.exchange_api_key)

        # API Secret input
        api_secret_lbl = QLabel("API Secret:")
        api_secret_lbl.setStyleSheet("font-size: 13px; color: #b0b0c0;")
        api_box_layout.addWidget(api_secret_lbl)

        secret_row = QHBoxLayout()
        self.exchange_api_secret = QLineEdit()
        self.exchange_api_secret.setPlaceholderText("Paste your API secret here...")
        self.exchange_api_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.exchange_api_secret.setStyleSheet("""
            QLineEdit {
                background-color: #1a1a30;
                border: 2px solid #4a4a7e;
                border-radius: 8px;
                padding: 14px;
                color: #ffffff;
                font-size: 14px;
                font-family: 'Consolas', monospace;
            }
            QLineEdit:focus { border-color: #4080ff; background-color: #202045; }
        """)
        self.exchange_api_secret.setMinimumHeight(50)
        secret_row.addWidget(self.exchange_api_secret)

        self.show_secret_btn = QPushButton("👁")
        self.show_secret_btn.setFixedSize(50, 50)
        self.show_secret_btn.setCheckable(True)
        self.show_secret_btn.setStyleSheet("""
            QPushButton {
                background-color: #3a3a5e;
                border: none;
                border-radius: 8px;
                font-size: 18px;
            }
            QPushButton:hover { background-color: #4a4a7e; }
            QPushButton:checked { background-color: #4080ff; }
        """)
        self.show_secret_btn.clicked.connect(self._toggle_secret_visibility)
        secret_row.addWidget(self.show_secret_btn)
        api_box_layout.addLayout(secret_row)

        help_text = QLabel("⚠️ Get these from your exchange API settings. Keep secret safe!")
        help_text.setStyleSheet("font-size: 11px; color: #ffd93d;")
        help_text.setWordWrap(True)
        api_box_layout.addWidget(help_text)

        exchange_layout.addWidget(api_box)

        # Testnet checkbox
        self.testnet_check = QCheckBox("  🧪 Use Testnet / Sandbox Mode")
        self.testnet_check.setStyleSheet("font-size: 13px; padding: 8px 0;")
        exchange_layout.addWidget(self.testnet_check)

        # Connect button
        self.connect_exchange_btn = QPushButton("🔌  Connect to Exchange")
        self.connect_exchange_btn.setStyleSheet("""
            QPushButton {
                background-color: #4080ff;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 15px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #5090ff; }
        """)
        self.connect_exchange_btn.setMinimumHeight(50)
        self.connect_exchange_btn.clicked.connect(self._on_connect_exchange)
        exchange_layout.addWidget(self.connect_exchange_btn)

        # Status
        self.exchange_status = QLabel("○  Not Connected")
        self.exchange_status.setStyleSheet("font-size: 13px; color: #ff6b6b; padding: 8px 0;")
        exchange_layout.addWidget(self.exchange_status)

        # Balance frame (hidden initially)
        self.balance_frame = QFrame()
        self.balance_frame.setStyleSheet("""
            QFrame {
                background-color: rgba(0, 212, 170, 0.15);
                border: 1px solid #00d4aa;
                border-radius: 8px;
                padding: 15px;
            }
        """)
        self.balance_frame.setVisible(False)
        balance_layout = QVBoxLayout(self.balance_frame)
        self.balance_label = QLabel("$0.00 USDT")
        self.balance_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #00d4aa;")
        balance_layout.addWidget(self.balance_label)
        exchange_layout.addWidget(self.balance_frame)

        # Portfolio section
        portfolio_label = QLabel("💼  Your Portfolio:")
        portfolio_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #b0b0c0; margin-top: 10px;")
        exchange_layout.addWidget(portfolio_label)

        self.portfolio_text = QTextEdit()
        self.portfolio_text.setReadOnly(True)
        self.portfolio_text.setMaximumHeight(120)
        self.portfolio_text.setPlaceholderText("Connect to exchange to see portfolio...")
        self.portfolio_text.setStyleSheet("""
            QTextEdit {
                background-color: #0f0f1a;
                border: 1px solid #2a2a4e;
                border-radius: 8px;
                color: #00d4aa;
                font-family: 'Consolas', monospace;
                font-size: 12px;
                padding: 10px;
            }
        """)
        exchange_layout.addWidget(self.portfolio_text)

        refresh_btn = QPushButton("🔄  Refresh Portfolio")
        refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a2a4e;
                color: #b0b0c0;
                border: none;
                border-radius: 6px;
                padding: 8px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #3a3a5e; color: white; }
        """)
        refresh_btn.clicked.connect(self._refresh_portfolio)
        exchange_layout.addWidget(refresh_btn)

        exchange_layout.addStretch()
        columns.addWidget(exchange_card)

        main_layout.addLayout(columns)
        scroll.setWidget(content)

        return scroll

    def _create_trading_tab(self) -> QWidget:
        """Create the trading controls tab with scroll support"""
        # Create scroll area for trading content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        # Content widget - use vertical layout for stats + columns
        content = QWidget()
        outer_layout = QVBoxLayout(content)
        outer_layout.setSpacing(15)
        outer_layout.setContentsMargins(10, 10, 10, 10)

        # ========== PERFORMANCE STATS DASHBOARD ==========
        stats_row = QHBoxLayout()
        stats_row.setSpacing(12)

        # Total P&L Card
        pnl_card = QFrame()
        pnl_card.setObjectName("statsCard")
        pnl_card.setMinimumWidth(160)
        pnl_card.setMaximumHeight(90)
        pnl_layout = QVBoxLayout(pnl_card)
        pnl_layout.setContentsMargins(14, 10, 14, 10)
        pnl_layout.setSpacing(4)

        pnl_label = QLabel("TOTAL P&L")
        pnl_label.setObjectName("statLabel")
        pnl_layout.addWidget(pnl_label)

        self.total_pnl_value = QLabel("$0.00")
        self.total_pnl_value.setObjectName("statValue")
        pnl_layout.addWidget(self.total_pnl_value)
        stats_row.addWidget(pnl_card)

        # Win Rate Card
        wr_card = QFrame()
        wr_card.setObjectName("statsCard")
        wr_card.setMinimumWidth(140)
        wr_card.setMaximumHeight(90)
        wr_layout = QVBoxLayout(wr_card)
        wr_layout.setContentsMargins(14, 10, 14, 10)
        wr_layout.setSpacing(4)

        wr_label = QLabel("WIN RATE")
        wr_label.setObjectName("statLabel")
        wr_layout.addWidget(wr_label)

        self.win_rate_value = QLabel("--")
        self.win_rate_value.setObjectName("statValue")
        wr_layout.addWidget(self.win_rate_value)
        stats_row.addWidget(wr_card)

        # Trades Today Card
        trades_card = QFrame()
        trades_card.setObjectName("statsCard")
        trades_card.setMinimumWidth(130)
        trades_card.setMaximumHeight(90)
        trades_layout = QVBoxLayout(trades_card)
        trades_layout.setContentsMargins(14, 10, 14, 10)
        trades_layout.setSpacing(4)

        trades_label = QLabel("TRADES TODAY")
        trades_label.setObjectName("statLabel")
        trades_layout.addWidget(trades_label)

        self.trades_today_value = QLabel("0")
        self.trades_today_value.setObjectName("statValue")
        trades_layout.addWidget(self.trades_today_value)
        stats_row.addWidget(trades_card)

        # Active Positions Card
        active_card = QFrame()
        active_card.setObjectName("statsCard")
        active_card.setMinimumWidth(130)
        active_card.setMaximumHeight(90)
        active_layout = QVBoxLayout(active_card)
        active_layout.setContentsMargins(14, 10, 14, 10)
        active_layout.setSpacing(4)

        active_label = QLabel("ACTIVE")
        active_label.setObjectName("statLabel")
        active_layout.addWidget(active_label)

        self.active_positions_value = QLabel("0")
        self.active_positions_value.setObjectName("statValue")
        active_layout.addWidget(self.active_positions_value)
        stats_row.addWidget(active_card)

        stats_row.addStretch()
        outer_layout.addLayout(stats_row)

        # ========== MAIN COLUMNS ==========
        main_layout = QHBoxLayout()
        main_layout.setSpacing(20)

        # ========== LEFT COLUMN - Settings & Signal ==========
        left_col = QVBoxLayout()
        left_col.setSpacing(15)

        # Trading Settings Card
        settings_card = QFrame()
        settings_card.setObjectName("card")
        settings_layout = QVBoxLayout(settings_card)
        settings_layout.setSpacing(18)

        # Header
        settings_header = QHBoxLayout()
        settings_icon = QLabel("⚙️")
        settings_icon.setStyleSheet("font-size: 24px;")
        settings_header.addWidget(settings_icon)

        settings_title = QLabel("Trading Settings")
        settings_title.setObjectName("sectionTitle")
        settings_header.addWidget(settings_title, 1)
        settings_layout.addLayout(settings_header)

        # Settings grid
        grid = QGridLayout()
        grid.setSpacing(15)

        # Trading pair
        pair_label = QLabel("Trading Pair")
        pair_label.setObjectName("fieldLabel")
        grid.addWidget(pair_label, 0, 0)

        self.pair_combo = QComboBox()
        self.pair_combo.setMinimumHeight(45)
        for pair in SUPPORTED_PAIRS:
            self.pair_combo.addItem(f"  {pair}")
        grid.addWidget(self.pair_combo, 0, 1)

        # Risk per trade
        risk_label = QLabel("Risk per Trade")
        risk_label.setObjectName("fieldLabel")
        grid.addWidget(risk_label, 1, 0)

        self.risk_spin = QDoubleSpinBox()
        self.risk_spin.setRange(0.5, 10.0)
        self.risk_spin.setValue(DEFAULT_RISK_PERCENT)
        self.risk_spin.setSingleStep(0.5)
        self.risk_spin.setSuffix(" %")
        self.risk_spin.setMinimumHeight(45)
        self.risk_spin.valueChanged.connect(self._on_risk_changed)
        grid.addWidget(self.risk_spin, 1, 1)

        # Minimum confidence
        conf_label = QLabel("Min Confidence")
        conf_label.setObjectName("fieldLabel")
        grid.addWidget(conf_label, 2, 0)

        self.confidence_spin = QDoubleSpinBox()
        self.confidence_spin.setRange(0.3, 1.0)
        self.confidence_spin.setValue(MIN_CONFIDENCE)
        self.confidence_spin.setSingleStep(0.05)
        self.confidence_spin.setMinimumHeight(45)
        grid.addWidget(self.confidence_spin, 2, 1)

        settings_layout.addLayout(grid)

        # Auto-trade toggle
        self.auto_trade_check = QCheckBox("  🤖  Enable Auto-Trading")
        self.auto_trade_check.setStyleSheet("font-size: 15px; font-weight: 600; padding: 10px 0;")
        self.auto_trade_check.stateChanged.connect(self._on_auto_trade_changed)
        settings_layout.addWidget(self.auto_trade_check)

        # Futures trading toggle (1x leverage, allows SHORT in down markets)
        self.futures_check = QCheckBox("  📉  Enable Futures (1x leverage)")
        self.futures_check.setStyleSheet("""
            QCheckBox {
                font-size: 14px;
                font-weight: 600;
                padding: 8px 0;
                color: #ffa500;
            }
            QCheckBox::indicator:checked {
                background: #ffa500;
                border-color: #ffa500;
            }
        """)
        self.futures_check.setToolTip(
            "Enable futures trading with 1x leverage (isolated margin).\n"
            "Allows SHORT positions in down markets.\n"
            "⚠️ Only for Binance/Bybit. Same risk as spot at 1x."
        )
        self.futures_check.stateChanged.connect(self._on_futures_changed)
        settings_layout.addWidget(self.futures_check)

        left_col.addWidget(settings_card)

        # ========== SIGNAL CARD ==========
        signal_card = QFrame()
        signal_card.setObjectName("card")
        self.signal_card = signal_card
        signal_layout = QVBoxLayout(signal_card)
        signal_layout.setSpacing(15)

        # Header
        signal_header = QHBoxLayout()
        signal_icon = QLabel("📊")
        signal_icon.setStyleSheet("font-size: 24px;")
        signal_header.addWidget(signal_icon)

        signal_title = QLabel("Current Signal")
        signal_title.setObjectName("sectionTitle")
        signal_header.addWidget(signal_title, 1)
        signal_layout.addLayout(signal_header)

        # Signal display frame
        self.signal_frame = QFrame()
        self.signal_frame.setObjectName("signalCardNeutral")
        signal_frame_layout = QVBoxLayout(self.signal_frame)
        signal_frame_layout.setSpacing(12)

        # Pair and side
        self.signal_pair_label = QLabel("--")
        self.signal_pair_label.setStyleSheet("font-size: 32px; font-weight: 800; color: #ffffff;")
        signal_frame_layout.addWidget(self.signal_pair_label)

        self.signal_side_label = QLabel("WAITING FOR SIGNAL")
        self.signal_side_label.setStyleSheet("font-size: 18px; color: #606080;")
        signal_frame_layout.addWidget(self.signal_side_label)

        # Signal details
        details_grid = QGridLayout()
        details_grid.setSpacing(12)

        self.entry_label = QLabel("📍 Entry: --")
        self.sl_label = QLabel("🛑 Stop Loss: --")
        self.tp_label = QLabel("🎯 Take Profit: --")
        self.conf_label = QLabel("📊 Confidence: --")
        self.regime_label = QLabel("📈 Regime: --")

        for label in [self.entry_label, self.sl_label, self.tp_label, self.conf_label, self.regime_label]:
            label.setStyleSheet("font-size: 14px; color: #a0a0b0;")

        details_grid.addWidget(self.entry_label, 0, 0)
        details_grid.addWidget(self.sl_label, 0, 1)
        details_grid.addWidget(self.tp_label, 1, 0)
        details_grid.addWidget(self.conf_label, 1, 1)
        details_grid.addWidget(self.regime_label, 2, 0, 1, 2)

        signal_frame_layout.addLayout(details_grid)

        # Execute info
        self.execute_info_label = QLabel("")
        self.execute_info_label.setStyleSheet("font-size: 12px; color: #ffd93d; margin-top: 8px;")
        self.execute_info_label.setWordWrap(True)
        signal_frame_layout.addWidget(self.execute_info_label)

        signal_layout.addWidget(self.signal_frame)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        self.get_signal_btn = QPushButton("📡  Get Signal")
        self.get_signal_btn.setObjectName("secondaryBtn")
        self.get_signal_btn.setMinimumHeight(50)
        self.get_signal_btn.clicked.connect(self._on_get_signal)
        btn_layout.addWidget(self.get_signal_btn)

        self.execute_btn = QPushButton("▶️  Execute Trade")
        self.execute_btn.setMinimumHeight(50)
        self.execute_btn.setEnabled(False)
        self.execute_btn.clicked.connect(self._on_execute_signal)
        btn_layout.addWidget(self.execute_btn)

        signal_layout.addLayout(btn_layout)
        left_col.addWidget(signal_card)

        left_col.addStretch()
        main_layout.addLayout(left_col, 1)

        # ========== RIGHT COLUMN - Positions ==========
        right_col = QVBoxLayout()
        right_col.setSpacing(20)

        positions_card = QFrame()
        positions_card.setObjectName("card")
        positions_layout = QVBoxLayout(positions_card)
        positions_layout.setSpacing(15)

        # Header
        pos_header = QHBoxLayout()
        pos_icon = QLabel("📂")
        pos_icon.setStyleSheet("font-size: 24px;")
        pos_header.addWidget(pos_icon)

        pos_title = QLabel("Active Positions")
        pos_title.setObjectName("sectionTitle")
        pos_header.addWidget(pos_title, 1)
        positions_layout.addLayout(pos_header)

        self.positions_text = QTextEdit()
        self.positions_text.setReadOnly(True)
        self.positions_text.setPlaceholderText("No active positions\n\nYour open trades will appear here.")
        positions_layout.addWidget(self.positions_text, 1)

        # ===== PRIMARY ACTION BUTTONS =====
        primary_btns = QHBoxLayout()
        primary_btns.setSpacing(10)

        self.close_all_btn = QPushButton("🛑  Close All")
        self.close_all_btn.setObjectName("dangerBtn")
        self.close_all_btn.setMinimumHeight(45)
        self.close_all_btn.setToolTip("Close all positions at market price")
        self.close_all_btn.clicked.connect(self._on_close_all)
        primary_btns.addWidget(self.close_all_btn)

        self.resync_btn = QPushButton("🔄  Sync")
        self.resync_btn.setObjectName("secondaryBtn")
        self.resync_btn.setMinimumHeight(45)
        self.resync_btn.setToolTip("Sync positions from exchange")
        self.resync_btn.clicked.connect(self._on_resync_positions)
        primary_btns.addWidget(self.resync_btn)

        positions_layout.addLayout(primary_btns)

        # ===== ADVANCED OPTIONS (COLLAPSIBLE) =====
        self.advanced_btn = QPushButton("⚙️  Advanced Options  ▼")
        self.advanced_btn.setObjectName("collapseBtn")
        self.advanced_btn.setCheckable(True)
        self.advanced_btn.setMinimumHeight(38)
        self.advanced_btn.clicked.connect(self._toggle_advanced_options)
        positions_layout.addWidget(self.advanced_btn)

        # Advanced options container (hidden by default)
        self.advanced_frame = QFrame()
        self.advanced_frame.setStyleSheet("""
            QFrame {
                background: rgba(20, 22, 35, 0.6);
                border: 1px solid rgba(60, 70, 100, 0.3);
                border-radius: 10px;
                padding: 12px;
            }
        """)
        self.advanced_frame.setVisible(False)
        advanced_layout = QVBoxLayout(self.advanced_frame)
        advanced_layout.setSpacing(8)
        advanced_layout.setContentsMargins(8, 8, 8, 8)

        # Force close button
        self.force_close_btn = QPushButton("⚡  Force Close All Positions")
        self.force_close_btn.setObjectName("dangerBtn")
        self.force_close_btn.setMinimumHeight(40)
        self.force_close_btn.setToolTip("Sell all tracked positions AND clear from tracking (fixes stuck positions)")
        self.force_close_btn.clicked.connect(self._on_force_close_positions)
        advanced_layout.addWidget(self.force_close_btn)

        # Grid for other advanced buttons
        adv_grid = QGridLayout()
        adv_grid.setSpacing(8)

        self.clear_positions_btn = QPushButton("🗑️  Clear Stale")
        self.clear_positions_btn.setMinimumHeight(36)
        self.clear_positions_btn.setToolTip("Remove position records without placing orders")
        self.clear_positions_btn.clicked.connect(self._on_clear_positions)
        adv_grid.addWidget(self.clear_positions_btn, 0, 0)

        self.cancel_orders_btn = QPushButton("❌  Cancel Orders")
        self.cancel_orders_btn.setMinimumHeight(36)
        self.cancel_orders_btn.setToolTip("Cancel all open orders on exchange")
        self.cancel_orders_btn.clicked.connect(self._on_cancel_all_orders)
        adv_grid.addWidget(self.cancel_orders_btn, 0, 1)

        self.fix_positions_btn = QPushButton("🔧  Fix SL/TP")
        self.fix_positions_btn.setMinimumHeight(36)
        self.fix_positions_btn.setToolTip("Fix positions with invalid SL/TP values")
        self.fix_positions_btn.clicked.connect(self._on_fix_positions)
        adv_grid.addWidget(self.fix_positions_btn, 1, 0)

        self.import_orphans_btn = QPushButton("📥  Import Lost")
        self.import_orphans_btn.setMinimumHeight(36)
        self.import_orphans_btn.setToolTip("Import untracked spot holdings")
        self.import_orphans_btn.clicked.connect(self._on_import_orphan_positions)
        adv_grid.addWidget(self.import_orphans_btn, 1, 1)

        self.convert_all_btn = QPushButton("💵  Convert to USDT")
        self.convert_all_btn.setMinimumHeight(36)
        self.convert_all_btn.setToolTip("Sell all crypto assets and convert to USDT")
        self.convert_all_btn.clicked.connect(self._on_convert_all_to_usdt)
        adv_grid.addWidget(self.convert_all_btn, 2, 0, 1, 2)

        advanced_layout.addLayout(adv_grid)
        positions_layout.addWidget(self.advanced_frame)

        right_col.addWidget(positions_card)
        main_layout.addLayout(right_col, 1)

        # Add main columns to outer layout
        outer_layout.addLayout(main_layout)

        # Set the content in scroll area
        scroll.setWidget(content)
        return scroll

    def _create_logs_tab(self) -> QWidget:
        """Create the logs tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(15)

        # Header
        header = QHBoxLayout()
        log_icon = QLabel("📋")
        log_icon.setStyleSheet("font-size: 24px;")
        header.addWidget(log_icon)

        log_title = QLabel("Activity Log")
        log_title.setObjectName("sectionTitle")
        header.addWidget(log_title)

        header.addStretch()

        clear_btn = QPushButton("🗑️  Clear Log")
        clear_btn.setObjectName("outlineBtn")
        clear_btn.clicked.connect(lambda: self.log_text.clear())
        header.addWidget(clear_btn)

        layout.addLayout(header)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setPlaceholderText("Activity logs will appear here...")
        layout.addWidget(self.log_text)

        return tab

    def _setup_timers(self):
        """Setup update timers - all run in background threads to prevent UI freeze"""
        # Position display update
        self.position_timer = QTimer()
        self.position_timer.timeout.connect(self._schedule_position_update)
        self.position_timer.start(15000)  # Every 15 seconds

        # SL/TP monitoring
        self.monitor_timer = QTimer()
        self.monitor_timer.timeout.connect(self._schedule_sl_tp_check)
        self.monitor_timer.start(10000)  # Every 10 seconds

        # Balance update timer
        self.balance_timer = QTimer()
        self.balance_timer.timeout.connect(self._schedule_balance_update)
        self.balance_timer.start(30000)  # Every 30 seconds

        # User data refresh
        self.user_data_timer = QTimer()
        self.user_data_timer.timeout.connect(self._refresh_user_data)
        self.user_data_timer.start(120000)  # Every 2 minutes

    def _connect_signals(self):
        """Connect PyQt signals for thread-safe UI updates"""
        self.signal_received.connect(self._on_signal_received)
        # Thread-safe signal connections
        self.log_signal.connect(self._log)
        self.status_signal.connect(self._set_status)
        self.balance_signal.connect(self._update_balance_ui)
        self.portfolio_signal.connect(self._update_portfolio_ui)
        self.trade_result_signal.connect(self._handle_trade_result)
        self.connect_result_signal.connect(self._handle_connect_result)
        self.login_result_signal.connect(self._handle_login_result)
        self.subscription_expired_signal.connect(self._show_subscription_expired)

    def _update_balance_ui(self, balance: float):
        """Thread-safe balance UI update"""
        self._total_balance = balance
        self.balance_label.setText(f"${balance:,.2f}")

    def _update_portfolio_ui(self, text: str):
        """Thread-safe portfolio text update"""
        self.portfolio_text.setPlainText(text)

    def _set_status(self, message: str):
        """Thread-safe status bar update"""
        self.status_bar.showMessage(message)

    def _show_subscription_expired(self, error_message: str):
        """Show subscription expired dialog with upgrade link"""
        # Prevent showing dialog multiple times
        if self._subscription_expired_shown:
            return
        self._subscription_expired_shown = True

        import webbrowser

        # Update signal display to show expired message
        self.signal_pair_label.setText("SUBSCRIPTION")
        self.signal_side_label.setText("⚠️  EXPIRED")
        self.signal_side_label.setStyleSheet("font-size: 20px; font-weight: 700; color: #ff6b6b;")
        self.entry_label.setText("Your API key has expired")
        self.sl_label.setText("Please renew your subscription")
        self.tp_label.setText("to continue receiving signals")
        self.conf_label.setText("")
        self.regime_label.setText("")

        # Create custom dialog with clickable link
        msg = QMessageBox(self)
        msg.setWindowTitle("⚠️ Subscription Expired")
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setText(
            f"<h3>Your Subscription Has Expired</h3>"
            f"<p>{error_message}</p>"
            f"<p>You need to renew your subscription to continue receiving trading signals.</p>"
            f"<p><b>Visit our website to upgrade:</b></p>"
            f"<p style='font-size: 16px;'><a href='https://selftrade.site'>https://selftrade.site</a></p>"
        )
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Open)

        # Set button text
        open_btn = msg.button(QMessageBox.StandardButton.Open)
        if open_btn:
            open_btn.setText("🌐 Open selftrade.site")

        result = msg.exec()

        # Open website if user clicks "Open"
        if result == QMessageBox.StandardButton.Open:
            webbrowser.open("https://selftrade.site")

        # Update status bar
        self.server_status.setText("⚠️  Subscription Expired - Please Upgrade")
        self.server_status.setStyleSheet("font-size: 13px; color: #ff6b6b; font-weight: 600; padding: 8px 0;")

        # Stop auto-trading
        if self.auto_trade:
            self.auto_trade = False
            self.auto_trade_toggle.setChecked(False)
            self._log("🛑 Auto-trading disabled due to expired subscription")

    def _toggle_password_visibility(self):
        """Toggle password visibility"""
        if self.show_password_btn.isChecked():
            self.password_input.setEchoMode(QLineEdit.EchoMode.Normal)
            self.show_password_btn.setText("🙈")
        else:
            self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
            self.show_password_btn.setText("👁")

    def _toggle_secret_visibility(self):
        """Toggle API secret visibility"""
        if self.show_secret_btn.isChecked():
            self.exchange_api_secret.setEchoMode(QLineEdit.EchoMode.Normal)
            self.show_secret_btn.setText("🙈")
        else:
            self.exchange_api_secret.setEchoMode(QLineEdit.EchoMode.Password)
            self.show_secret_btn.setText("👁")

    def _toggle_advanced_options(self):
        """Toggle visibility of advanced position options"""
        is_expanded = self.advanced_btn.isChecked()
        self.advanced_frame.setVisible(is_expanded)
        if is_expanded:
            self.advanced_btn.setText("⚙️  Advanced Options  ▲")
        else:
            self.advanced_btn.setText("⚙️  Advanced Options  ▼")

    def _on_login(self):
        """Handle login - launches background thread"""
        username = self.username_input.text().strip()
        password = self.password_input.text().strip()

        if not username or not password:
            QMessageBox.warning(self, "Missing Credentials", "Please enter both username and password.")
            return

        self.login_btn.setText("Connecting...")
        self.login_btn.setEnabled(False)

        # Run login in background thread to prevent UI freeze
        _executor.submit(self._background_login, username, password)

    def _background_login(self, username: str, password: str):
        """Background thread for login"""
        try:
            result = self.server_client.login(username, password)
            self.login_result_signal.emit({
                'success': True,
                'username': username,
                'result': result,
                'api_key': self.server_client.api_key
            })
        except Exception as e:
            self.login_result_signal.emit({
                'success': False,
                'username': username,
                'error': str(e)
            })

    def _handle_login_result(self, result: dict):
        """Handle login result from background thread (runs in main thread)"""
        try:
            if result['success']:
                username = result['username']
                login_result = result['result']
                api_key = result['api_key']

                self.connected_server = True
                self._subscription_expired_shown = False  # Reset for new login
                self.signal_handler.set_api_key(api_key)

                user = login_result.get('user', {})
                self.user_data = user
                self._update_user_info()

                # Connect WebSocket
                self.ws_client.set_api_key(api_key)
                self.ws_client.on_signal = lambda s: self.signal_received.emit(s)
                self.ws_client.on_subscription_expired = lambda msg: self.subscription_expired_signal.emit(msg)

                # Set on_connect callback to send exchange preference and portfolio
                def on_ws_connect():
                    # Send exchange preference to server
                    exchange = self.exchange_combo.currentText().strip().lower().replace(" ", "")
                    if exchange:
                        self.ws_client.set_exchange(exchange)
                        self.log_signal.emit(f"📡 Server will use {exchange.upper()} prices")

                    # Send initial portfolio state
                    self._sync_portfolio_to_server()

                self.ws_client.on_connect = on_ws_connect
                self.ws_client.connect(SUPPORTED_PAIRS)

                self.server_status.setText(f"●  Connected as {username}")
                self.server_status.setStyleSheet("font-size: 13px; color: #00d4aa; font-weight: 600; padding: 8px 0;")

                # Show API key
                if api_key:
                    self.api_key_frame.setVisible(True)
                    self.api_key_label.setText(f"{api_key[:30]}...")

                self._log(f"✅ Logged in as {username}")
                self._update_status()
                self._save_config()

            else:
                error_msg = result.get('error', 'Unknown error')
                QMessageBox.critical(self, "Login Failed", error_msg)
                self._log(f"❌ Login failed: {error_msg}")

        finally:
            self.login_btn.setText("🔐  Login to Server")
            self.login_btn.setEnabled(True)

    def _update_user_info(self):
        """Update user info in header"""
        self.user_card.setVisible(True)

        username = self.user_data.get('username', 'Unknown')
        plan = self.user_data.get('subscription_plan', 'free').upper()
        self.signals_remaining = self.user_data.get('trade_signals_remaining', 0)
        self.signals_used = self.user_data.get('trade_signals_used', 0)

        self.user_label.setText(f"👤 {username}")

        # Style plan badge
        plan_styles = {
            'FREE': "background: rgba(100, 100, 150, 0.4); color: #a0a0b0;",
            'BASIC': "background: rgba(64, 128, 255, 0.4); color: #80c0ff;",
            'PREMIUM': "background: rgba(255, 180, 0, 0.4); color: #ffd93d;"
        }
        self.plan_badge.setText(plan)
        self.plan_badge.setStyleSheet(f"""
            {plan_styles.get(plan, plan_styles['FREE'])}
            padding: 4px 12px;
            border-radius: 6px;
            font-size: 11px;
            font-weight: 700;
        """)

        # Calculate total signals for this period
        total_signals = self.signals_remaining + self.signals_used

        # Calculate days left
        days_left_text = ""
        sub_expires = self.user_data.get('subscription_expires')
        if sub_expires:
            try:
                from datetime import datetime, timezone
                if isinstance(sub_expires, str):
                    # Remove 'Z' and parse
                    sub_expires = sub_expires.replace('Z', '+00:00')
                    exp_date = datetime.fromisoformat(sub_expires)
                else:
                    exp_date = sub_expires
                # Make now timezone-aware if exp_date is
                if exp_date.tzinfo:
                    now = datetime.now(timezone.utc)
                else:
                    now = datetime.utcnow()
                days_left = (exp_date - now).days
                if days_left < 0:
                    days_left = 0
                if days_left <= 5:
                    days_left_text = f" ⚠️{days_left}d"
                else:
                    days_left_text = f" 📅{days_left}d"
            except Exception as e:
                logger.warning(f"Failed to parse subscription_expires: {e}")

        # Check for unlimited (premium)
        if plan == 'PREMIUM' or total_signals >= 999999:
            self.signal_count_label.setText(f"∞ Unlimited{days_left_text}")
            self.signal_progress.setMaximum(100)
            self.signal_progress.setValue(0)
        elif total_signals > 0:
            self.signal_count_label.setText(f"{self.signals_used}/{total_signals} used{days_left_text}")
            self.signal_progress.setMaximum(total_signals)
            self.signal_progress.setValue(self.signals_used)
        else:
            self.signal_count_label.setText(f"0 signals left{days_left_text}")
            self.signal_progress.setMaximum(1)
            self.signal_progress.setValue(1)

    def _refresh_user_data(self):
        """Refresh user data from server"""
        if not self.connected_server:
            return
        try:
            profile = self.server_client.get_profile()
            self.user_data = profile
            self._update_user_info()
        except Exception as e:
            logger.warning(f"Failed to refresh user data: {e}")

    def _on_connect_exchange(self):
        """Handle exchange connection - launches background thread"""
        # Get exchange name (remove spaces from combo text)
        exchange = self.exchange_combo.currentText().strip().lower().replace(" ", "")
        api_key = self.exchange_api_key.text().strip()
        api_secret = self.exchange_api_secret.text().strip()
        testnet = self.testnet_check.isChecked()

        if not api_key or not api_secret:
            QMessageBox.warning(self, "Missing API Credentials",
                "Please enter both API Key and API Secret.\n\n"
                "You can find these in your exchange account settings under API Management.")
            return

        self.connect_exchange_btn.setText("Connecting...")
        self.connect_exchange_btn.setEnabled(False)

        # Run connection in background thread to prevent UI freeze
        _executor.submit(self._background_connect_exchange, exchange, api_key, api_secret, testnet)

    def _background_connect_exchange(self, exchange: str, api_key: str, api_secret: str, testnet: bool):
        """Background thread for exchange connection"""
        try:
            self.exchange_client = ExchangeClient(exchange)
            self.exchange_client.connect(api_key, api_secret, testnet)

            # Get portfolio in background
            balances = self.exchange_client.get_all_balances(min_value_usdt=0.5)
            total = sum(b['usdt_value'] for b in balances.values()) if balances else 0

            # Get USDT details
            usdt_free = self.exchange_client.get_balance('USDT')
            open_orders = self.exchange_client.get_open_orders()

            # Emit success result to main thread
            self.connect_result_signal.emit({
                'success': True,
                'exchange': exchange,
                'total': total,
                'usdt_free': usdt_free,
                'open_orders': len(open_orders) if open_orders else 0,
                'balances': balances
            })

        except Exception as e:
            self.connect_result_signal.emit({
                'success': False,
                'exchange': exchange,
                'error': str(e)
            })

    def _handle_connect_result(self, result: dict):
        """Handle connection result from background thread (runs in main thread)"""
        try:
            if result['success']:
                exchange = result['exchange']
                self.connected_exchange = True

                # Create SL/TP monitor with trailing stop
                self.sl_tp_monitor = SLTPMonitor(
                    self.exchange_client,
                    self.position_manager,
                    self.trailing_config
                )
                self.sl_tp_monitor.on_exit = self._on_sl_tp_exit
                self.sl_tp_monitor.on_sl_updated = self._on_sl_updated

                # Create order executor with monitor
                self.order_executor = OrderExecutor(
                    self.exchange_client,
                    self.position_sizer,
                    self.position_manager,
                    self.sl_tp_monitor
                )

                # Update portfolio display
                self._total_balance = result['total']
                self._update_portfolio_from_balances(result.get('balances', {}))

                self._log(f"💵 USDT free (available): ${result['usdt_free']:,.2f}")
                if result['open_orders'] > 0:
                    self._log(f"⚠️ {result['open_orders']} open orders on exchange")

                # SYNC POSITIONS FROM EXCHANGE (fresh start - exchange is source of truth)
                # This clears stale local cache and creates positions based on actual holdings
                self._log("🔄 Starting position sync from exchange...")
                synced = self._sync_positions_from_exchange()
                if synced == 0:
                    self._log("📊 No existing holdings to track - ready for new trades")
                else:
                    # Verify positions were added
                    final_count = self.position_manager.get_position_count()
                    self._log(f"📊 Position manager now has {final_count} position(s)")

                self.exchange_status.setText(f"●  Connected to {exchange.upper()}")
                self.exchange_status.setStyleSheet("font-size: 13px; color: #00d4aa; font-weight: 600; padding: 8px 0;")
                self.balance_frame.setVisible(True)
                self.balance_label.setText(f"${self._total_balance:,.2f}")

                self._log(f"✅ Connected to {exchange.upper()}: ${self._total_balance:,.2f} total portfolio")
                self._update_status()
                self._save_config()

                # Sync portfolio to server (now with balance info)
                self._sync_portfolio_to_server()

                # Also notify server about exchange change (if WebSocket connected)
                if self.ws_client and self.ws_client.connected:
                    self.ws_client.set_exchange(exchange)
                    self._log(f"📡 Server will use {exchange.upper()} prices")

            else:
                error_msg = result.get('error', 'Unknown error')
                if "IP" in error_msg or "whitelist" in error_msg.lower() or "-2015" in error_msg:
                    QMessageBox.critical(self, "IP Not Whitelisted",
                        f"Connection failed: {error_msg}\n\n"
                        "⚠️ Your IP address is not whitelisted!\n\n"
                        "To fix this:\n"
                        "1. Go to your exchange API settings\n"
                        "2. Edit your API key\n"
                        "3. Add your current IP to the whitelist\n"
                        "4. Try connecting again")
                else:
                    QMessageBox.critical(self, "Connection Failed", error_msg)
                self._log(f"❌ Exchange connection failed: {error_msg}")

        finally:
            self.connect_exchange_btn.setText("🔌  Connect to Exchange")
            self.connect_exchange_btn.setEnabled(True)

    def _update_portfolio_from_balances(self, balances: dict):
        """Update portfolio display from balances dict"""
        if not balances:
            self.portfolio_text.setPlainText("No assets found")
            return

        lines = []
        total = 0

        sorted_balances = sorted(balances.items(), key=lambda x: x[1]['usdt_value'], reverse=True)

        for currency, data in sorted_balances:
            free = data.get('free', 0)
            used = data.get('used', 0)
            total_amt = data.get('total', free)
            value = data['usdt_value']
            total += value

            if currency == 'USDT':
                if used > 0:
                    lines.append(f"💵 USDT: ${total_amt:,.2f} (free: ${free:,.2f}, in orders: ${used:,.2f})")
                else:
                    lines.append(f"💵 USDT: ${total_amt:,.2f}")
            else:
                if used > 0:
                    lines.append(f"🪙 {currency}: {total_amt:.6f} (${value:,.2f}) [in orders: {used:.6f}]")
                else:
                    lines.append(f"🪙 {currency}: {total_amt:.6f} (${value:,.2f})")

        lines.append("─" * 35)
        lines.append(f"📊 Total Portfolio: ${total:,.2f}")

        self.portfolio_text.setPlainText("\n".join(lines))

    def _on_risk_changed(self, value):
        """Handle risk change"""
        self.position_sizer.set_risk_percent(value)
        self._log(f"Risk per trade set to {value}%")

    def _refresh_portfolio(self):
        """Refresh portfolio display - uses background thread"""
        if not self.connected_exchange:
            self.portfolio_text.setPlainText("Not connected")
            return

        # Run in background thread
        _executor.submit(self._background_refresh_portfolio)

    def _background_refresh_portfolio(self):
        """Background thread for portfolio refresh"""
        try:
            balances = self.exchange_client.get_all_balances(min_value_usdt=0.5)

            if not balances:
                self.portfolio_signal.emit("No assets found")
                return

            lines = []
            total = 0

            sorted_balances = sorted(balances.items(), key=lambda x: x[1]['usdt_value'], reverse=True)

            for currency, data in sorted_balances:
                free = data.get('free', 0)
                used = data.get('used', 0)
                total_amt = data.get('total', free)
                value = data['usdt_value']
                total += value

                if currency == 'USDT':
                    if used > 0:
                        lines.append(f"💵 USDT: ${total_amt:,.2f} (free: ${free:,.2f}, in orders: ${used:,.2f})")
                    else:
                        lines.append(f"💵 USDT: ${total_amt:,.2f}")
                else:
                    if used > 0:
                        lines.append(f"🪙 {currency}: {total_amt:.6f} (${value:,.2f}) [in orders: {used:.6f}]")
                    else:
                        lines.append(f"🪙 {currency}: {total_amt:.6f} (${value:,.2f})")

            lines.append("─" * 35)
            lines.append(f"📊 Total Portfolio: ${total:,.2f}")

            self.portfolio_signal.emit("\n".join(lines))
            self.balance_signal.emit(total)

        except Exception as e:
            self.portfolio_signal.emit(f"Error: {e}")

    def _on_get_signal(self):
        """Get signal from server - runs in background thread"""
        if not self.connected_server:
            QMessageBox.warning(self, "Not Connected", "Please login to the server first.")
            return

        pair = self.pair_combo.currentText().strip()
        self.get_signal_btn.setText("Fetching...")
        self.get_signal_btn.setEnabled(False)

        # Run in background thread to prevent UI freeze
        _executor.submit(self._background_get_signal, pair)

    def _background_get_signal(self, pair: str):
        """Background thread for getting signal"""
        try:
            signal = self.server_client.get_live_signal(pair)
            # Use signal_received to update UI (thread-safe)
            self.signal_received.emit(signal)
            self.log_signal.emit(f"📊 Signal received for {pair}")
        except SubscriptionExpiredError as e:
            # API key expired - show upgrade dialog
            self.subscription_expired_signal.emit(str(e))
            self.log_signal.emit(f"⚠️ Subscription expired: {e}")
        except Exception as e:
            self.log_signal.emit(f"❌ Signal fetch failed: {e}")
        finally:
            # Reset button in main thread
            QTimer.singleShot(0, self._reset_get_signal_btn)

    def _reset_get_signal_btn(self):
        """Reset get signal button (called in main thread)"""
        self.get_signal_btn.setText("📡  Get Signal")
        self.get_signal_btn.setEnabled(True)
        self._refresh_user_data()

    def _on_signal_received(self, signal: dict):
        """Handle WebSocket signal"""
        self._current_signal = signal
        self._display_signal(signal)

        # Auto-trade: execute if possible, but pre-check silently first
        if self.auto_trade and signal.get('side') != 'hold':
            can_execute, reason = self._can_execute_trade(signal)
            if can_execute:
                # CRITICAL: Pass signal directly to avoid race condition
                # where _current_signal gets overwritten by next signal
                self._execute_signal(signal)
            elif reason:
                # Only log if there's an actual reason (not silent skips)
                self._log(f"⏭️ Skipped {signal.get('pair')}: {reason}")
            # else: silent skip for duplicate positions - no log

    def _display_signal(self, signal: dict):
        """Display signal in the UI"""
        pair = signal.get('pair', '--')
        side = signal.get('side', 'hold').upper()
        entry = signal.get('entry_price', 0)
        stop = signal.get('stop_loss', 0)
        target = signal.get('target_price') or signal.get('take_profit', 0)
        confidence = signal.get('confidence', 0)
        regime = signal.get('regime', 'UNKNOWN')

        self.signal_pair_label.setText(pair)

        # Style based on signal type
        if side in ['LONG', 'BUY']:
            self.signal_side_label.setText("🟢  LONG / BUY")
            self.signal_side_label.setStyleSheet("font-size: 20px; font-weight: 700; color: #00d4aa;")
            self.signal_frame.setObjectName("signalCardLong")
        elif side in ['SHORT', 'SELL']:
            self.signal_side_label.setText("🔴  SHORT / SELL")
            self.signal_side_label.setStyleSheet("font-size: 20px; font-weight: 700; color: #ff6b6b;")
            self.signal_frame.setObjectName("signalCardShort")
        else:
            self.signal_side_label.setText("⏸️  HOLD / WAIT")
            self.signal_side_label.setStyleSheet("font-size: 20px; color: #606080;")
            self.signal_frame.setObjectName("signalCardNeutral")

        self.signal_frame.setStyleSheet(self.signal_frame.styleSheet())

        # For HOLD signals, show market analysis instead of trade prices
        if side == 'HOLD':
            reason = signal.get('reason', 'Analyzing market...')
            trend = signal.get('trend', 'unknown')
            market_status = signal.get('market_status', '')
            indicators = signal.get('indicators', {})

            # Show market info instead of empty prices
            current_price = indicators.get('current_price', 0)
            rsi = indicators.get('rsi', 0)
            adx = indicators.get('adx', 0)
            volume_ratio = indicators.get('volume_ratio', 0)

            self.entry_label.setText(f"💰 Price: ${current_price:,.2f}" if current_price else "📍 Entry: --")
            self.sl_label.setText(f"📊 RSI: {rsi:.0f} | ADX: {adx:.0f}" if rsi else "🛑 Stop Loss: --")
            self.tp_label.setText(f"📈 Trend: {trend.upper()}" if trend else "🎯 Take Profit: --")

            # Show reason in regime label
            self.regime_label.setText(f"💡 {reason[:50]}" if reason else f"📈 Regime: {regime}")

            # Show volume info instead of confidence for hold signals
            if volume_ratio:
                vol_status = "High" if volume_ratio > 1.5 else "Low" if volume_ratio < 0.5 else "Normal"
                self.conf_label.setText(f"📊 Volume: {vol_status} ({volume_ratio:.1f}x)")
                self.conf_label.setStyleSheet("font-size: 14px; color: #808090; font-weight: 600;")
        else:
            self.entry_label.setText(f"📍 Entry: ${entry:,.2f}")
            self.sl_label.setText(f"🛑 Stop Loss: ${stop:,.2f}")
            self.tp_label.setText(f"🎯 Take Profit: ${target:,.2f}")
            self.regime_label.setText(f"📈 Regime: {regime}")

            conf_color = '#00d4aa' if confidence >= 0.7 else '#ffd93d' if confidence >= 0.5 else '#ff6b6b'
            self.conf_label.setText(f"📊 Confidence: {confidence:.0%}")
            self.conf_label.setStyleSheet(f"font-size: 14px; color: {conf_color}; font-weight: 600;")

        # Check executability
        can_execute = False
        execute_note = ""

        if self.connected_exchange and side not in ['HOLD', '']:
            if side in ['LONG', 'BUY']:
                usdt = self.exchange_client.get_balance('USDT')
                can_execute = usdt >= 5.0
                if can_execute:
                    execute_note = f"✅ Can buy with ${usdt:.2f} USDT"
                else:
                    execute_note = f"⚠️ Need more USDT (have ${usdt:.2f})"
            elif side in ['SHORT', 'SELL']:
                asset_info = self.exchange_client.has_asset_balance(pair, min_value_usdt=5.0)
                can_execute = asset_info['has_balance']
                if can_execute:
                    execute_note = f"✅ Can sell {asset_info['amount']:.4f} {asset_info['currency']}"
                else:
                    execute_note = f"⚠️ No {asset_info['currency']} to sell - need LONG signal first"

        self.execute_btn.setEnabled(can_execute)
        self.execute_info_label.setText(execute_note)

        summary = self.signal_handler.get_signal_summary(signal)
        self._log(f"📊 Signal: {summary}")

    def _on_execute_signal(self):
        """Execute current signal (manual button click)"""
        if self._current_signal:
            self._execute_signal(self._current_signal)

    def _execute_current_signal(self):
        """Execute the current signal (for backwards compatibility)"""
        if self._current_signal:
            self._execute_signal(self._current_signal)

    def _execute_signal(self, signal: dict):
        """Execute a specific signal - pass signal directly to avoid race conditions"""
        if not self.order_executor or not signal:
            return

        # Quick validation (no network calls)
        validation = self.signal_handler.validate_signal(signal)
        if not validation['valid']:
            self._log(f"⚠️ Invalid signal: {validation['reason']}")
            return

        min_conf = self.confidence_spin.value()
        if signal.get('confidence', 0) < min_conf:
            self._log(f"⚠️ Confidence {signal.get('confidence', 0):.0%} below minimum {min_conf:.0%}")
            return

        # Disable execute button while processing
        self.execute_btn.setEnabled(False)
        self.execute_btn.setText("Executing...")
        self._log(f"🔄 Executing {signal.get('pair')} {signal.get('side', '').upper()}...")

        processed = self.signal_handler.process_signal(signal)

        # Run execution in background thread
        _executor.submit(self._background_execute_signal, processed)

    def _background_execute_signal(self, processed: dict):
        """Background thread for signal execution"""
        try:
            # Pre-check in background
            can_execute, reason = self._can_execute_trade_sync(processed)
            if not can_execute:
                # If reason is None, it's a silent skip (duplicate signal) - don't emit
                if reason is not None:
                    self.trade_result_signal.emit({'success': False, 'reason': reason})
                else:
                    # Silent skip - just re-enable button without logging
                    self.trade_result_signal.emit({'success': False, 'reason': None})
                return

            result = self.order_executor.execute_signal(processed)
            self.trade_result_signal.emit(result)

        except Exception as e:
            self.trade_result_signal.emit({'success': False, 'reason': str(e)})

    def _can_execute_trade_sync(self, signal: dict) -> tuple:
        """Synchronous version for background thread (same logic as _can_execute_trade)"""
        if not self.connected_exchange:
            return False, "Exchange not connected"

        pair = signal.get('pair', '').upper()
        side = signal.get('side', '').lower()

        try:
            # CHECK 1: Do we already have a position for this pair?
            existing_position = self.position_manager.get_position(pair)
            if existing_position:
                current_thesis = existing_position.get('thesis', existing_position.get('side', '')).lower()

                # Same direction thesis = skip silently
                if side in ['long', 'buy'] and current_thesis in ['long', 'buy']:
                    return False, None
                if side in ['short', 'sell'] and current_thesis in ['short', 'sell']:
                    return False, None

                # Opposite direction = FLIP thesis (no fee!)
                if (side in ['short', 'sell'] and current_thesis in ['long', 'buy']) or \
                   (side in ['long', 'buy'] and current_thesis in ['short', 'sell']):
                    return True, f"OK: Will flip {pair} to {side.upper()} (no fee)"

            # CHECK 2: Balance checks for NEW positions
            if side in ['long', 'buy']:
                usdt = self.exchange_client.get_balance('USDT')
                if usdt < 12.0:
                    return False, f"Insufficient USDT: ${usdt:.2f} (need $12+)"
                return True, f"OK: ${usdt:.2f} USDT available"

            elif side in ['short', 'sell']:
                # CHECK FUTURES FIRST - if enabled, use futures for SHORT
                if self.exchange_client.futures_enabled and self.exchange_client.futures_connected:
                    futures_balance = self.exchange_client.get_futures_balance()
                    if futures_balance >= 6.0:
                        return True, f"OK: ${futures_balance:.2f} USDT (futures)"
                    else:
                        return False, f"Insufficient futures balance: ${futures_balance:.2f} (need $6+)"

                # SPOT FALLBACK
                asset_info = self.exchange_client.has_asset_balance(pair, min_value_usdt=12.0)
                if not asset_info.get('has_balance'):
                    return False, None  # Silent skip
                return True, f"OK: {asset_info['amount']:.4f} {asset_info['currency']} available"

            return False, f"Unknown side: {side}"

        except Exception as e:
            return False, f"Check failed: {e}"

    def _handle_trade_result(self, result: dict):
        """Handle trade result from background thread (runs in main thread)"""
        try:
            if result.get('success'):
                action = result.get('action', '')

                if action == 'flipped':
                    # Position flip - NO FEE
                    self._log(f"🔄 FLIPPED {result.get('pair')} to {result.get('side', '').upper()} "
                             f"(NO FEE!) SL: ${result.get('stop_loss', 0):.2f} | TP: ${result.get('take_profit', 0):.2f}")
                    self._update_positions()
                elif action == 'updated':
                    # SL/TP updated
                    self._log(f"📝 Updated {result.get('pair')} {result.get('side', '').upper()} SL/TP levels")
                    self._update_positions()
                elif action == 'cleaned':
                    # Position too small, cleaned from tracking
                    self._log(f"🧹 {result.get('pair')} position too small - removed from tracking")
                    self._update_positions()
                else:
                    # Normal order execution
                    self._log(f"✅ Order executed: {result.get('pair')} {result.get('side')} "
                             f"qty={result.get('quantity', 0):.6f} @ ${result.get('fill_price', 0):.2f}")
                    self._update_positions()
                    self._schedule_balance_update()

            elif result.get('skipped'):
                # Smart delay decided to skip - log but not as error
                self._log(f"⏭️ Trade skipped: {result.get('reason')}")
            elif result.get('reason'):
                # Only log errors that have a reason (not silent skips)
                self._log(f"❌ Execution failed: {result.get('reason')}")
            # else: silent skip - don't log anything
        finally:
            self.execute_btn.setEnabled(True)
            self.execute_btn.setText("⚡ Execute Trade")

    def _schedule_balance_update(self):
        """Schedule a balance update in background"""
        QTimer.singleShot(500, self._update_balance_display)

    def _on_close_all(self):
        """Close all positions - uses background thread"""
        if not self.order_executor:
            self._log("❌ Cannot close: Order executor not initialized")
            return

        # Check if there are any positions to close
        positions = self.position_manager.get_all_positions()
        if not positions:
            self._log("ℹ️ No positions to close")
            QMessageBox.information(self, "No Positions", "There are no open positions to close.")
            return

        # Show what will be closed
        position_list = "\n".join([f"• {pair}: {pos['side'].upper()}" for pair, pos in positions.items()])

        reply = QMessageBox.question(self, "Confirm Close All",
            f"Close these {len(positions)} position(s)?\n\n{position_list}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            self._log(f"🔄 Closing {len(positions)} positions...")
            self.close_all_btn.setEnabled(False)
            self.close_all_btn.setText("Closing...")

            # Run in background thread
            _executor.submit(self._background_close_all)

    def _background_close_all(self):
        """Background thread for closing all positions"""
        try:
            result = self.order_executor.close_all_positions()

            # Emit result to main thread
            closed = result.get('closed_count', 0)
            if closed > 0:
                self.log_signal.emit(f"✅ Closed {closed} position(s)")
            else:
                self.log_signal.emit(f"⚠️ Failed to close positions")
                for r in result.get('results', []):
                    if not r.get('success'):
                        self.log_signal.emit(f"   ❌ {r.get('pair', 'Unknown')}: {r.get('reason', 'Unknown error')}")

            # Schedule UI updates in main thread
            QTimer.singleShot(0, self._update_positions)
            QTimer.singleShot(100, self._update_balance_display)

        except Exception as e:
            self.log_signal.emit(f"❌ Close all failed: {e}")
        finally:
            # Re-enable button in main thread
            QTimer.singleShot(0, lambda: self.close_all_btn.setEnabled(True))
            QTimer.singleShot(0, lambda: self.close_all_btn.setText("⚠️ Close All Positions"))

    def _on_force_close_positions(self):
        """Force close all tracked positions - sells on exchange AND clears tracking"""
        if not self.order_executor:
            self._log("❌ Cannot force close: Order executor not initialized")
            return

        if not self.connected_exchange:
            self._log("❌ Not connected to exchange")
            return

        # Get positions
        positions = self.position_manager.get_all_positions()
        if not positions:
            self._log("ℹ️ No positions to force close")
            QMessageBox.information(self, "No Positions", "There are no tracked positions to close.")
            return

        # Calculate estimated values and fees
        fee_rate = 0.001  # 0.1%
        total_value = 0
        position_details = []

        for pair, pos in positions.items():
            try:
                if pos.get('market') == 'futures':
                    position_details.append(f"• {pair}: FUTURES (skipped)")
                    continue

                current_price = self.exchange_client.get_current_price(pair)
                quantity = pos.get('quantity', 0)
                value = current_price * quantity
                total_value += value
                position_details.append(f"• {pair}: {quantity:.6f} @ ${current_price:.2f} = ${value:.2f}")
            except Exception as e:
                position_details.append(f"• {pair}: Error getting price")

        estimated_fees = total_value * fee_rate
        net_usdt = total_value - estimated_fees

        reply = QMessageBox.warning(self, "⚡ Force Close All Positions",
            f"This will SELL all {len(positions)} tracked position(s) on the exchange:\n\n"
            f"{chr(10).join(position_details)}\n\n"
            f"Total value: ~${total_value:.2f}\n"
            f"Estimated fees: ~${estimated_fees:.4f}\n"
            f"USDT after fees: ~${net_usdt:.2f}\n\n"
            "This action:\n"
            "✓ Sells assets on exchange (market order)\n"
            "✓ Removes positions from tracking\n"
            "✓ Stops SL/TP monitoring\n\n"
            "Are you SURE?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            self._log(f"⚡ Force closing {len(positions)} positions...")
            self.force_close_btn.setEnabled(False)
            self.force_close_btn.setText("Force Closing...")

            # Run in background thread
            _executor.submit(self._background_force_close)

    def _background_force_close(self):
        """Background thread for force closing all positions"""
        try:
            result = self.order_executor.force_liquidate_all_to_usdt(dry_run=False)

            if result.get('success'):
                closed = result.get('closed_count', 0)
                actual_usdt = result.get('actual_usdt_recovered', 0)
                actual_fees = result.get('actual_fees', 0)

                self.log_signal.emit(f"✅ Force closed {closed} position(s)")
                self.log_signal.emit(f"   💰 USDT recovered: ${actual_usdt:.2f}")
                self.log_signal.emit(f"   💸 Fees paid: ${actual_fees:.4f}")

                if result.get('errors'):
                    for err in result['errors']:
                        self.log_signal.emit(f"   ❌ {err['pair']}: {err['error']}")
            else:
                self.log_signal.emit(f"⚠️ Force close had issues: {result.get('message', 'Unknown')}")

            # Schedule UI updates in main thread
            QTimer.singleShot(0, self._update_positions)
            QTimer.singleShot(100, self._update_balance_display)
            QTimer.singleShot(500, self._refresh_portfolio)

        except Exception as e:
            self.log_signal.emit(f"❌ Force close failed: {e}")
        finally:
            # Re-enable button in main thread
            QTimer.singleShot(0, lambda: self.force_close_btn.setEnabled(True))
            QTimer.singleShot(0, lambda: self.force_close_btn.setText("⚡  Force Close All Positions"))

    def _on_clear_positions(self):
        """Clear all position records without placing orders (for stuck/phantom positions)"""
        positions = self.position_manager.get_all_positions()

        if not positions:
            self._log("ℹ️ No position records to clear")
            QMessageBox.information(self, "No Positions", "There are no position records to clear.")
            return

        position_list = "\n".join([f"• {pair}: {pos['side'].upper()}" for pair, pos in positions.items()])

        reply = QMessageBox.warning(self, "Clear Position Records",
            f"This will DELETE these {len(positions)} position record(s) WITHOUT placing any orders:\n\n"
            f"{position_list}\n\n"
            "Use this only if positions are stuck/phantom.\n"
            "Any open orders on the exchange will NOT be cancelled.\n\n"
            "Are you sure?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            # Stop monitoring all positions
            if self.sl_tp_monitor:
                for pair in list(positions.keys()):
                    self.sl_tp_monitor.stop_monitoring(pair)

            # Clear all positions from manager
            self.position_manager.positions.clear()
            self.position_manager._save_positions()

            self._log(f"🗑️ Cleared {len(positions)} position record(s)")
            self._update_positions()

    def _on_cancel_all_orders(self):
        """Cancel all open orders on the exchange"""
        if not self.connected_exchange:
            self._log("❌ Not connected to exchange")
            return

        try:
            open_orders = self.exchange_client.get_open_orders()

            if not open_orders:
                self._log("ℹ️ No open orders to cancel")
                QMessageBox.information(self, "No Orders", "There are no open orders on the exchange.")
                return

            # Show orders
            order_list = "\n".join([
                f"• {o.get('symbol', 'Unknown')}: {o.get('side', '?').upper()} {o.get('amount', 0):.6f} @ ${o.get('price', 0):,.2f}"
                for o in open_orders[:10]  # Show max 10
            ])
            if len(open_orders) > 10:
                order_list += f"\n... and {len(open_orders) - 10} more"

            reply = QMessageBox.warning(self, "Cancel All Orders",
                f"Cancel these {len(open_orders)} open order(s)?\n\n{order_list}\n\n"
                "This will free up any locked funds.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

            if reply == QMessageBox.StandardButton.Yes:
                self._log(f"🔄 Cancelling {len(open_orders)} orders...")

                cancelled = self.exchange_client.cancel_all_orders()

                self._log(f"✅ Cancelled {len(cancelled)} order(s)")
                self._refresh_portfolio()
                self._update_balance_display()

        except Exception as e:
            self._log(f"❌ Failed to cancel orders: {e}")
            QMessageBox.critical(self, "Error", f"Failed to cancel orders: {e}")

    def _on_fix_positions(self):
        """Fix positions with invalid SL/TP values"""
        positions = self.position_manager.get_all_positions()

        if not positions:
            self._log("ℹ️ No positions to fix")
            QMessageBox.information(self, "No Positions", "There are no positions to fix.")
            return

        # Show current positions with their SL/TP issues
        issues = []
        for pair, pos in positions.items():
            # Use THESIS entry and direction for validation (SL/TP are based on thesis)
            thesis = pos.get('thesis', pos.get('side', '')).lower()
            thesis_entry = pos.get('thesis_entry', pos.get('entry_price', 0))
            sl = pos.get('stop_loss', 0)
            tp = pos.get('take_profit', 0)

            if thesis_entry <= 0:
                issues.append(f"• {pair}: Invalid entry price (${thesis_entry:.4f})")
            elif thesis in ['long', 'buy']:
                if sl >= thesis_entry:
                    issues.append(f"• {pair} LONG: SL ${sl:.4f} >= Entry ${thesis_entry:.4f}")
                if tp <= thesis_entry:
                    issues.append(f"• {pair} LONG: TP ${tp:.4f} <= Entry ${thesis_entry:.4f}")
            elif thesis in ['short', 'sell']:
                if sl <= thesis_entry:
                    issues.append(f"• {pair} SHORT: SL ${sl:.4f} <= Entry ${thesis_entry:.4f}")
                if tp >= thesis_entry:
                    issues.append(f"• {pair} SHORT: TP ${tp:.4f} >= Entry ${thesis_entry:.4f}")

        if not issues:
            self._log("✅ All positions have valid SL/TP values")
            QMessageBox.information(self, "Positions OK",
                "All positions have valid SL/TP values. No fixes needed.")
            return

        issue_list = "\n".join(issues[:15])
        if len(issues) > 15:
            issue_list += f"\n... and {len(issues) - 15} more"

        reply = QMessageBox.question(self, "Fix Position SL/TP",
            f"Found {len(issues)} issue(s) with position SL/TP values:\n\n"
            f"{issue_list}\n\n"
            "Fix these issues automatically?\n"
            "(LONG: SL 2% below entry, TP 4% above entry)\n"
            "(SHORT: SL 2% above entry, TP 4% below entry)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            result = self.position_manager.fix_all_positions()
            self._log(f"🔧 Fixed positions: {result}")

            if result.get('removed', 0) > 0:
                self._log(f"   ⚠️ Removed {result['removed']} corrupted position(s) with invalid entry prices")

            self._update_positions()
            QMessageBox.information(self, "Positions Fixed",
                f"Fixed {len(issues)} issue(s).\n"
                f"Removed {result.get('removed', 0)} corrupted position(s).")

    def _on_convert_all_to_usdt(self):
        """Convert all crypto assets to USDT by selling them"""
        if not self.connected_exchange:
            self._log("❌ Not connected to exchange")
            return

        try:
            # Get all non-USDT balances
            balances = self.exchange_client.get_all_balances(min_value_usdt=1.0)

            if not balances:
                self._log("ℹ️ No assets to convert")
                QMessageBox.information(self, "No Assets", "No crypto assets found to convert.")
                return

            # Filter out USDT
            assets_to_sell = {k: v for k, v in balances.items() if k != 'USDT' and v.get('free', 0) > 0}

            if not assets_to_sell:
                self._log("ℹ️ No assets to convert (only USDT)")
                QMessageBox.information(self, "No Assets", "You only have USDT. Nothing to convert.")
                return

            # Show what will be sold
            asset_list = "\n".join([
                f"• {currency}: {data['free']:.6f} (~${data['usdt_value']:.2f})"
                for currency, data in assets_to_sell.items()
            ])
            total_value = sum(d['usdt_value'] for d in assets_to_sell.values())

            reply = QMessageBox.question(self, "Convert All to USDT",
                f"Sell these {len(assets_to_sell)} asset(s) for USDT?\n\n"
                f"{asset_list}\n\n"
                f"Total value: ~${total_value:.2f}\n\n"
                "Note: This uses market orders. There will be small trading fees (~0.1%).",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

            if reply == QMessageBox.StandardButton.Yes:
                self._log(f"🔄 Converting {len(assets_to_sell)} assets to USDT...")
                self.convert_all_btn.setEnabled(False)
                self.convert_all_btn.setText("Converting...")

                # Run in background thread
                _executor.submit(self._background_convert_all, assets_to_sell)

        except Exception as e:
            self._log(f"❌ Failed to get balances: {e}")
            QMessageBox.critical(self, "Error", f"Failed to get balances: {e}")

    def _background_convert_all(self, assets_to_sell: dict):
        """Background thread for converting all assets to USDT"""
        sold_count = 0
        total_usdt = 0
        positions_cleared = 0

        for currency, data in assets_to_sell.items():
            try:
                amount = data.get('free', 0)
                if amount <= 0:
                    continue

                pair = f"{currency}USDT"
                self.log_signal.emit(f"   💱 Selling {amount:.6f} {currency}...")

                order = self.exchange_client.place_market_order(pair, 'sell', amount)
                fill_price = float(order.get('average') or order.get('price') or 0)
                usdt_received = amount * fill_price

                self.log_signal.emit(f"   ✅ Sold {currency} @ ${fill_price:.4f} = ${usdt_received:.2f} USDT")
                sold_count += 1
                total_usdt += usdt_received

                # ALSO clear position tracking for this pair
                if self.position_manager.get_position(pair):
                    if self.sl_tp_monitor:
                        self.sl_tp_monitor.stop_monitoring(pair)
                    self.position_manager.remove_position(pair)
                    positions_cleared += 1
                    self.log_signal.emit(f"   🗑️ Cleared {pair} from tracking")

            except Exception as e:
                self.log_signal.emit(f"   ❌ Failed to sell {currency}: {e}")

        self.log_signal.emit(f"💵 Converted {sold_count} asset(s) -> ~${total_usdt:.2f} USDT")
        if positions_cleared > 0:
            self.log_signal.emit(f"🗑️ Cleared {positions_cleared} position(s) from tracking")

        # Update UI
        QTimer.singleShot(0, self._update_positions)
        QTimer.singleShot(500, self._refresh_portfolio)
        QTimer.singleShot(0, lambda: self.convert_all_btn.setEnabled(True))
        QTimer.singleShot(0, lambda: self.convert_all_btn.setText("💵  Convert All to USDT"))

    def _load_config(self) -> dict:
        """Load saved configuration from file"""
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, 'r') as f:
                    config = json.load(f)
                    logger.info("Loaded saved credentials")
                    return config
        except Exception as e:
            logger.warning(f"Could not load config: {e}")
        return {}

    def _save_config(self):
        """Save configuration to file"""
        try:
            config = {
                '_warning': 'API keys stored in plaintext. Keep this file secure!',
                'server': {
                    'username': self.username_input.text().strip(),
                },
                'exchange': {
                    'name': self.exchange_combo.currentText().lower(),
                    'api_key': self.exchange_api_key.text().strip(),
                    'api_secret': self.exchange_api_secret.text().strip(),
                    'testnet': self.testnet_check.isChecked()
                }
            }
            with open(CONFIG_FILE, 'w') as f:
                json.dump(config, f, indent=2)
            # Set restrictive file permissions (owner read/write only)
            try:
                import os
                os.chmod(CONFIG_FILE, 0o600)
            except (OSError, AttributeError):
                pass  # Windows doesn't support chmod the same way
            logger.info(f"Credentials saved to {CONFIG_FILE}")
        except Exception as e:
            logger.warning(f"Could not save config: {e}")

    def _apply_saved_credentials(self):
        """Apply saved credentials to input fields"""
        if not self._saved_config:
            return

        try:
            # Server credentials
            server = self._saved_config.get('server', {})
            if server.get('username'):
                self.username_input.setText(server['username'])

            # Exchange credentials
            exchange = self._saved_config.get('exchange', {})
            if exchange.get('name'):
                # Find matching exchange (handle leading spaces in combo items)
                saved_name = exchange['name'].lower().strip()
                for i in range(self.exchange_combo.count()):
                    item_name = self.exchange_combo.itemText(i).lower().strip()
                    if item_name == saved_name:
                        self.exchange_combo.setCurrentIndex(i)
                        break
            if exchange.get('api_key'):
                self.exchange_api_key.setText(exchange['api_key'])
            if exchange.get('api_secret'):
                self.exchange_api_secret.setText(exchange['api_secret'])
            if exchange.get('testnet'):
                self.testnet_check.setChecked(True)

            logger.info("Applied saved credentials to input fields")
        except Exception as e:
            logger.warning(f"Could not apply saved credentials: {e}")

    def _schedule_position_update(self):
        """Schedule position update in background thread"""
        if self._position_update_running or not self.connected_exchange:
            return
        self._position_update_running = True
        _executor.submit(self._background_position_update)

    def _background_position_update(self):
        """Run position update in background thread"""
        try:
            positions = self.position_manager.get_all_positions()
            if positions and self.connected_exchange:
                for pair in positions:
                    try:
                        price = self.exchange_client.get_current_price(pair)
                        if price:
                            self.position_manager.update_unrealized_pnl(pair, price)
                    except Exception as e:
                        logger.debug(f"Failed to update price for {pair}: {e}")
            # Update UI on main thread
            QTimer.singleShot(0, self._update_positions_display)
            # Sync portfolio to server (for smart signal filtering)
            QTimer.singleShot(100, self._sync_portfolio_to_server)
        except Exception as e:
            logger.debug(f"Position update error: {e}")
        finally:
            self._position_update_running = False

    def _update_positions_display(self):
        """Update positions display (called on main thread)"""
        try:
            positions = self.position_manager.get_all_positions()

            # Update stats dashboard
            self._update_stats_dashboard(positions)

            if not positions:
                self.positions_text.setPlainText("No active positions")
                return

            lines = []
            for pair, pos in positions.items():
                # Use THESIS direction (what you're betting on) for display
                # This matches SL/TP which are calculated for thesis
                thesis = pos.get('thesis', pos['side']).upper()
                holding = pos['side'].upper()
                thesis_entry = pos.get('thesis_entry', pos['entry_price'])
                flip_count = pos.get('flip_count', 0)

                emoji = "🟢" if thesis in ['LONG', 'BUY'] else "🔴"
                pnl_net = pos.get('unrealized_pnl_net', 0)
                pnl_pct = pos.get('unrealized_pnl_pct_net', 0)
                current = pos.get('current_price', thesis_entry)

                # Show thesis direction and flip indicator
                flip_indicator = f" (↔{flip_count})" if flip_count > 0 else ""
                lines.append(f"{emoji} {pair} {thesis}{flip_indicator}")
                lines.append(f"   Entry: ${thesis_entry:,.2f} | Now: ${current:,.2f}")
                lines.append(f"   SL: ${pos.get('stop_loss', 0):,.2f} | TP: ${pos.get('take_profit', 0):,.2f}")
                pnl_emoji = "📈" if pnl_net >= 0 else "📉"
                lines.append(f"   {pnl_emoji} P&L: ${pnl_net:,.2f} ({pnl_pct:+.2f}%)")
                lines.append("─" * 30)

            self.positions_text.setPlainText("\n".join(lines))
        except Exception as e:
            logger.debug(f"Display update error: {e}")

    def _update_stats_dashboard(self, positions: dict = None):
        """Update the performance stats dashboard"""
        try:
            # Get positions if not provided
            if positions is None:
                positions = self.position_manager.get_all_positions()

            # Count active positions
            active_count = len(positions) if positions else 0
            self.active_positions_value.setText(str(active_count))

            # Calculate total unrealized P&L from active positions
            total_pnl = 0.0
            if positions:
                for pos in positions.values():
                    total_pnl += pos.get('unrealized_pnl_net', 0)

            # Update P&L display with color
            if total_pnl >= 0:
                self.total_pnl_value.setText(f"+${total_pnl:,.2f}")
                self.total_pnl_value.setObjectName("statValueProfit")
            else:
                self.total_pnl_value.setText(f"-${abs(total_pnl):,.2f}")
                self.total_pnl_value.setObjectName("statValueLoss")
            self.total_pnl_value.setStyleSheet("")  # Force style refresh

            # Get trade history for win rate
            trade_history = self.position_manager.trade_history
            if trade_history and len(trade_history) >= 3:
                wins = sum(1 for t in trade_history if t.get('realized_pnl', t.get('unrealized_pnl', 0)) > 0)
                total_trades = len(trade_history)
                win_rate = (wins / total_trades) * 100 if total_trades > 0 else 0
                self.win_rate_value.setText(f"{win_rate:.0f}%")

                # Color code win rate
                if win_rate >= 50:
                    self.win_rate_value.setObjectName("statValueProfit")
                else:
                    self.win_rate_value.setObjectName("statValueLoss")
                self.win_rate_value.setStyleSheet("")  # Force style refresh
            else:
                self.win_rate_value.setText("--")
                self.win_rate_value.setObjectName("statValue")

            # Count trades today
            from datetime import datetime, timedelta
            today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            trades_today = 0
            if trade_history:
                for t in trade_history:
                    trade_time = t.get('timestamp', t.get('entry_timestamp'))
                    if trade_time:
                        if isinstance(trade_time, str):
                            try:
                                trade_dt = datetime.fromisoformat(trade_time.replace('Z', '+00:00'))
                            except (ValueError, TypeError):
                                # Failed to parse timestamp, skip this trade
                                continue
                        elif isinstance(trade_time, (int, float)):
                            trade_dt = datetime.fromtimestamp(trade_time)
                        else:
                            trade_dt = trade_time

                        if trade_dt >= today_start:
                            trades_today += 1

            self.trades_today_value.setText(str(trades_today))

        except Exception as e:
            logger.debug(f"Stats dashboard update error: {e}")

    def _schedule_sl_tp_check(self):
        """Schedule SL/TP check in background thread"""
        if self._sl_tp_check_running or not self.connected_exchange or not self.sl_tp_monitor:
            return
        positions = self.position_manager.get_all_positions()
        if not positions:
            return
        self._sl_tp_check_running = True
        _executor.submit(self._background_sl_tp_check)

    def _background_sl_tp_check(self):
        """Run SL/TP check in background thread"""
        try:
            exits = self.sl_tp_monitor.check_all_positions()
            for exit_info in exits:
                try:
                    result = self.sl_tp_monitor.execute_exit(exit_info)
                    if result.get('success'):
                        # Log on main thread
                        msg = f"Position {exit_info['pair']} closed: {exit_info['reason'].value}"
                        QTimer.singleShot(0, lambda m=msg: self._log(m))
                except Exception as e:
                    logger.warning(f"Exit execution failed: {e}")
        except Exception as e:
            logger.debug(f"SL/TP check error: {e}")
        finally:
            self._sl_tp_check_running = False

    def _schedule_balance_update(self):
        """Schedule balance update in background thread"""
        if self._balance_update_running or not self.connected_exchange:
            return
        self._balance_update_running = True
        _executor.submit(self._background_balance_update)

    def _background_balance_update(self):
        """Run balance update in background thread"""
        try:
            balances = self.exchange_client.get_all_balances(min_value_usdt=0.5)
            total = sum(b['usdt_value'] for b in balances.values())
            self._total_balance = total
            # Update UI on main thread
            QTimer.singleShot(0, lambda: self.balance_label.setText(f"${total:,.2f}"))
        except Exception as e:
            logger.debug(f"Balance update error: {e}")
        finally:
            self._balance_update_running = False

    def _get_cached_price(self, pair: str) -> float:
        """Get price with caching to reduce API calls"""
        import time
        now = time.time()

        # Return cached price if fresh
        if pair in self._price_cache:
            if now - self._price_cache_time.get(pair, 0) < self._cache_ttl:
                return self._price_cache[pair]

        # Fetch new price
        try:
            price = self.exchange_client.get_current_price(pair)
            self._price_cache[pair] = price
            self._price_cache_time[pair] = now
            return price
        except Exception as e:
            logger.warning(f"Failed to get price for {pair}: {e}")
            return self._price_cache.get(pair, 0)

    def _update_balance_display(self):
        """Update the balance display with total portfolio value"""
        if not self.connected_exchange:
            return

        try:
            # Get all balances
            balances = self.exchange_client.get_all_balances(min_value_usdt=0.5)
            total = sum(b['usdt_value'] for b in balances.values())
            self._total_balance = total

            # Update the main balance display
            self.balance_label.setText(f"${total:,.2f} USDT")

            # Update portfolio text
            self._refresh_portfolio()

        except Exception as e:
            logger.warning(f"Balance update failed: {e}")

    def _check_sl_tp_safe(self):
        """Safe wrapper for SL/TP check - won't freeze UI"""
        if not self.sl_tp_monitor or not self.connected_exchange:
            return

        try:
            # Only check positions that exist (no unnecessary API calls)
            positions = self.position_manager.get_all_positions()
            if not positions:
                return

            # Check positions using cached prices where possible
            exits = []
            for pair in positions:
                try:
                    result = self.sl_tp_monitor.check_position(pair)
                    if result:
                        exits.append(result)
                except Exception as e:
                    logger.debug(f"SL/TP check skipped for {pair}: {e}")
                    continue

            # Execute exits
            for exit_info in exits:
                try:
                    result = self.sl_tp_monitor.execute_exit(exit_info)
                    if result.get('success'):
                        reason = exit_info['reason']
                        emoji = "🛑" if reason == ExitReason.STOP_LOSS else "🎯" if reason == ExitReason.TAKE_PROFIT else "📈"
                        self._log(f"{emoji} {exit_info['pair']} closed by {reason.value}: P&L ${result.get('pnl', 0):.2f}")
                except Exception as e:
                    logger.warning(f"Exit execution failed: {e}")

        except Exception as e:
            logger.debug(f"SL/TP check error: {e}")

    def _update_positions_safe(self):
        """Safe wrapper for position update - won't freeze UI"""
        try:
            self._update_positions()
        except Exception as e:
            logger.warning(f"Position update error: {e}")

    def _can_execute_trade(self, signal: dict) -> tuple:
        """
        Pre-check if trade can be executed before trying.
        Returns (can_execute: bool, reason: str)
        None reason = silent skip (don't log noise for duplicate signals)
        """
        # EMERGENCY CHECK: Is trading halted?
        if self._trading_halted:
            return False, f"Trading HALTED: {self._halt_reason}"

        if not self.connected_exchange:
            return False, "Exchange not connected"

        pair = signal.get('pair', '').upper()
        side = signal.get('side', '').lower()

        try:
            # CHECK 0: Stop-loss cooldown - prevent re-entering after recent SL
            if pair in self._sl_cooldown:
                elapsed = time.time() - self._sl_cooldown[pair]
                remaining = self._sl_cooldown_seconds - elapsed
                if remaining > 0:
                    mins_remaining = int(remaining // 60)
                    secs_remaining = int(remaining % 60)
                    return False, f"Cooldown: {pair} stopped out recently ({mins_remaining}m {secs_remaining}s left)"
                else:
                    # Cooldown expired, remove from tracking
                    del self._sl_cooldown[pair]

            # CHECK 1: Do we already have a position for this pair?
            existing_position = self.position_manager.get_position(pair)
            if existing_position:
                current_thesis = existing_position.get('thesis', existing_position.get('side', '')).lower()

                # Same direction thesis = skip silently (already tracking this direction)
                if side in ['long', 'buy'] and current_thesis in ['long', 'buy']:
                    return False, None  # Silent skip
                if side in ['short', 'sell'] and current_thesis in ['short', 'sell']:
                    return False, None  # Silent skip

                # Opposite direction = FLIP thesis (no fee!)
                if (side in ['short', 'sell'] and current_thesis in ['long', 'buy']) or \
                   (side in ['long', 'buy'] and current_thesis in ['short', 'sell']):
                    return True, f"OK: Will flip {pair} to {side.upper()} (no fee)"

            # CHECK 2: Balance checks for NEW positions
            if side in ['long', 'buy']:
                usdt = self.exchange_client.get_balance('USDT')
                if usdt < 12.0:  # Need at least $12 (min notional + buffer)
                    # Suppress repeated "insufficient balance" logs for same pair
                    current_time = time.time()
                    last_logged = self._insufficient_balance_logged.get(pair, 0)
                    if current_time - last_logged > self._insufficient_log_cooldown:
                        self._insufficient_balance_logged[pair] = current_time
                        return False, f"Insufficient USDT: ${usdt:.2f} (need $12+)"
                    return False, None  # Silent skip
                # Clear from insufficient tracking if we can now execute
                self._insufficient_balance_logged.pop(pair, None)
                return True, f"OK: ${usdt:.2f} USDT available"

            elif side in ['short', 'sell']:
                # CHECK FUTURES FIRST - if enabled, use futures for SHORT
                if self.exchange_client.futures_enabled and self.exchange_client.futures_connected:
                    futures_balance = self.exchange_client.get_futures_balance()
                    # Futures has lower minimum (~$5-6) than spot
                    if futures_balance >= 6.0:
                        self._insufficient_balance_logged.pop(pair, None)
                        return True, f"OK: ${futures_balance:.2f} USDT (futures)"
                    else:
                        # Suppress repeated insufficient balance logs
                        current_time = time.time()
                        last_logged = self._insufficient_balance_logged.get(pair, 0)
                        if current_time - last_logged > self._insufficient_log_cooldown:
                            self._insufficient_balance_logged[pair] = current_time
                            return False, f"Insufficient futures balance: ${futures_balance:.2f} (need $6+)"
                        return False, None  # Silent skip

                # SPOT FALLBACK - Need the asset to short on spot
                asset_info = self.exchange_client.has_asset_balance(pair, min_value_usdt=12.0)
                if not asset_info.get('has_balance'):
                    # Track skipped SHORT signals and periodically log summary
                    self._short_skip_count += 1
                    current_time = time.time()
                    # Log every 60 seconds if signals are being skipped
                    if current_time - self._last_short_skip_log > 60 and self._short_skip_count > 0:
                        self._log(f"ℹ️ {self._short_skip_count} SHORT signals skipped (spot: need to own asset to sell)")
                        self._short_skip_count = 0
                        self._last_short_skip_log = current_time
                    return False, None  # Silent skip - no asset to short
                return True, f"OK: {asset_info['amount']:.4f} {asset_info['currency']} available"

            return False, f"Unknown side: {side}"

        except Exception as e:
            return False, f"Check failed: {e}"

    def _on_auto_trade_changed(self, state):
        """Handle auto-trade toggle"""
        self.auto_trade = state == Qt.CheckState.Checked.value
        status = "enabled" if self.auto_trade else "disabled"
        self._log(f"🤖 Auto-trading {status}")

        if self.auto_trade:
            # Reset SHORT skip counter on enable
            self._short_skip_count = 0
            self._last_short_skip_log = time.time()

            QMessageBox.information(self, "Auto-Trade Enabled",
                "Auto-trading is now ENABLED.\n\n"
                "The bot will automatically execute valid signals.\n\n"
                "SPOT TRADING NOTE:\n"
                "• LONG signals: Buys crypto with your USDT\n"
                "• SHORT signals: Sells crypto you already own\n"
                "• SHORT signals will be skipped if you don't own the asset\n\n"
                "Make sure:\n"
                "• Exchange is connected\n"
                "• You have USDT for LONG signals\n"
                "• Risk settings are configured")

    def _on_futures_changed(self, state):
        """Handle futures trading toggle"""
        enabled = state == Qt.CheckState.Checked.value

        if enabled:
            # Check if exchange supports futures
            if not self.connected_exchange:
                QMessageBox.warning(self, "Not Connected",
                    "Please connect to exchange first before enabling futures.")
                self.futures_check.setChecked(False)
                return

            if self.exchange_client.exchange_name not in ['binance', 'bybit']:
                QMessageBox.warning(self, "Futures Not Supported",
                    f"Futures trading is only supported on Binance and Bybit.\n"
                    f"Currently connected to: {self.exchange_client.exchange_name.upper()}")
                self.futures_check.setChecked(False)
                return

            # Connect to futures if not already
            if not self.exchange_client.futures_connected:
                self._log("📉 Connecting to futures exchange...")
                api_key = self.exchange_api_key.text().strip()
                api_secret = self.exchange_api_secret.text().strip()
                testnet = self.testnet_check.isChecked()

                if self.exchange_client.connect_futures(api_key, api_secret, testnet):
                    self._log("✅ Connected to futures (1x leverage, isolated margin)")
                else:
                    QMessageBox.critical(self, "Futures Connection Failed",
                        "Failed to connect to futures exchange.\n"
                        "Make sure your API key has futures trading permission.")
                    self.futures_check.setChecked(False)
                    return

            # Enable futures
            self.exchange_client.enable_futures(True)

            # Show confirmation with safety info
            futures_balance = self.exchange_client.get_futures_balance()
            QMessageBox.information(self, "Futures Enabled",
                f"Futures trading is now ENABLED.\n\n"
                f"📉 SHORT signals will now execute on futures\n"
                f"📈 LONG signals still use spot trading\n\n"
                f"⚙️ Safety Settings:\n"
                f"• Leverage: 1x (no liquidation risk)\n"
                f"• Margin: Isolated (only position at risk)\n\n"
                f"💰 Futures Balance: ${futures_balance:,.2f} USDT")

            self._log(f"📉 Futures trading ENABLED (balance: ${futures_balance:,.2f})")

        else:
            # Disable futures
            if self.exchange_client.futures_connected:
                self.exchange_client.enable_futures(False)
            self._log("📉 Futures trading DISABLED (using spot only)")

    def _check_sl_tp(self):
        """Check SL/TP conditions for all positions (called every 2 seconds)"""
        if not self.sl_tp_monitor or not self.connected_exchange:
            return

        try:
            # Check all positions for exit conditions
            exits = self.sl_tp_monitor.check_all_positions()

            # Execute any triggered exits
            for exit_info in exits:
                result = self.sl_tp_monitor.execute_exit(exit_info)
                if result['success']:
                    reason = exit_info['reason']
                    emoji = "🛑" if reason == ExitReason.STOP_LOSS else "🎯" if reason == ExitReason.TAKE_PROFIT else "📈"
                    self._log(f"{emoji} {exit_info['pair']} closed by {reason.value}: "
                             f"P&L ${result.get('pnl', 0):.2f}")
                    self._update_positions()
                    self._refresh_portfolio()

        except Exception as e:
            logger.warning(f"SL/TP check error: {e}")

    def _on_sl_tp_exit(self, pair: str, reason: ExitReason, details: dict):
        """Callback when SL/TP monitor triggers an exit - THREAD SAFE"""
        pnl = details.get('pnl', 0)
        fill_price = details.get('fill_price', 0)

        # Use thread-safe signal for logging (callback may be from background thread)
        if reason == ExitReason.STOP_LOSS:
            self.log_signal.emit(f"🛑 STOP LOSS: {pair} closed @ ${fill_price:.2f}, P&L: ${pnl:.2f}")
            # Record cooldown to prevent re-entering same losing trade (BOTH layers)
            self._sl_cooldown[pair] = time.time()
            if self.order_executor:
                self.order_executor.record_stopout(pair)  # Also record in executor
            cooldown_mins = self._sl_cooldown_seconds // 60
            self.log_signal.emit(f"⏳ {pair} on {cooldown_mins}min cooldown (will skip signals)")

            # EMERGENCY STOP: Track consecutive losses
            self._consecutive_losses += 1
            if self._consecutive_losses >= self._max_consecutive_losses:
                self._trading_halted = True
                self._halt_reason = f"{self._consecutive_losses} consecutive stop losses"
                self.log_signal.emit(f"🚨 TRADING HALTED: {self._halt_reason}")
                self.log_signal.emit(f"🚨 Signal prices may not match your exchange. Please verify prices manually.")
                self.log_signal.emit(f"🚨 Use 'Resume Trading' button to continue after investigating.")

        elif reason == ExitReason.TAKE_PROFIT:
            self.log_signal.emit(f"🎯 TAKE PROFIT: {pair} closed @ ${fill_price:.2f}, P&L: ${pnl:.2f}")
            # Reset consecutive losses on profitable trade
            self._consecutive_losses = 0

        elif reason == ExitReason.TRAILING_STOP:
            self.log_signal.emit(f"📈 TRAILING STOP: {pair} locked profit @ ${fill_price:.2f}, P&L: ${pnl:.2f}")
            # Trailing stop usually locks profit - reset losses
            if pnl >= 0:
                self._consecutive_losses = 0

        elif reason == ExitReason.BREAKEVEN_STOP:
            self.log_signal.emit(f"⚖️ BREAKEVEN: {pair} closed @ ${fill_price:.2f}, P&L: ${pnl:.2f}")
            # Breakeven is not a loss - reset
            self._consecutive_losses = 0

        # Schedule UI updates on main thread
        QTimer.singleShot(0, self._update_positions)
        QTimer.singleShot(100, self._refresh_portfolio)

    def _on_sl_updated(self, pair: str, new_sl: float, reason: str):
        """Callback when trailing stop updates the SL - THREAD SAFE"""
        # Use thread-safe signal for logging (callback may be from background thread)
        if reason == "breakeven":
            self.log_signal.emit(f"⚖️ {pair} SL moved to breakeven: ${new_sl:.2f}")
        elif reason == "trailing":
            self.log_signal.emit(f"📈 {pair} trailing SL updated: ${new_sl:.2f}")
        # Schedule UI update on main thread
        QTimer.singleShot(0, self._update_positions)

    def resume_trading(self):
        """Resume trading after emergency halt"""
        if self._trading_halted:
            self._trading_halted = False
            self._consecutive_losses = 0
            self._halt_reason = ""
            self._log("✅ Trading RESUMED - consecutive loss counter reset")
            self._log("⚠️ Please verify signal prices match your exchange before trading!")
        else:
            self._log("Trading is not halted")

    def _update_positions(self):
        """Update positions display"""
        positions = self.position_manager.get_all_positions()
        logger.debug(f"_update_positions: Got {len(positions)} positions from manager")

        if not positions:
            self.positions_text.setPlainText("No active positions")
            return

        lines = []
        for pair, pos in list(positions.items()):  # Use list() to avoid dict mutation issues
            # Validate position data
            if not pos or not isinstance(pos, dict):
                logger.warning(f"Invalid position data for {pair}: {pos}")
                continue

            # Fetch current price and update P&L
            if self.connected_exchange:
                try:
                    current_price = self.exchange_client.get_current_price(pair)
                    if current_price:
                        self.position_manager.update_unrealized_pnl(pair, current_price)
                        pos = self.position_manager.get_position(pair)
                        if not pos:  # Position was removed during update
                            continue
                except Exception as e:
                    logger.warning(f"Failed to get price for {pair}: {e}")

            # Validate required fields
            if not pos.get('side') or not pos.get('entry_price') or not pos.get('quantity'):
                logger.warning(f"Position {pair} missing required fields: side={pos.get('side')}, entry={pos.get('entry_price')}, qty={pos.get('quantity')}")
                continue

            # Use THESIS direction (what you're betting on) for display
            thesis = pos.get('thesis', pos['side']).upper()
            holding = pos['side'].upper()
            thesis_entry = pos.get('thesis_entry', pos['entry_price'])
            flip_count = pos.get('flip_count', 0)

            emoji = "🟢" if thesis in ['LONG', 'BUY'] else "🔴"
            pnl_gross = pos.get('unrealized_pnl', 0) or 0
            pnl_net = pos.get('unrealized_pnl_net', pnl_gross) or 0
            pnl_pct_net = pos.get('unrealized_pnl_pct_net', pos.get('unrealized_pnl_pct', 0)) or 0
            fees = pos.get('estimated_fees', 0) or 0
            pnl_emoji = "📈" if pnl_net >= 0 else "📉"
            current = pos.get('current_price') or thesis_entry

            # Show thesis direction with flip indicator
            flip_indicator = f" (↔{flip_count})" if flip_count > 0 else ""
            lines.append(f"{emoji} {pair} {thesis}{flip_indicator}")
            lines.append(f"   Qty: {pos['quantity']:.6f}")
            lines.append(f"   Entry: ${thesis_entry:,.2f}")
            lines.append(f"   Current: ${current:,.2f}")
            lines.append(f"   SL: ${pos.get('stop_loss', 0):,.2f}")
            lines.append(f"   TP: ${pos.get('take_profit', 0):,.2f}")
            lines.append(f"   {pnl_emoji} Net P&L: ${pnl_net:,.2f} ({pnl_pct_net:+.2f}%)")
            if fees > 0:
                lines.append(f"   💸 Fees: ${fees:,.4f}")

            # Show trailing stop status
            if self.sl_tp_monitor:
                status = self.sl_tp_monitor.get_monitoring_status(pair)
                if status.get('monitoring'):
                    trail_info = []
                    if status.get('breakeven_activated'):
                        trail_info.append("⚖️ BE")
                    if status.get('trailing_active'):
                        trail_info.append("📈 Trail")
                    if status.get('tp_order_on_exchange'):
                        trail_info.append("🎯 TP:Exch")
                    if trail_info:
                        lines.append(f"   Status: {' | '.join(trail_info)}")
                    if status.get('peak_price'):
                        lines.append(f"   Peak: ${status['peak_price']:,.2f}")

            lines.append("─" * 35)

        self.positions_text.setPlainText("\n".join(lines))

    def _sync_positions_from_exchange(self) -> int:
        """
        Sync positions from exchange - CLEAR local cache and create fresh positions.
        This is the source of truth - exchange holdings, not local JSON.

        Returns: Number of positions synced
        """
        if not self.connected_exchange or not self.exchange_client:
            return 0

        try:
            exchange_name = self.exchange_client.exchange_name

            # STEP 1: Clear ALL local positions (fresh start)
            old_count = self.position_manager.clear_all_positions()
            if old_count > 0:
                self._log(f"🗑️ Cleared {old_count} stale position(s) from cache")

            synced_count = 0

            # STEP 2: Get SPOT holdings from exchange
            self._log("📡 Fetching SPOT balances...")
            try:
                balances = self.exchange_client.get_all_balances(min_value_usdt=5.0)
                self._log(f"   Found {len(balances)} asset(s) with value > $5")
                logger.info(f"SPOT balances: {balances}")
            except Exception as e:
                self._log(f"   ⚠️ Failed to fetch SPOT balances: {e}")
                balances = {}

            # STEP 3: Create LONG positions for each SPOT holding (except stablecoins)
            if balances:
                for currency, info in balances.items():
                    if currency in ['USDT', 'BUSD', 'USDC', 'TUSD', 'FDUSD', 'DAI']:
                        continue  # Skip stablecoins

                    pair = f"{currency}USDT"
                    amount = info.get('amount', 0)
                    usdt_value = info.get('usdt_value', 0)
                    current_price = info.get('price', 0)

                    if amount <= 0 or current_price <= 0:
                        continue

                    # Create LONG position with current price as entry
                    stop_loss = current_price * 0.98      # 2% below
                    take_profit = current_price * 1.04    # 4% above

                    self.position_manager.add_position(
                        pair=pair,
                        side='long',
                        entry_price=current_price,
                        quantity=amount,
                        stop_loss=stop_loss,
                        take_profit=take_profit,
                        order_id=None,
                        exchange=exchange_name,
                        market='spot'
                    )

                    # Start monitoring for spot
                    if self.sl_tp_monitor:
                        self.sl_tp_monitor.start_monitoring(pair)

                    synced_count += 1
                    self._log(f"📊 [SPOT] {pair}: {amount:.6f} @ ${current_price:.2f} (${usdt_value:.2f})")

            # STEP 4: Get FUTURES positions - try to sync even if not explicitly enabled
            # User may have existing futures positions that need to be tracked
            self._log(f"   Futures enabled: {self.exchange_client.futures_enabled}, connected: {self.exchange_client.futures_connected}")

            # Try to connect to futures if not already connected (for Binance/Bybit)
            futures_synced = False
            if exchange_name in ['binance', 'bybit']:
                if not self.exchange_client.futures_connected:
                    self._log("📡 Attempting to connect to futures for position sync...")
                    try:
                        # Get saved credentials
                        api_key = self.exchange_api_key.text().strip()
                        api_secret = self.exchange_api_secret.text().strip()
                        testnet = self.testnet_check.isChecked()

                        if self.exchange_client.connect_futures(api_key, api_secret, testnet):
                            self._log("   ✅ Futures connection established for sync")
                            futures_synced = True
                        else:
                            self._log("   ⚠️ Could not connect to futures")
                    except Exception as e:
                        self._log(f"   ⚠️ Futures connection failed: {e}")
                else:
                    futures_synced = True

            if futures_synced or self.exchange_client.futures_connected:
                self._log("📡 Fetching FUTURES positions...")
                try:
                    # First, cancel all existing SL/TP orders to avoid duplicates
                    self._log("   Cancelling existing futures orders...")
                    cancelled = self.exchange_client.cancel_all_futures_orders()
                    if cancelled:
                        self._log(f"   Cancelled {len(cancelled)} existing order(s)")

                    futures_positions = self.exchange_client.get_futures_positions()
                    self._log(f"   Found {len(futures_positions)} futures position(s)")
                    logger.info(f"Raw futures positions: {futures_positions}")

                    # Log first position details for debugging
                    if futures_positions:
                        first_pos = futures_positions[0]
                        logger.info(f"First futures position keys: {first_pos.keys()}")
                        logger.info(f"First futures position: symbol={first_pos.get('symbol')}, "
                                   f"side={first_pos.get('side')}, contracts={first_pos.get('contracts')}, "
                                   f"entryPrice={first_pos.get('entryPrice')}")

                    if futures_positions:
                        for pos in futures_positions:
                            # CCXT returns different formats, handle both
                            symbol = pos.get('symbol', '')
                            pair = symbol.replace('/', '') if '/' in symbol else symbol

                            # Skip if not USDT pair
                            if not pair.endswith('USDT'):
                                continue

                            # Get position side
                            pos_side = pos.get('side', '')
                            contracts = float(pos.get('contracts', 0) or 0)

                            # Determine side from contracts if side not explicit
                            if not pos_side:
                                pos_side = 'long' if contracts > 0 else 'short'
                            pos_side = pos_side.lower()

                            amount = abs(contracts)
                            entry_price = float(pos.get('entryPrice', 0) or pos.get('info', {}).get('entryPrice', 0))
                            mark_price = float(pos.get('markPrice', 0) or pos.get('info', {}).get('markPrice', 0))

                            if amount <= 0 or entry_price <= 0:
                                logger.warning(f"Skipping futures position {pair}: amount={amount}, entry={entry_price}")
                                continue

                            current_price = mark_price if mark_price > 0 else entry_price

                            # Calculate SL/TP based on side
                            if pos_side in ['long', 'buy']:
                                stop_loss = entry_price * 0.98      # 2% below for LONG
                                take_profit = entry_price * 1.04    # 4% above for LONG
                                sl_order_side = 'sell'  # Sell to close LONG
                                tp_order_side = 'sell'
                            else:
                                stop_loss = entry_price * 1.02      # 2% above for SHORT
                                take_profit = entry_price * 0.96    # 4% below for SHORT
                                sl_order_side = 'buy'   # Buy to close SHORT
                                tp_order_side = 'buy'

                            # Add position to tracker
                            self.position_manager.add_position(
                                pair=pair,
                                side=pos_side,
                                entry_price=entry_price,
                                quantity=amount,
                                stop_loss=stop_loss,
                                take_profit=take_profit,
                                order_id=None,
                                exchange=exchange_name,
                                market='futures'
                            )

                            synced_count += 1
                            self._log(f"📊 [FUTURES] {pair} {pos_side.upper()}: {amount:.6f} @ ${entry_price:.2f}")

                            # STEP 5: Place SL/TP orders on futures exchange
                            sl_order_id = None
                            tp_order_id = None

                            try:
                                sl_order = self.exchange_client.set_futures_stop_loss(
                                    pair, sl_order_side, stop_loss, amount
                                )
                                sl_order_id = sl_order.get('id')
                                self._log(f"   ✅ SL order placed: {sl_order_side} @ ${stop_loss:.4f}")
                            except Exception as e:
                                self._log(f"   ⚠️ Failed to place SL order: {e}")
                                logger.warning(f"Futures SL order failed for {pair}: {e}")

                            try:
                                tp_order = self.exchange_client.set_futures_take_profit(
                                    pair, tp_order_side, take_profit, amount
                                )
                                tp_order_id = tp_order.get('id')
                                self._log(f"   ✅ TP order placed: {tp_order_side} @ ${take_profit:.4f}")
                            except Exception as e:
                                self._log(f"   ⚠️ Failed to place TP order: {e}")
                                logger.warning(f"Futures TP order failed for {pair}: {e}")

                            # Start monitoring (as backup to exchange orders)
                            if self.sl_tp_monitor:
                                self.sl_tp_monitor.start_monitoring(pair, tp_order_id)

                except Exception as e:
                    logger.error(f"Failed to sync futures positions: {e}")
                    self._log(f"⚠️ Futures sync failed: {e}")

            if synced_count > 0:
                self._log(f"✅ Synced {synced_count} position(s) from {exchange_name.upper()}")
            else:
                self._log("📊 No significant holdings found on exchange")

            # Update the positions display
            self._update_positions()

            return synced_count

        except Exception as e:
            logger.error(f"Failed to sync positions from exchange: {e}")
            self._log(f"⚠️ Position sync failed: {e}")
            return 0

    def _on_resync_positions(self):
        """Manual re-sync positions from exchange"""
        if not self.connected_exchange:
            QMessageBox.warning(self, "Not Connected",
                "Please connect to an exchange first.")
            return

        reply = QMessageBox.question(self, "Re-sync Positions",
            "This will:\n"
            "• Clear all locally tracked positions\n"
            "• Fetch current holdings from exchange\n"
            "• Create fresh positions with current prices\n\n"
            "SL/TP will be reset to defaults (2% SL, 4% TP).\n\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            synced = self._sync_positions_from_exchange()
            self._update_positions()
            QMessageBox.information(self, "Sync Complete",
                f"Synced {synced} position(s) from exchange.")

    def _on_import_orphan_positions(self):
        """Import untracked spot holdings as positions"""
        if not self.connected_exchange:
            QMessageBox.warning(self, "Not Connected",
                "Please connect to an exchange first.")
            return

        reply = QMessageBox.question(self, "Import Lost Positions",
            "This will scan your exchange for spot holdings\n"
            "that aren't being tracked by the bot.\n\n"
            "For each untracked asset:\n"
            "• Use current price as entry (actual entry unknown)\n"
            "• Set 5% Stop Loss below entry\n"
            "• Set 10% Take Profit above entry\n\n"
            "This helps recover positions the bot lost track of.\n\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            self._log("📥 Importing lost positions from exchange...")

            try:
                result = self.position_manager.import_orphaned_positions(
                    exchange_client=self.exchange_client,
                    min_value_usdt=1.0,  # Import even small positions ($1+)
                    default_sl_pct=5.0,   # 5% stop loss
                    default_tp_pct=10.0   # 10% take profit
                )

                imported_count = result.get('imported_count', 0)
                total_value = result.get('total_imported_value', 0)

                if imported_count > 0:
                    # Start monitoring the new positions
                    for pos_info in result.get('imported', []):
                        pair = pos_info['pair']
                        self.sl_tp_monitor.start_monitoring(pair)
                        self._log(f"📥 Imported: {pair} ${pos_info['usdt_value']:.2f}")

                    self._update_positions()
                    QMessageBox.information(self, "Import Complete",
                        f"Imported {imported_count} position(s)\n"
                        f"Total value: ${total_value:.2f}\n\n"
                        f"These positions are now being monitored with:\n"
                        f"• Stop Loss: 5% below current price\n"
                        f"• Take Profit: 10% above current price")
                else:
                    skipped = result.get('skipped_count', 0)
                    QMessageBox.information(self, "No Positions to Import",
                        f"No untracked positions found.\n\n"
                        f"Already tracked: {skipped} position(s)")

            except Exception as e:
                logger.error(f"Failed to import orphan positions: {e}")
                QMessageBox.warning(self, "Import Failed", f"Error: {e}")

    def _sync_portfolio_to_server(self):
        """Sync current portfolio state to server for smart signal filtering"""
        try:
            if not self.ws_client or not self.ws_client.connected:
                return

            # Get current positions
            positions = self.position_manager.get_all_positions()

            # Get balance if connected to exchange
            balance = 0
            if self.connected_exchange and self.exchange_client:
                try:
                    balance = self.exchange_client.get_balance('USDT')
                except Exception:
                    pass  # Balance fetch failed, use 0

            # Send to server
            self.ws_client.update_portfolio(positions, balance)
            logger.debug(f"Synced portfolio: {len(positions)} positions, ${balance:.2f}")

        except Exception as e:
            logger.error(f"Failed to sync portfolio: {e}")

    def _update_status(self):
        """Update status bar"""
        parts = []

        if self.connected_server:
            parts.append("🌐 Server: ✅")
        else:
            parts.append("🌐 Server: ❌")

        if self.connected_exchange:
            parts.append(f"💱 {self.exchange_client.exchange_name.upper()}: ✅")
        else:
            parts.append("💱 Exchange: ❌")

        parts.append(f"📂 Positions: {self.position_manager.get_position_count()}")

        if self.auto_trade:
            parts.append("🤖 Auto: ON")

        self.status_bar.showMessage("  │  ".join(parts))

    def _log(self, message: str):
        """Add log message"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"<span style='color:#606080'>[{timestamp}]</span> {message}")
        logger.info(message)

    def closeEvent(self, event):
        """Handle window close"""
        self.ws_client.disconnect()
        logger.info("Application closed")
        event.accept()
