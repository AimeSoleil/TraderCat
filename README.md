# TraderCat 🐱📈

**TraderCat** is a robust, asynchronous quantitative trading bot and backtesting framework designed for multi-symbol and multi-strategy execution. It leverages the power of **OpenBB** for market data and provides a flexible architecture for implementing custom trading strategies.

## 🚀 Features

*   **Multi-Strategy Support**: Run multiple strategies simultaneously (e.g., Bollinger Bands, Candlestick Patterns, Momentum, Sector Rotation).
*   **AsyncIO Architecture**: Efficiently process hundreds of symbols concurrently using Python's `asyncio`.
*   **Modular Design**: Clean separation of concerns between Data, Strategy, Execution, and Notification layers.
*   **Backtesting Engine**: Built-in framework to test strategies against historical data.
*   **Notifications**: Integrated Discord support for real-time trade alerts.
*   **Scheduling**: Built-in scheduler to run jobs at specific market times (e.g., market close).
*   **OpenBB Integration**: Uses the OpenBB SDK for high-quality financial data.

## 📂 Project Structure

The project follows a modern Python `src` layout:

```text
TraderCat/
├── src/
│   └── tradercat/           # Core Package
│       ├── bot.py           # Main Bot Logic
│       ├── backtest/        # Backtesting Engine
│       ├── data/            # Data Providers (OpenBB)
│       ├── execution/       # Trade Execution Logic
│       ├── logger/          # Logging Configuration
│       ├── notification/    # Notification Services (Discord)
│       ├── strategy/        # Trading Strategies & Signal Generators
│       └── utils/           # Helper Utilities
├── tests/                   # Unit Tests
├── pyproject.toml           # Project Configuration & Dependencies
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

### Run Once (Immediate Execution)
Run the bot immediately for a specific set of symbols.

```bash
tradercat -m once -s "AAPL,MSFT,GOOG"
```

### Run with Scheduler
Schedule the bot to run daily (default is 16:00 US Eastern Time).

```bash
tradercat -m schedule -f symbols.txt
```

### CLI Options

| Option | Long Option | Description | Default |
| :--- | :--- | :--- | :--- |
| `-m` | `--mode` | Run mode: `once` (immediate) or `schedule` (daily loop). | `once` |
| `-s` | `--symbols` | Comma-separated list of symbols (e.g., `AAPL,TSLA`). | `None` |
| `-f` | `--symbols-file` | Path to a `.txt` or `.yaml` file containing symbols. | `None` |
| `-H` | `--schedule-hour` | **(Schedule Mode)** Hour (0-23) to run in US/Eastern time. | `16` (4 PM) |
| `-M` | `--schedule-minute` | **(Schedule Mode)** Minute (0-59) to run. | `0` |
| `-c` | `--concurrency` | Max number of bots running at the same time. | `5` |
| `-S` | `--stagger` | Seconds to wait between starting bots (prevents API rate limits). | `5` |

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