"""知识库增量更新插件 — 检查 Git commits 增量更新"""

import asyncio
import json
import logging
import os

from src.plugin.base import Plugin, register_plugin
from src.platform.event import MessageEvent
from src.knowledge.parser import parse_story_file, extract_tags, CHARACTER_PATTERNS

logger = logging.getLogger("autochat.plugin.update_kb")

_MASTER_QQ: int = 0
_RETRIEVER = None

REPO_URL = "https://github.com/ci-ke/ProjectSekai-story.git"
CLONE_DIR = "/opt/autochat/tmp/ProjectSekai-story"
KB_PATH = "memory/knowledge.json"
COMMIT_FILE = "memory/kb_commit.txt"

LANG_DIR_MAP = {"story_cn": "cn", "story_jp": "jp", "story_en": "en"}


def setup(master_qq: int, retriever):
    global _MASTER_QQ, _RETRIEVER
    _MASTER_QQ = master_qq
    _RETRIEVER = retriever


def _lang_from_git_path(git_path: str) -> tuple[str | None, str | None]:
    """story_cn/event/xxx.txt -> ('cn', 'event/xxx.txt')"""
    parts = git_path.split("/", 1)
    if len(parts) != 2:
        return None, None
    lang = LANG_DIR_MAP.get(parts[0])
    return lang, parts[1]


