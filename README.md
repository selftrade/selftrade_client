# SelfTrade Client

Desktop trading client for [SelfTrade.site](https://www.selftrade.site) - AI-powered crypto trading signals.

## Features

- **Real-time Signals**: Receive live BUY/SELL signals for BTC, ETH, BNB, ADA, SOL
- **Auto-Trading**: Execute trades automatically on your exchange
- **Multi-Exchange**: Supports Binance, MEXC, Bybit
- **Your Keys, Your Control**: Trades execute locally on your computer
- **No Fund Access**: We never have access to your exchange funds

## Security

This client runs **entirely on your computer**. Your exchange API keys are stored locally and never sent to our servers. The only communication with SelfTrade.site is to receive trading signals.

## Installation

### Requirements
- Python 3.10+
- PyQt6

### Setup

```bash
# Clone the repository
git clone https://github.com/selftrade/selftrade_client.git
cd selftrade_client

# Install dependencies
pip install -r client_requirements.txt

# Run the client
python client.py
```

## Configuration

1. Get your API key from [SelfTrade.site](https://www.selftrade.site)
2. Enter your exchange API credentials in the client
3. Select your trading pair and risk settings
4. Enable auto-trading or trade manually

## Supported Exchanges

| Exchange | Spot | Futures |
|----------|------|---------|
| Binance  | Yes  | Yes     |
| MEXC     | Yes  | Yes     |
| Bybit    | Yes  | Yes     |

## Quick Start

See [QUICK_START.md](QUICK_START.md) for detailed setup instructions.

## License

MIT License - See LICENSE file for details.

## Support

- Website: [selftrade.site](https://www.selftrade.site)
- Guide: [selftrade.site/guide](https://www.selftrade.site/guide)
