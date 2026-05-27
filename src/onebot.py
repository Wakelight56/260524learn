import json
import logging
from typing import Optional

import aiohttp

logger = logging.getLogger("autochat.onebot")


class OneBotClient:
    """OneBot v11 WebSocket 客户端 — 连接 NapCat"""

    def __init__(self, config: dict):
        self.host = config.get("host", "127.0.0.1")
        self.port = config.get("port", 3001)
        self.access_token = config.get("access_token", "")
        self.ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.session: Optional[aiohttp.ClientSession] = None
        self._running = False
        self._message_handlers = []

    @property
    def _url(self) -> str:
        return f"ws://{self.host}:{self.port}"

    def on_message(self, handler):
        """注册消息处理器"""
        self._message_handlers.append(handler)

    async def connect(self):
        """连接 NapCat WebSocket"""
        headers = {}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"

        self.session = aiohttp.ClientSession(headers=headers)
        logger.info("正在连接 NapCat: %s", self._url)

        try:
            self.ws = await self.session.ws_connect(self._url)
            self._running = True
            logger.info("NapCat 连接成功")
        except Exception as e:
            logger.error("连接失败: %s", e)
            raise

    async def listen(self):
        """监听消息事件循环"""
        async for msg in self.ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                await self._handle_raw(msg.data)
            elif msg.type == aiohttp.WSMsgType.ERROR:
                logger.error("WebSocket 错误: %s", self.ws.exception())
                break
            elif msg.type == aiohttp.WSMsgType.CLOSED:
                logger.info("WebSocket 连接已关闭")
                break

    async def _handle_raw(self, raw: str):
        """解析并分发原始消息"""
        try:
            data = json.loads(raw)
            post_type = data.get("post_type")

            if post_type == "message":
                for handler in self._message_handlers:
                    await handler(data)
        except json.JSONDecodeError:
            logger.warning("收到无效JSON: %s", raw[:200])

    async def send_msg(
        self,
        message: str,
        user_id: Optional[int] = None,
        group_id: Optional[int] = None,
    ):
        """发送消息 — 私聊或群聊"""
        action = "send_msg"
        params = {"message": message}
        if group_id:
            params["group_id"] = group_id
        elif user_id:
            params["user_id"] = user_id

        await self._call_api(action, params)

    async def _call_api(self, action: str, params: dict):
        """调用 OneBot API"""
        payload = {"action": action, "params": params}
        if self.ws and not self.ws.closed:
            await self.ws.send_json(payload)

    async def get_friend_list(self) -> list:
        """获取好友列表"""
        resp = await self._call_api_and_wait("get_friend_list", {})
        return resp.get("data", [])

    async def get_group_list(self) -> list:
        """获取群列表"""
        resp = await self._call_api_and_wait("get_group_list", {})
        return resp.get("data", [])

    async def _call_api_and_wait(self, action: str, params: dict) -> dict:
        """调用API并等待响应（简化版，实际应使用echo机制）"""
        payload = {"action": action, "params": params}
        if self.ws and not self.ws.closed:
            await self.ws.send_json(payload)
        return {"data": []}

    async def close(self):
        """关闭连接"""
        self._running = False
        if self.ws and not self.ws.closed:
            await self.ws.close()
        if self.session:
            await self.session.close()
        logger.info("OneBot 连接已关闭")

    @property
    def is_running(self) -> bool:
        return self._running
