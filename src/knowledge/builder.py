"""知识库构建脚本 — 从 ProjectSekai-story 仓库构建多语言角色知识库"""

import argparse
import logging
import os
import sys

from src.knowledge.parser import build_knowledge_base

logger = logging.getLogger("autochat.knowledge.builder")

DEFAULT_STORY_DIRS = [
    "D:/tmp/ProjectSekai-story/story_cn",
    "D:/tmp/ProjectSekai-story/story_jp",
    "D:/tmp/ProjectSekai-story/story_en",
]


def main():
    parser = argparse.ArgumentParser(description="构建 AutoChat 角色知识库（支持多语言）")
    parser.add_argument(
        "--story-dirs", nargs="*", default=None,
        help="故事目录列表（默认: cn + jp + en）",
    )
    parser.add_argument(
        "--output", default="memory/knowledge.json",
        help="输出 JSON 路径",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    story_dirs = args.story_dirs
    if not story_dirs:
        story_dirs = [d for d in DEFAULT_STORY_DIRS if os.path.isdir(d)]

    if not story_dirs:
        logger.error("未找到任何故事目录！请指定 --story-dirs")
        return 1

    logger.info("开始构建多语言知识库...")
    for d in story_dirs:
        logger.info("  扫描目录: %s", d)
    logger.info("输出路径: %s", args.output)

    entries = build_knowledge_base(
        story_dirs=story_dirs,
        output_path=args.output,
    )

    logger.info("构建完成: 共 %d 条故事条目", len(entries))
    return 0


if __name__ == "__main__":
    sys.exit(main())
