#!/usr/bin/env python3
"""AutoChat — 基于 NapCat OneBot 的 AI 自动聊天机器人"""

import asyncio
import logging
import sys
from pathlib import Path

from src.bot import AutoBot
from src.config_manager import ConfigManager


def setup_logging(log_config: dict):
    level = getattr(logging, log_config.get("level", "INFO").upper(), logging.INFO)
    log_file = log_config.get("file", "logs/bot.log")

    handlers = [logging.StreamHandler(sys.stdout)]
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )


def main():
    cfg_mgr = ConfigManager("config")
    config = cfg_mgr.load()

    setup_logging(config.get("log", {}))
    logger = logging.getLogger("autochat")
    logger.info("=" * 50)
    logger.info("AutoChat 启动中...")

    bot = AutoBot(config)

    try:
        asyncio.run(bot.start())
    except KeyboardInterrupt:
        logger.info("收到中断信号")
        asyncio.run(bot.stop())
    except Exception as e:
        logger.exception("启动失败: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
