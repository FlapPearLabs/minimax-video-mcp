#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API key 读取与解析 —— 全项目共用（server / install / tests）。

设计目标：**用户只需要把 key 粘贴进 api.txt，其余一律容错。**

处理的情况：
  - 文件不存在 / 空文件 / 只有注释 / 只有空白
  - UTF-8 BOM、CRLF 换行、行尾空白与 Tab
  - 前后引号（单/双）、`Bearer ` 前缀、整行 `Authorization: Bearer sk-xxx`
  - 粘贴成了 JSON（`{"api_key": "sk-..."}`）
  - 一个文件里有多行内容（取第一个像 key 的，优先 `sk-` 开头）
  - 误粘了带空格的一行（识别出来并跳过，不当成 key）
  - 优先级：配置内联 > 环境变量 > 密钥文件
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# 允许的密钥文件名，按优先级排列
KEY_FILE_CANDIDATES: Tuple[str, ...] = ("api.txt", "apikey.txt", "api_key.txt")

# JSON 里可能出现的 key 字段名
_JSON_FIELDS: Tuple[str, ...] = ("api_key", "apikey", "api-key", "key", "token", "sk")

# key 的最小长度，低于此值判定为误粘贴
MIN_KEY_LEN = 8


@dataclass
class KeyResult:
    """key 解析结果。"""

    key: Optional[str] = None
    source: str = "missing"          # config / env:NAME / file:NAME / missing
    path: Optional[Path] = None
    warnings: List[str] = field(default_factory=list)
    candidates: List[str] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return bool(self.key)


def _strip_wrapping(text: str) -> str:
    """去掉成对的首尾引号。"""
    s = text.strip()
    for _ in range(2):
        if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
            s = s[1:-1].strip()
    return s


def _normalize_candidate(raw: str) -> Optional[str]:
    """把一行原始内容归一化成可能的 key。

    顺序很关键：**先剥引号，再认 Authorization / Bearer 前缀**。
    否则 `"Bearer sk-xxx"` 这种（引号套着前缀的）会被漏掉。
    """
    s = _strip_wrapping(raw)
    if not s:
        return None

    # 整行 Authorization 头
    m = re.match(r"(?i)^authorization\s*[:=]\s*(.+)$", s)
    if m:
        s = _strip_wrapping(m.group(1).strip())

    # Bearer 前缀（大小写不敏感）
    m = re.match(r"(?i)^bearer\s+(.+)$", s)
    if m:
        s = _strip_wrapping(m.group(1).strip())

    s = _strip_wrapping(s)
    return s or None


def read_text_safe(path: Path) -> str:
    """读文件，自动吃掉 BOM、统一换行，解码失败也不抛。"""
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    for enc in ("utf-8-sig", "utf-8", "gbk", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - latin-1 不会失败
        text = data.decode("utf-8", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def parse_key_text(text: str) -> Tuple[Optional[str], List[str], List[str]]:
    """从一段文本里解析出 key。

    返回 (key, warnings, candidates)。
    key 为 None 表示没解析出来，此时 warnings 一定非空。
    """
    warnings: List[str] = []
    candidates: List[str] = []

    if not text or not text.strip():
        return None, ["文件是空的"], candidates

    # 去掉 BOM（即使调用方直接传原文也要兜住）
    text = text.lstrip("\ufeff")

    # --- 情况 1：整个文件是 JSON ---
    stripped = text.strip()
    if stripped.startswith("{"):
        obj = None
        try:
            obj = json.loads(stripped)
        except (json.JSONDecodeError, ValueError):
            obj = None
        if isinstance(obj, dict):
            for field_name in _JSON_FIELDS:
                value = obj.get(field_name)
                if isinstance(value, str) and value.strip():
                    key = _normalize_candidate(value)
                    if key:
                        warnings.append(
                            f"检测到 JSON 格式，已从 {field_name!r} 字段取出 key"
                        )
                        return key, warnings, [key]
            warnings.append("文件是 JSON，但里面没有找到 api_key / key / token 字段")

    # --- 情况 2：逐行 ---
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("#") or line.startswith("//"):
            continue
        normalized = _normalize_candidate(line)
        if normalized:
            candidates.append(normalized)

    if not candidates:
        return None, warnings + ["没找到任何可用的 key（只有注释或空行）"], candidates

    # --- 情况 3：过滤掉明显不是 key 的 ---
    valid: List[str] = []
    for c in candidates:
        if re.search(r"\s", c):
            warnings.append("跳过了一行含空格的疑似内容（不像 key）")
            continue
        if len(c) < MIN_KEY_LEN:
            warnings.append("跳过了一行过短的疑似内容（不像 key）")
            continue
        valid.append(c)

    if not valid:
        return None, warnings + ["没找到可用的 key（内容不像 key）"], candidates

    # --- 情况 4：多个候选时优先 sk- 开头 ---
    sk_candidates = [c for c in valid if c.lower().startswith("sk-")]
    if sk_candidates:
        key = sk_candidates[0]
        if len(valid) > 1:
            warnings.append(f"文件里有 {len(valid)} 行可用内容，已取第一个 sk- 开头的 key")
    else:
        key = valid[0]
        if not key.lower().startswith("sk-"):
            warnings.append("key 不是 sk- 开头，仍会尝试使用（不同厂商前缀可能不同）")
        if len(valid) > 1:
            warnings.append(f"文件里有 {len(valid)} 行可用内容，已取第一行")

    return key, warnings, candidates


def find_key_file(
    directory: Path,
    explicit: Optional[str] = None,
    extra: Sequence[str] = (),
) -> List[Path]:
    """列出可能存在的密钥文件（按优先级），已存在的排前面。"""
    ordered: List[Path] = []

    def add(p: Path) -> None:
        if p not in ordered:
            ordered.append(p)

    if explicit:
        p = Path(explicit)
        add(p if p.is_absolute() else directory / p)
    for name in KEY_FILE_CANDIDATES:
        add(directory / name)
    for name in extra:
        p = Path(name)
        add(p if p.is_absolute() else directory / p)
    return ordered


def resolve_key(
    auth_cfg: Optional[Dict[str, object]],
    config_dir: Path,
    env: Optional[Dict[str, str]] = None,
) -> KeyResult:
    """按优先级解析出可用的 key。

    优先级：配置内联 api_key > 环境变量 api_key_env > 密钥文件。
    """
    env = os.environ if env is None else env
    auth_cfg = auth_cfg or {}
    warnings: List[str] = []

    inline = auth_cfg.get("api_key")
    if inline and str(inline).strip():
        return KeyResult(
            key=str(inline).strip(),
            source="config",
            warnings=warnings,
            candidates=[str(inline).strip()],
        )

    env_name = auth_cfg.get("api_key_env")
    if env_name:
        value = env.get(str(env_name))
        if value and value.strip():
            return KeyResult(
                key=value.strip(),
                source=f"env:{env_name}",
                warnings=warnings,
                candidates=[value.strip()],
            )

    explicit = auth_cfg.get("api_key_file")
    for path in find_key_file(config_dir, str(explicit) if explicit else None):
        if not path.exists() or not path.is_file():
            continue
        key, file_warnings, candidates = parse_key_text(read_text_safe(path))
        for w in file_warnings:
            warnings.append(f"{path.name}: {w}")
        if key:
            return KeyResult(
                key=key,
                source=f"file:{path.name}",
                path=path,
                warnings=warnings,
                candidates=candidates,
            )
        warnings.append(f"{path.name} 里没找到可用的 key，继续找下一个")

    if not warnings:
        warnings.append("没有找到任何密钥文件")
    return KeyResult(key=None, source="missing", warnings=warnings)
