# TraderCat

一个支持多标的、多策略、可定时运行的量化交易机器人。

## 目录结构

```bash
TraderCat/
├── main.py
├── trade_bot/
│   └── ...（策略、数据、执行、通知等模块）
├── pyproject.toml
├── requirements.txt
└── README.md
```

## 环境准备

1. **安装 Python 3.10+**

2. **安装主依赖和命令行工具（推荐用 pyproject.toml）**

   ```bash
   pip install .
   ```

   > 安装后会自动生成 `tradercat` 命令到你的 PATH（如 `~/.local/bin/` 或虚拟环境的 `bin/` 目录）。

3. **（可选）安装开发依赖**

   ```bash
   pip install ".[dev]"
   ```

4. **（可选）设置Discord通知**
   在运行前，请先设置环境变量 DISCORD_WEBHOOK_URL，例如：`export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/your_webhook_url"`
   你可以将这行命令加入到 ~/.bashrc、~/.zshrc 等 shell 配置文件中，或在运行命令前手动设置。

## 命令行用法

### 直接运行

```bash
tradercat -m once -s "AAPL,MSFT"
```

参数说明：

- `-m` 或 `--mode`：`once`（只运行一次）或 `schedule`（每天美东时间16:00定时运行）
- `-s` 或 `--symbols`：逗号分隔的股票代码列表，如 `"AAPL,MSFT,GOOG"`
- `-f` 或 `--symbols-file`：外部配置文件（txt/yaml），每行一个或 yaml 格式的 symbols 列表

### 示例

```bash
tradercat -m once -s "AAPL,MSFT"
tradercat -m schedule -f symbols.txt
```

## 配置股票代码

- 直接用 `-s` 参数输入
- 或用 `-f` 指定 txt/yaml 文件（如 `symbols.txt` 每行一个，或 `symbols.yaml` 结构为 `symbols: [AAPL, MSFT, ...]`）

## 通知配置

本项目支持通过 Discord Webhook 发送通知。请确保你已在 Discord 创建 webhook，并将其 URL 通过环境变量 DISCORD_WEBHOOK_URL 提供给程序。

```bash
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/your_webhook_url"
tradercat -m once -s "AAPL,MSFT"
```

## 其他说明

- 支持多种通知方式（如 Discord、Slack、Telegram 等），请在 `trade_bot/notification/` 下配置相关参数。
- 支持多策略组合，可在 `main.py` 中自定义策略列表。
- 支持异常日志输出，单个标的出错不会影响其他标的运行。

---

如有问题欢迎提 Issue 或 PR