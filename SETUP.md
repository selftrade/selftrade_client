# SelfTrade Client - Complete Setup Guide

## Table of Contents
- [System Requirements](#system-requirements)
- [Installation](#installation)
- [Exchange API Setup](#exchange-api-setup)
- [IP Whitelisting](#ip-whitelisting)
- [Client Configuration](#client-configuration)
- [Running the Client](#running-the-client)
- [Security Best Practices](#security-best-practices)
- [Troubleshooting](#troubleshooting)

---

## System Requirements

- **OS**: Windows 10/11, macOS 10.15+, or Linux (Ubuntu 20.04+)
- **Python**: 3.10 or higher
- **RAM**: 4GB minimum
- **Internet**: Stable connection required

### Python Dependencies
```
PyQt6>=6.4.0
ccxt>=4.0.0
websockets>=10.0
qasync>=0.23.0
requests>=2.28.0
python-dotenv>=1.0.0
```

---

## Installation

### Option 1: Clone from GitHub
```bash
git clone https://github.com/selftrade/selftrade_client.git
cd selftrade_client
pip install -r client_requirements.txt
```

### Option 2: Download ZIP
1. Go to https://github.com/selftrade/selftrade_client
2. Click "Code" → "Download ZIP"
3. Extract and open terminal in the folder
4. Run `pip install -r client_requirements.txt`

### Verify Installation
```bash
python client.py --version
```

---

## Exchange API Setup

### Binance

1. **Login** to [Binance](https://www.binance.com)
2. Go to **Profile** → **API Management**
3. Click **Create API** → Select **System generated**
4. Complete 2FA verification
5. **Configure Permissions**:
   - ✅ Enable Spot & Margin Trading
   - ✅ Enable Futures (if using futures)
   - ❌ Disable Withdrawals (IMPORTANT!)
6. **Restrict IP Access** (see IP Whitelisting below)
7. Copy your **API Key** and **Secret Key**

### MEXC

1. **Login** to [MEXC](https://www.mexc.com)
2. Go to **Account** → **API Management**
3. Click **Create API Key**
4. Complete verification
5. **Set Permissions**:
   - ✅ Spot Trading
   - ❌ Withdrawals disabled
6. Add IP whitelist
7. Copy your **Access Key** and **Secret Key**

### Bybit

1. **Login** to [Bybit](https://www.bybit.com)
2. Go to **Account & Security** → **API**
3. Click **Create New Key**
4. Select **API Transaction**
5. **Set Permissions**:
   - ✅ Spot Trading
   - ❌ Withdrawals disabled
6. Add IP whitelist
7. Copy your **API Key** and **Secret Key**

---

## IP Whitelisting

**CRITICAL**: Most exchanges require IP whitelisting for API trading.

### Step 1: Find Your Public IP
1. Open browser and go to https://whatismyip.com
2. Note your **IPv4 address** (e.g., `203.45.67.89`)

### Step 2: Add IP to Exchange

#### Binance
1. API Management → Select your API key
2. "IP Access Restrictions" → "Restrict to trusted IPs only"
3. Add your IP address
4. Confirm with 2FA

#### MEXC
1. API Management → Edit your API key
2. Add IP to whitelist
3. Save changes

#### Bybit
1. API Management → Edit your API key
2. IP Whitelist → Add your IP
3. Confirm

### Important Notes
- **Dynamic IP**: If your ISP assigns dynamic IPs, you may need to update regularly
- **VPN Users**: Whitelist your VPN's IP, not your home IP
- **Multiple Locations**: Add all IPs you'll trade from
- **Changes take 1-5 minutes** to propagate

---

## Client Configuration

### First Run Setup

1. **Launch the client**:
   ```bash
   python client.py
   ```

2. **Enter SelfTrade API Key**:
   - Get from https://www.selftrade.site after registration
   - Paste in the "Server API Key" field

3. **Select Exchange**:
   - Choose Binance, MEXC, or Bybit

4. **Enter Exchange Credentials**:
   - API Key
   - Secret Key

5. **Trading Settings**:
   - **Pair**: Select trading pair (BTC/USDT, ETH/USDT, etc.)
   - **Risk %**: Percentage of balance per trade (1-5% recommended)
   - **Auto-Trade**: Enable/disable automatic execution

### Settings Storage
Settings are saved locally in `settings.ini`. Your credentials are stored on YOUR computer only - never sent to SelfTrade servers.

---

## Running the Client

### Start Trading
```bash
python client.py
```

### GUI Mode (Default)
- Full graphical interface
- Real-time signal display
- Position management
- Trade history

### Headless Mode (Advanced)
```bash
python -m client.main --headless
```

---

## Security Best Practices

### API Key Security
- ✅ **Never enable withdrawals** on trading API keys
- ✅ **Always whitelist IPs**
- ✅ **Use separate API keys** for each application
- ✅ **Rotate keys periodically** (every 3-6 months)

### Local Security
- ✅ Keep your computer secure (antivirus, firewall)
- ✅ Don't share your `settings.ini` file
- ✅ Use strong passwords for your exchange accounts
- ✅ Enable 2FA on all exchange accounts

### What SelfTrade CAN'T Do
- ❌ Access your exchange funds
- ❌ Make withdrawals
- ❌ See your API secret (only you have it)
- ❌ Trade without your client running

---

## Troubleshooting

### "Invalid API Key" Error
**Cause**: SelfTrade API key is incorrect or expired
**Fix**:
1. Login to selftrade.site
2. Check your API key in dashboard
3. Verify subscription is active

### "Signature for this request is not valid"
**Cause**: Exchange API issue
**Fix**:
1. Verify IP is whitelisted
2. Check API key and secret are correct
3. Ensure clock is synchronized (`timedatectl set-ntp true` on Linux)

### "Insufficient Balance"
**Cause**: Not enough funds for trade
**Fix**:
1. Check your exchange balance
2. Lower your risk percentage
3. Ensure funds are in Spot wallet (not Futures)

### "Connection Refused"
**Cause**: Network issue
**Fix**:
1. Check internet connection
2. Verify selftrade.site is accessible
3. Check if firewall is blocking

### Client Crashes on Start
**Cause**: Missing dependencies
**Fix**:
```bash
pip install --upgrade -r client_requirements.txt
```

### No Signals Received
**Cause**: WebSocket connection issue
**Fix**:
1. Check internet connection
2. Restart the client
3. Verify API key is valid

---

## Support

- **Website**: https://www.selftrade.site
- **Guide**: https://www.selftrade.site/guide
- **GitHub Issues**: https://github.com/selftrade/selftrade_client/issues
