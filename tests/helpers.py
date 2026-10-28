#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试公用工具。"""

from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Dict, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_provider_config() -> dict:
    return json.loads((ROOT / "provider.json").read_text(encoding="utf-8"))


def make_env(
    base_url: str,
    tmpdir: Path,
    key: str = "sk-test-key-0123456789",
    key_filename: str = "api.txt",
    write_key: bool = True,
    extra: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, str], Path]:
    """造一份指向 base_url 的 provider.json + 密钥文件，返回 (env, provider_path)。"""
    cfg = load_provider_config()
    cfg["base_url"] = base_url
    cfg["base_url_fallbacks"] = []
    provider_path = tmpdir / "provider.json"
    provider_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    if write_key:
        (tmpdir / key_filename).write_text(key + "\n", encoding="utf-8")

    env = dict(os.environ)
    env["VIDEO_PROVIDER_DIR"] = str(tmpdir)
    env["VIDEO_PROVIDER_CONFIG"] = str(provider_path)
    env.pop("VIDEO_API_KEY", None)
    if extra:
        env.update(extra)
    return env, provider_path


def apply_env(env: Dict[str, str]) -> None:
    """把 env 里的 VIDEO_* 写进当前进程环境（供 importlib.reload 使用）。"""
    for key, value in env.items():
        if key.startswith("VIDEO_"):
            os.environ[key] = value
    os.environ.pop("VIDEO_API_KEY", None)


def load_server(env: Dict[str, str]):
    """在给定环境下重新加载 server 模块（配置在 import 时读取）。"""
    apply_env(env)
    import server

    return importlib.reload(server)


def tmpdir() -> Path:
    return Path(tempfile.mkdtemp(prefix="video-mcp-test-"))
