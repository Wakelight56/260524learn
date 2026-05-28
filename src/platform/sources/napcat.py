"""NapCat / OneBot v11 平台适配器 — WebSocket 服务端模式（NapCat 以 WS 客户端连入）"""

import asyncio
import json
import logging
import time
import uuid
from typing import Optional

import aiohttp
from aiohttp import web

from src.event_bus import EventBus
from src.platform.base import Platform
from src.platform.event import MessageEvent, MessageType

logger = logging.getLogger("autochat.napcat")


class NapCatAdapter(Platform):
    """NapCat OneBot v11 WebSocket 适配器（服务端模式）

    监听本地端口，等待 NapCat 以 WebSocket 客户端连入。
    """

    @property
    def platform_name(self) -> str:
        return "napcat"

    def __init__(self, config: dict, event_bus: EventBus):
        super().__init__(config, event_bus)
        ws_cfg = config.get("onebot", {})
        self._ws_host = ws_cfg.get("host", "127.0.0.1")
        self._ws_port = ws_cfg.get("port", 6199)
        self._ws_token = ws_cfg.get("access_token", "")
        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._ws_clients: set[web.WebSocketResponse] = set()

    async def start(self):
        """启动 WebSocket 服务端，等待 NapCat 连接"""
        self._app = web.Application()
        self._app.router.add_get("/ws", self._handle_ws)
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()

        site = web.TCPSite(self._runner, self._ws_host, self._ws_port)
        await site.start()
        self._running = True
        logger.info(
            "NapCat WS 服务端已启动: ws://%s:%s/ws",
            self._ws_host, self._ws_port,
        )

        # 保持运行直到被停止
        while self._running:
            await asyncio.sleep(1)

    async def _handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        """处理 NapCat 的 WebSocket 连接请求"""
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        # Token 验证
        if self._ws_token:
            auth = request.headers.get("Authorization", "")
            if auth != f"Bearer {self._ws_token}":
                logger.warning("NapCat 连接 token 验证失败")
                await ws.close(code=4001)
                return ws

        self._ws_clients.add(ws)
        logger.info("NapCat 已连接 (%d 个客户端)", len(self._ws_clients))

        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        await self._handle_raw(msg.data)
                    except Exception as e:
                        logger.error("处理消息异常: %s", e, exc_info=True)
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    logger.info("NapCat 连接正常关闭")
                    break
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error("NapCat WS 连接错误: %s", ws.exception())
                    break
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("NapCat WS 处理器异常: %s", e, exc_info=True)
        finally:
            self._ws_clients.discard(ws)
            logger.info("NapCat 断开 (%d 个客户端剩余)", len(self._ws_clients))

    async def stop(self):
        """停止服务端"""
        self._running = False
        # 关闭所有 WS 连接
        for ws in list(self._ws_clients):
            await ws.close()
        self._ws_clients.clear()
        if self._runner:
            await self._runner.cleanup()
        logger.info("NapCat 服务端已停止")

    async def send_message(self, target: dict, message: str):
        """通过 OneBot API 发送消息"""
        params = {"message": message}
        params.update(target)
        await self._call_api("send_msg", params)

    async def _call_api(self, action: str, params: dict, echo: str = ""):
        """向所有连接的 NapCat 客户端发送 API 调用请求"""
        payload = {
            "action": action,
            "params": params,
            "echo": echo,
        }
        for ws in list(self._ws_clients):
            try:
                await ws.send_json(payload)
            except Exception as e:
                logger.error("发送 API 请求失败: %s", e)

    async def _handle_raw(self, raw: str):
        """处理 NapCat 发来的原始消息"""
        logger.debug("收到 WS 消息: %s", raw[:200])
        try:
            data = json.loads(raw)
            if data.get("post_type") == "message":
                event = self._convert(data)
                if event:
                    logger.debug("发布消息事件: user=%s msg=%s", event.user_id, event.message[:50])
                    await self._publish_event(event)
                else:
                    logger.debug("消息被 _convert 过滤（自己发的消息?）")
        except json.JSONDecodeError:
            logger.warning("无效消息: %s", raw[:200])

    def _convert(self, raw: dict) -> Optional[MessageEvent]:
        """将 OneBot 消息转为统一 MessageEvent"""
        msg_type = raw.get("message_type")
        user_id = str(raw.get("user_id", ""))
        self_id = str(raw.get("self_id", ""))

        if user_id == self_id:
            return None  # 忽略自己

        if msg_type == "private":
            return MessageEvent(
                platform_name="napcat",
                platform_id=self._ws_host,
                message_type=MessageType.PRIVATE,
                message=raw.get("raw_message", ""),
                raw_message=json.dumps(raw, ensure_ascii=False),
                user_id=user_id,
                self_id=self_id,
                message_id=str(uuid.uuid4().hex[:8]),
                timestamp=int(time.time()),
            )
        elif msg_type == "group":
            return MessageEvent(
                platform_name="napcat",
                platform_id=self._ws_host,
                message_type=MessageType.GROUP,
                message=raw.get("raw_message", ""),
                raw_message=json.dumps(raw, ensure_ascii=False),
                user_id=user_id,
                group_id=str(raw.get("group_id", "")),
                self_id=self_id,
                message_id=str(uuid.uuid4().hex[:8]),
                timestamp=int(time.time()),
            )
        return None
