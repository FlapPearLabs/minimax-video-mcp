#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键安装 / 自检脚本。

    python install.py

做六件事，全部幂等，重复跑不会出事：
  1. 检查 Python 版本与依赖（缺了就装）
  2. 从 api.txt 解析 API key（容错解析，见 keyfile.py）
  3. 拿 key 打一次站点，验证鉴权是否通过（只读，不花钱）
  4. 列出这个 key 能用的视频模型
  5. 跑一遍完整测试套件
  6. 打印 MCP server 注册参数（由 Agent 用 mavis 工具完成注册）

不会发起任何计费的视频生成。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# 密钥文件所在目录。默认与本脚本同级，可用 VIDEO_PROVIDER_DIR 覆盖（便于测试 / 集中存放密钥）。
CONFIG_DIR = Path(os.environ.get("VIDEO_PROVIDER_DIR") or HERE)

import keyfile  # noqa: E402

MIN_PYTHON = (3, 9)
OK = "\033[92m OK \033[0m"
BAD = "\033[91mFAIL\033[0m"
WARN = "\033[93mWARN\033[0m"
INFO = "\033[90m .. \033[0m"


def _c(text: str, code: str) -> str:
    return f"{code} {text}"


def step(n: int, title: str) -> None:
    print(f"\n\033[1m[{n}/6] {title}\033[0m")


def fail(msg: str, hints: list[str] | None = None) -> None:
    print(_c(msg, BAD))
    for h in hints or []:
        print(f"       {h}")
    raise SystemExit(1)


def ensure_dependencies(auto_install: bool) -> None:
    missing = []
    for module, pkg in (("mcp", "mcp"), ("requests", "requests")):
        try:
            __import__(module)
        except ImportError:
            missing.append(pkg)

    if not missing:
        print(_c("依赖齐全（mcp / requests）", OK))
        return

    if not auto_install:
        fail(
            f"缺少依赖：{', '.join(missing)}",
            [
                "装一下：  python -m pip install -r requirements.txt",
                "或用虚拟环境：",
                "    python -m venv .venv",
                "    .venv\\Scripts\\activate        # Windows",
                "    source .venv/bin/activate       # macOS / Linux",
                "    pip install -r requirements.txt",
            ],
        )

    print(_c(f"缺少依赖 {', '.join(missing)}，正在自动安装…", WARN))
    req = HERE / "requirements.txt"
    cmd = [sys.executable, "-m", "pip", "install", "-q"]
    cmd += ["-r", str(req)] if req.exists() else missing
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        fail(
            "自动安装依赖失败",
            [
                "请手动执行：",
                "    python -m pip install -r requirements.txt",
                "或用虚拟环境（推荐，避免系统 Python 限制）：",
                "    python -m venv .venv && .venv\\Scripts\\activate",
                "    pip install -r requirements.txt",
                "然后重新运行：python install.py",
                "",
                f"安装器输出：{(proc.stderr or proc.stdout or '').strip()[:500]}",
            ],
        )
    print(_c("依赖安装完成", OK))


def load_config() -> dict:
    cfg_path = HERE / "provider.json"
    if not cfg_path.exists():
        fail(
            "找不到 provider.json",
            [f"应该在 {HERE} 下，请确认仓库完整（重新 git clone）"],
        )
    try:
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"provider.json 解析失败：{exc}", ["文件可能被改坏了，重新 clone 一次"])


def step_key(cfg: dict) -> keyfile.KeyResult:
    step(2, "读取 API key")
    result = keyfile.resolve_key(cfg.get("auth"), CONFIG_DIR)
    for w in result.warnings:
        print(_c(w, WARN))

    if not result.found:
        fail(
            "没找到 API key",
            [
                f"请在这个文件里填入你的 key：{CONFIG_DIR / 'api.txt'}",
                "",
                "内容就一行，例如：",
                "    sk-xxxxxxxxxxxxxxxx",
                "",
                "获取方式：在中转站控制台「管理 API 密钥」创建。",
                "也可以改用环境变量：set VIDEO_API_KEY=sk-xxx",
            ],
        )

    preview = result.key[:6] + "…" + result.key[-4:] if len(result.key) > 12 else result.key
    print(_c(f"已读到 key（来源 {result.source}，{preview}）", OK))
    return result


