# TraderCat 🐱📈

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
![Python Version](https://img.shields.io/badge/python-3.10%2B-blue)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Maintenance](https://img.shields.io/badge/Maintained%3F-yes-green.svg)](https://github.com/AimeSoleil/TraderCat/graphs/commit-activity)

**TraderCat** is a robust, asynchronous quantitative trading bot and terminal. It combines traditional algorithmic indicators with **Generative AI** analysis to provide deep market insights. It leverages **OpenBB** for high-quality market data and offers a flexible plugin architecture for custom strategies and AI personalities.

## 🚀 Features

*   **🧠 AI Analyst Core**: Chat with specialized AI personas (e.g., "Warren Buffett", "Wyckoff") about any stock.
*   **🤖 Multi-Model Support**: Plug-and-play support for GitHub Models (Azure AI), OpenAI, and more.
*   **⚡ AsyncIO Architecture**: Efficiently process hundreds of symbols concurrently for traditional algo-trading.
*   **📊 Multi-Strategy Engine**: Run technical strategies (Bollinger, Patterns, Momentum) alongside AI analysis.
*   **💬 Interactive Chat**: Don't just get a report—ask follow-up questions to the AI about the chart.
*   **🛠️ Modular Design**: Clean separation between Data, Strategy, AI Providers, and Execution layers.
*   **📈 Backtesting Engine**: Built-in framework to test algorithmic strategies against historical data.

## 📂 Project Structure

The project follows a modern Python `src` layout:

```text
TraderCat/
├── src/
│   └── tradercat/           # Core Package
│       ├── ai/              # AI Subsystem (Providers, Analysts, Prompts)
│       ├── bot.py           # Algo Trading Bot Logic
│       ├── core/            # Core Session Runners
│       ├── data/            # Data Providers (OpenBB)
│       ├── strategy/        # Algorithmic Strategies
│       └── utils/           # Helper Utilities
├── tests/                   # Unit Tests
├── pyproject.toml           # Project Configuration
└── README.md                # Documentation
```

## 🛠️ Installation

### Prerequisites
*   Python 3.10+
*   [Optional] Virtual Environment (recommended)

### Setup

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/AimeSoleil/TraderCat.git
    cd TraderCat
    ```

2.  **Install in Editable Mode:**
    This installs the project and its dependencies while allowing you to edit the code without reinstalling.
    ```bash
    pip install -e .
    ```

3.  **Install Development Dependencies (Optional):**
    For running tests or contributing.
    ```bash
    pip install -e ".[dev]"
    ```

## ⚙️ Configuration

### Environment Variables
Create a `.env` file or export these variables in your shell:

*   `DISCORD_WEBHOOK_URL`: (Optional) URL for Discord notifications.
*   `ENV_SYMBOLS`: (Optional) Default comma-separated list of symbols (e.g., "AAPL,MSFT").

### Symbol Configuration
You can provide symbols via:
1.  **CLI Argument**: `-s "AAPL,MSFT"`
2.  **File**: `-f symbols.txt` (One symbol per line) or `symbols.yaml` (`symbols: [...]`)
3.  **Environment Variable**: `ENV_SYMBOLS`

## 🖥️ Usage

After installation, the `tradercat` command is available in your terminal.

### Commands

*   `tradercat run`: Start the trading bot session.
*   `tradercat help`: Show help information.

### Run Once (Immediate Execution)

```bash
# Display Help
tradercat help

# Run for specific symbols
tradercat run -s "AAPL,MSFT,GOOG"

# Run using a symbols file
tradercat run -f symbols.yml

# Run only Single Asset strategies
tradercat run -f symbols.yml --scope single

# Run only Portfolio strategies (No symbols file required)
tradercat run --scope portfolio
```

### Automation (Cron / Systemd)

Since the internal scheduler has been removed in favor of robust system-level tools, use **Cron** (Linux/macOS) to schedule daily runs.

**Example Crontab:**

```cron
# Set Timezone to ensure 5:00 PM is always New York time
CRON_TZ=America/New_York

# 1. Daily Swing Trading Signals (Mon-Fri at 5:00 PM)
# Logs are saved with date suffix (NOTE: % must be escaped with \ in crontab)
0 17 * * 1-5 cd /path/to/TraderCat && /path/to/python -m tradercat run -f symbols.yml --scope single >> logs/daily_swing_$(date +\%Y-\%m-\%d).log 2>&1

# 2. Weekly Portfolio Rebalancing (Fridays at 5:00 PM)
# Runs sector rotation strategies (No symbols file needed)
0 17 * * 5 cd /path/to/TraderCat && /path/to/python -m tradercat run --scope portfolio >> logs/weekly_portfolio_$(date +\%Y-\%m-\%d).log 2>&1
```

### CLI Options (for `run` command)

| Option | Long Option | Description | Default |
| :--- | :--- | :--- | :--- |
| `-s` | `--symbols` | Comma-separated list of symbols (e.g., `AAPL,TSLA`). | `None` |
| `-f` | `--symbols-file` | Path to a `.txt` or `.yaml` file containing symbols. | `None` |
| `-c` | `--concurrency` | Max number of bots running at the same time. | `5` |
| `-S` | `--stagger` | Seconds to wait between starting bots (prevents API rate limits). | `2` |
|| `--scope` | Execution scope: `all` (default), `single`, or `portfolio`. | `all` |

## 🧠 Strategies

TraderCat comes with several built-in strategies located in `src/tradercat/strategy/`:

*   **Candlestick Patterns**: Detects patterns like Hammer, Engulfing, Morning Star, etc.
*   **Bollinger Bands**: Breakout and Reversal strategies.
*   **Momentum**: RSI and other momentum-based indicators.
*   **Sector Rotation**: Analyzes sector performance to find rotation opportunities.
*   **Fibonacci Retracement**: Identifies potential support/resistance levels.
*   **Divergence**: Detects divergence between price and indicators.

## 📈 Backtesting

TraderCat includes a built-in backtesting engine to evaluate your strategies against historical data.

### Running a Backtest

1.  **Configure**: Open `src/tradercat/backtest/main.py` and modify the `BacktestConfig` class to set your desired parameters:
    *   `start_date` / `end_date`
    *   `initial_cash`
    *   `target_symbols` (e.g., `["AAPL", "TSLA"]`)
    *   `active_strategies` (Select which strategies and presets to test)

2.  **Run**: Execute the backtest module:
    ```bash
    python -m tradercat.backtest.main
    ```

3.  **Analyze**: The engine will simulate trading and output a performance report, including:
    *   Final Portfolio Value
    *   Net Profit
    *   Win Rate
    *   Max Drawdown
    *   Trade Logs

## 🧪 Testing

Run the unit test suite to ensure everything is working correctly.

```bash
# Run all tests
pytest

# Run specific tests (e.g., candle patterns)
pytest tests/strategy/candle_pattern/detectors
```

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1.  Fork the project.
2.  Create your feature branch (`git checkout -b feature/AmazingFeature`).
3.  Commit your changes (`git commit -m 'Add some AmazingFeature'`).
4.  Push to the branch (`git push origin feature/AmazingFeature`).
5.  Open a Pull Request.

## 📄 License

Distributed under the MIT License. See `LICENSE` for more information.