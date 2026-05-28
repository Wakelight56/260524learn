"""图库插件 — 完整实现（基于 lunabot 画廊系统）"""

import asyncio
import base64
import hashlib
import io
import json
import logging
import math
import os
import random
import re
import shutil
import time
import traceback
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

from src.plugin.base import Plugin, register_plugin
from src.platform.event import MessageEvent

logger = logging.getLogger("autochat.plugin.user.gallery")

# ── 配置 ──────────────────────────────────────────────

GALLERY_DIR = "data/gallery"
METADATA_FILE = "data/galleries.json"
ADD_LOG_FILE = "data/gallery_add.log"
ADD_HISTORY_FILE = "data/gallery_add_history.json"
PIC_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
THUMBNAIL_SIZE = (128, 128)
SIZE_LIMIT_MB = 5
HASH1_DIFFERENCE_THRESHOLD = 3
HASH2_DIFFERENCE_THRESHOLD = 500
THUMBNAIL_BG = (230, 240, 255, 255)

# 最近消息缓存 (message_id -> {images, files, user_id})
_msg_cache: dict[str, dict] = {}
MAX_CACHE = 300


# ── 数据类 ────────────────────────────────────────────

@dataclass
class GalleryPic:
    gall_name: str
    pid: int
    path: str
    hash1: str = ""
    hash2: str = ""
    thumb_path: str = ""
    user_id: str = ""
    time_added: float = 0.0

    @classmethod
    def load(cls, data: dict) -> "GalleryPic":
        return cls(
            gall_name=data.get("gall_name", ""),
            pid=data.get("pid", 0),
            path=data.get("path", ""),
            hash1=data.get("hash1", ""),
            hash2=data.get("hash2", ""),
            thumb_path=data.get("thumb_path", ""),
            user_id=data.get("user_id", ""),
            time_added=data.get("time_added", 0.0),
        )

    def calc_hash(self):
        """计算感知哈希"""
        try:
            from PIL import Image
            img = Image.open(self.path)
            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                img = img.convert("RGBA").resize((64, 64), Image.BILINEAR)
                bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
                bg.alpha_composite(img)
                img = bg
            img = img.convert("RGB").resize((16, 16), Image.BILINEAR).convert("L")
            # hash2: 16x16 灰度值用于 MAE 比较
            self.hash2 = img.tobytes().hex()
            # hash1: 8x8 感知哈希（平均哈希）
            img = img.resize((8, 8), Image.BILINEAR)
            pixels = list(img.getdata())
            avg = sum(pixels) / len(pixels)
            bits = 0
            for i, p in enumerate(pixels):
                if p >= avg:
                    bits |= 1 << (63 - i)
            self.hash1 = f"{bits:016x}"
            logger.info("哈希计算完成 pid=%s hash1=%s hash2_len=%d", getattr(self, 'pid', '?'), self.hash1[:16], len(self.hash2))
        except ImportError:
            logger.warning("PIL 未安装，跳过哈希计算")
        except Exception as e:
            logger.error("计算哈希失败 %s: %s", self.path, e)

    def is_same(self, other: "GalleryPic") -> bool:
        """判断两张图片是否相似（通过感知哈希）"""
        # 没有 hash2 无法判断
        if not self.hash2 or not other.hash2:
            logger.warning("is_same: hash2 不足 pid=%d/%d", getattr(self, 'pid', 0), other.pid)
            return False

        # hash1 快速通道：完全匹配或极低差异直接判定相似
        if self.hash1 and other.hash1:
            diff_bits = (int(self.hash1, 16) ^ int(other.hash1, 16)).bit_count()
            if diff_bits <= HASH1_DIFFERENCE_THRESHOLD:
                # hash2 确认
                b1 = bytes.fromhex(self.hash2)
                b2 = bytes.fromhex(other.hash2)
                mae = sum(abs(a - b) for a, b in zip(b1, b2))
                if mae <= HASH2_DIFFERENCE_THRESHOLD:
                    logger.info("查重命中: pid=%d <-> pid=%d diff_bits=%d mae=%d", getattr(self, 'pid', 0), other.pid, diff_bits, mae)
                    return True

        # 完整 MAE 比较：即使 hash1 差异大，也检查 hash2
        b1 = bytes.fromhex(self.hash2)
        b2 = bytes.fromhex(other.hash2)
        mae = sum(abs(a - b) for a, b in zip(b1, b2))
        result = mae <= HASH2_DIFFERENCE_THRESHOLD
        if result:
            logger.info("查重命中(MAE): pid=%d <-> pid=%d mae=%d", getattr(self, 'pid', 0), other.pid, mae)
        return result

    def ensure_thumb(self):
        """生成缩略图"""
        if self.thumb_path and os.path.exists(self.thumb_path):
            return
        try:
            from PIL import Image
            thumb_dir = os.path.join(os.path.dirname(self.path), "_thumbs")
            os.makedirs(thumb_dir, exist_ok=True)
            thumb_name = f"thumb_{os.path.basename(self.path)}"
            if not thumb_name.lower().endswith(".jpg"):
                thumb_name += ".jpg"
            self.thumb_path = os.path.join(thumb_dir, thumb_name)
            if os.path.exists(self.thumb_path):
                return
            img = Image.open(self.path).convert("RGBA")
            img.thumbnail(THUMBNAIL_SIZE, Image.LANCZOS)
            bg = Image.new("RGBA", img.size, THUMBNAIL_BG)
            bg.alpha_composite(img)
            bg.convert("RGB").save(self.thumb_path, format="JPEG", optimize=True, quality=85)
        except ImportError:
            pass
        except Exception as e:
            logger.warning("生成缩略图失败 %s: %s", self.path, e)
            self.thumb_path = ""