def step_verify(cfg: dict, key: str) -> str:
    step(3, "验证 key 与站点连通性")
    import requests

    bases = [cfg.get("base_url")] + list(cfg.get("base_url_fallbacks") or [])
    bases = [b.rstrip("/") for b in bases if b]
    if not bases:
        fail("provider.json 里没有 base_url")

    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {key}"

    last = ""
    for base in bases:
        try:
            r = session.get(f"{base}/v1/models", timeout=25)
        except requests.RequestException as exc:
            last = f"{type(exc).__name__}: {exc}"
            print(_c(f"{base} 连不上（{last}）", INFO))
            continue

        if r.status_code == 200:
            print(_c(f"鉴权通过，base_url = {base}", OK))
            return base

        last = f"HTTP {r.status_code} {r.text[:200]}"
        if r.status_code == 401:
            print(_c(f"{base} -> 401，key 不正确", BAD))
            break
        if r.status_code == 403:
            body = r.text
            if "ip_not_allowed" in body:
                print(_c(f"{base} -> 403 ip_not_allowed：你的 IP 不在白名单", BAD))
                print("       去中转站控制台把本机公网 IP 加进「API 密钥 / IP 白名单」，或清空白名单。")
                raise SystemExit(1)
            print(_c(f"{base} -> 403 {body[:160]}", BAD))
            break
        if r.status_code == 402:
            print(_c(f"{base} -> 402 余额不足", BAD))
            print("       去中转站控制台充值后再试。")
            raise SystemExit(1)
        if r.status_code == 429:
            print(_c(f"{base} -> 429 触发限流，等 30 秒后重跑", BAD))
            raise SystemExit(1)
        print(_c(f"{base} -> {last}", INFO))

    hints = []
    if "401" in last:
        hints = [
            "key 复制错了吧？去控制台重新复制，注意没有多余空格。",
            "确认用的是中转站的 key，不是 MiniMax 官方的 key。",
        ]
    elif "403" in last:
        hints = ["检查控制台里的 IP 白名单设置。"]
    elif "余额" in last:
        hints = ["账号余额不足，先充值。"]
    else:
        hints = [
            "站点连不上，检查网络/代理。",
            "也可以改 provider.json 的 base_url 指向你自己的中转站域名。",
        ]
    fail("验证未通过", hints)


def step_models(cfg: dict, key: str, base: str) -> None:
    step(4, "列出可用视频模型")
    import requests

    try:
        data = requests.get(
            f"{base}/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=25,
        ).json().get("data", [])
    except Exception as exc:  # noqa: BLE001
        print(_c(f"拉模型列表失败（不影响使用）：{exc}", WARN))
        return

    hints = [h.lower() for h in (cfg.get("video_model_hints") or [])]
    known = {str(x).lower() for x in (cfg.get("known_video_models") or [])}
    video = [
        m.get("id")
        for m in data
        if m.get("id")
        and (
            str(m["id"]).lower() in known
            or any(h in str(m["id"]).lower() for h in hints)
        )
    ]
    if video:
        print(_c(f"可用视频模型 {len(video)} 个：", OK))
        for m in video[:20]:
            print(f"       - {m}")
        if len(video) > 20:
            print(f"       … 还有 {len(video) - 20} 个")
    else:
        print(_c(f"没识别到视频模型（共 {len(data)} 个模型），不影响视频接口", WARN))


def step_tests() -> None:
    step(5, "运行测试套件")
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-v"],
        cwd=str(HERE),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    tail = (proc.stdout or "").strip().splitlines()[-6:]
    for line in tail:
        print("       " + line)
    if proc.returncode != 0:
        print()
        print((proc.stderr or "")[-2500:])
        fail("测试未通过，请不要继续注册 MCP", ["把上面的报错贴给 Agent 排查"])


def step_register_hint(cfg: dict) -> None:
    step(6, "注册 MCP server")
    print("把下面的参数交给 Agent（用 mavis 工具的 mcp create；若已存在同名则用 mcp update）：")
    print()
    payload = {
        "name": "minimax-video",
        "transport": "stdio",
        "command": "python",
        "args": [str(HERE / "server.py")],
        "env": {"VIDEO_API_KEY": "<你的 key>"},
        "description": "第三方中转站 MiniMax 视频生成",
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print()
    print("如果 Agent 端不方便带 env，也可以不传 env —— server.py 会自己读同目录的 api.txt。")


def main() -> int:
    parser = argparse.ArgumentParser(description="一键安装 / 自检")
    parser.add_argument("--no-install", action="store_true", help="不自动装依赖")
    parser.add_argument("--skip-tests", action="store_true", help="跳过测试")
    args = parser.parse_args()

    print("\033[1m视频 API MCP · 一键安装\033[0m")
    print(f"目录：{HERE}")

    step(1, "检查运行环境")
    if sys.version_info < MIN_PYTHON:
        fail(
            f"Python 版本过低：{sys.version.split()[0]}，需要 {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+",
            ["去 python.org 下载 3.9 以上版本"],
        )
    print(_c(f"Python {sys.version.split()[0]}", OK))
    ensure_dependencies(not args.no_install)

    cfg = load_config()
    key_result = step_key(cfg)
    base = step_verify(cfg, key_result.key or "")
    step_models(cfg, key_result.key or "", base)
    if not args.skip_tests:
        step_tests()
    step_register_hint(cfg)

    print("\n\033[1m准备就绪。\033[0m 把上面第 6 步的 JSON 交给 Agent 完成注册即可。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
