"""今日小猪插件 — 每日随机抽取专属小猪并生成配图"""
import asyncio
import datetime
import json
import logging
import random
import tempfile
from pathlib import Path

from PIL import Image as PILImage
from PIL import ImageDraw, ImageFont

from src.plugin.base import Plugin, register_plugin
from src.platform.event import MessageEvent

logger = logging.getLogger("autochat.plugin.user.rollpig")

RESOURCE_DIR = Path(__file__).parent / "rollpig_data"
FONT_DIR = RESOURCE_DIR / "font"
IMAGE_DIR = RESOURCE_DIR / "image"
PIGINFO_PATH = RESOURCE_DIR / "pig.json"
DATA_DIR = Path("data/rollpig")
TODAY_PATH = DATA_DIR / "rollpig_today.json"


def _image_to_cq(filepath: str) -> str:
    """将图片文件转为 CQ image code（base64 编码）"""
    import base64
    with open(filepath, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"[CQ:image,file=base64://{b64}]"


@register_plugin
class RollPigPlugin(Plugin):
    CANVAS_WIDTH = 800
    CANVAS_HEIGHT = 800
    AVATAR_SIZE = 280
    SPACING_AVATAR_NAME = 20
    SPACING_NAME_DESC = 25
    SPACING_DESC_ANALYSIS = 30
    DESC_FONT_SIZE = 32
    ANALYSIS_FONT_SIZE = 28
    ANALYSIS_LINE_HEIGHT_FACTOR = 1.6
    ANALYSIS_WIDTH_RATIO = 0.85
    NAME_FONT_SIZE = 66

    def __init__(self):
        super().__init__()
        self.config = {"at_view_pig": False}

        self.res_dir = RESOURCE_DIR
        self.font_dir = FONT_DIR
        self.piginfo_path = PIGINFO_PATH
        self.image_dir = IMAGE_DIR

        FONT_DIR.mkdir(parents=True, exist_ok=True)
        IMAGE_DIR.mkdir(parents=True, exist_ok=True)

        self.pig_list = self.load_json(self.piginfo_path, [])
        if not self.pig_list:
            logger.error("小猪信息为空或不存在，请检查资源文件！")
        self.today_path = TODAY_PATH
        self.font_regular = self._init_regular_font()
        self.font_bold = self._init_bold_font()

    def _load_font(self, font_candidates, size, purpose):
        for font_path in font_candidates:
            if Path(font_path).exists():
                try:
                    return ImageFont.truetype(str(font_path), size)
                except Exception as e:
                    logger.warning(f"加载{purpose}字体{font_path}失败: {e}")
                    continue
        logger.warning(f"未找到{purpose}字体，使用默认字体")
        return ImageFont.load_default()

    def _init_regular_font(self):
        font_paths = [
            # 宋体优先（思源宋体 / Noto Serif CJK）
            self.font_dir / "NotoSerifSC-Regular.otf",
            # 微软雅黑（仅 Windows 可用）
            "C:/Windows/Fonts/msyh.ttc",
            # Linux Docker 备选
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            # macOS 备选
            "/System/Library/Fonts/PingFang.ttc",
        ]
        return self._load_font(font_paths, self.DESC_FONT_SIZE, "常规")

    def _init_bold_font(self):
        font_paths = [
            self.font_dir / "NotoSerifSC-Bold.otf",
            "C:/Windows/Fonts/msyhbd.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/System/Library/Fonts/PingFang.ttc",
        ]
        return self._load_font(font_paths, self.NAME_FONT_SIZE, "加粗")

    def _get_text_size(self, text, font):
        draw = ImageDraw.Draw(PILImage.new("RGB", (1, 1)))
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            return (bbox[2] - bbox[0], bbox[3] - bbox[1])
        except Exception:
            return draw.textsize(text, font=font)

    def _draw_bold_text(self, draw, pos, text, font, fill):
        x, y = pos
        offsets = [(1, 0), (-1, 0), (0, 1), (0, -1)]
        for ox, oy in offsets:
            draw.text((x + ox, y + oy), text, fill=fill, font=font)
        draw.text((x, y), text, fill=fill, font=font)

    def load_json(self, path, default):
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(default, ensure_ascii=False, indent=2), encoding="utf-8")
            return default
        try:
            return json.loads(path.read_text("utf-8"))
        except json.JSONDecodeError:
            logger.error(f"JSON文件解析失败，重置为默认值: {path}")
            path.write_text(json.dumps(default, ensure_ascii=False, indent=2), encoding="utf-8")
            return default

    def save_json(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def find_image_file(self, pig_id):
        exts = ["png", "jpg", "jpeg", "webp", "gif"]
        for ext in exts:
            file = self.image_dir / f"{pig_id}.{ext}"
            if file.exists():
                return file
        return None

    def render_pig_image(self, pig_data):
        pig_id = pig_data.get("id", "")
        pig_name = pig_data.get("name", "未知小猪")
        pig_desc = pig_data.get("description", "无描述")
        pig_analysis = pig_data.get("analysis", "无解析")

        canvas_width = self.CANVAS_WIDTH
        canvas_height = self.CANVAS_HEIGHT
        canvas = PILImage.new("RGB", (canvas_width, canvas_height), (255, 255, 255))
        draw = ImageDraw.Draw(canvas)

        avatar_w = self.AVATAR_SIZE
        avatar_h = self.AVATAR_SIZE
        avatar = None
        avatar_path = self.find_image_file(pig_id)
        if avatar_path:
            try:
                avatar = PILImage.open(avatar_path)
                avatar.thumbnail((avatar_w, avatar_h))
                if avatar.size != (avatar_w, avatar_h):
                    center_x = avatar.width // 2
                    center_y = avatar.height // 2
                    half = self.AVATAR_SIZE // 2
                    avatar = avatar.crop((center_x - half, center_y - half, center_x + half, center_y + half))
            except Exception as e:
                logger.error(f"加载小猪图片失败: {e}")
                avatar = None

        name_font = self.font_bold
        name_w, name_h = self._get_text_size(pig_name, name_font)

        desc_font = self.font_regular.font_variant(size=self.DESC_FONT_SIZE)
        desc_w, desc_h = self._get_text_size(pig_desc, desc_font)

        analysis_font = self.font_regular.font_variant(size=self.ANALYSIS_FONT_SIZE)
        line_height = int(self.ANALYSIS_FONT_SIZE * self.ANALYSIS_LINE_HEIGHT_FACTOR)
        max_analysis_width = int(canvas_width * self.ANALYSIS_WIDTH_RATIO)

        analysis_lines = []
        current_line = ""
        for char in pig_analysis:
            current_line += char
            line_w, _ = self._get_text_size(current_line, analysis_font)
            if line_w > max_analysis_width:
                analysis_lines.append(current_line[:-1])
                current_line = char
        if current_line:
            analysis_lines.append(current_line)
        analysis_total_h = len(analysis_lines) * line_height

        total_content_h = (avatar_h + self.SPACING_AVATAR_NAME + name_h
                          + self.SPACING_NAME_DESC + desc_h
                          + self.SPACING_DESC_ANALYSIS + analysis_total_h)
        start_y = (canvas_height - total_content_h) // 2

        avatar_x = (canvas_width - avatar_w) // 2
        avatar_y = start_y
        if avatar:
            canvas.paste(avatar, (avatar_x, avatar_y), mask=avatar if avatar.mode == "RGBA" else None)
        else:
            error_font = self.font_regular.font_variant(size=24)
            error_text = "图片加载失败"
            error_w, _ = self._get_text_size(error_text, error_font)
            draw.text(((canvas_width - error_w) // 2, avatar_y + 120), error_text, fill=(255, 0, 0), font=error_font)

        name_y = avatar_y + avatar_h + self.SPACING_AVATAR_NAME
        name_x = (canvas_width - name_w) // 2
        self._draw_bold_text(draw, (name_x, name_y), pig_name, name_font, (0, 0, 0))

        desc_y = name_y + name_h + self.SPACING_NAME_DESC
        desc_x = (canvas_width - desc_w) // 2
        draw.text((desc_x, desc_y), pig_desc, fill=(85, 85, 85), font=desc_font)

        analysis_y = desc_y + desc_h + self.SPACING_DESC_ANALYSIS
        for line in analysis_lines:
            line_w, _ = self._get_text_size(line, analysis_font)
            line_x = (canvas_width - line_w) // 2
            draw.text((line_x, analysis_y), line, fill=(51, 51, 51), font=analysis_font)
            analysis_y += line_height

        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = Path(tmp.name)
                canvas.save(tmp_path, format="PNG", quality=95)
            if not tmp_path.exists():
                return None
            return tmp_path
        except Exception as e:
            logger.error(f"合成图片失败: {e}")
            return None

    async def roll_pig(self, event: MessageEvent) -> str:
        """抽取今日小猪"""
        today_str = datetime.date.today().isoformat()
        user_id = event.user_id

        today_cache = self.load_json(self.today_path, {"date": "", "records": {}})
        if today_cache.get("date") != today_str:
            today_cache = {"date": today_str, "records": {}}
        user_records = today_cache["records"]

        if user_id in user_records:
            pig = user_records[user_id]
        else:
            if not self.pig_list:
                return "小猪信息加载失败，请检查后台报错！"
            pig = random.choice(self.pig_list)
            user_records[user_id] = pig
            self.save_json(self.today_path, today_cache)

        return await self.send_rendered_pig(pig, user_id)

    async def send_rendered_pig(self, pig_data, user_id):
        """合成并发送小猪图片"""
        img_path = await asyncio.to_thread(self.render_pig_image, pig_data)
        if img_path and img_path.exists():
            try:
                cq = _image_to_cq(str(img_path.absolute()))
                return f". 这是你的今日小猪：\n{cq}"
            except Exception as e:
                logger.error(f"合成图片失败: {e}")
            finally:
                try:
                    img_path.unlink(missing_ok=True)
                except Exception:
                    pass

        return self.send_fallback_msg(pig_data)

    def send_fallback_msg(self, pig_data):
        """降级发送：纯文本"""
        pig_name = pig_data.get("name", "未知小猪")
        pig_desc = pig_data.get("description", "无描述")
        pig_analysis = pig_data.get("analysis", "无解析")
        return f"【今日小猪】\n名称：{pig_name}\n描述：{pig_desc}\n解析：{pig_analysis}"

    def get_pig_by_id(self, pig_id: str) -> dict | None:
        for pig in self.pig_list:
            if pig.get("id") == pig_id:
                return pig
        return None

    @property
    def name(self) -> str:
        return "rollpig"

    @property
    def description(self) -> str:
        return "每日随机抽取专属小猪"

    async def on_message(self, event: MessageEvent) -> str | None:
        text = event.message.strip()
        for cmd in ["rollpig", "今日小猪", "抽小猪", "我的小猪"]:
            if text == cmd or text.startswith(cmd + " "):
                return await self.roll_pig(event)
        return None
