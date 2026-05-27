#!/usr/bin/env python3
"""
AutoChat — 基于 NapCat OneBot 的 AI 自动聊天机器人
"""

import json
import logging
import sys
from pathlib import Path

from src.bot import AutoBot


def setup_logging(log_config: dict):
    """配置日志"""
    level = getattr(logging, log_config.get("level", "INFO").upper(), logging.INFO)
    log_file = log_config.get("file", "logs/bot.log")

    handlers = [
        logging.StreamHandler(sys.stdout),
    ]

    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )


def load_config(config_path: str = "config/config.json") -> dict:
    """加载配置文件"""
    path = Path(config_path)
    if not path.exists():
        print(f"配置文件不存在: {config_path}")
        sys.exit(1)

    with open(path, encoding="utf-8") as f:
        config = json.load(f)

    # 加载本地覆盖配置
    local_path = path.with_stem(path.stem + ".local")
    if local_path.exists():
        with open(local_path, encoding="utf-8") as f:
            local_config = json.load(f)
        _deep_merge(config, local_config)

    return config


def _deep_merge(base: dict, override: dict):
    """递归合并配置"""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def main():
    config = load_config()
    setup_logging(config.get("log", {}))

    logger = logging.getLogger("autochat")
    logger.info("AutoChat 启动中...")

    bot = AutoBot(config)
    bot.run()


if __name__ == "__main__":
    main()
