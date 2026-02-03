# client/services/server_client.py - HTTP API client for SelfTrade server
import requests
import logging
from typing import Optional, Dict, Any

from client.config import SERVER_URL

logger = logging.getLogger(__name__)


class ServerClient:
    """HTTP client for SelfTrade server API"""

    def __init__(self, server_url: str = SERVER_URL):
        self.server_url = server_url.rstrip("/")
        self.access_token: Optional[str] = None
        self.api_key: Optional[str] = None
        self.session = requests.Session()

    def set_auth(self, access_token: str, api_key: str):
        """Set authentication credentials"""
        self.access_token = access_token
        self.api_key = api_key
        self.session.headers.update({"Authorization": f"Bearer {access_token}"})

    def login(self, username: str, password: str) -> Dict[str, Any]:
        """Login and get access token"""
        try:
            response = self.session.post(
                f"{self.server_url}/login",
                data={"username": username, "password": password},
                timeout=10
            )
            response.raise_for_status()
            data = response.json()

            self.access_token = data.get("access_token")
            self.api_key = data.get("user", {}).get("api_key")
            self.session.headers.update({"Authorization": f"Bearer {self.access_token}"})

            logger.info(f"Logged in successfully as {username}")
            return data

        except requests.RequestException as e:
            logger.error(f"Login failed: {e}")
            raise

    def register(self, email: str, username: str, password: str) -> Dict[str, Any]:
        """Register a new user"""
        try:
            response = self.session.post(
                f"{self.server_url}/register",
                json={"email": email, "username": username, "password": password},
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            logger.info(f"Registered successfully as {username}")
            return data

        except requests.RequestException as e:
            logger.error(f"Registration failed: {e}")
            raise

    def get_profile(self) -> Dict[str, Any]:
        """Get current user profile"""
        try:
            response = self.session.get(f"{self.server_url}/profile", timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Failed to get profile: {e}")
            raise

    def validate_api_key(self, api_key: str = None) -> Dict[str, Any]:
        """Validate API key"""
        key = api_key or self.api_key
        if not key:
            raise ValueError("No API key provided")

        try:
            response = self.session.get(
                f"{self.server_url}/api/validate",
                params={"api_key": key},
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"API key validation failed: {e}")
            raise

    def get_live_signal(self, pair: str = "BTCUSDT") -> Dict[str, Any]:
        """Get live trading signal for a pair"""
        if not self.api_key:
            raise ValueError("Not authenticated. Login first.")

        try:
            response = self.session.get(
                f"{self.server_url}/api/live/signal",
                params={"pair": pair, "api_key": self.api_key},
                timeout=15
            )

            # Check for unauthorized (expired API key)
            if response.status_code == 401:
                error_detail = "Unauthorized"
                try:
                    error_data = response.json()
                    error_detail = error_data.get('detail', 'API key expired or invalid')
                except:
                    pass
                raise SubscriptionExpiredError(error_detail)

            response.raise_for_status()
            return response.json()
        except SubscriptionExpiredError:
            raise
        except requests.RequestException as e:
            logger.error(f"Failed to get signal: {e}")
            raise


class SubscriptionExpiredError(Exception):
    """Raised when API key is expired or invalid"""
    pass

    def use_signal(self) -> Dict[str, Any]:
        """Decrement signal count after trade"""
        if not self.api_key:
            raise ValueError("Not authenticated")

        try:
            response = self.session.post(
                f"{self.server_url}/api/use_signal",
                params={"api_key": self.api_key},
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Failed to use signal: {e}")
            raise

    def get_supported_pairs(self) -> Dict[str, Any]:
        """Get list of supported trading pairs"""
        try:
            response = self.session.get(
                f"{self.server_url}/api/supported_pairs",
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Failed to get supported pairs: {e}")
            raise

    def create_payment(self, plan: str) -> Dict[str, Any]:
        """Create payment invoice for subscription"""
        try:
            response = self.session.post(
                f"{self.server_url}/create-payment",
                json={"plan": plan},
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Failed to create payment: {e}")
            raise

    def health_check(self) -> bool:
        """Check if server is healthy"""
        try:
            response = self.session.get(f"{self.server_url}/health", timeout=5)
            return response.status_code == 200
        except Exception:
            return False
