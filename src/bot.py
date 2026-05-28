"""AutoChat 主控 — 连接平台、事件总线、Pipeline、插件"""

import asyncio
import json
import logging
from pathlib import Path

from src.config_manager import ConfigManager
from src.event_bus import EventBus
from src.emotion.tracker import EmotionTracker
from src.knowledge.retriever import StoryRetriever
from src.pipeline.scheduler import PipelineScheduler
from src.pipeline.stages.waking import WakingStage
from src.pipeline.stages.permission import PermissionStage
from src.pipeline.stages.rate_limit import RateLimitStage
from src.pipeline.stages.process import AIProcessStage
from src.pipeline.stages.decorate import DecorateStage
from src.platform.sources.napcat import NapCatAdapter
from src.platform.event import MessageEvent
from src.plugin.manager import PluginManager
from src.plugin.builtins.clear_memory import ClearMemoryPlugin
from src.plugin.builtins.whitelist import setup as whitelist_setup
from src.plugin.builtins.restart import setup as restart_setup
from src.plugin.builtins.help import setup as help_setup
from src.plugin.builtins.update_knowledge import setup as update_kb_setup
from src.provider.factory import create_provider
from src.knowledge.poke_replies import PokeReplyManager
from src.store.memory import MemoryStore

logger = logging.getLogger("autochat.bot")