@register_plugin
class UpdateKnowledgePlugin(Plugin):
    @property
    def name(self) -> str:
        return "update_knowledge"

    async def on_message(self, event: MessageEvent) -> str | None:
        if event.message.strip() not in ("更新知识库", "/update_kb"):
            return None
        if int(event.user_id) != _MASTER_QQ:
            return "你没有权限执行此操作。"
        asyncio.create_task(self._do_update(event))
        return "正在检查知识库更新，请稍候……"

    # ---- helpers ----

    def _read_last_commit(self) -> str | None:
        try:
            with open(COMMIT_FILE) as f:
                return f.read().strip()
        except FileNotFoundError:
            return None

    def _save_commit(self, commit: str):
        os.makedirs(os.path.dirname(COMMIT_FILE), exist_ok=True)
        with open(COMMIT_FILE, "w") as f:
            f.write(commit.strip())

    async def _run_git(self, *args) -> tuple[str, str]:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        return out.decode(), err.decode()

    def _get_story_dirs(self) -> list[str]:
        return [
            d for d in (
                os.path.join(CLONE_DIR, "story_cn"),
                os.path.join(CLONE_DIR, "story_jp"),
                os.path.join(CLONE_DIR, "story_en"),
            ) if os.path.isdir(d)
        ]

    def _parse_one(self, full_path: str, lang: str, rel_path: str) -> dict | None:
        """Parse a single story file into a KB entry."""
        parsed = parse_story_file(full_path)
        if not parsed or not parsed.get("touya_lines"):
            return None
        parsed["source"] = rel_path
        all_text = " ".join(parsed["touya_lines"])
        parsed["tags"] = extract_tags(all_text, lang)
        dialogue_texts = []
        for scene in parsed.get("scenes", []):
            for d in scene.get("dialogue", []):
                dialogue_texts.append(f"{d['speaker']}: {d['text']}")
        parsed["_search_text"] = "\n".join(dialogue_texts)
        return parsed

    async def _full_build(self) -> int | None:
        """Full rebuild from scratch (first time or fallback)."""
        from src.knowledge.parser import build_knowledge_base
        story_dirs = self._get_story_dirs()
        if not story_dirs:
            logger.error("未找到故事目录")
            return None
        entries = build_knowledge_base(story_dirs=story_dirs, output_path=KB_PATH)
        out, _ = await self._run_git("git", "-C", CLONE_DIR, "rev-parse", "HEAD")
        self._save_commit(out.strip())
        if _RETRIEVER:
            _RETRIEVER.load(KB_PATH)
        return len(entries)

    # ---- main update ----

    async def _do_update(self, event: MessageEvent):
        global _RETRIEVER
        try:
            # 1. 首次使用：完整克隆 + 全量构建
            if not os.path.exists(CLONE_DIR):
                logger.info("首次更新: 克隆仓库 %s", REPO_URL)
                out, err = await self._run_git("git", "clone", REPO_URL, CLONE_DIR)
                if "fatal" in (err or "").lower():
                    logger.error("克隆失败: %s", err)
                    return
                count = await self._full_build()
                if count is not None:
                    logger.info("知识库全量构建完成: %d 条", count)
                return

            # 2. 处理浅克隆（兼容旧代码的 --depth 1）
            if os.path.exists(os.path.join(CLONE_DIR, ".git", "shallow")):
                logger.info("转换浅克隆为完整仓库以支持增量更新...")
                await self._run_git("git", "-C", CLONE_DIR, "fetch", "--unshallow", "origin")

            # 3. 获取远程更新
            logger.info("检查远程更新...")
            out, err = await self._run_git("git", "-C", CLONE_DIR, "fetch", "origin")
            if "fatal" in (err or "").lower():
                logger.error("fetch 失败: %s", err)
                return

            # 4. 对比 commit
            last = self._read_last_commit()
            if not last:
                out, _ = await self._run_git("git", "-C", CLONE_DIR, "rev-parse", "HEAD")
                last = out.strip()
            out, _ = await self._run_git("git", "-C", CLONE_DIR, "rev-parse", "origin/main")
            latest = out.strip()

            if last == latest:
                logger.info("知识库已是最新")
                return

            # 5. 获取变更的故事文件
            out, _ = await self._run_git(
                "git", "-C", CLONE_DIR, "diff", "--name-status",
                f"{last}..{latest}", "--",
                "story_cn/", "story_jp/", "story_en/", "*.txt",
            )

            # 如果 diff 失败（历史不连续等），回退全量构建
            if not out.strip():
                logger.warning("增量 diff 无结果，回退全量构建")
                await self._run_git("git", "-C", CLONE_DIR, "pull", "--ff-only")
                await self._full_build()
                return

            changes = []
            for line in out.strip().split("\n"):
                line = line.strip()
                if not line:
                    continue
                parts = line.split("\t", 1)
                if len(parts) == 2 and parts[1].endswith(".txt"):
                    changes.append((parts[0], parts[1]))

            if not changes:
                logger.info("没有故事文件变更，仅更新 commit 记录")
                self._save_commit(latest)
                return

            logger.info("检测到 %d 个文件变更", len(changes))

            # 6. 更新本地工作区
            await self._run_git("git", "-C", CLONE_DIR, "pull", "--ff-only")

            # 7. 解析变更的文件
            new_entries: dict[tuple[str, str], dict] = {}
            deleted_keys: set[tuple[str, str]] = set()

            for status, path in changes:
                lang, rel_path = _lang_from_git_path(path)
                if not lang or not rel_path:
                    continue

                if status == "D":
                    deleted_keys.add((lang, rel_path))
                    continue

                # A / M — 解析文件
                full_path = os.path.join(CLONE_DIR, path)
                if not os.path.exists(full_path):
                    continue

                # 先快速检查是否包含角色名
                _, name_variants = CHARACTER_PATTERNS.get(lang, ("", []))
                try:
                    with open(full_path, encoding="utf-8") as f:
                        preview = f.read(2048)
                    if not any(n in preview for n in name_variants):
                        continue
                except Exception:
                    continue

                parsed = self._parse_one(full_path, lang, rel_path)
                if parsed:
                    new_entries[(lang, rel_path)] = parsed

            # 8. 合并到现有知识库
            kb = []
            if os.path.exists(KB_PATH):
                with open(KB_PATH, encoding="utf-8") as f:
                    kb = json.load(f)

            remove_keys = deleted_keys | set(new_entries.keys())
            kb = [
                e for e in kb
                if (e.get("language"), e.get("source")) not in remove_keys
            ]
            kb.extend(new_entries.values())

            os.makedirs(os.path.dirname(KB_PATH), exist_ok=True)
            with open(KB_PATH, "w", encoding="utf-8") as f:
                json.dump(kb, f, ensure_ascii=False, indent=2)

            # 9. 保存 commit + 重载检索器
            self._save_commit(latest)
            if _RETRIEVER:
                _RETRIEVER.load(KB_PATH)

            logger.info(
                "知识库增量更新完成: +%d -%d =%d 条",
                len(new_entries), len(deleted_keys), len(kb),
            )

        except FileNotFoundError:
            logger.error("知识库更新失败: 服务器未安装 git")
        except Exception as e:
            logger.error("知识库更新异常: %s", e)
