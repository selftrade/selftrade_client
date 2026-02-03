# Quick Start Guide

Get up and running with SelfTrade Client in 5 minutes.

## Prerequisites

- Python 3.10 or higher
- A SelfTrade account ([Sign up here](https://www.selftrade.site))
- Exchange API keys (Binance, MEXC, or Bybit)

## Step 1: Install

```bash
# Clone the repository
git clone https://github.com/selftrade/selftrade_client.git
cd selftrade_client

# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r client_requirements.txt
```

## Step 2: Get Your SelfTrade API Key

1. Go to [selftrade.site](https://www.selftrade.site)
2. Register or login to your account
3. Copy your API key from the dashboard

## Step 3: Configure Exchange API

Create your exchange API keys with these permissions:
- **Spot Trading**: Enabled
- **Futures Trading**: Enabled (optional)
- **Withdrawals**: DISABLED (for safety)

### Binance
1. Go to [Binance API Management](https://www.binance.com/en/my/settings/api-management)
2. Create new API key
3. Enable "Spot & Margin Trading"
4. Whitelist your IP address

### MEXC
1. Go to Account → API Keys
2. Create new API key
3. Enable "Spot Trading"

### Bybit
1. Go to Account → API
2. Create new API key
3. Enable "Spot Trading"

## Step 4: Run the Client

```bash
python client.py
```

## Step 5: Configure in the App

1. Enter your **SelfTrade API Key**
2. Select your **Exchange** (Binance/MEXC/Bybit)
3. Enter your **Exchange API Key** and **Secret**
4. Select trading **Pair** (BTC/USDT, ETH/USDT, etc.)
5. Set your **Risk %** (1-5% recommended)
6. Click **Connect**

## Step 6: Start Trading

- **Manual Mode**: Review signals and click to execute
- **Auto Mode**: Enable auto-trading to execute signals automatically

## Supported Trading Pairs

| Pair | Symbol |
|------|--------|
| Bitcoin | BTC/USDT |
| Ethereum | ETH/USDT |
| BNB | BNB/USDT |
| Cardano | ADA/USDT |
| Solana | SOL/USDT |

## Safety Tips

1. **Start Small**: Test with minimum trade amounts first
2. **Use Stop Loss**: Always enabled by default
3. **Monitor**: Watch the first few trades
4. **Risk Management**: Don't risk more than 1-2% per trade

## Troubleshooting

### "Invalid API Key" Error
- Verify your SelfTrade API key is correct
- Check your subscription status at selftrade.site

### "Signature Invalid" Error
- Your IP may not be whitelisted on the exchange
- Check your exchange API key permissions

### Connection Issues
- Check your internet connection
- Verify selftrade.site is accessible

## Need Help?

- Website: [selftrade.site](https://www.selftrade.site)
- Guide: [selftrade.site/guide](https://www.selftrade.site/guide)
