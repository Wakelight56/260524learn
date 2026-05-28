"""配置管理 — 加载/合并/热重载"""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("autochat.config")


class ConfigManager:
    """配置管理器，支持 config.json + config.local.json 合并"""

    def __init__(self, config_dir: str = "config"):
        self._config_dir = Path(config_dir)
        self._data: dict[str, Any] = {}

    def load(self):
        main_path = self._config_dir / "config.json"
        local_path = self._config_dir / "config.local.json"

        if not main_path.exists():
            raise FileNotFoundError(f"配置文件不存在: {main_path}")

        with open(main_path, encoding="utf-8") as f:
            self._data = json.load(f)

        if local_path.exists():
            with open(local_path, encoding="utf-8") as f:
                local = json.load(f)
            self._deep_merge(self._data, local)
            logger.info("已合并本地配置覆盖: %s", local_path)

        return self._data

    def reload(self):
        self.load()

    def get(self, key: str, default=None):
        keys = key.split(".")
        val = self._data
        for k in keys:
            if isinstance(val, dict):
                val = val.get(k)
                if val is None:
                    return default
            else:
                return default
        return val

    @property
    def data(self) -> dict:
        return self._data

    @staticmethod
    def _deep_merge(base: dict, override: dict):
        for k, v in override.items():
            if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                ConfigManager._deep_merge(base[k], v)
            else:
                base[k] = v
