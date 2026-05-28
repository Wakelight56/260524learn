"""权限检查阶段 — 白名单优先，黑名单兜底"""

import logging

from src.pipeline.stage import Stage, StageContext

logger = logging.getLogger("autochat.stage.permission")


class PermissionStage(Stage):
    """权限控制：白名单优先，黑名单兜底"""

    def __init__(self, config: dict):
        bot_cfg = config.get("bot", {})
        self._master_qq = int(bot_cfg.get("master_qq", 0))
        self._allowed_users = [int(u) for u in bot_cfg.get("allowed_users", [])]
        self._allowed_groups = [int(g) for g in bot_cfg.get("allowed_groups", [])]
        self._blocked_users = [int(u) for u in bot_cfg.get("blocked_users", [])]
        self._blocked_groups = [int(g) for g in bot_cfg.get("blocked_groups", [])]

    @property
    def allowed_users(self):
        return self._allowed_users

    @property
    def allowed_groups(self):
        return self._allowed_groups

    async def process(self, ctx: StageContext):
        event = ctx.event
        uid = int(event.user_id)
        gid = int(event.group_id) if event.group_id else 0

        # master 永远放行
        if uid == self._master_qq:
            return

        # 黑名单优先
        if uid in self._blocked_users:
            ctx.should_stop = True
            return
        if gid and gid in self._blocked_groups:
            ctx.should_stop = True
            return

        # 白名单：私聊按用户，群聊按群
        if self._allowed_users and uid not in self._allowed_users:
            ctx.should_stop = True
            return
        if gid and self._allowed_groups and gid not in self._allowed_groups:
            ctx.should_stop = True

