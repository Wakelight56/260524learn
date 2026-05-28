"""白名单管理插件 — 通过聊天指令动态增删"""

import json
import logging
import os
from typing import Optional

from src.pipeline.stages.permission import PermissionStage
from src.plugin.base import Plugin, register_plugin
from src.platform.event import MessageEvent

logger = logging.getLogger("autochat.plugin.whitelist")

# 模块级全局（绕过 class 被重复定义的问题）
_stage: Optional[PermissionStage] = None
_config_path: str = ""
_master_qq: int = 0


@register_plugin
class WhitelistPlugin(Plugin):

    @property
    def name(self) -> str:
        return "whitelist"

    @property
    def description(self) -> str:
        return "白名单管理：/whitelist 查看，/whitelist add/del user/group <id>"

    async def on_message(self, event: MessageEvent) -> str | None:
        global _stage, _config_path, _master_qq

        if not event.message.strip().startswith("/whitelist") and not event.message.strip().startswith("白名单"):
            return None

        raw = event.message.strip()
        # 统一 /whitelist 和 白名单 两种格式
        if raw.startswith("/whitelist"):
            raw = raw[len("/whitelist"):].strip()
        elif raw.startswith("白名单"):
            raw = raw[len("白名单"):].strip()
        parts = raw.split() if raw else []
        cmd = parts[0] if parts else "show"
        uid_int = int(event.user_id)
        is_master = uid_int == _master_qq
        logger.info(
            "whitelist cmd: user=%s uid_int=%d master_qq=%d is_master=%s cmd=%s",
            event.user_id, uid_int, _master_qq, is_master, cmd,
        )

        if cmd == "show":
            return _show()

        if not is_master:
            return "你没有权限执行此操作。"

        if cmd in ("add", "del", "delete", "remove", "添加", "删除"):
            if len(parts) < 3:
                return "格式: 白名单 添加/删除 用户/群 <QQ号>\n或: /whitelist add/del user/group <id>"
            ncmd = "add" if cmd in ("add", "添加") else "del"
            ntarget = "user" if parts[1] in ("user", "用户") else "group"
            return await _modify(ncmd, ntarget, parts[2])

        return _show()


def setup(stage: PermissionStage, config_path: str, master_qq: int):
    global _stage, _config_path, _master_qq
    _stage = stage
    _config_path = config_path
    _master_qq = master_qq
    logger.info("whitelist setup: master_qq=%d", _master_qq)


def _show() -> str:
    if not _stage:
        return "白名单未加载"
    users = _stage.allowed_users
    groups = _stage.allowed_groups
    lines = ["当前白名单:"]
    lines.append(f"用户 ({len(users)}): {', '.join(str(u) for u in users) if users else '无'}")
    lines.append(f"群组 ({len(groups)}): {', '.join(str(g) for g in groups) if groups else '无'}")
    return "\n".join(lines)


async def _modify(action: str, target: str, value: str) -> str:
    global _stage, _config_path

    if not _stage:
        return "白名单未加载"

    try:
        val = int(value)
    except ValueError:
        return f"无效的ID: {value}"

    if target == "user":
        lst = _stage.allowed_users
        key = "allowed_users"
    elif target == "group":
        lst = _stage.allowed_groups
        key = "allowed_groups"
    else:
        return "目标类型错误，请使用 user/用户 或 group/群"

    if action in ("del", "delete", "remove"):
        if val not in lst:
            return f"{value} 不在白名单中"
        lst.remove(val)
        _persist(key, lst)
        logger.info("已将 %s %s 移出白名单", target, value)
        return f"已将 {value} 移出{target}白名单"
    else:
        if val in lst:
            return f"{value} 已在白名单中"
        lst.append(val)
        _persist(key, lst)
        logger.info("已将 %s %s 加入白名单", target, value)
        return f"已将 {value} 加入{target}白名单"


def _persist(key: str, lst: list[int]):
    global _config_path
    if not _config_path or not os.path.exists(_config_path):
        logger.warning("config.json 路径无效，无法持久化")
        return
    try:
        with open(_config_path, encoding="utf-8") as f:
            cfg = json.load(f)
        cfg.setdefault("bot", {})[key] = lst
        with open(_config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("持久化白名单失败: %s", e)



