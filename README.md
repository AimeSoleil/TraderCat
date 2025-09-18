# TraderCat

A multi-symbol, multi-strategy, and schedulable quantitative trading bot.

## Directory Structure

```bash
TraderCat/
├── main.py
├── trade_bot/
│   └── ... (strategies, data, execution, notification modules, etc.)
├── pyproject.toml
├── requirements.txt
└── README.md
```

## Environment Setup

1. **Install Python 3.10+**

2. **Install main dependencies and CLI tool (recommended via pyproject.toml)**

   ```bash
   pip install .
   # if need to generate requirements.txt, 
   pip install .  # Installs main dependencies
   pip freeze | grep -v "tradercat" > requirements.txt
   ```

   > After installation, the `tradercat` command will be automatically added to your PATH (such as `~/.local/bin/` or your virtual environment's `bin/` directory).

3. **(Optional) Install development dependencies**

   ```bash
   pip install ".[dev]"
   ```

4. **(Optional) Set up Discord notifications**  
   Before running, set the environment variable `DISCORD_WEBHOOK_URL`, for example:  
   `export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/your_webhook_url"`  
   You can add this line to your `~/.bashrc`, `~/.zshrc`, or set it manually before running the command.

## Command Line Usage

### Run directly

```bash
tradercat -m once -s "AAPL,MSFT"
```

Parameter description:

- `-m` or `--mode`: `once` (run once) or `schedule` (run every day at 16:00 US Eastern Time)
- `-s` or `--symbols`: Comma-separated list of stock symbols, e.g. `"AAPL,MSFT,GOOG"`
- `-f` or `--symbols-file`: External config file (txt/yaml), one symbol per line or a yaml file with a `symbols` list

### Examples

```bash
tradercat -m once -s "AAPL,MSFT"
tradercat -m schedule -f symbols.txt
```

## Configuring Stock Symbols

- Use the `-s` parameter to input directly
- Or use `-f` to specify a txt/yaml file (e.g. `symbols.txt` with one symbol per line, or `symbols.yaml` with structure `symbols: [AAPL, MSFT, ...]`)

## Notification Configuration

This project supports sending notifications via Discord Webhook. Please make sure you have created a webhook in Discord and provide its URL to the program via the `DISCORD_WEBHOOK_URL` environment variable.

```bash
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/your_webhook_url"
tradercat -m once -s "AAPL,MSFT"
```

## Other Notes

- Supports multiple notification methods (such as Discord, Slack, Telegram, etc.). Please configure the relevant parameters in `trade_bot/notification/`.
- Supports multi-strategy combinations, which can be customized in `main.py`.
- Supports exception logging; errors for individual symbols will not affect the operation of others.

---

If you have any questions, feel free to open an Issue or PR.