@dataclass
class Gallery:
    name: str
    aliases: list
    pics_dir: str
    mode: str  # edit / view / off
    cover_pid: int
    pics: list


# ── 持久化 ────────────────────────────────────────────

def _load_data(path: str) -> dict:
    p = Path(path)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error("读取 %s 失败: %s", path, e)
    return {}


def _save_data(path: str, data: dict):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── 辅助 ──────────────────────────────────────────────

def _extract_image_urls(raw: str) -> list[str]:
    return re.findall(r"url=([^,\]]+)", raw)


def _extract_image_files(raw: str) -> list[str]:
    files = re.findall(r"\[CQ:image,file=([^,\]]+)", raw)
    files += re.findall(r"\[CQ:mface,id=([^,\]]+)", raw)
    return files


def _extract_reply_id(raw: str) -> str | None:
    m = re.search(r"\[CQ:reply,id=(-?\d+)\]", raw)
    return m.group(1) if m else None


def _clean_text(raw: str) -> str:
    return re.sub(r"\[CQ:[^\]]*\]", "", raw).strip()


def _image_to_cq(filepath: str) -> str:
    try:
        with open(filepath, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        return f"[CQ:image,file=base64://{b64}]"
    except Exception as e:
        logger.error("读取图片失败 %s: %s", filepath, e)
        return ""


def _cq_from_pil_img(pil_img, quality: int = 85) -> str:
    """PIL Image 直接转 CQ base64"""
    import io
    from PIL import Image
    buf = io.BytesIO()
    if pil_img.mode == "RGBA":
        bg = Image.new("RGB", pil_img.size, (255, 255, 255))
        bg.paste(pil_img, mask=pil_img.split()[3])
        bg.save(buf, format="JPEG", quality=quality, optimize=True)
    else:
        pil_img.save(buf, format="JPEG", quality=quality, optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"[CQ:image,file=base64://{b64}]"


def _format_size(size_bytes: int) -> str:
    mb = size_bytes / (1024 * 1024)
    if mb < 1:
        return "<1M"
    elif mb < 1024:
        return f"{mb:.0f}M"
    else:
        return f"{mb / 1024:.0f}G"


# ── 图片处理 ──────────────────────────────────────────

def _process_image_for_gallery(path: str) -> str:
    """缩放过大图片并保存，返回原始路径"""
    try:
        from PIL import Image
        filesize_mb = os.path.getsize(path) / (1024 * 1024)
        if filesize_mb <= SIZE_LIMIT_MB:
            return path

        img = Image.open(path)
        scale = (SIZE_LIMIT_MB * 0.9) / filesize_mb
        new_w = int(img.width * math.sqrt(scale))
        new_h = int(img.height * math.sqrt(scale))
        img = img.resize((new_w, new_h), Image.LANCZOS)

        base, ext = os.path.splitext(path)
        out_path = f"{base}_scaled{ext}"
        img.save(out_path, optimize=True)
        logger.info("图片过大 %s: %.2fM -> %s", path, filesize_mb, out_path)
        return out_path
    except ImportError:
        return path
    except Exception as e:
        logger.warning("缩放图片失败 %s: %s", path, e)
        return path


# ── 画廊管理器 ────────────────────────────────────────

class GalleryManager:
    _instance = None

    def __init__(self):
        self._pid_top = 0
        self._galleries: dict[str, Gallery] = {}
        self._dirty = False

    @classmethod
    def get(cls) -> "GalleryManager":
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._load()
        return cls._instance

    # ── 持久化 ──

    def _load(self):
        data = _load_data(METADATA_FILE)
        self._pid_top = data.get("pid_top", 0)
        self._galleries = {}
        for name, g in data.get("galleries", {}).items():
            self._galleries[name] = Gallery(
                name=g.get("name", name),
                aliases=g.get("aliases", []),
                pics_dir=g.get("pics_dir", f"{name}/"),
                mode=g.get("mode", "edit"),
                cover_pid=g.get("cover_pid"),
                pics=[GalleryPic.load(p) for p in g.get("pics", [])],
            )
        logger.info("加载了 %d 个画廊, pid_top=%d", len(self._galleries), self._pid_top)
        self._backfill_hashes()

    def _backfill_hashes(self):
        """为没有哈希的旧图片补算哈希"""
        count = 0
        for g in self._galleries.values():
            for pic in g.pics:
                if not pic.hash1 and os.path.exists(pic.path):
                    pic.calc_hash()
                    count += 1
        if count:
            self._save()
            logger.info("补算了 %d 张图片的哈希", count)

    def _save(self):
        data = {
            "pid_top": self._pid_top,
            "galleries": {
                name: {
                    "name": g.name,
                    "aliases": g.aliases,
                    "pics_dir": g.pics_dir,
                    "mode": g.mode,
                    "cover_pid": g.cover_pid,
                    "pics": [asdict(p) for p in g.pics],
                }
                for name, g in self._galleries.items()
            },
        }
        _save_data(METADATA_FILE, data)

    def save_later(self):
        self._dirty = True

    def flush(self):
        if self._dirty:
            self._save()
            self._dirty = False

    # ── 画廊 CRUD ──

    def _check_name(self, name: str) -> bool:
        if not name or len(name) > 32:
            return False
        if any(c in name for c in r'\/:*?"<>| '):
            return False
        if name.isdigit():
            return False
        return True

    def all_galleries(self) -> dict[str, Gallery]:
        return self._galleries

    def find(self, name_or_alias: str) -> Gallery | None:
        for g in self._galleries.values():
            if g.name == name_or_alias or name_or_alias in g.aliases:
                return g
        return None

    def create(self, name: str) -> str:
        if not self._check_name(name):
            return f"图库名「{name}」无效（不能含空格/特殊字符，最多32字）"
        if self.find(name):
            return f"图库「{name}」已存在。"
        g = Gallery(
            name=name,
            aliases=[],
            pics_dir=name,
            mode="edit",
            cover_pid=None,
            pics=[],
        )
        self._galleries[name] = g
        Path(GALLERY_DIR, name).mkdir(parents=True, exist_ok=True)
        self._save()
        logger.info("创建图库: %s", name)
        return f"已创建图库「{name}」。"

    def delete(self, name_or_alias: str) -> str:
        g = self.find(name_or_alias)
        if not g:
            return f"图库「{name_or_alias}」不存在。"
        count = len(g.pics)
        del self._galleries[g.name]
        self._save()
        logger.info("删除图库: %s (%d 张图)", g.name, count)
        return f"已删除图库「{g.name}」（{count} 张图片）。"

    def add_alias(self, name_or_alias: str, alias: str) -> str:
        if not self._check_name(alias):
            return f"别名「{alias}」无效。"
        g = self.find(name_or_alias)
        if not g:
            return f"图库「{name_or_alias}」不存在。"
        if self.find(alias):
            return f"别名「{alias}」已被占用。"
        g.aliases.append(alias)
        self._save()
        return f"图库「{g.name}」添加别名「{alias}」成功。"

    def del_alias(self, name_or_alias: str, alias: str) -> str:
        g = self.find(name_or_alias)
        if not g:
            return f"图库「{name_or_alias}」不存在。"
        if alias not in g.aliases:
            return f"别名「{alias}」不存在。"
        g.aliases.remove(alias)
        self._save()
        return f"图库「{g.name}」删除别名「{alias}」成功。"

    def set_mode(self, name_or_alias: str, mode: str) -> str:
        g = self.find(name_or_alias)
        if not g:
            return f"图库「{name_or_alias}」不存在。"
        if mode not in ("edit", "view", "off"):
            return "模式须为 edit/view/off。"
        old = g.mode
        g.mode = mode
        self._save()
        return f"图库「{g.name}」模式 {old} -> {mode}。"

    def set_cover(self, name_or_alias: str, pid: int) -> str:
        g = self.find(name_or_alias)
        if not g:
            return f"图库「{name_or_alias}」不存在。"
        pic = self.find_pic(pid)
        if not pic or pic.gall_name != g.name:
            return f"图片 pid={pid} 不属于该图库。"
        g.cover_pid = pid
        self._save()
        return f"图库「{g.name}」封面已设为 pid={pid}。"

    def find_pic(self, pid: int) -> GalleryPic | None:
        for g in self._galleries.values():
            for p in g.pics:
                if p.pid == pid:
                    return p
        return None

    # ── 图片 CRUD ──

    async def add_pic(self, name_or_alias: str, img_path: str, user_id: str = "",
                      check_duplicated: bool = True) -> tuple[int, str]:
        """添加图片，返回 (pid, 错误消息)"""
        g = self.find(name_or_alias)
        if not g:
            return 0, f"图库「{name_or_alias}」不存在。"

        self._pid_top += 1
        pid = self._pid_top

        pic = GalleryPic(
            gall_name=g.name,
            pid=pid,
            path=img_path,
            user_id=user_id,
            time_added=time.time(),
        )

        # 处理（缩放）
        processed = await asyncio.to_thread(_process_image_for_gallery, img_path)

        # 复制到画廊目录
        _, ext = os.path.splitext(processed)
        time_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        dst_name = f"{time_str}_{pid}{ext}"
        dst_dir = Path(GALLERY_DIR, g.pics_dir)
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst_path = str(dst_dir / dst_name)
        shutil.copy2(processed, dst_path)
        pic.path = dst_path

        # 如果处理产生缩放副本，清理
        if processed != img_path and os.path.exists(processed):
            try:
                os.remove(processed)
            except OSError:
                pass

        # 计算哈希
        await asyncio.to_thread(pic.calc_hash)

        # 查重
        if check_duplicated:
            for existing in g.pics:
                if await asyncio.to_thread(pic.is_same, existing):
                    # 删除刚复制的文件
                    try:
                        os.remove(dst_path)
                    except OSError:
                        pass
                    self._pid_top -= 1
                    return 0, f"与现有图片重复 (pid={existing.pid})"

        # 生成缩略图
        await asyncio.to_thread(pic.ensure_thumb)

        g.pics.append(pic)
        self._save()
        logger.info("图库 %s: 添加图片 pid=%d (%s)", g.name, pid, dst_path)
        return pid, ""

    def del_pic(self, pid: int) -> str:
        pic = self.find_pic(pid)
        if not pic:
            return f"图片 pid={pid} 不存在。"
        g = self._galleries.get(pic.gall_name)
        if g:
            g.pics.remove(pic)
        try:
            if os.path.exists(pic.path):
                os.remove(pic.path)
            if pic.thumb_path and os.path.exists(pic.thumb_path):
                os.remove(pic.thumb_path)
        except OSError as e:
            logger.warning("删除图片文件失败 pid=%d: %s", pid, e)
        self._save()
        return f"已删除 pid={pid}。"

    # ── 统计 ──

    def gallery_stats(self, name_or_alias: str) -> dict:
        g = self.find(name_or_alias)
        if not g:
            return {}
        total_size = 0
        for pic in g.pics:
            if os.path.exists(pic.path):
                total_size += os.path.getsize(pic.path)
        return {
            "name": g.name,
            "count": len(g.pics),
            "size": total_size,
            "size_text": _format_size(total_size) if total_size else "",
            "mode": g.mode,
            "aliases": g.aliases,
        }


# ── 图库拼图生成 ──────────────────────────────────────

def _render_gallery_overview(galleries: list, manager: GalleryManager) -> str | None:
    """生成画廊总览拼图，返回 CQ 码"""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None

    if not galleries:
        return None

    card_w, card_h = 160, 200
    cols = max(1, int(math.sqrt(len(galleries))))
    rows = math.ceil(len(galleries) / cols)
    grid_w = cols * (card_w + 8) + 8
    grid_h = rows * (card_h + 8) + 8

    canvas = Image.new("RGBA", (grid_w, grid_h), THUMBNAIL_BG)
    draw = ImageDraw.Draw(canvas)

    # 尝试加载字体
    font = None
    font_small = None
    for fp in [
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttf",
    ]:
        try:
            if os.path.exists(fp):
                font = ImageFont.truetype(fp, 16)
                font_small = ImageFont.truetype(fp, 12)
                break
        except Exception:
            continue

    for idx, g in enumerate(galleries):
        col = idx % cols
        row = idx // cols
        x = 8 + col * (card_w + 8)
        y = 8 + row * (card_h + 8)

        # 获取封面图
        cover_img = None
        if g.cover_pid:
            pic = manager.find_pic(g.cover_pid)
            if pic and pic.thumb_path and os.path.exists(pic.thumb_path):
                cover_img = Image.open(pic.thumb_path)
        if cover_img is None and g.pics:
            pic = g.pics[0]
            if pic.thumb_path and os.path.exists(pic.thumb_path):
                cover_img = Image.open(pic.thumb_path)
            elif os.path.exists(pic.path):
                cover_img = Image.open(pic.path)
                cover_img.thumbnail((128, 128), Image.LANCZOS)

        # 绘制缩略图区域
        thumb_area = Image.new("RGBA", (card_w - 16, card_w - 16), (255, 255, 255, 255))
        if cover_img:
            t = cover_img.convert("RGBA")
            t.thumbnail((card_w - 16, card_w - 16), Image.LANCZOS)
            tx = (thumb_area.width - t.width) // 2
            ty = (thumb_area.height - t.height) // 2
            thumb_area.paste(t, (tx, ty), t)
        canvas.paste(thumb_area, (x + 8, y + 8), thumb_area)

        # 绘制名称和数量
        name_y = y + (card_w - 16) + 12
        if font:
            draw.text((x + 8, name_y), g.name, fill=(0, 0, 0), font=font)
        else:
            draw.text((x + 8, name_y), g.name, fill=(0, 0, 0))
        info_text = f"{len(g.pics)}张"
        if font_small:
            draw.text((x + 8, name_y + 20), info_text, fill=(80, 80, 80), font=font_small)
        else:
            draw.text((x + 8, name_y + 20), info_text, fill=(80, 80, 80))

    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="JPEG", quality=80, optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"[CQ:image,file=base64://{b64}]"


def _render_gallery_detail(g: Gallery) -> str | None:
    """生成单个画廊的图片墙，返回 CQ 码"""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None

    if not g.pics:
        return None

    thumb_w, thumb_h = 80, 80
    cols = max(1, int(math.sqrt(len(g.pics) * 1.5)))
    rows = math.ceil(len(g.pics) / cols)
    pad = 4
    grid_w = cols * (thumb_w + pad) + pad
    grid_h = rows * (thumb_h + pad) + 40 + pad  # +40 for title

    canvas = Image.new("RGBA", (grid_w, grid_h), THUMBNAIL_BG)
    draw = ImageDraw.Draw(canvas)

    font = None
    font_small = None
    for fp in [
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttf",
    ]:
        try:
            if os.path.exists(fp):
                font = ImageFont.truetype(fp, 14)
                font_small = ImageFont.truetype(fp, 10)
                break
        except Exception:
            continue

    if font:
        draw.text((pad, pad), f"「{g.name}」共 {len(g.pics)} 张", fill=(0, 0, 0), font=font)
    else:
        draw.text((pad, pad), f"{g.name}: {len(g.pics)}张", fill=(0, 0, 0))

    for idx, pic in enumerate(g.pics):
        col = idx % cols
        row = idx // cols
        x = pad + col * (thumb_w + pad)
        y_inner = 40 + row * (thumb_h + pad)

        thumb = None
        if pic.thumb_path and os.path.exists(pic.thumb_path):
            thumb = Image.open(pic.thumb_path)
        elif os.path.exists(pic.path):
            thumb = Image.open(pic.path)
            thumb.thumbnail((thumb_w, thumb_h), Image.LANCZOS)

        cell = Image.new("RGBA", (thumb_w, thumb_h), (255, 255, 255, 255))
        if thumb:
            t = thumb.convert("RGBA")
            t.thumbnail((thumb_w, thumb_h), Image.LANCZOS)
            tx = (cell.width - t.width) // 2
            ty = (cell.height - t.height) // 2
            cell.paste(t, (tx, ty), t)

        canvas.paste(cell, (x, y_inner), cell)

        # 在缩略图底部绘制 pid 编号（直接画在 canvas 上，保证不透明）
        pid_text = str(pic.pid)
        if font_small:
            bbox = draw.textbbox((0, 0), pid_text, font=font_small)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
        else:
            tw, th = len(pid_text) * 7, 12
        bar_h = th + 4
        lx, ly = x, y_inner + thumb_h - bar_h
        draw.rectangle([(lx, ly), (lx + tw + 6, y_inner + thumb_h)], fill=(0, 0, 0))
        if font_small:
            draw.text((lx + 3, ly + 1), pid_text, fill=(255, 255, 255), font=font_small)
        else:
            draw.text((lx + 3, ly + 1), pid_text, fill=(255, 255, 255))

    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="JPEG", quality=80, optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"[CQ:image,file=base64://{b64}]"


# ── 上传历史 ──────────────────────────────────────────

def _add_history(user_id: str, pids: list[int]) -> int:
    data = _load_data(ADD_HISTORY_FILE)
    history = data.get("history", [])
    record = {
        "id": len(history) + 1,
        "uid": user_id,
        "pids": pids,
        "ts": time.time(),
        "reverted": False,
    }
    history.append(record)
    data["history"] = history
    _save_data(ADD_HISTORY_FILE, data)
    return record["id"]


def _revert_history(hid: int, manager: GalleryManager) -> str:
    data = _load_data(ADD_HISTORY_FILE)
    history = data.get("history", [])
    for h in history:
        if h["id"] == hid:
            if h["reverted"]:
                return f"上传记录 #{hid} 已被撤销过。"
            ok_list, err_list = [], []
            for pid in h["pids"]:
                result = manager.del_pic(pid)
                if "不存在" not in result:
                    ok_list.append(pid)
                else:
                    err_list.append(pid)
            h["reverted"] = True
            data["history"] = history
            _save_data(ADD_HISTORY_FILE, data)
            msg = f"已撤销上传记录 #{hid}（{h['uid']} 的 {len(h['pids'])} 张图）"
            if err_list:
                msg += f"\n失败: {len(err_list)} 张"
            return msg
    return f"上传记录 #{hid} 不存在。"


# ── 插件 ──────────────────────────────────────────────

@register_plugin
class GalleryPlugin(Plugin):

    def __init__(self):
        self._mgr = GalleryManager.get()
        self._master_qq = "3437401237"
        self._api_caller = None

    @property
    def name(self) -> str:
        return "gallery"

    @property
    def description(self) -> str:
        return "图库：存图/取图/管理，支持查重、缩略图、拼图预览"

    async def on_message(self, event: MessageEvent) -> str | None:
        raw = event.message
        text = _clean_text(raw)
        uid = event.user_id

        # 缓存图片消息
        urls = _extract_image_urls(raw)
        files = _extract_image_files(raw) if not urls else []
        if urls or files:
            _msg_cache[event.message_id] = {
                "images": urls, "files": files,
                "user_id": uid, "time": time.time(),
            }
            if len(_msg_cache) > MAX_CACHE:
                oldest = min(_msg_cache, key=lambda k: _msg_cache[k]["time"])
                _msg_cache.pop(oldest, None)

        # 管理命令
        if text.startswith("/gallery") or text.startswith("图库"):
            return await self._handle_admin(event, text)

        # 存图
        if text.startswith("存") and len(text) > 1:
            return await self._save_image(event, text[1:].strip())

        # 取图
        if text.startswith("发张") and len(text) > 2:
            return await self._get_image(event, text[2:].strip())

        return None

    # ── 权限 ──

    def _is_master(self, uid: int | str) -> bool:
        return int(uid) == int(self._master_qq)

    # ── 管理 ──

    async def _handle_admin(self, event: MessageEvent, text: str) -> str | None:
        uid = int(event.user_id)
        body = text.replace("图库", "").replace("/gallery", "").strip()
        parts = body.split()
        cmd = parts[0] if parts else "list"

        if cmd == "list" or cmd == "":
            return self._cmd_list(body)

        if cmd in ("help", "帮助"):
            return self._cmd_help()

        if not self._is_master(uid):
            return "你没有权限执行此操作。"

        handlers = {
            "create": lambda: self._cmd_create(parts[1:]),
            "新建": lambda: self._cmd_create(parts[1:]),
            "添加": lambda: self._cmd_create(parts[1:]),
            "del": lambda: self._cmd_del(parts[1:]),
            "delete": lambda: self._cmd_del(parts[1:]),
            "删除": lambda: self._cmd_del(parts[1:]),
            "alias": lambda: self._cmd_alias(parts[1:]),
            "mode": lambda: self._cmd_mode(parts[1:]),
            "cover": lambda: self._cmd_cover(parts[1:]),
            "封面": lambda: self._cmd_cover(parts[1:]),
            "delpic": lambda: self._cmd_delpic(parts[1:]),
            "check": lambda: self._cmd_check(parts[1:]),
            "检查": lambda: self._cmd_check(parts[1:]),
            "查看": lambda: self._cmd_view(parts[1:]),
        }

        handler = handlers.get(cmd)
        if handler:
            return await handler() if asyncio.iscoroutinefunction(handler) else handler()

        return self._cmd_list(body)

    # ── 命令实现 ──

    def _cmd_list(self, args: str) -> str:
        args = args.replace("list", "", 1).strip() if args.startswith("list") else args.strip()
        name = args

        # 指定画廊：查看详情
        if name:
            g = self._mgr.find(name)
            if not g:
                return f"图库「{name}」不存在。"
            cq = _render_gallery_detail(g)
            if cq:
                return cq
            info = self._mgr.gallery_stats(name)
            if not info:
                return f"图库「{name}」不存在。"
            return f"📖 {info['name']}: {info['count']}张 {info['size_text']} | 模式: {info['mode']}"

        # 所有画廊总览
        galls = list(self._mgr.all_galleries().values())
        if not galls:
            return "暂无图库。管理员可用「图库 create <名称>」创建。"

        # 尝试生成拼图
        cq = _render_gallery_overview(galls, self._mgr)
        if cq:
            return cq

        # 降级为文本
        lines = ["📖 图库列表:"]
        for g in galls:
            info = self._mgr.gallery_stats(g.name)
            mode_tag = f" [{info['mode']}]" if info.get("mode") != "edit" else ""
            lines.append(f"  {g.name}: {info['count']}张{info['size_text']}{mode_tag}")
        return "\n".join(lines)

    def _cmd_help(self) -> str:
        return (
            "📖 图库帮助\n"
            "━━━━ 通用 ━━━━\n"
            "图库 list           — 画廊总览（缩略图拼图）\n"
            "图库 list <名称>    — 查看指定画廊详情\n"
            "存<名称>            — 回复带图消息存到画廊\n"
            "发张<名称>          — 随机取一张图\n"
            "图库 help           — 显示本帮助\n"
            "━━━━ 管理 ━━━━\n"
            "图库 create <名称>  — 创建新画廊\n"
            "图库 del <名称>     — 删除画廊\n"
            "图库 alias <名> <别> — 添加别名\n"
            "图库 alias del <名> <别> — 删除别名\n"
            "图库 mode <名> <模式> — 设置模式 edit/view/off\n"
            "图库 cover <名> <pid>  — 设置封面\n"
            "图库 delpic <pid...>   — 删除图片\n"
            "图库 check <名称>   — 查重\n"
            "图库 查看 <名称>    — 随机查看一张"
        )

    def _cmd_create(self, args: list) -> str:
        if not args:
            return "格式: 图库 create <名称>"
        return self._mgr.create(" ".join(args))

    def _cmd_del(self, args: list) -> str:
        if not args:
            return "格式: 图库 del <名称>"
        return self._mgr.delete(" ".join(args))

    def _cmd_alias(self, args: list) -> str:
        if len(args) < 2:
            return "格式: 图库 alias <图库名> <别名>"
        if args[0] == "add" and len(args) >= 3:
            return self._mgr.add_alias(args[1], args[2])
        if args[0] in ("del", "delete", "remove") and len(args) >= 3:
            return self._mgr.del_alias(args[1], args[2])
        return self._mgr.add_alias(args[0], args[1])

    def _cmd_mode(self, args: list) -> str:
        if len(args) < 2:
            return "格式: 图库 mode <名称> <edit/view/off>"
        return self._mgr.set_mode(args[0], args[1])

    def _cmd_cover(self, args: list) -> str:
        if len(args) < 2:
            return "格式: 图库 cover <名称> <pid>"
        try:
            return self._mgr.set_cover(args[0], int(args[1]))
        except ValueError:
            return "pid 须为数字。"

    def _cmd_delpic(self, args: list) -> str:
        if not args:
            return "格式: 图库 delpic <pid1> [pid2...]"
        results = []
        for arg in args:
            try:
                pid = int(arg)
                results.append(self._mgr.del_pic(pid))
            except ValueError:
                results.append(f"无效 pid: {arg}")
        return "\n".join(results)

    async def _cmd_check(self, args: list) -> str:
        name = " ".join(args) if args else ""
        if not name:
            return "格式: 图库 check <名称>"
        g = self._mgr.find(name)
        if not g:
            return f"图库「{name}」不存在。"
        if len(g.pics) < 2:
            return f"图库「{name}」仅 {len(g.pics)} 张，无需查重。"

        dup_groups = []
        checked = set()
        for i, a in enumerate(g.pics):
            if i in checked:
                continue
            group = [i]
            for j, b in enumerate(g.pics):
                if j <= i or j in checked:
                    continue
                same = await asyncio.to_thread(a.is_same, b)
                if same:
                    group.append(j)
            if len(group) > 1:
                dup_groups.append([g.pics[k] for k in group])
                checked.update(group)
            else:
                checked.add(i)

        if not dup_groups:
            return f"图库「{name}」查重完成，未发现重复图片。"

        lines = [f"发现 {len(dup_groups)} 组重复:"]
        for group in dup_groups:
            pids = [str(p.pid) for p in group]
            lines.append(f"  " + ", ".join(pids))
        lines.append(f"可用「图库 delpic <pid>」删除重复图片。")
        return "\n".join(lines)

    async def _cmd_view(self, args: list) -> str | None:
        name = " ".join(args) if args else ""
        if not name:
            return "格式: 图库 查看 <名称>"
        g = self._mgr.find(name)
        if not g:
            return f"图库「{name}」不存在。"
        if not g.pics:
            return f"图库「{name}」是空的。"
        # 随机取一张
        pic = random.choice(g.pics)
        if not os.path.exists(pic.path):
            return f"图片文件不存在了 (pid={pic.pid})"
        cq = _image_to_cq(pic.path)
        if not cq:
            return "读取图片失败。"
        return cq

    # ── 存图 ──

    async def _save_image(self, event: MessageEvent, name: str) -> str | None:
        g = self._mgr.find(name)
        if not g:
            return f"图库「{name}」不存在。可用「图库 create {name}」创建。"

        raw = event.message
        urls = _extract_image_urls(raw)
        files = _extract_image_files(raw) if not urls else []

        # 检查回复中的图片
        if not urls and not files:
            reply_id = _extract_reply_id(raw)
            if reply_id:
                # 先查内存缓存
                if reply_id in _msg_cache:
                    cache = _msg_cache[reply_id]
                    urls = cache.get("images", [])
                    files = cache.get("files", [])
                # 缓存未命中，通过 API 获取原消息
                if not urls and not files and self._api_caller:
                    try:
                        resp = await self._api_caller("get_msg", {"message_id": int(reply_id)})
                        if resp and resp.get("status") == "ok":
                            orig_msg = resp.get("data", {}).get("message", "")
                            if isinstance(orig_msg, str):
                                urls = _extract_image_urls(orig_msg)
                                files = _extract_image_files(orig_msg) if not urls else []
                            elif isinstance(orig_msg, list):
                                msg_str = "".join(
                                    seg.get("data", {}).get("text", "")
                                    if seg.get("type") == "text"
                                    else f"[CQ:{seg['type']},{','.join(f'{k}={v}' for k, v in seg.get('data', {}).items())}]"
                                    for seg in orig_msg
                                )
                                urls = _extract_image_urls(msg_str)
                                files = _extract_image_files(msg_str) if not urls else []
                    except Exception as e:
                        logger.error("通过 API 获取原消息失败: %s", e)

        if not urls and not files:
            return None

        ok_pids = []
        dup_count = 0
        # 下载 URL 图片
        for url in urls:
            url = url.replace("&amp;", "&")
            tmp_path = str(Path(GALLERY_DIR, f"_tmp_{int(time.time() * 1000)}_{random.randint(0, 999)}.jpg"))
            try:
                await self._download(url, tmp_path)
                pid, err = await self._mgr.add_pic(name, tmp_path, user_id=event.user_id,
                                                    check_duplicated=True)
                if pid:
                    ok_pids.append(pid)
                else:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
                    if err:
                        logger.info("存图跳过: %s", err)
                        dup_count += 1
            except Exception as e:
                logger.error("下载图片失败: %s", e)
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

        # 通过 API 下载
        for f in files:
            real_url = await self._get_image_url_via_api(f)
            if not real_url:
                continue
            tmp_path = str(Path(GALLERY_DIR, f"_tmp_{int(time.time() * 1000)}_{random.randint(0, 999)}.jpg"))
            try:
                await self._download(real_url, tmp_path)
                pid, err = await self._mgr.add_pic(name, tmp_path, user_id=event.user_id,
                                                    check_duplicated=True)
                if pid:
                    ok_pids.append(pid)
                else:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
                    if err:
                        logger.info("存图跳过: %s", err)
                        dup_count += 1
            except Exception as e:
                logger.error("API 下载图片失败: %s", e)
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

        if ok_pids:
            hid = _add_history(event.user_id, ok_pids)
            log_line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | @{event.user_id} | {name} | pids={ok_pids}"
            Path(ADD_LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
            with open(ADD_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(log_line + "\n")
            logger.info("图库 %s: 用户 %s 存了 %d 张 pids=%s", name, event.user_id, len(ok_pids), ok_pids)
            msg = f"已存入 {len(ok_pids)} 张到「{name}」图库。"
            if dup_count:
                msg += f" 跳过 {dup_count} 张重复。"
            return msg
        if dup_count:
            return f"图片重复，未存入。"
        return None

    async def _get_image_url_via_api(self, file_id: str) -> str | None:
        if not self._api_caller:
            logger.warning("未设置 API caller")
            return None
        resp = await self._api_caller("get_image", {"file": file_id})
        if resp and resp.get("status") == "ok":
            return resp.get("data", {}).get("url")
        return None

    async def _download(self, url: str, path: str):
        import aiohttp
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    with open(path, "wb") as f:
                        f.write(await resp.read())

    # ── 取图 ──

    async def _get_image(self, event: MessageEvent, name: str) -> str | None:
        g = self._mgr.find(name)
        if not g:
            return f"图库「{name}」不存在。"
        if not g.pics:
            return f"图库「{name}」是空的。"
        pic = random.choice(g.pics)
        if not os.path.exists(pic.path):
            return f"图片文件不存在了 (pid={pic.pid})"
        cq = _image_to_cq(pic.path)
        return cq or "读取图片失败。"

    # ── 查看画廊 ── (已移除 /看 指令)
