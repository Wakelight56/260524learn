import asyncio
import logging

from .ai import OpenAIProvider, ClaudeProvider
from .handlers.message import MessageHandler
from .onebot import OneBotClient

logger = logging.getLogger("autochat.bot")


class AutoBot:
    """AutoChat 机器人主控"""

    def __init__(self, config: dict):
        self.config = config
        self.onebot = OneBotClient(config.get("onebot", {}))
        self.ai = self._init_ai()
        self.handler = MessageHandler(config, self.ai)

    def _init_ai(self):
        """初始化 AI 提供商"""
        ai_config = self.config.get("ai", {})
        provider = ai_config.get("provider", "openai")
        logger.info("初始化 AI 提供商: %s", provider)

        if provider == "claude":
            return ClaudeProvider(ai_config.get("claude", {}))
        return OpenAIProvider(ai_config.get("openai", {}))

    async def start(self):
        """启动机器人"""
        await self.onebot.connect()

        # 注册消息处理器
        self.onebot.on_message(lambda msg: self.handler.handle(msg, self.onebot.send_msg))

        logger.info("AutoChat 机器人已启动")
        await self.onebot.listen()

    async def stop(self):
        """停止机器人"""
        await self.onebot.close()
        logger.info("AutoChat 机器人已停止")

    def run(self):
        """运行入口"""
        try:
            asyncio.run(self._run())
        except KeyboardInterrupt:
            logger.info("收到中断信号")

    async def _run(self):
        while True:
            try:
                await self.start()
            except (ConnectionError, ConnectionRefusedError):
                logger.warning("连接失败，10秒后重试...")
                await asyncio.sleep(10)
            except Exception as e:
                logger.error("运行异常: %s", e)
                await asyncio.sleep(5)
            else:
                break
