# client/services/websocket_client.py - WebSocket client for real-time signals
import asyncio
import json
import logging
import websockets
from typing import Optional, Callable, List, Dict, Any
from threading import Thread

from client.config import WS_URL

logger = logging.getLogger(__name__)


class WebSocketClient:
    """WebSocket client for receiving real-time signals"""

    def __init__(self, ws_url: str = WS_URL, api_key: str = None):
        self.ws_url = ws_url
        self.api_key = api_key
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.connected = False
        self.running = False
        self._thread: Optional[Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Callbacks
        self.on_signal: Optional[Callable[[Dict], None]] = None
        self.on_connect: Optional[Callable[[], None]] = None
        self.on_disconnect: Optional[Callable[[str], None]] = None
        self.on_error: Optional[Callable[[Exception], None]] = None
        self.on_subscription_expired: Optional[Callable[[str], None]] = None  # Called when API key expires

        # Subscriptions
        self.subscribed_pairs: List[str] = []

    def set_api_key(self, api_key: str):
        """Set API key for authenticated connection"""
        self.api_key = api_key

    def connect(self, pairs: List[str] = None):
        """Start WebSocket connection in background thread"""
        if self.running:
            logger.warning("WebSocket already running")
            return

        self.subscribed_pairs = pairs or []
        self.running = True
        self._thread = Thread(target=self._run_async, daemon=True)
        self._thread.start()

    def disconnect(self):
        """Disconnect WebSocket"""
        self.running = False
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)

    def _run_async(self):
        """Run async event loop in thread"""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._connect_and_listen())
        except Exception as e:
            logger.error(f"WebSocket thread error: {e}")
        finally:
            self._loop.close()

    async def _connect_and_listen(self):
        """Connect and listen for messages"""
        # Use headers for API key authentication (more secure than URL params)
        extra_headers = {}
        if self.api_key:
            extra_headers['X-API-Key'] = self.api_key

        while self.running:
            try:
                async with websockets.connect(self.ws_url, extra_headers=extra_headers) as ws:
                    self.websocket = ws
                    self.connected = True
                    logger.info(f"WebSocket connected to {self.ws_url}")

                    if self.on_connect:
                        self.on_connect()

                    # Subscribe to pairs
                    if self.subscribed_pairs:
                        await ws.send(json.dumps({
                            'type': 'subscribe',
                            'pairs': self.subscribed_pairs
                        }))

                    # Listen for messages
                    await self._listen(ws)

            except websockets.ConnectionClosed as e:
                self.connected = False
                logger.warning(f"WebSocket connection closed: {e}")
                if self.on_disconnect:
                    self.on_disconnect(str(e))

            except Exception as e:
                self.connected = False
                logger.error(f"WebSocket error: {e}")
                if self.on_error:
                    self.on_error(e)

            # Reconnect delay
            if self.running:
                logger.info("Reconnecting in 5 seconds...")
                await asyncio.sleep(5)

    async def _listen(self, ws):
        """Listen for WebSocket messages"""
        try:
            async for message in ws:
                try:
                    data = json.loads(message)
                    await self._handle_message(data)
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON received: {message[:100]}")
        except websockets.ConnectionClosed:
            raise
        except Exception as e:
            logger.error(f"Error processing message: {e}")

    async def _handle_message(self, data: Dict[str, Any]):
        """Handle incoming WebSocket message"""
        msg_type = data.get('type')

        if msg_type == 'signal':
            signal = data.get('data', {})
            logger.info(f"Signal received: {signal.get('pair')} {signal.get('side')}")
            if self.on_signal:
                self.on_signal(signal)

        elif msg_type == 'heartbeat':
            logger.debug("Heartbeat received")

        elif msg_type == 'subscribed':
            logger.info(f"Subscribed to pairs: {data.get('pairs')}")

        elif msg_type == 'pong':
            logger.debug("Pong received")

        elif msg_type == 'exchange_set':
            exchange = data.get('exchange', 'unknown')
            logger.info(f"Server exchange set to: {exchange}")

        elif msg_type == 'portfolio_updated':
            positions_count = data.get('positions_count', 0)
            balance = data.get('balance', 0)
            logger.debug(f"Server portfolio updated: {positions_count} positions, ${balance:.2f}")

        elif msg_type == 'error':
            error_msg = data.get('message', 'Unknown error')
            logger.error(f"Server error: {error_msg}")
            if self.on_error:
                self.on_error(Exception(error_msg))

        elif msg_type == 'unauthorized' or msg_type == 'subscription_expired':
            # API key expired or invalid
            error_msg = data.get('message', 'Subscription expired or API key invalid')
            logger.warning(f"Subscription expired: {error_msg}")
            if self.on_subscription_expired:
                self.on_subscription_expired(error_msg)

    async def send_message(self, message: Dict):
        """Send message to server"""
        if self.websocket and self.connected:
            await self.websocket.send(json.dumps(message))

    def subscribe(self, pairs: List[str]):
        """Subscribe to trading pairs"""
        self.subscribed_pairs = pairs
        if self.connected and self._loop:
            asyncio.run_coroutine_threadsafe(
                self.send_message({'type': 'subscribe', 'pairs': pairs}),
                self._loop
            )

    def request_signal(self, pair: str):
        """Request signal for a specific pair"""
        if self.connected and self._loop:
            asyncio.run_coroutine_threadsafe(
                self.send_message({'type': 'get_signal', 'pair': pair}),
                self._loop
            )

    def set_exchange(self, exchange: str):
        """Set exchange preference for signal generation (e.g., 'mexc', 'binance')"""
        if self.connected and self._loop:
            logger.info(f"Setting server exchange to: {exchange}")
            asyncio.run_coroutine_threadsafe(
                self.send_message({'type': 'set_exchange', 'exchange': exchange}),
                self._loop
            )

    def update_portfolio(self, positions: Dict[str, Any], balance: float = 0):
        """
        Send portfolio info to server for smart signal filtering.

        positions: Dict of pair -> position info (side, thesis, entry_price, etc.)
        balance: Available USDT balance
        """
        if self.connected and self._loop:
            logger.debug(f"Updating server portfolio: {len(positions)} positions, ${balance:.2f}")
            asyncio.run_coroutine_threadsafe(
                self.send_message({
                    'type': 'update_portfolio',
                    'positions': positions,
                    'balance': balance
                }),
                self._loop
            )
