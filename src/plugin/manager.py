"""插件管理器 — 加载/卸载/查找插件"""

import importlib
import logging
import os
import pkgutil
import sys

from src.platform.event import MessageEvent
from src.plugin.base import Plugin, plugin_registry

logger = logging.getLogger("autochat.plugin")


class PluginManager:
    """插件管理器"""

    def __init__(self):
        self._plugins: dict[str, Plugin] = {}

    @property
    def plugins(self) -> dict[str, Plugin]:
        return dict(self._plugins)

    def load_builtins(self):
        """加载内置插件"""
        import src.plugin.builtins as pkg
        self._load_from_package(pkg)

    def load_user_plugins(self):
        """加载用户自定义插件（src/plugin/user/）"""
        import src.plugin.user as pkg
        self._load_from_package(pkg)
        logger.info("用户插件目录已扫描")

    def load_external_plugins(self):
        """加载外部插件（src/plugin/external/）"""
        import src.plugin.external as pkg
        self._load_from_package(pkg)
        logger.info("外部插件目录已扫描")

    def load_from_path(self, path: str):
        """从目录加载外部插件"""
        if not os.path.isdir(path):
            logger.warning("插件目录不存在: %s", path)
            return
        import sys
        sys.path.insert(0, os.path.dirname(path))
        for f in os.listdir(path):
            if f.endswith(".py") and not f.startswith("_"):
                mod_name = f[:-3]
                try:
                    mod = importlib.import_module(mod_name)
                    importlib.reload(mod)
                except Exception as e:
                    logger.error("加载插件 %s 失败: %s", mod_name, e)

    def _load_from_package(self, pkg):
        """从包导入所有模块，触发 @register_plugin 装饰器"""
        pkg_path = os.path.dirname(pkg.__file__)
        for importer, mod_name, is_pkg in pkgutil.iter_modules([pkg_path]):
            if not is_pkg:
                try:
                    # 跳过已被 bot.py import 的模块，避免二次加载
                    full_name = f"{pkg.__name__}.{mod_name}"
                    if full_name in sys.modules:
                        continue
                    importer.find_spec(mod_name).loader.load_module(mod_name)
                except Exception as e:
                    logger.error("加载插件模块 %s 失败: %s", mod_name, e)

        # 实例化所有注册的插件
        for plugin_cls in plugin_registry:
            try:
                inst = plugin_cls()
                self._plugins[inst.name] = inst
                logger.info("已加载插件: %s", inst.name)
            except Exception as e:
                logger.error("实例化插件 %s 失败: %s", plugin_cls.__name__, e)

        plugin_registry.clear()

    def get(self, name: str) -> Plugin | None:
        return self._plugins.get(name)

    async def notify_message(self, event: MessageEvent) -> str | None:
        """通知所有插件有消息。返回第一个非空结果（即插件拦截）。"""
        for p in self._plugins.values():
            try:
                result = await p.on_message(event)
                if result is not None:
                    return result
            except Exception as e:
                logger.error("插件 %s 处理异常: %s", p.name, e)
        return None

    async def notify_start(self):
        for p in self._plugins.values():
            try:
                await p.on_bot_start()
            except Exception as e:
                logger.error("插件 %s start 异常: %s", p.name, e)

    async def notify_stop(self):
        for p in self._plugins.values():
            try:
                await p.on_bot_stop()
            except Exception as e:
                logger.error("插件 %s stop 异常: %s", p.name, e)