class AutoBot:
    """AutoChat 机器人主控制器"""

    def __init__(self, config: dict):
        self.config = config
        self.event_bus = EventBus()
        self.memory = MemoryStore(
            data_dir="memory",
            max_history=config.get("bot", {}).get("max_history", 50),
        )
        self.plugin_mgr = PluginManager()
        self.scheduler = PipelineScheduler()
        self.platforms = []
        self.emotion_tracker = EmotionTracker()
        self._running = False
        self._retriever = None
        self._provider = None

    def _init_knowledge_base(self):
        """初始化剧情知识库"""
        kb_path = "memory/knowledge.json"
        if Path(kb_path).exists():
            self._retriever = StoryRetriever(kb_path)
            logger.info("知识库加载完成: %d 条故事", self._retriever.size)
        else:
            logger.warning(
                "知识库文件不存在: %s。请运行 python -m src.knowledge.builder 构建。",
                kb_path,
            )

    def _build_pipeline(self):
        """装配管线阶段"""
        self.scheduler.add_stage(WakingStage(self.config))
        self.scheduler.add_stage(PermissionStage(self.config))
        self.scheduler.add_stage(RateLimitStage(self.config))

        self._provider = create_provider(self.config)
        self.scheduler.add_stage(AIProcessStage(
            self._provider, self.memory, self.config,
            retriever=self._retriever, emotion_tracker=self.emotion_tracker,
        ))
        self.scheduler.add_stage(DecorateStage(self.config))

    async def _on_message_event(self, event: MessageEvent):
        """消息事件回调 — 先让插件拦截，再走管线"""
        logger.info("_on_message_event: user=%s msg=%s", event.user_id, event.message[:80])
        await self._handle_event(event)

    async def _handle_event(self, event: MessageEvent):
        """处理消息：插件优先，然后走管线"""
        # 插件拦截
        plugin_reply = await self.plugin_mgr.notify_message(event)
        if plugin_reply:
            target = event.reply(plugin_reply)
            for platform in self.platforms:
                try:
                    await platform.send_message(target, plugin_reply)
                except Exception as e:
                    logger.error("插件回复发送失败: %s", e)
            return

        # 走 AI 管线
        logger.info("开始管线执行")
        await self.scheduler.execute(event)
        logger.info("管线执行完成")

    async def start(self):
        """启动机器人"""
        self._running = True

        # 1. 初始化知识库
        self._init_knowledge_base()

        # 2. 加载插件
        logger.info("加载插件...")
        self.plugin_mgr.load_builtins()
        self.plugin_mgr.load_user_plugins()
        self.plugin_mgr.load_external_plugins()
        ClearMemoryPlugin.set_store(self.memory)
        master_qq = self.config.get("bot", {}).get("master_qq", 0)
        restart_setup(master_qq)
        help_setup(master_qq)
        update_kb_setup(master_qq, self._retriever)

        # 注入 master_qq 到自学习插件
        sl_plugin = self.plugin_mgr.get("self_learning")
        if sl_plugin:
            sl_plugin.setup(master_qq)
            logger.info("自学习插件已配置")

        # 3. 装配管线
        self._build_pipeline()

        # 4. 装配白名单插件
        for stage in self.scheduler._stages:
            if isinstance(stage, PermissionStage):
                whitelist_setup(
                    stage=stage,
                    config_path="config/config.json",
                    master_qq=master_qq,
                )
                break

        # 5. 设置消息发送器
        async def send_to_platform(target: dict, msg: str):
            for p in self.platforms:
                try:
                    await p.send_message(target, msg)
                except Exception as e:
                    logger.error("发送到 %s 失败: %s", p.platform_name, e)

        self.scheduler.set_sender(send_to_platform)

        # 5. 注册事件处理
        async def on_event(event):
            await self._on_message_event(event.data)
        self.event_bus.subscribe("message", on_event)

        # 6. 戳一戳回复管理器
        self._poke_mgr = PokeReplyManager(self._provider) if self._provider else None

        # 7. 启动平台适配器
        napcat_cfg = self.config.get("onebot", {})
        if napcat_cfg.get("enabled", True):
            napcat = NapCatAdapter(self.config, self.event_bus, poke_mgr=self._poke_mgr)
            self.platforms.append(napcat)

        # 为图库插件注入 API caller（用于通过 file= 下载图片）
        gallery_plugin = self.plugin_mgr.get("gallery")
        if gallery_plugin:
            for p in self.platforms:
                if hasattr(p, "call_api_and_wait"):
                    gallery_plugin._api_caller = p.call_api_and_wait
                    logger.info("图库插件 API caller 已注入")
                    break

        # 6. 启动事件分发 + 平台连接
        await self.plugin_mgr.notify_start()
        logger.info("AutoChat 启动完成")

        # 发送重启完毕通知（如果有重启标志）
        tasks = [asyncio.create_task(self._send_restart_notification())]

        # 并发运行：事件分发 + 所有平台 + 定时清理
        tasks += [asyncio.create_task(self.event_bus.dispatch())]
        for p in self.platforms:
            tasks.append(asyncio.create_task(self._run_platform(p)))
        tasks.append(asyncio.create_task(self._periodic_cleanup()))

        await asyncio.gather(*tasks)

    async def _run_platform(self, platform):
        """运行平台连接（含自动重连）"""
        while self._running:
            try:
                await platform.start()
            except ConnectionRefusedError:
                logger.warning("%s 连接失败，5秒后重试...", platform.platform_name)
                await asyncio.sleep(5)
            except Exception as e:
                logger.error("%s 异常: %s, 10秒后重试", platform.platform_name, e)
                await asyncio.sleep(10)

    async def _periodic_cleanup(self):
        """定时清理过期会话"""
        cleanup_days = self.config.get("bot", {}).get("cleanup_days", 7)
        interval = max(3600, cleanup_days * 86400 // 7)  # 至少1小时，默认1天
        while self._running:
            await asyncio.sleep(interval)
            cleaned = self.memory.cleanup_stale_sessions(days=cleanup_days)
            if cleaned:
                logger.info("定时清理: 移除了 %d 个过期会话", cleaned)

    async def _send_restart_notification(self):
        """检查重启标志，发送重启完毕通知（含已加载的插件列表）"""
        flag_path = Path("memory/.restart_flag.json")
        if not flag_path.exists():
            return
        try:
            target = json.loads(flag_path.read_text(encoding="utf-8"))
            flag_path.unlink()
            # 等待平台连接就绪（NapCat WS 连接需要几秒）
            plugin_names = list(self.plugin_mgr.plugins.keys())
            parts = ["已重启完毕。\n"]
            parts.append(f"已加载插件 ({len(plugin_names)}): {', '.join(plugin_names)}")
            if self._retriever:
                parts.append("知识库: 已加载")
            parts.append(f"AI: {type(self._provider).__name__ if self._provider else 'N/A'}")
            msg = " | ".join(parts)
            await asyncio.sleep(10)
            for platform in self.platforms:
                try:
                    await platform.send_message(target, msg)
                    logger.info("重启通知已发送到 %s", target)
                except Exception as e:
                    logger.warning("发送重启通知失败: %s", e)
        except Exception as e:
            logger.error("重启通知异常: %s", e)

    async def stop(self):
        """停止机器人"""
        self._running = False
        for p in self.platforms:
            await p.stop()
        await self.plugin_mgr.notify_stop()
        logger.info("AutoChat 已停止")
