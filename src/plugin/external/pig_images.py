"""随机猪图插件 — 从 pighub.top 获取随机猪图片"""
import asyncio
import json
import logging
import os
import random
import re
import shutil
import time
import urllib.parse
import tempfile
import base64
from pathlib import Path
from typing import Optional

import aiohttp

from src.plugin.base import Plugin, register_plugin
from src.platform.event import MessageEvent

logger = logging.getLogger("autochat.plugin.external.pig_images")

DATA_DIR = Path("data/pig_images")
LIST_JSON_PATH = DATA_DIR / "list.json"
REMOTE_API_URL = "https://pighub.top/api/images?limit=10000&sort=latest"
IMAGE_BASE_URL = "https://pighub.top/"


def _image_to_cq_base64(filepath: str) -> str:
    with open(filepath, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"[CQ:image,file=base64://{b64}]"


@register_plugin
class PigImagesPlugin(Plugin):
    """随机发送猪相关图片"""

    def __init__(self):
        super().__init__()
        self.cooldown_period = 5.0
        self.max_retries = 2
        self.update_cycle = 0
        self.is_match_all_msg = False
        self.is_exact_match = True
        self.match_keywords = ["猪", "祝", "🐷", "🐖", "🐽", "㊗", "㊗️"]
        self.exclude_prefixes = ("/", "!", "！", "#", "ww")

        self.last_called_times: dict[str, float] = {}
        self.pig_images: list[dict] = []
        self._download_semaphore = asyncio.Semaphore(3)
        self._update_lock = asyncio.Lock()
        self._scheduler_task: Optional[asyncio.Task] = None

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._load_pig_from_json()

    # -------------------- JSON 加载 --------------------
    def _load_pig_from_json(self):
        if not LIST_JSON_PATH.exists():
            logger.info("list.json 不存在，跳过本地加载")
            self.pig_images = []
            return

        try:
            json_data = json.loads(LIST_JSON_PATH.read_text("utf-8"))
        except Exception as e:
            logger.error(f"加载list.json失败: {e}")
            self.pig_images = []
            return

        raw_images = json_data.get("images", []) if isinstance(json_data, dict) else []
        self.pig_images.clear()
        for img in raw_images:
            if not isinstance(img, dict):
                continue
            thumbnail = img.get("thumbnail", "")
            if not thumbnail:
                continue

            thumbnail = str(thumbnail).lstrip("/")
            if thumbnail.startswith(("http://", "https://")):
                full_url = thumbnail
            else:
                full_url = urllib.parse.urljoin(IMAGE_BASE_URL, thumbnail)

            self.pig_images.append({
                "title": img.get("title", "随机猪图"),
                "full_url": full_url,
                "id": img.get("id"),
            })

        logger.info(f"图片配置加载成功，共 {len(self.pig_images)} 张图片")

    async def _fetch_remote_images(self):
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                async with session.get(REMOTE_API_URL) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    logger.error(f"远程请求失败: {resp.status}")
                    return None
        except Exception as e:
            logger.error(f"远程请求异常: {e}")
            return None

    def _apply_remote_data_if_needed(self, remote_data):
        if not isinstance(remote_data, dict):
            return False

        local_data = None
        if LIST_JSON_PATH.exists():
            try:
                local_data = json.loads(LIST_JSON_PATH.read_text("utf-8"))
            except Exception:
                local_data = None

        def extract_ids(d):
            if not d or not isinstance(d, dict):
                return set()
            imgs = d.get("images")
            if not imgs or not isinstance(imgs, list):
                return set()
            return {item.get("id") for item in imgs if isinstance(item, dict) and "id" in item}

        local_ids = extract_ids(local_data)
        remote_ids = extract_ids(remote_data)

        if local_data and local_ids == remote_ids and len(local_data.get("images", [])) == len(remote_data.get("images", [])):
            return False

        LIST_JSON_PATH.write_text(json.dumps(remote_data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("list.json 已从远程更新")
        self._load_pig_from_json()
        return True

    # -------------------- 图片下载 --------------------
    def _is_on_cooldown(self) -> bool:
        now = time.time()
        last = self.last_called_times.get("pig", 0)
        return (now - last) < self.cooldown_period

    def _cooldown_remaining(self) -> float:
        now = time.time()
        last = self.last_called_times.get("pig", 0)
        return max(0, self.cooldown_period - (now - last))

    async def _download_image(self, url: str) -> Optional[str]:
        for attempt in range(1, self.max_retries + 1):
            try:
                async with self._download_semaphore:
                    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                        async with session.get(url) as resp:
                            if resp.status != 200:
                                logger.warning(f"下载失败(attempt {attempt}): HTTP {resp.status}")
                                continue
                            data = await resp.read()
                            suffix = Path(urllib.parse.urlparse(url).path).suffix or ".jpg"
                            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
                                f.write(data)
                                return f.name
            except Exception as e:
                logger.debug(f"下载尝试失败(attempt {attempt}): {e}")
                if attempt < self.max_retries:
                    await asyncio.sleep(2 ** attempt)
        return None

    # -------------------- 核心逻辑 --------------------
    async def _get_random_pig_image(self) -> str:
        if self._is_on_cooldown():
            return f"冷却中～还需{self._cooldown_remaining():.0f}秒"

        if not self.pig_images:
            self.last_called_times["pig"] = time.time()
            return "无可用猪图数据"

        max_candidates = min(len(self.pig_images), 3)
        tried = set()
        for _ in range(max_candidates):
            idx = random.randrange(len(self.pig_images))
            if idx in tried and len(tried) < len(self.pig_images):
                continue
            tried.add(idx)
            selected = self.pig_images[idx]
            title = selected.get("title", "随机猪图")
            url = selected.get("full_url", "")

            temp_path = await self._download_image(url)
            if temp_path:
                self.last_called_times["pig"] = time.time()
                try:
                    cq = _image_to_cq_base64(temp_path)
                    return cq
                except Exception as e:
                    logger.error(f"图片转码失败: {e}")
                finally:
                    try:
                        os.unlink(temp_path)
                    except Exception:
                        pass
                break

        self.last_called_times["pig"] = time.time()
        return "获取猪图失败，请稍后重试"

    async def _manual_update(self) -> str:
        async with self._update_lock:
            remote = await self._fetch_remote_images()
            if not remote:
                return "[Pig] 手动更新失败：无法拉取远程数据"
            updated = self._apply_remote_data_if_needed(remote)
            if updated:
                return "[Pig] 手动更新成功：本地列表已更新"
            return "[Pig] 手动更新完成：本地已是最新"

    # -------------------- 消息处理 --------------------
    async def on_message(self, event: MessageEvent) -> Optional[str]:
        text = event.message.strip()

        # 命令: /pig 或 /pig update
        m = re.match(r"(?i)^[/／]?pig(?:\s+(.+))?$", text)
        if m:
            sub = m.group(1).strip().lower() if m.group(1) else ""
            if sub in ("update", "更新"):
                return await self._manual_update()
            return await self._get_random_pig_image()

        # 关键词触发（仅群聊）
        if event.is_group and self.is_match_all_msg:
            if text.startswith(self.exclude_prefixes):
                return None
            if self._is_trigger_keyword(text):
                return await self._get_random_pig_image()

        return None

    def _is_trigger_keyword(self, message: str) -> bool:
        if message.strip() in self.match_keywords:
            return True
        if not self.is_exact_match:
            for kw in self.match_keywords:
                if kw in message:
                    return True
        return False

    # -------------------- 生命周期 --------------------
    async def on_bot_start(self):
        remote = await self._fetch_remote_images()
        if remote:
            self._apply_remote_data_if_needed(remote)
        logger.info(f"猪图插件初始化完成，发送 /pig 获取图片（{len(self.pig_images)} 张可用）")

    async def on_bot_stop(self):
        if self._scheduler_task:
            self._scheduler_task.cancel()
        logger.info("猪图插件已卸载")

    @property
    def name(self) -> str:
        return "pig_images"

    @property
    def description(self) -> str:
        return "随机发送猪相关图片（来自 pighub.top）"
