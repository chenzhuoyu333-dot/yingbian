"""读取项目根目录的 .env（不进 Git）。

规则：
  · 不覆盖已存在的环境变量（命令行 set 的优先级更高）
  · 支持 # 注释、空行、KEY=VALUE、值两侧引号
  · 导入本模块即生效
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env(path: str | None = None) -> None:
    f = Path(path) if path else ROOT / ".env"
    if not f.exists():
        return
    for raw in f.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def key(name: str) -> str:
    """取一个配置项；取不到返回空字符串"""
    return (os.environ.get(name) or "").strip()


load_env()
