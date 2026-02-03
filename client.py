import sys
import asyncio
import json
import hmac
import hashlib
import logging
import os
import requests
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit,
    QLineEdit, QLabel, QComboBox, QTabWidget, QGroupBox, QFormLayout,
    QMessageBox, QProgressBar, QStatusBar, QSplitter, QFrame
)
from PyQt6.QtCore import Qt, QTimer, QSettings, pyqtSignal, QThread
from PyQt6.QtGui import QFont, QPalette, QColor, QIcon
import ccxt.async_support as ccxt
import websockets
from qasync import QEventLoop, asyncSlot

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('client.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ===================== CONFIG =====================
# SelfTrade.site signal server
DEFAULT_SERVER_URL = "https://www.selftrade.site"
DEFAULT_WS_URL = "wss://www.selftrade.site/ws/live"
SUPPORTED_PAIRS = ["BTC/USDT", "ETH/USDT", "BNB/USDT", "ADA/USDT", "SOL/USDT"]
SUPPORTED_EXCHANGES = {
    "Binance": ccxt.binance,
    "MEXC": ccxt.mexc,
    "Bybit": ccxt.bybit,
}
# ==================================================

# Global state
EXCHANGE_CLIENT = None
EXCHANGE_API_KEY = ""
EXCHANGE_API_SECRET = ""
SELECTED_EXCHANGE = None
AUTH_TOKEN = ""
SERVER_API_KEY = ""  # API key from server
SERVER_URL = DEFAULT_SERVER_URL
WS_URL = DEFAULT_WS_URL
ACTIVE_POSITIONS = {}  # Track positions: pair -> {'side': 'long/short', 'quantity': float, 'entry_price': float, 'timestamp': int}

def generate_binance_signature(query_string: str, secret: str) -> str:
    """Generate HMAC SHA256 signature for Binance API"""
    return hmac.new(secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()

def get_binance_server_time() -> int:
    """Get Binance server time in milliseconds"""
    try:
        response = requests.get('https://api.binance.com/api/v3/time', timeout=5)
        if response.status_code == 200:
            data = response.json()
            return data['serverTime']
        else:
            logger.warning("Failed to get Binance server time, using adjusted local time")
            # Adjust for simulation time difference (2026 -> 2024 approx)
            return int(time.time() * 1000) - 63196800000  # ~2 years back
    except Exception as e:
        logger.warning(f"Error getting Binance server time: {e}, using adjusted local time")
        return int(time.time() * 1000) - 63196800000  # ~2 years back

# ===================== GUI =====================
class TradeUI(QWidget):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("SelfTrade", "Client")
        self.auth_token = ""
        self.ws_task = None
        self.reconnect_timer = QTimer()
        self.reconnect_timer.timeout.connect(self.attempt_reconnect)

        self.init_ui()
        self.load_settings()

    def init_ui(self):
        self.setWindowTitle("SelfTrade Pro - Trading Client")
        self.setGeometry(100, 100, 900, 700)
        self.setStyleSheet("""
            QWidget {
                background-color: #1e1e2e;
                color: #cdd6f4;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            }
            QGroupBox {
                font-weight: bold;
                border: 2px solid #89b4fa;
                border-radius: 5px;
                margin-top: 1ex;
                color: #89b4fa;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 10px 0 10px;
            }
            QLabel {
                color: #cdd6f4;
            }
            QLineEdit, QComboBox, QTextEdit {
                background-color: #313244;
                border: 1px solid #45475a;
                border-radius: 5px;
                padding: 5px;
                color: #cdd6f4;
            }
            QLineEdit:focus, QComboBox:focus, QTextEdit:focus {
                border-color: #89b4fa;
            }
            QPushButton {
                background-color: #89b4fa;
                color: #1e1e2e;
                border: none;
                border-radius: 5px;
                padding: 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #74c7ec;
            }
            QPushButton:disabled {
                background-color: #45475a;
                color: #6c7086;
            }
            QTabWidget::pane {
                border: 1px solid #45475a;
                background-color: #1e1e2e;
            }
            QTabBar::tab {
                background-color: #313244;
                color: #cdd6f4;
                padding: 10px 20px;
                border: 1px solid #45475a;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background-color: #89b4fa;
                color: #1e1e2e;
            }
        """)

        # Main layout
        main_layout = QVBoxLayout()
        self.setLayout(main_layout)

        # Tab widget
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)

        # Connection tab
        self.connection_tab = QWidget()
        self.setup_connection_tab()
        self.tab_widget.addTab(self.connection_tab, "Connection")

        # Trading tab
        self.trading_tab = QWidget()
        self.setup_trading_tab()
        self.tab_widget.addTab(self.trading_tab, "Trading")

        # Logs tab
        self.logs_tab = QWidget()
        self.setup_logs_tab()
        self.tab_widget.addTab(self.logs_tab, "Logs")

        # Status bar
        self.status_bar = QStatusBar()
        main_layout.addWidget(self.status_bar)
        self.status_bar.showMessage("Ready")

    def setup_connection_tab(self):
        layout = QVBoxLayout()

        # Server Configuration
        server_group = QGroupBox("Server Configuration")
        server_layout = QFormLayout()

        self.server_url_input = QLineEdit(DEFAULT_SERVER_URL)
        self.server_url_input.setPlaceholderText("http://127.0.0.1:8001 (signal server)")
        server_layout.addRow("Signal Server URL:", self.server_url_input)

        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText("Obtained after login")
        self.api_key_input.setReadOnly(True)
        server_layout.addRow("API Key:", self.api_key_input)

        self.test_connection_btn = QPushButton("Test Connection")
        self.test_connection_btn.clicked.connect(self.test_connection)
        server_layout.addRow(self.test_connection_btn)

        server_group.setLayout(server_layout)
        layout.addWidget(server_group)

        # Authentication
        auth_group = QGroupBox("Authentication")
        auth_layout = QFormLayout()

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Your username")
        auth_layout.addRow("Username:", self.username_input)

        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("Your password")
        auth_layout.addRow("Password:", self.password_input)

        auth_buttons = QHBoxLayout()
        self.login_btn = QPushButton("Login")
        self.login_btn.clicked.connect(self.login)
        auth_buttons.addWidget(self.login_btn)

        self.register_btn = QPushButton("Register")
        self.register_btn.clicked.connect(self.register_user)
        auth_buttons.addWidget(self.register_btn)

        auth_layout.addRow(auth_buttons)
        auth_group.setLayout(auth_layout)
        layout.addWidget(auth_group)

        layout.addStretch()
        self.connection_tab.setLayout(layout)

    def setup_trading_tab(self):
        layout = QVBoxLayout()

        # Exchange Configuration
        exchange_group = QGroupBox("Exchange Configuration")
        exchange_layout = QFormLayout()

        self.exchange_select = QComboBox()
        self.exchange_select.addItems(SUPPORTED_EXCHANGES.keys())
        exchange_layout.addRow("Exchange:", self.exchange_select)

        self.exchange_api_key_input = QLineEdit()
        self.exchange_api_key_input.setPlaceholderText("Exchange API Key")
        exchange_layout.addRow("Exchange API Key:", self.exchange_api_key_input)

        self.exchange_api_secret_input = QLineEdit()
        self.exchange_api_secret_input.setPlaceholderText("Exchange API Secret")
        self.exchange_api_secret_input.setEchoMode(QLineEdit.EchoMode.Password)
        exchange_layout.addRow("Exchange API Secret:", self.exchange_api_secret_input)



        self.connect_exchange_btn = QPushButton("Connect Exchange")
        self.connect_exchange_btn.clicked.connect(self.connect_exchange)
        exchange_layout.addRow(self.connect_exchange_btn)

        exchange_group.setLayout(exchange_layout)
        layout.addWidget(exchange_group)

        # IP Whitelist Instructions
        ip_group = QGroupBox("⚠️ Important: IP Whitelisting Required")
        ip_layout = QVBoxLayout()
        ip_label = QLabel("Trading platforms require IP whitelisting for API access.\n\n1. Visit https://www.whatismyip.com/ to find your IP\n2. Add your IP to exchange API settings under 'IP Access Restrictions'\n3. Enable 'Restrict access to trusted IPs only'\n\nWithout this, you'll get signature errors!")
        ip_label.setWordWrap(True)
        ip_layout.addWidget(ip_label)
        ip_group.setLayout(ip_layout)
        layout.addWidget(ip_group)

        # Trading Controls
        trading_group = QGroupBox("Trading Controls")
        trading_layout = QVBoxLayout()

        self.start_trading_btn = QPushButton("Start Auto Trading")
        self.start_trading_btn.clicked.connect(self.start_trading)
        self.start_trading_btn.setEnabled(False)
        trading_layout.addWidget(self.start_trading_btn)

        self.stop_trading_btn = QPushButton("Stop Trading")
        self.stop_trading_btn.clicked.connect(self.stop_trading)
        self.stop_trading_btn.setEnabled(False)
        trading_layout.addWidget(self.stop_trading_btn)

        # Trading status
        self.trading_status_label = QLabel("Status: Not Connected")
        trading_layout.addWidget(self.trading_status_label)

        trading_group.setLayout(trading_layout)
        layout.addWidget(trading_group)

        # Portfolio and Signals
        portfolio_signals_layout = QHBoxLayout()

        # Portfolio display
        portfolio_group = QGroupBox("Portfolio")
        portfolio_layout = QVBoxLayout()

        self.portfolio_text = QTextEdit()
        self.portfolio_text.setReadOnly(True)
        self.portfolio_text.setMaximumHeight(150)
        portfolio_layout.addWidget(self.portfolio_text)

        self.refresh_portfolio_btn = QPushButton("Refresh Portfolio")
        self.refresh_portfolio_btn.clicked.connect(self.refresh_portfolio)
        portfolio_layout.addWidget(self.refresh_portfolio_btn)

        portfolio_group.setLayout(portfolio_layout)
        portfolio_signals_layout.addWidget(portfolio_group)

        # Recent signals
        signals_group = QGroupBox("Recent Signals")
        signals_layout = QVBoxLayout()

        self.signals_text = QTextEdit()
        self.signals_text.setReadOnly(True)
        self.signals_text.setMaximumHeight(150)
        signals_layout.addWidget(self.signals_text)

        signals_group.setLayout(signals_layout)
        portfolio_signals_layout.addWidget(signals_group)

        layout.addLayout(portfolio_signals_layout)

        self.trading_tab.setLayout(layout)

    def setup_logs_tab(self):
        layout = QVBoxLayout()

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setFont(QFont("Consolas", 9))
        layout.addWidget(self.log_box)

        clear_btn = QPushButton("Clear Logs")
        clear_btn.clicked.connect(lambda: self.log_box.clear())
        layout.addWidget(clear_btn)

        self.logs_tab.setLayout(layout)

    def log(self, msg: str, level: str = "INFO"):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        formatted_msg = f"[{timestamp}] [{level}] {msg}"

        # Add to log box if it exists
        if hasattr(self, 'log_box') and self.log_box:
            self.log_box.append(formatted_msg)

        # Log to file
        if level == "ERROR":
            logger.error(msg)
        elif level == "WARNING":
            logger.warning(msg)
        else:
            logger.info(msg)

        print(formatted_msg)

    def load_settings(self):
        """Load saved settings"""
        global SERVER_URL, WS_URL
        SERVER_URL = self.settings.value("server_url", DEFAULT_SERVER_URL)
        WS_URL = self.settings.value("ws_url", DEFAULT_WS_URL)
        self.server_url_input.setText(SERVER_URL)
        self.username_input.setText(self.settings.value("username", ""))
        self.exchange_api_key_input.setText(self.settings.value("exchange_api_key", ""))
        self.exchange_api_secret_input.setText(self.settings.value("exchange_api_secret", ""))

    def save_settings(self):
        """Save settings"""
        global SERVER_URL, WS_URL
        SERVER_URL = self.server_url_input.text()
        WS_URL = f"ws://{SERVER_URL.split('://')[1]}/ws/live" if "://" in SERVER_URL else f"ws://{SERVER_URL}/ws/live"

        self.settings.setValue("server_url", SERVER_URL)
        self.settings.setValue("ws_url", WS_URL)
        self.settings.setValue("username", self.username_input.text())
        self.settings.setValue("exchange_api_key", self.exchange_api_key_input.text())
        self.settings.setValue("exchange_api_secret", self.exchange_api_secret_input.text())

    def test_connection(self):
        """Test connection to server and validate API key"""
        try:
            server_url = self.server_url_input.text().strip()
            api_key = self.api_key_input.text().strip()

            # First test basic server connectivity
            response = requests.get(f"{server_url}/health", timeout=5)
            if response.status_code != 200:
                self.log("❌ Server is not reachable", "ERROR")
                self.status_bar.showMessage("Server connection: Failed")
                return

            # If API key is provided, validate it
            if api_key:
                try:
                    response = requests.get(f"{server_url}/api/validate", params={"api_key": api_key}, timeout=10)
                    if response.status_code == 200:
                        data = response.json()
                        plan = data.get('plan', 'unknown')
                        signals_remaining = data.get('signals_remaining', 0)
                        signals_used = data.get('signals_used', 0)
                        self.log(f"✅ API key valid - Plan: {plan}, Used: {signals_used}, Remaining: {signals_remaining}")
                        self.status_bar.showMessage(f"API: {signals_remaining} signals left")

                        # Update UI if we have the fields
                        if hasattr(self, 'signals_remaining_label'):
                            self.signals_remaining_label.setText(f"Signals Remaining: {signals_remaining}")
                        if hasattr(self, 'signals_used_label'):
                            self.signals_used_label.setText(f"Signals Used: {signals_used}")

                    else:
                        error_data = response.json()
                        self.log(f"❌ Invalid API key: {error_data.get('detail', 'Unknown error')}", "ERROR")
                        self.status_bar.showMessage("API Key: Invalid")
                        return
                except requests.RequestException as e:
                    self.log(f"❌ API key validation failed: {e}", "ERROR")
                    self.status_bar.showMessage("API validation: Failed")
                    return
            else:
                self.log("✅ Server connection successful (no API key to validate)")
                self.status_bar.showMessage("Server: OK (no API key)")

            self.save_settings()

        except requests.RequestException as e:
            self.log(f"❌ Connection test failed: {e}", "ERROR")
            self.status_bar.showMessage("Server connection: Failed")
        except Exception as e:
            self.log(f"❌ Unexpected error during connection test: {e}", "ERROR")
            self.status_bar.showMessage("Connection test: Error")

    def login(self):
        """Login to server"""
        try:
            username = self.username_input.text().strip()
            password = self.password_input.text().strip()
            server_url = self.server_url_input.text()

            if not username or not password:
                self.log("⚠️ Enter username and password", "WARNING")
                return

            response = requests.post(f"{server_url}/login", json={
                "username": username,
                "password": password
            }, timeout=10)

            if response.status_code == 200:
                data = response.json()
                self.auth_token = data["access_token"]
                global AUTH_TOKEN, SERVER_API_KEY
                AUTH_TOKEN = self.auth_token
                SERVER_API_KEY = data["user"]["api_key"]

                # Populate the API key field with the received key
                self.api_key_input.setText(SERVER_API_KEY)

                self.log("✅ Login successful")
                self.status_bar.showMessage(f"Logged in as {username}")
                self.save_settings()
                self.update_ui_after_login()
            else:
                error_data = response.json()
                self.log(f"❌ Login failed: {error_data.get('detail', 'Unknown error')}", "ERROR")

        except Exception as e:
            self.log(f"❌ Login error: {e}", "ERROR")

    def register_user(self):
        """Register new user"""
        try:
            username = self.username_input.text().strip()
            password = self.password_input.text().strip()
            server_url = self.server_url_input.text()

            email = f"{username}@selftrade.local"  # Temporary email for demo

            if not username or not password:
                self.log("⚠️ Enter username and password", "WARNING")
                return

            response = requests.post(f"{server_url}/register", json={
                "username": username,
                "email": email,
                "password": password
            }, timeout=10)

            if response.status_code == 200:
                self.log("✅ Registration successful! Please login.")
                QMessageBox.information(self, "Success", "Registration successful! Please login with your credentials.")
            else:
                error_data = response.json()
                self.log(f"❌ Registration failed: {error_data.get('detail', 'Unknown error')}", "ERROR")

        except Exception as e:
            self.log(f"❌ Registration error: {e}", "ERROR")

    def update_ui_after_login(self):
        """Update UI after successful login"""
        self.tab_widget.setCurrentIndex(1)  # Switch to trading tab
        self.start_trading_btn.setEnabled(True)

    @asyncSlot()
    async def refresh_portfolio(self):
        """Fetch and display current portfolio"""
        if not EXCHANGE_CLIENT:
            self.log("⚠️ Connect to exchange first", "WARNING")
            return

        balance = None
        try:
            balance = await EXCHANGE_CLIENT.fetch_balance()
            portfolio_info = "📊 Current Portfolio:\n\n"

            total_value_usdt = 0
            for currency, data in balance.items():
                if isinstance(data, dict):
                    free_balance = data.get('free', 0)
                    used_balance = data.get('used', 0)
                    if free_balance > 0 or used_balance > 0:
                        total = free_balance + used_balance
                        if currency == 'USDT':
                            total_value_usdt += total
                            portfolio_info += f"💵 {currency}: {total:.2f}\n"
                        else:
                            # Try to get current price for valuation
                            try:
                                if currency != 'USDT':
                                    pair = f"{currency}/USDT"
                                    ticker = await EXCHANGE_CLIENT.fetch_ticker(pair)
                                    price = ticker['last']
                                    value_usdt = total * price
                                    total_value_usdt += value_usdt
                                    portfolio_info += f"🪙 {currency}: {total:.6f} (≈${value_usdt:.2f})\n"
                            except:
                                portfolio_info += f"🪙 {currency}: {total:.6f}\n"

            portfolio_info += f"\n💰 Total Value: ≈${total_value_usdt:.2f} USDT"

            # Add active positions
            if ACTIVE_POSITIONS:
                portfolio_info += "\n\n📊 Active Positions:"
                for pair, pos in ACTIVE_POSITIONS.items():
                    pnl = "N/A"
                    try:
                        current_ticker = await EXCHANGE_CLIENT.fetch_ticker(pair)
                        current_price = current_ticker['last']
                        if pos['side'] == 'long':
                            pnl_value = (current_price - pos['entry_price']) * pos['quantity']
                            pnl_pct = ((current_price - pos['entry_price']) / pos['entry_price']) * 100
                        else:
                            pnl_value = (pos['entry_price'] - current_price) * pos['quantity']
                            pnl_pct = ((pos['entry_price'] - current_price) / pos['entry_price']) * 100
                        pnl = f"${pnl_value:.2f} ({pnl_pct:.1f}%)"
                    except:
                        pass

                    portfolio_info += f"\n{pos['side'].upper()} {pair}: {pos['quantity']:.6f} @ ${pos['entry_price']:.2f} | P&L: {pnl}"

            self.portfolio_text.setPlainText(portfolio_info)
            self.log(f"✅ Portfolio refreshed - Total: ${total_value_usdt:.2f} USDT | Positions: {len(ACTIVE_POSITIONS)}")

            # Check positions for profit taking
            await self.check_positions_for_profit_taking()

        except Exception as e:
            self.log(f"❌ Failed to fetch portfolio: {e}", "ERROR")
            # Show error message in portfolio display
            error_msg = "❌ Failed to fetch portfolio\n\n"
            error_msg += f"Error: {str(e)}\n\n"
            error_msg += "Please check your exchange connection and API keys."
            self.portfolio_text.setPlainText(error_msg)

    def connect_exchange(self):
        """Connect to exchange"""
        global EXCHANGE_CLIENT, EXCHANGE_API_KEY, EXCHANGE_API_SECRET, SELECTED_EXCHANGE

        api_key = self.exchange_api_key_input.text().strip()
        api_secret = self.exchange_api_secret_input.text().strip()
        exchange_name = self.exchange_select.currentText()

        if not api_key:
            self.log("⚠️ Enter exchange API key", "WARNING")
            return

        if not api_secret:
            self.log("⚠️ Enter exchange API secret", "WARNING")
            return

        # Validate API key format (basic check)
        if len(api_key) < 10:
            self.log("⚠️ API key appears too short - please double-check your credentials", "WARNING")
            return

        if len(api_secret) < 10:
            self.log("⚠️ API secret appears too short - please double-check your credentials", "WARNING")
            return

        try:
            EXCHANGE_API_KEY = api_key
            EXCHANGE_API_SECRET = api_secret
            SELECTED_EXCHANGE = exchange_name

            EXCHANGE_CLIENT = SUPPORTED_EXCHANGES[exchange_name]({
                'apiKey': EXCHANGE_API_KEY,
                'secret': EXCHANGE_API_SECRET,
                'enableRateLimit': True,
                'options': {
                    'adjustForTimeDifference': True,  # Sync with exchange server time for accurate signatures
                }
            })

            self.log(f"✅ {exchange_name} client initialized")
            self.connect_exchange_btn.setEnabled(False)
            self.start_trading_btn.setEnabled(True)
            self.trading_status_label.setText("Status: Exchange Connected")
            self.save_settings()  # Save the credentials

        except Exception as e:
            self.log(f"❌ Exchange connection failed: {e}", "ERROR")

    @asyncSlot()
    async def start_trading(self):
        """Start automated trading"""
        if not EXCHANGE_CLIENT:
            self.log("⚠️ Connect to exchange first", "WARNING")
            # Show warning in UI
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Connection Required",
                              "Please connect to an exchange first before starting automated trading.")
            return

        if not self.auth_token:
            self.log("⚠️ Login to server first", "WARNING")
            return

        self.log("🚀 Starting automated trading...")
        self.start_trading_btn.setEnabled(False)
        self.stop_trading_btn.setEnabled(True)
        self.trading_status_label.setText("Status: Trading Active")

        # Start websocket for real-time signals
        self.ws_task = asyncio.create_task(self.start_ws())

        # Also start HTTP polling as backup
        self.http_task = asyncio.create_task(self.start_http_polling())

    def stop_trading(self):
        """Stop automated trading"""
        if self.ws_task:
            self.ws_task.cancel()
        if hasattr(self, 'http_task') and self.http_task:
            self.http_task.cancel()
        self.start_trading_btn.setEnabled(True)
        self.stop_trading_btn.setEnabled(False)
        self.trading_status_label.setText("Status: Stopped")
        self.log("🛑 Trading stopped")

    async def start_ws(self):
        """Start WebSocket connection for real-time signals"""
        while True:  # Reconnection loop
            try:
                async with websockets.connect(WS_URL) as ws:
                    self.log(f"🌐 Connected to server {WS_URL}")
                    self.trading_status_label.setText("Status: Connected & Trading")
                    self.reconnect_timer.stop()

                    while True:
                        try:
                            msg = await ws.recv()
                            data = json.loads(msg)
                            await self.handle_signal(data)
                        except json.JSONDecodeError:
                            self.log("❌ Received invalid JSON message", "WARNING")
                        except Exception as e:
                            self.log(f"❌ Failed to process message: {e}", "ERROR")

            except websockets.exceptions.ConnectionClosed:
                self.log("🔄 WebSocket connection closed, attempting reconnection...", "WARNING")
                self.trading_status_label.setText("Status: Reconnecting...")
                self.attempt_reconnect()
                await asyncio.sleep(5)
            except Exception as e:
                self.log(f"❌ WebSocket error: {e}", "ERROR")
                self.trading_status_label.setText("Status: Connection Error")
                self.attempt_reconnect()
                await asyncio.sleep(5)

    def attempt_reconnect(self):
        """Attempt to reconnect WebSocket"""
        if not self.reconnect_timer.isActive():
            self.reconnect_timer.start(5000)  # Try every 5 seconds

    async def handle_signal(self, signal: dict):
        """Handle incoming trading signal"""
        try:
            # Verify signal structure
            required_fields = ["pair", "side", "timestamp", "signature"]
            if not all(field in signal for field in required_fields):
                self.log("❌ Invalid signal format", "WARNING")
                return

            # Handle hold signals professionally
            side = signal["side"].lower()
            if side == "hold":
                self.log(f"📊 Market analysis: HOLD position for {signal['pair']} - awaiting better conditions")
                # Don't return, continue to log but don't trade

            # Verify HMAC signature using server API key
            payload = f"{signal['pair']}|{signal['side']}|{signal['timestamp']}"
            expected_sig = hmac.new(SERVER_API_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()
            if expected_sig != signal.get("signature"):
                self.log("❌ Invalid signature, skipping signal", "WARNING")
                return

            pair = signal["pair"].replace("-", "/")  # ensure CCXT format
            if "/" not in pair and pair.endswith("USDT"):
                pair = pair[:-4] + "/USDT"
            side = signal["side"].lower()

            # Get entry price and quantity from signal
            entry_price = signal.get("entry_price", 0)
            qty = signal.get("quantity", 0.001)

            # Validate pair
            if pair not in SUPPORTED_PAIRS:
                self.log(f"⚠️ Unsupported pair {pair}", "WARNING")
                return

            # Check for position conflicts and close if needed
            if pair in ACTIVE_POSITIONS:
                current_pos = ACTIVE_POSITIONS[pair]
                if current_pos['side'] != side.lower():
                    # Opposite signal - close existing position first
                    self.log(f"🔄 Closing existing {current_pos['side'].upper()} position for {pair} due to opposite signal")
                    await self.close_position(pair)
                    # Wait a bit for order to process
                    await asyncio.sleep(1)

            # Quick balance check before processing signal to avoid logging irrelevant signals
            if EXCHANGE_CLIENT:
                try:
                    balance = await EXCHANGE_CLIENT.fetch_balance()
                    base_currency, quote_currency = pair.split('/')

                    if side.lower() in ['sell', 'short']:
                        base_data = balance.get(base_currency, {})
                        if isinstance(base_data, dict):
                            base_balance = base_data.get('free', 0)
                            if base_balance <= 0:
                                self.log(f"⚠️ Skipping {side.upper()} signal for {pair} - no {base_currency} balance", "WARNING")
                                return
                    elif side.lower() in ['buy', 'long']:
                        quote_data = balance.get(quote_currency, {})
                        if isinstance(quote_data, dict):
                            quote_balance = quote_data.get('free', 0)
                            if quote_balance <= 0:
                                self.log(f"⚠️ Skipping {side.upper()} signal for {pair} - no {quote_currency} balance", "WARNING")
                                return
                except Exception as e:
                    self.log(f"⚠️ Could not check balance for signal validation: {e}", "WARNING")
                    # Continue processing anyway

            # Log signal to UI
            signal_info = f"📡 Signal: {side.upper()} {pair} qty={qty}"
            if "confidence" in signal:
                signal_info += f" conf={signal['confidence']}"
            if entry_price:
                signal_info += f" price={entry_price}"

            self.log(signal_info)

            # Add to signals display
            current_signals = self.signals_text.toPlainText()
            new_signal = f"{datetime.now().strftime('%H:%M:%S')} - {signal_info}\n"
            self.signals_text.setPlainText(new_signal + current_signals[:1000])  # Keep last 1000 chars

            # Refresh signal counts after receiving signal
            asyncio.create_task(self.refresh_signal_counts())

            # Place order with portfolio check
            target_price = signal.get('target_price', 0)
            stop_loss = signal.get('stop_loss', 0)
            await self.place_order(pair, side, qty, entry_price, target_price, stop_loss, signal)

        except Exception as e:
            self.log(f"❌ Error handling signal: {e}", "ERROR")

    async def place_order(self, pair: str, side: str, quantity: float, entry_price: float = 0, target_price: float = 0, stop_loss: float = 0, signal: Optional[Dict[str, Any]] = None):
        """Place order on exchange with portfolio-based risk management"""
        if not EXCHANGE_CLIENT:
            self.log("❌ Exchange client not initialized", "ERROR")
            return

        try:
            # Get current balance for risk management
            balance = await EXCHANGE_CLIENT.fetch_balance()
            base_currency, quote_currency = pair.split('/')

            # Get balances safely
            base_data = balance.get(base_currency, {})
            quote_data = balance.get(quote_currency, {})
            base_balance = base_data.get('free', 0) if isinstance(base_data, dict) else 0
            quote_balance = quote_data.get('free', 0) if isinstance(quote_data, dict) else 0

            self.log(f"📊 Portfolio: {base_currency}={base_balance:.6f}, {quote_currency}={quote_balance:.2f}")

            # Enhanced portfolio management
            current_price = entry_price
            if current_price <= 0:
                try:
                    ticker = await EXCHANGE_CLIENT.fetch_ticker(pair)
                    current_price = ticker['last']
                except:
                    self.log("❌ Could not get current price", "ERROR")
                    return

            signal_confidence = signal.get('confidence', 0.5) if signal else 0.5

            if side.lower() == 'hold':
                # Professional handling of hold signals
                self.log(f"📊 Strategy: HOLD position for {pair} - monitoring market conditions")
                return

            elif side.lower() == 'buy' or side.lower() == 'long':
                # For buy orders, check quote currency balance
                if quote_balance <= 10:  # Minimum 10 USDT
                    self.log(f"❌ Insufficient {quote_currency} balance ({quote_balance:.2f}) for buy signal", "ERROR")
                    return

                # Advanced position sizing based on signal confidence
                confidence_multiplier = min(signal_confidence, 1.0)

                # Base risk: 5-15% of available balance based on confidence
                base_risk_pct = 0.05 + (confidence_multiplier * 0.10)  # 5% to 15%

                # Calculate position size
                amount_to_spend = quote_balance * base_risk_pct
                calculated_qty = amount_to_spend / current_price

                # Apply minimum and maximum limits
                min_value_equivalent = 10 / current_price  # Minimum 10 USD equivalent
                max_qty = quote_balance * 0.2 / current_price  # Maximum 20% of balance

                final_qty = max(min_value_equivalent, min(calculated_qty, max_qty))

                # Ensure quantity is never zero
                if final_qty <= 0:
                    final_qty = min_value_equivalent

                # Check if signal has quantity suggestion and adjust
                if quantity > 0:
                    final_qty = min(final_qty, quantity)

            elif side.lower() == 'sell' or side.lower() == 'short':
                # For sell orders, check base currency balance
                if base_balance <= 0.000001:  # Very small threshold for crypto
                    self.log(f"❌ Insufficient {base_currency} balance ({base_balance:.6f}) for sell signal", "ERROR")
                    return

                # For sell orders, use signal confidence to determine position size
                confidence_multiplier = min(signal_confidence, 1.0)

                # Sell 10-50% of holdings based on confidence
                sell_pct = 0.10 + (confidence_multiplier * 0.40)  # 10% to 50%

                final_qty = base_balance * sell_pct

                # Ensure minimum sell quantity
                if final_qty <= 0:
                    self.log(f"⚠️ Sell quantity too small, using minimum: {base_balance * 0.01}")
                    final_qty = base_balance * 0.01  # At least 1% of holdings

                # Check if signal has quantity suggestion
                if quantity > 0:
                    final_qty = min(final_qty, quantity)

                # Ensure we don't sell everything (keep some for fees/etc)
                max_sell_qty = base_balance * 0.9  # Never sell more than 90%
                final_qty = min(final_qty, max_sell_qty)

            elif side.lower() == 'buy' or side.lower() == 'long':
                # For buy orders, check quote currency balance
                if quote_balance <= 10:  # Minimum 10 USDT
                    self.log(f"❌ Insufficient {quote_currency} balance ({quote_balance:.2f}) for buy signal", "ERROR")
                    return

                # Advanced position sizing based on signal confidence
                confidence_multiplier = min(signal_confidence, 1.0)

                # Base risk: 5-15% of available balance based on confidence
                base_risk_pct = 0.05 + (confidence_multiplier * 0.10)  # 5% to 15%

                # Calculate position size
                amount_to_spend = quote_balance * base_risk_pct
                calculated_qty = amount_to_spend / current_price

                # Apply minimum and maximum limits
                min_value_equivalent = 10 / current_price  # Minimum 10 USD equivalent
                max_qty = quote_balance * 0.2 / current_price  # Maximum 20% of balance

                final_qty = max(min_value_equivalent, min(calculated_qty, max_qty))

                # Ensure quantity is never zero
                if final_qty <= 0:
                    final_qty = min_value_equivalent

                # Check if signal has quantity suggestion and adjust
                if quantity > 0:
                    final_qty = min(final_qty, quantity)

            elif side.lower() == 'sell' or side.lower() == 'short':
                # For sell orders, check base currency balance
                if base_balance <= 0.000001:  # Very small threshold for crypto
                    self.log(f"❌ Insufficient {base_currency} balance ({base_balance:.6f}) for sell signal", "ERROR")
                    return

                # For sell orders, use signal confidence to determine position size
                confidence_multiplier = min(signal_confidence, 1.0)

                # Sell 10-50% of holdings based on confidence
                sell_pct = 0.10 + (confidence_multiplier * 0.40)  # 10% to 50%

                final_qty = base_balance * sell_pct

                # Ensure minimum sell quantity
                if final_qty <= 0:
                    self.log(f"⚠️ Sell quantity too small, using minimum: {base_balance * 0.01}")
                    final_qty = base_balance * 0.01  # At least 1% of holdings

                # Check if signal has quantity suggestion
                if quantity > 0:
                    final_qty = min(final_qty, quantity)

                # Ensure we don't sell everything (keep some for fees/etc)
                max_sell_qty = base_balance * 0.9  # Never sell more than 90%
                final_qty = min(final_qty, max_sell_qty)

            else:
                self.log(f"❌ Unknown side: {side}", "ERROR")
                return

            # Ensure minimum order size and round appropriately
            if final_qty <= 0.000001:
                self.log(f"❌ Calculated quantity too small: {final_qty}", "ERROR")
                return

            # Simplified quantity validation - use known good values for crypto pairs
            if pair.startswith('BTC/'):
                # BTC: 6 decimal places, minimum 0.000001
                final_qty = round(final_qty, 6)
                if final_qty < 0.000001:
                    final_qty = 0.000001
            elif pair.startswith('ETH/'):
                # ETH: 5 decimal places, minimum 0.00001
                final_qty = round(final_qty, 5)
                if final_qty < 0.00001:
                    final_qty = 0.00001
            elif pair.startswith('BNB/'):
                # BNB: 2 decimal places, minimum 0.01
                final_qty = round(final_qty, 2)
                if final_qty < 0.01:
                    final_qty = 0.01
            elif pair.startswith('ADA/'):
                # ADA: 0 decimal places (whole numbers), minimum 1
                final_qty = round(final_qty, 0)
                if final_qty < 1:
                    final_qty = 1
            elif pair.startswith('SOL/'):
                # SOL: 2 decimal places, minimum 0.001
                final_qty = round(final_qty, 2)
                if final_qty < 0.001:
                    final_qty = 0.001
            else:
                # Default: 6 decimal places
                final_qty = round(final_qty, 6)
                if final_qty < 0.000001:
                    final_qty = 0.000001

            # Normalize side for exchange APIs
            if side.lower() in ['buy', 'long']:
                api_side = 'BUY'
            elif side.lower() in ['sell', 'short']:
                api_side = 'SELL'
            else:
                self.log(f"❌ Invalid side: {side}", "ERROR")
                return

            # Final validation - ensure quantity meets all requirements
            if final_qty <= 0:
                self.log(f"❌ Invalid quantity: {final_qty}", "ERROR")
                return

            # Final validation - ensure minimum order value
            order_value = final_qty * current_price
            min_required_value = 20.0 if SELECTED_EXCHANGE == 'Binance' else 5.0

            if order_value < min_required_value:
                # Calculate minimum quantity needed
                required_qty = min_required_value / current_price

                # Apply same precision rules
                if pair.startswith('BTC/'):
                    required_qty = max(required_qty, 0.000001)
                    required_qty = round(required_qty, 6)
                elif pair.startswith('ETH/'):
                    required_qty = max(required_qty, 0.00001)
                    required_qty = round(required_qty, 5)
                elif pair.startswith('BNB/'):
                    required_qty = max(required_qty, 0.01)
                    required_qty = round(required_qty, 2)
                elif pair.startswith('ADA/'):
                    required_qty = max(required_qty, 1)
                    required_qty = round(required_qty, 0)
                elif pair.startswith('SOL/'):
                    required_qty = max(required_qty, 0.001)
                    required_qty = round(required_qty, 2)

                final_qty = required_qty
                order_value = final_qty * current_price
                self.log(f"⚠️ Increased quantity to meet minimum value: {final_qty:.6f} (${order_value:.2f})")

            # Final safety check
            if final_qty <= 0:
                self.log(f"❌ Invalid quantity after validation: {final_qty}", "ERROR")
                return

            self.log(f"✅ Final order: {api_side} {pair} qty={final_qty:.6f} value=${order_value:.2f}")

            if SELECTED_EXCHANGE == 'Binance':
                # Use ccxt for order placement instead of manual signature
                order_params = {
                    'symbol': pair,
                    'type': 'market',
                    'side': api_side.lower(),  # ccxt expects lowercase
                    'amount': final_qty
                }

                try:
                    order = await EXCHANGE_CLIENT.create_order(**order_params)
                    qty_display = f"{final_qty:.6f}".rstrip('0').rstrip('.')
                    self.log(f"✅ Order placed: {order['id']} {api_side} {pair} qty={qty_display} status={order['status']}")

                    # Log order details
                    if 'cost' in order and 'fee' in order:
                        self.log(f"💰 Order cost: {order.get('cost', 0):.2f} fee: {order.get('fee', {}).get('cost', 0):.4f}")

                except Exception as e:
                    self.log(f"❌ Binance order failed: {e}", "ERROR")
                    return

            elif SELECTED_EXCHANGE == 'MEXC':
                # MEXC manual order placement
                timestamp = int(time.time() * 1000)
                qty_str = f"{final_qty:.6f}".rstrip('0').rstrip('.')
                params = {
                    'symbol': pair.replace('/', ''),  # MEXC uses BTCUSDT format
                    'side': api_side,
                    'type': 'MARKET',
                    'quantity': qty_str,
                    'timestamp': timestamp
                }

                # Build query string
                query_string = '&'.join([f"{k}={urllib.parse.quote(str(v))}" for k, v in sorted(params.items())])

                # Generate signature for MEXC (different from Binance)
                signature = hmac.new(EXCHANGE_API_SECRET.encode(), query_string.encode(), hashlib.sha256).hexdigest()

                # Add signature to params
                params['signature'] = signature

                headers = {
                    'X-MEXC-APIKEY': EXCHANGE_API_KEY,
                    'Content-Type': 'application/json'
                }

                try:
                    response = requests.post(
                        'https://api.mexc.com/api/v3/order',
                        params=params,
                        headers=headers,
                        timeout=10
                    )
                    response.raise_for_status()
                    order = response.json()
                    self.log(f"✅ MEXC Order placed: {order.get('orderId', 'N/A')} {api_side} {pair} qty={qty_str} status={order.get('status', 'unknown')}")

                except requests.RequestException as e:
                    self.log(f"❌ MEXC order failed: {e}", "ERROR")
                    if hasattr(e, 'response') and e.response:
                        self.log(f"❌ MEXC Response: {e.response.text}", "ERROR")
                    return

            else:
                # Use ccxt for other exchanges
                order_params = {
                    'symbol': pair,
                    'type': 'market',
                    'side': api_side.lower(),  # ccxt expects lowercase
                    'amount': final_qty
                }

                order = await EXCHANGE_CLIENT.create_order(**order_params)
                qty_display = f"{final_qty:.6f}".rstrip('0').rstrip('.')
                self.log(f"✅ Order placed: {order['id']} {api_side} {pair} qty={qty_display} status={order['status']}")

                # Decrement signal count on successful order
                if order['status'] == 'closed':
                    try:
                        api_key = self.api_key_input.text().strip()
                        server_url = self.server_url_input.text()
                        response = requests.post(f"{server_url}/api/use_signal", json={"api_key": api_key}, timeout=5)
                        if response.status_code == 200:
                            data = response.json()
                            remaining = data.get('remaining', 'unknown')
                            self.log(f"📊 Signal used - {remaining} remaining")
                        else:
                            self.log(f"⚠️ Failed to update signal count: {response.status_code}")
                    except Exception as e:
                        self.log(f"⚠️ Signal count update failed: {e}")

                # Update position tracking
                if order['status'] == 'closed':
                    fill_price = order.get('price', order.get('average', current_price))
                    if side.lower() in ['buy', 'long']:
                        ACTIVE_POSITIONS[pair] = {
                            'side': 'long',
                            'quantity': final_qty,
                            'entry_price': fill_price,
                            'timestamp': int(time.time())
                        }
                        self.log(f"📈 Opened LONG position: {pair} qty={qty_display} price={fill_price:.2f}")
                    elif side.lower() in ['sell', 'short']:
                        # For sell/short, remove from positions if it was a close
                        if pair in ACTIVE_POSITIONS and ACTIVE_POSITIONS[pair]['side'] == 'long':
                            del ACTIVE_POSITIONS[pair]
                            self.log(f"📉 Closed LONG position: {pair} qty={qty_display}")

                # Log order details
                if 'cost' in order and 'fee' in order:
                    self.log(f"💰 Order cost: {order.get('cost', 0):.2f} fee: {order.get('fee', {}).get('cost', 0):.4f}")

            # Skip OCO for now to reduce complexity
            # Place OCO order for stop loss and take profit if this was a buy/long order
            if side.lower() in ['buy', 'long'] and target_price > 0 and stop_loss > 0:
                try:
                    await self.place_oco_order(pair, final_qty, target_price, stop_loss)
                except Exception as e:
                    self.log(f"⚠️ Failed to place OCO order: {e}", "WARNING")

        except ccxt.InsufficientFunds as e:
            self.log(f"❌ Insufficient funds: {e}", "ERROR")
        except ccxt.InvalidOrder as e:
            self.log(f"❌ Invalid order: {e}", "ERROR")
        except ccxt.NetworkError as e:
            self.log(f"❌ Network error: {e}", "ERROR")
        except ccxt.ExchangeError as e:
            self.log(f"❌ Exchange error: {e}", "ERROR")
        except Exception as e:
            self.log(f"❌ Unknown error placing order: {e}", "ERROR")

    async def close_position(self, pair: str):
        """Close existing position for a pair"""
        if pair not in ACTIVE_POSITIONS:
            return

        position = ACTIVE_POSITIONS[pair]
        side = 'sell' if position['side'] == 'long' else 'buy'
        quantity = position['quantity']

        try:
            if SELECTED_EXCHANGE == 'Binance':
                # Use ccxt for Binance now
                order_params = {
                    'symbol': pair,
                    'type': 'market',
                    'side': side,
                    'amount': quantity
                }

                order = await EXCHANGE_CLIENT.create_order(**order_params)
                self.log(f"✅ Position closed: {order['id']} {side.upper()} {pair} qty={quantity:.6f}")

                # Remove from active positions
                del ACTIVE_POSITIONS[pair]

            else:
                # For other exchanges, use ccxt
                order_params = {
                    'symbol': pair,
                    'type': 'market',
                    'side': side,
                    'amount': quantity
                }

                order = await EXCHANGE_CLIENT.create_order(**order_params)
                self.log(f"✅ Position closed: {order['id']} {side.upper()} {pair} qty={quantity:.6f}")

                # Remove from active positions
                del ACTIVE_POSITIONS[pair]

        except Exception as e:
            self.log(f"❌ Failed to close position {pair}: {e}", "ERROR")

    async def check_positions_for_profit_taking(self):
        """Check active positions and close profitable ones"""
        if not EXCHANGE_CLIENT or not ACTIVE_POSITIONS:
            return

        for pair in list(ACTIVE_POSITIONS.keys()):
            try:
                position = ACTIVE_POSITIONS[pair]
                ticker = await EXCHANGE_CLIENT.fetch_ticker(pair)
                current_price = ticker['last']

                if position['side'] == 'long':
                    pnl_pct = (current_price - position['entry_price']) / position['entry_price']
                else:
                    pnl_pct = (position['entry_price'] - current_price) / position['entry_price']

                # Take profit at 1% gain
                if pnl_pct >= 0.01:
                    self.log(f"✅ Taking profit on {pair} at {pnl_pct:.1f}% gain")
                    await self.close_position(pair)

                # Stop loss at -2% loss
                elif pnl_pct <= -0.02:
                    self.log(f"🛑 Stop loss on {pair} at {pnl_pct:.1f}% loss")
                    await self.close_position(pair)

            except Exception as e:
                self.log(f"❌ Error checking position {pair}: {e}", "WARNING")

    async def place_oco_order(self, pair: str, quantity: float, target_price: float, stop_loss: float):
        """Place OCO (One Cancels Other) order for take profit and stop loss"""
        if not EXCHANGE_CLIENT:
            self.log("❌ Exchange client not initialized", "ERROR")
            return

        try:
            if SELECTED_EXCHANGE == 'Binance':
                # Manual OCO order placement with programmatic signature generation
                timestamp = get_binance_server_time()
                params = {
                    'symbol': pair.replace('/', ''),  # Binance uses BTCUSDT format
                    'side': 'SELL',
                    'quantity': f"{quantity:.6f}",
                    'price': f"{target_price:.2f}",  # Take profit price
                    'stopPrice': f"{stop_loss:.2f}",  # Stop loss trigger price
                    'stopLimitPrice': f"{stop_loss:.2f}",  # Stop limit price (same as stop for simplicity)
                    'stopLimitTimeInForce': 'GTC',
                    'timestamp': timestamp
                }

                # Build query string (sorted by key)
                query_string = '&'.join([f"{k}={urllib.parse.quote(str(v))}" for k, v in sorted(params.items())])

                # Generate signature
                signature = generate_binance_signature(query_string, EXCHANGE_API_SECRET)

                # Add signature to params
                params['signature'] = signature

                # Make API request
                headers = {
                    'X-MBX-APIKEY': EXCHANGE_API_KEY
                }

                try:
                    response = requests.post(
                        'https://api.binance.com/api/v3/order/oco',
                        params=params,
                        headers=headers,
                        timeout=10
                    )
                    response.raise_for_status()
                    oco_order = response.json()
                    self.log(f"✅ OCO order placed: Take Profit at {target_price}, Stop Loss at {stop_loss}")

                except requests.RequestException as e:
                    self.log(f"❌ Manual OCO order failed: {e}", "ERROR")
                    if hasattr(e, 'response') and e.response:
                        self.log(f"❌ Response: {e.response.text}", "ERROR")
                    return

            elif SELECTED_EXCHANGE == 'MEXC':
                # MEXC doesn't have native OCO, so place separate orders
                # Place take profit limit sell order
                try:
                    timestamp = int(time.time() * 1000)
                    tp_params = {
                        'symbol': pair.replace('/', ''),
                        'side': 'SELL',
                        'type': 'LIMIT',
                        'quantity': f"{quantity:.6f}",
                        'price': f"{target_price:.2f}",
                        'timestamp': timestamp
                    }

                    query_string = '&'.join([f"{k}={urllib.parse.quote(str(v))}" for k, v in sorted(tp_params.items())])
                    signature = hmac.new(EXCHANGE_API_SECRET.encode(), query_string.encode(), hashlib.sha256).hexdigest()
                    tp_params['signature'] = signature

                    headers = {
                        'X-MEXC-APIKEY': EXCHANGE_API_KEY,
                        'Content-Type': 'application/json'
                    }

                    response = requests.post(
                        'https://api.mexc.com/api/v3/order',
                        params=tp_params,
                        headers=headers,
                        timeout=10
                    )
                    response.raise_for_status()
                    tp_order = response.json()
                    self.log(f"✅ MEXC Take Profit limit order placed at {target_price}")

                except requests.RequestException as e:
                    self.log(f"❌ MEXC Take Profit order failed: {e}", "ERROR")

                # Place stop loss limit sell order (MEXC doesn't have stop_market like Binance)
                try:
                    timestamp = int(time.time() * 1000)
                    sl_params = {
                        'symbol': pair.replace('/', ''),
                        'side': 'SELL',
                        'type': 'LIMIT',
                        'quantity': f"{quantity:.6f}",
                        'price': f"{stop_loss:.2f}",
                        'timestamp': timestamp
                    }

                    query_string = '&'.join([f"{k}={urllib.parse.quote(str(v))}" for k, v in sorted(sl_params.items())])
                    signature = hmac.new(EXCHANGE_API_SECRET.encode(), query_string.encode(), hashlib.sha256).hexdigest()
                    sl_params['signature'] = signature

                    headers = {
                        'X-MEXC-APIKEY': EXCHANGE_API_KEY,
                        'Content-Type': 'application/json'
                    }

                    response = requests.post(
                        'https://api.mexc.com/api/v3/order',
                        params=sl_params,
                        headers=headers,
                        timeout=10
                    )
                    response.raise_for_status()
                    sl_order = response.json()
                    self.log(f"✅ MEXC Stop Loss limit order placed at {stop_loss}")

                except requests.RequestException as e:
                    self.log(f"❌ MEXC Stop Loss order failed: {e}", "ERROR")

            else:
                # For other exchanges, place separate orders (less ideal but functional)
                # Place take profit limit sell order
                tp_order = await EXCHANGE_CLIENT.createOrder(
                    symbol=pair,
                    type='limit',
                    side='sell',
                    amount=quantity,
                    price=target_price
                )
                self.log(f"✅ Take Profit limit order placed at {target_price}")

                # Place stop loss market sell order
                sl_order = await EXCHANGE_CLIENT.createOrder(
                    symbol=pair,
                    type='stop_market',
                    side='sell',
                    amount=quantity,
                    stopPrice=stop_loss
                )
                self.log(f"✅ Stop Loss order placed at {stop_loss}")

        except ccxt.InsufficientFunds as e:
            self.log(f"❌ Insufficient funds for OCO: {e}", "ERROR")
        except ccxt.InvalidOrder as e:
            self.log(f"❌ Invalid OCO order: {e}", "ERROR")
        except ccxt.ExchangeError as e:
            self.log(f"❌ Exchange error with OCO: {e}", "ERROR")
        except Exception as e:
            self.log(f"❌ Unknown error placing OCO order: {e}", "ERROR")

    async def refresh_signal_counts(self):
        """Refresh signal usage counts from server"""
        try:
            api_key = self.api_key_input.text().strip()
            if not api_key:
                return

            server_url = self.server_url_input.text()
            response = requests.get(f"{server_url}/api/validate", params={"api_key": api_key}, timeout=5)

            if response.status_code == 200:
                data = response.json()
                signals_remaining = data.get('signals_remaining', 0)
                signals_used = data.get('signals_used', 0)
                self.log(f"📊 Signal counts updated - Used: {signals_used}, Remaining: {signals_remaining}")
                self.status_bar.showMessage(f"Signals: {signals_remaining} left")
        except Exception as e:
            self.log(f"❌ Failed to refresh signal counts: {e}", "WARNING")

    async def start_http_polling(self):
        """HTTP polling for signals as backup to WebSocket"""
        while True:
            try:
                if self.auth_token:
                    # Poll for signals from supported pairs
                    for pair in SUPPORTED_PAIRS:
                        try:
                            api_key = self.api_key_input.text().strip()
                            exchange_api_key = self.exchange_api_key_input.text().strip()
                            exchange_api_secret = self.exchange_api_secret_input.text().strip()

                            if not api_key:
                                continue  # Skip if no API key

                            # Server uses its own API keys for market data analysis
                            params = {"api_key": api_key, "pair": pair}

                            response = requests.get(
                                f"{SERVER_URL}/api/live/signal",
                                params=params,
                                timeout=5
                            )

                            if response.status_code == 200:
                                signal = response.json()
                                await self.handle_signal(signal)
                            elif response.status_code == 204:
                                # No signal available
                                pass
                            else:
                                logger.warning(f"HTTP polling error for {pair}: {response.status_code}")

                        except requests.RequestException as e:
                            logger.debug(f"HTTP polling failed for {pair}: {e}")

                await asyncio.sleep(30)  # Poll every 30 seconds

            except Exception as e:
                logger.error(f"HTTP polling error: {e}")
                await asyncio.sleep(60)  # Wait longer on error

    def closeEvent(self, event):
        """Handle application close"""
        self.log("🛑 Application closing...")
        if self.ws_task:
            self.ws_task.cancel()
        if hasattr(self, 'http_task') and self.http_task:
            self.http_task.cancel()
        self.save_settings()
        event.accept()

# ===================== MAIN =====================
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("SelfTrade Client")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("SelfTrade")

    # Set application icon if available
    try:
        # You can add an icon file later
        pass
    except:
        pass

    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = TradeUI()
    window.show()

    with loop:
        loop.run_forever()


if __name__ == "__main__":
    main()
