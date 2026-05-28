"""故事文件解析器 — 从 ProjectSekai-story 仓库提取冬弥相关剧情（支持多语言）"""

import json
import logging
import os
import re
from typing import Optional

logger = logging.getLogger("autochat.knowledge.parser")

# 各语言角色名模式
CHARACTER_PATTERNS = {
    "cn": ("冬弥", ["冬弥", "青柳冬弥"]),
    "jp": ("冬弥", ["冬弥", "青柳冬弥"]),
    "en": ("Toya", ["Toya", "Toya Aoyagi"]),
}

# 语言检测：从路径关键字判断
LANG_MAP = {
    "story_cn": "cn",
    "story_jp": "story_jp",
    "story_en": "story_en",
}


def _detect_language(filepath: str) -> str:
    """从文件路径检测语言。"""
    normalized = filepath.replace("\\", "/")
    if "/story_cn/" in normalized:
        return "cn"
    if "/story_jp/" in normalized:
        return "jp"
    if "/story_en/" in normalized:
        return "en"
    return "cn"


def _get_name_patterns(filepath: str) -> tuple[str, list[str]]:
    """根据语言获取角色名模式。"""
    lang = _detect_language(filepath)
    return CHARACTER_PATTERNS[lang]


# 台词正则（匹配 角色名：文本）
SPEECH_RE = re.compile(r"^(.+?)[：:](\s*.+)$")

# 场景标题正则
SCENE_RE = re.compile(r"[【\[\(<](.+?)[】\]\)>]")


def parse_story_file(filepath: str) -> Optional[dict]:
    """解析单个故事文件，提取冬弥的台词及相关场景。

    Returns:
        {
            "source": str,
            "title": str,
            "language": "cn"|"jp"|"en",
            "characters": [str],
            "scenes": [{ "name": str, "dialogue": [...] }],
            "touya_lines": [str],
        }
    """
    try:
        with open(filepath, encoding="utf-8") as f:
            text = f.read()
    except Exception as e:
        logger.warning("读取失败 %s: %s", filepath, e)
        return None

    lines = text.split("\n")
    lang = _detect_language(filepath)
    name_label, name_variants = _get_name_patterns(filepath)
    touya_names = set(name_variants)

    # 标题（首行）
    title = lines[0].strip() if lines else ""

    # 登场角色 — 处理各语言格式
    characters = []
    for line in lines[:10]:
        m = re.search(r"(?:角色|Character)[：:]*(.+?)\)", line)
        if m:
            chars = [c.strip() for c in re.split(r"[、,，]", m.group(1)) if c.strip()]
            characters.extend(chars)

    # 按场景分割
    scenes = []
    current_scene = None
    current_dialogue = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        scene_match = SCENE_RE.search(stripped)
        if scene_match and len(stripped) < 60:
            # 保存上一个场景
            if current_scene is not None:
                scenes.append({
                    "name": current_scene,
                    "dialogue": list(current_dialogue),
                })
            current_scene = scene_match.group(1)
            current_dialogue = []
            continue

        # 台词行
        speaker_match = SPEECH_RE.match(stripped)
        if speaker_match:
            speaker = speaker_match.group(1).strip()
            speech = speaker_match.group(2).strip()
            current_dialogue.append({"speaker": speaker, "text": speech})

    # 最后一个场景
    if current_scene is not None:
        scenes.append({
            "name": current_scene,
            "dialogue": list(current_dialogue),
        })

    # 提取角色的台词
    touya_lines = []
    for scene in scenes:
        for d in scene["dialogue"]:
            if d["speaker"] in touya_names:
                touya_lines.append(d["text"])

    return {
        "source": filepath,
        "title": title,
        "language": lang,
        "characters": list(set(characters)),
        "scenes": scenes,
        "touya_lines": touya_lines,
    }


def extract_tags(text: str, language: str = "cn") -> list[str]:
    """从文本中提取关键词标签。"""
    if language == "jp":
        # 日文：提取假名+汉字
        keywords = re.findall(r"[一-鿿ぁ-んァ-ンーa-zA-Z]{2,}", text)
    elif language == "en":
        # 英文：提取单词
        keywords = re.findall(r"[a-zA-Z]{3,}", text)
        keywords = [kw.lower() for kw in keywords]
    else:
        # 中文
        keywords = re.findall(r"[一-鿿A-Za-z0-9]{2,}", text)

    stop_words = {
        "一个", "什么", "这个", "那个", "可以", "没有", "我们",
        "自己", "知道", "时候", "这么", "怎么", "还是", "就是",
        "因为", "已经", "但是", "不是", "如果", "虽然", "所以",
        "不过", "然后", "而且", "非常", "一下", "可能", "大家",
        "the", "and", "for", "that", "this", "with", "was",
        "are", "but", "not", "you", "all", "can", "have",
        "has", "had", "its", "just", "like", "what", "were",
        "will", "your", "だっ", "ない", "いる", "する", "いう",
        "ある", "これ", "それ", "ため", "こと", "もの", "さん",
    }
    seen = set()
    tags = []
    for kw in keywords:
        lkw = kw.lower() if language == "en" else kw
        if lkw not in seen and lkw not in stop_words and len(kw) > 1:
            tags.append(kw)
            seen.add(lkw)
    return tags[:20]


def build_knowledge_base(
    story_dirs: list[str],
    output_path: str,
) -> list[dict]:
    """扫描多个语言的剧情目录，构建角色台词知识库。

    Args:
        story_dirs: 各语言故事目录路径列表
        output_path: 输出 JSON 路径
        character_names: 各语言角色名，用于过滤文件

    Returns:
        知识库条目列表
    """
    knowledge = []
    total = 0
    skipped = 0

    for story_dir in story_dirs:
        if not os.path.isdir(story_dir):
            logger.warning("故事目录不存在，跳过: %s", story_dir)
            continue

        lang_label = _detect_language(story_dir)
        logger.info("扫描 %s (%s)...", story_dir, lang_label)

        for root, dirs, files in os.walk(story_dir):
            for fname in files:
                if not fname.endswith(".txt"):
                    continue
                fpath = os.path.join(root, fname)

                # 检查文件内容是否包含角色名（按语言匹配）
                try:
                    with open(fpath, encoding="utf-8") as f:
                        preview = f.read(2048)
                    _, name_variants = _get_name_patterns(fpath)
                    if not any(n in preview for n in name_variants):
                        continue
                except Exception:
                    continue

                total += 1
                parsed = parse_story_file(fpath)
                if parsed is None or not parsed["touya_lines"]:
                    skipped += 1
                    continue

                rel_path = os.path.relpath(fpath, story_dir)
                parsed["source"] = rel_path

                # 提取标签
                all_text = " ".join(parsed["touya_lines"])
                parsed["tags"] = extract_tags(all_text, parsed["language"])

                # 索引文本（用于检索）
                dialogue_texts = []
                for scene in parsed["scenes"]:
                    for d in scene["dialogue"]:
                        dialogue_texts.append(f"{d['speaker']}: {d['text']}")
                parsed["_search_text"] = "\n".join(dialogue_texts)

                knowledge.append(parsed)

    # 写出 JSON
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(knowledge, f, ensure_ascii=False, indent=2)

    logger.info(
        "知识库构建完成: 共 %d 个故事文件 (跳过 %d 个), 输出到 %s",
        total, skipped, output_path,
    )
    # 按语言统计
    lang_count = {}
    for entry in knowledge:
        lang = entry.get("language", "?")
        lang_count[lang] = lang_count.get(lang, 0) + 1
    logger.info("语言分布: %s", lang_count)

    return knowledge
