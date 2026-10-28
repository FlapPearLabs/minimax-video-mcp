#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
第三方视频生成 API —— MCP 接入层

对外暴露与 MiniMax 内置 matrix 连接器**同名同形**的工具，Agent 侧的
「提交 → 轮询 → 取货」逻辑可以整套平移：

    submit_video_generation   提交异步任务 → 返回 task_id
    query_video_generation    轮询 → status / video_url / error
    list_video_tasks          批量查任务
    list_video_models         列出站点上可用的视频模型
    regenerate_video_2k       768P 成品升 2K
    delete_video_task         删除已结束的任务记录
    describe_provider         返回适配器配置概览

支持两种请求体形状（由 provider.json 决定，不需要改代码）：

  A. 平铺字段      { "model": ..., "prompt": ..., "duration": ... }
  B. content 数组  { "model": ..., "content": [ {type, role, ...} ], ... }
     —— MiniMax 官方 V2 格式就是 B，provider.json 里存在 "roles" 即启用。

运行（stdio MCP）：
    python server.py

依赖：
    pip install mcp requests
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import requests
except ImportError as _exc:  # pragma: no cover
    sys.stderr.write(
        "缺少依赖 requests。请先运行：\n"
        "    python -m pip install -r requirements.txt\n"
        f"（原始错误：{_exc}）\n"
    )
    raise SystemExit(2)

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as _exc:  # pragma: no cover
    sys.stderr.write(
        "缺少依赖 mcp。请先运行：\n"
        "    python -m pip install -r requirements.txt\n"
        f"（原始错误：{_exc}）\n"
    )
    raise SystemExit(2)

import keyfile

# --------------------------------------------------------------------------
# 配置装载
# --------------------------------------------------------------------------
CONFIG_DIR = Path(os.environ.get("VIDEO_PROVIDER_DIR") or Path(__file__).parent)
CONFIG_PATH = Path(
    os.environ.get("VIDEO_PROVIDER_CONFIG") or (CONFIG_DIR / "provider.json")
)
CONFIG: Dict[str, Any] = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

RETRY_STATUS = {429, 500, 502, 503, 504}
TERMINAL_OK = {"succeeded"}
TERMINAL_BAD = {"failed", "cancelled"}

mcp = FastMCP(CONFIG.get("name", "video-api"))


# --------------------------------------------------------------------------
# 通用工具函数
# --------------------------------------------------------------------------
def dig(obj: Any, path: str, default: Any = None) -> Any:
    """按 'a.b.0.c' 取值；缺失或类型不符返回 default。"""
    cur = obj
    for part in path.split("."):
        if cur is None:
            return default
        if isinstance(cur, list):
            if not part.lstrip("-").isdigit():
                return default
            idx = int(part)
            if idx < 0:
                idx += len(cur)
            if not 0 <= idx < len(cur):
                return default
            cur = cur[idx]
        elif isinstance(cur, dict):
            if part not in cur:
                return default
            cur = cur[part]
        else:
            return default
    return default if cur is None else cur


def _base_candidates() -> List[str]:
    """主 base_url + 备用（同一服务的不同入口/域名）。"""
    out: List[str] = []
    primary = CONFIG.get("base_url")
    if primary:
        out.append(str(primary).rstrip("/"))
    for extra in CONFIG.get("base_url_fallbacks") or []:
        if extra and str(extra).rstrip("/") not in out:
            out.append(str(extra).rstrip("/"))
    return out


def _key_result() -> "keyfile.KeyResult":
    """解析出可用的 key。

    每次调用都重新读盘（文件很小），所以用户改完 api.txt 立刻生效，
    不需要重启 MCP server。
    """
    return keyfile.resolve_key(CONFIG.get("auth"), CONFIG_DIR)


def _api_key() -> Optional[str]:
    """取 key 优先级：配置内联 > 环境变量 > 密钥文件。"""
    return _key_result().key


def _headers() -> Dict[str, str]:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    headers.update(CONFIG.get("extra_headers") or {})
    auth = CONFIG.get("auth", {})
    key = _api_key()
    kind = auth.get("type", "bearer")
    if kind == "bearer" and key:
        headers["Authorization"] = f"Bearer {key}"
    elif kind == "header" and key:
        headers[auth.get("header", "X-Api-Key")] = key
    return headers


def _request(
    method: str,
    path: str,
    *,
    json_body: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: int = 30,
    retries: int = 3,
) -> Dict[str, Any]:
    """带退避重试的 JSON 请求。

    - 只对 429 / 5xx / 网络错误重试；其余 4xx 直接抛出（避免重复扣费）
    - 主域名连不上时自动切到备用域名
    """
    bases = _base_candidates()
    if not bases:
        raise RuntimeError("provider.json 未配置 base_url")
    absolute = str(path).startswith("http")

    auth = CONFIG.get("auth", {})
    if auth.get("type") == "query":
        key = _api_key()
        if key:
            params = dict(params or {})
            params[auth.get("key_param", "key")] = key

    headers = _headers()
    last_err = "unknown"
    # 连接超时单独设上限：站点挂住时不应该把一次工具调用拖到几分钟
    connect_timeout = CONFIG.get("connect_timeout_seconds")

    for base in bases:
        url = path if absolute else base + path
        attempt_timeout = timeout
        if connect_timeout:
            attempt_timeout = min(timeout, int(connect_timeout))
        for attempt in range(retries + 1):
            try:
                resp = requests.request(
                    method, url, headers=headers, json=json_body, params=params,
                    timeout=attempt_timeout,
                )
            except requests.RequestException as exc:
                last_err = f"network error: {exc}"
                # 连不上（DNS 失败 / 端口不通 / 代理挂了）通常不是瞬时问题，
                # 立刻换下一个 base，别在同一个死域名上做 4 次退避重试。
                break

            if resp.status_code in RETRY_STATUS and attempt < retries:
                last_err = f"HTTP {resp.status_code}: {resp.text[:400]}"
                time.sleep(min(2 ** attempt, 8))
                continue

            if resp.status_code >= 400:
                raise RuntimeError(
                    f"{method} {url} failed: HTTP {resp.status_code} :: {resp.text[:800]}"
                )

            try:
                return resp.json()
            except ValueError as exc:
                raise RuntimeError(
                    f"{method} {url} returned non-JSON: {resp.text[:400]}"
                ) from exc

        # 这个域名彻底连不上 -> 试下一个
        time.sleep(1)

    raise RuntimeError(
        f"{method} {path} failed on all base urls {bases}: {last_err}"
    )


def _upload(path: Path, field_hint: str) -> str:
    """本地文件先上传换 URL。需在 provider.json 里配好 upload 段。"""
    spec = CONFIG.get("upload")
    if not spec:
        raise RuntimeError(
            f"{field_hint}: 需要先上传素材，但 provider.json 未配置 upload 段。"
            f"（当前 media_mode={CONFIG.get('media_mode', 'base64')}）"
        )
    url = spec["path"] if str(spec["path"]).startswith("http") else _base_candidates()[0] + spec["path"]
    headers = {k: v for k, v in _headers().items() if k.lower() != "content-type"}
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    with path.open("rb") as fh:
        files = {spec.get("file_field", "file"): (path.name, fh, mime)}
        resp = requests.post(
            url,
            headers=headers,
            files=files,
            data=spec.get("extra_fields") or {},
            timeout=spec.get("timeout_seconds", 120),
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"upload failed: HTTP {resp.status_code} :: {resp.text[:500]}")
    payload = resp.json()
    remote = dig(payload, spec.get("url_path", "data.url"))
    if not remote:
        raise RuntimeError(
            f"upload 响应里找不到素材 URL（url_path={spec.get('url_path')}）: "
            f"{json.dumps(payload, ensure_ascii=False)[:400]}"
        )
    return str(remote)


def _media_value(value: str, field_hint: str) -> str:
    """把媒体引用转成请求体里可用的值。

    - http(s):// / data:  -> 原样透传
    - 本地路径            -> 按 provider.json 的 media_mode 处理
    """
    if not value:
        return value
    if value.startswith(("http://", "https://", "data:")):
        return value

    local = Path(value)
    if not local.exists():
        raise RuntimeError(f"{field_hint}: 本地文件不存在 -> {value}")

    mode = CONFIG.get("media_mode", "base64")
    if mode == "base64":
        mime = mimetypes.guess_type(local.name)[0] or "application/octet-stream"
        blob = base64.b64encode(local.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{blob}"
    if mode == "url":
        raise RuntimeError(
            f"{field_hint}: media_mode=url 只接受公网直链，本地文件请先上传后传 URL"
        )
    if mode == "upload":
        return _upload(local, field_hint)
    raise RuntimeError(
        f"{field_hint}: media_mode 只支持 'base64' / 'url' / 'upload'，当前为 {mode}"
    )


# --------------------------------------------------------------------------
# 请求体组装
# --------------------------------------------------------------------------
def _resolve_model(model: Optional[str]) -> Optional[str]:
    name = model or CONFIG.get("default_model")
    if not name:
        return None
    aliases = CONFIG.get("model_aliases") or {}
    return aliases.get(name, name)


def _build_content_array(args: Dict[str, Any]) -> List[Dict[str, Any]]:
    """按 MiniMax 官方 V2 的 content[] 形状组装多模态输入。"""
    ca = CONFIG.get("content_array", {})
    roles = CONFIG.get("roles") or {}

    content: List[Dict[str, Any]] = [
        {"type": "text", "text": args["prompt"]}
    ]

    for param, spec in roles.items():
        value = args.get(param)
        if not value:
            continue
        items = value if isinstance(value, list) else [value]
        for item in items:
            url = _media_value(item, param)
            entry: Dict[str, Any] = {"type": spec["type"]}
            entry[spec.get("url_container", "image_url")] = {"url": url}
            if spec.get("role"):
                entry["role"] = spec["role"]
            content.append(entry)

    return content


def _validate_request(args: Dict[str, Any], content: Optional[List[Dict[str, Any]]]) -> None:
    """客户端侧先拦下必然被服务端拒绝的组合，避免白烧额度。"""
    rules = CONFIG.get("rules") or {}

    prompt = (args.get("prompt") or "").strip()
    if not prompt:
        raise RuntimeError("prompt 必填且不能为空")
    max_chars = rules.get("prompt_max_chars")
    if max_chars and len(prompt) > max_chars:
        raise RuntimeError(f"prompt 超长：{len(prompt)} 字符，上限 {max_chars}")

    if rules.get("duration_required") and args.get("duration") is None:
        raise RuntimeError("duration 必填（整数秒）")
    if rules.get("resolution_required") and not args.get("resolution"):
        raise RuntimeError("resolution 必填")

    if content is not None:
        roles_seen = {c.get("role") for c in content if c.get("role")}
        # 帧模式与参考模式互斥
        frame_roles = {"first_frame", "last_frame"}
        ref_roles = {"reference_image", "reference_video", "reference_audio"}
        if roles_seen & frame_roles and roles_seen & ref_roles:
            raise RuntimeError(
                "首尾帧模式与多模态参考模式互斥："
                "first_frame/last_frame 不能与 reference_image/reference_video/reference_audio 同传"
            )
        if rules.get("last_frame_requires_first_frame"):
            if "last_frame" in roles_seen and "first_frame" not in roles_seen:
                raise RuntimeError(
                    "本平台暂不支持只传尾帧：last_frame 必须与 first_frame 同时提供"
                )
        if rules.get("max_reference_images"):
            n = len([c for c in content if c.get("role") == "reference_image"])
            if n > rules["max_reference_images"]:
                raise RuntimeError(f"参考图最多 {rules['max_reference_images']} 张，当前 {n}")
        if rules.get("max_reference_videos"):
            n = len([c for c in content if c.get("role") == "reference_video"])
            if n > rules["max_reference_videos"]:
                raise RuntimeError(f"参考视频最多 {rules['max_reference_videos']} 个，当前 {n}")
        if rules.get("max_reference_audios"):
            n = len([c for c in content if c.get("role") == "reference_audio"])
            if n > rules["max_reference_audios"]:
                raise RuntimeError(f"参考音频最多 {rules['max_reference_audios']} 段，当前 {n}")

        # 文生视频必须给具体比例，且不能是 adaptive
        only_text = all(c.get("type") == "text" for c in content)
        ratio = args.get("ratio")
        if only_text:
            if rules.get("ratio_required_for_text_only") and not ratio:
                raise RuntimeError("文生视频必须指定 ratio（如 16:9 / 9:16 / 1:1）")
            if ratio and rules.get("ratio_forbidden_for_text_only") and ratio in rules["ratio_forbidden_for_text_only"]:
                raise RuntimeError(f"文生视频的 ratio 不能是 {ratio}，请给具体比例（如 16:9）")
        if ratio and rules.get("ratio_forbidden_values") and ratio in rules["ratio_forbidden_values"]:
            raise RuntimeError(f"ratio 不支持 {ratio}")

    dr = rules.get("duration_range")
    if dr and args.get("duration") is not None:
        if not (dr[0] <= int(args["duration"]) <= dr[1]):
            raise RuntimeError(f"duration 必须是 {dr[0]}~{dr[1]} 之间的整数秒")


def _build_payload(args: Dict[str, Any]) -> Dict[str, Any]:
    m = CONFIG.get("payload", {})
    payload: Dict[str, Any] = {}

    content = None
    if CONFIG.get("roles"):
        content = _build_content_array(args)
        _validate_request(args, content)

    model = _resolve_model(args.get("model"))
    if model:
        payload[m.get("model_field", "model")] = model

    for opt, field_key in (
        ("duration", "duration_field"),
        ("resolution", "resolution_field"),
        ("ratio", "ratio_field"),
    ):
        value = args.get(opt)
        if value is not None and m.get(field_key):
            payload[m[field_key]] = value

    if content is not None:
        # content 数组模式：官方 V2 只有 model/content/resolution/duration/ratio/extra/callback_url，
        # 不要再多发一个平铺的 prompt 字段。
        payload[CONFIG.get("content_array", {}).get("field", "content")] = content
    else:
        # 平铺字段模式
        payload[m.get("prompt_field", "prompt")] = args["prompt"]
        for opt, field_key in (
            ("input_image", "first_frame_field"),
            ("last_frame_image", "last_frame_field"),
        ):
            if args.get(opt) and m.get(field_key):
                payload[m[field_key]] = _media_value(args[opt], opt)
        for opt, field_key in (
            ("reference_images", "reference_images_field"),
            ("reference_videos", "reference_videos_field"),
            ("reference_audios", "reference_audios_field"),
        ):
            items = args.get(opt) or []
            if items and m.get(field_key):
                payload[m[field_key]] = [_media_value(i, opt) for i in items]
        _validate_request(args, None)

    if args.get("callback_url"):
        payload[CONFIG.get("callback_field", "callback_url")] = args["callback_url"]

    return _adapt_payload(payload, args)


def _adapt_payload(payload: Dict[str, Any], args: Dict[str, Any]) -> Dict[str, Any]:
    """【ADAPTER】无法用配置表达的请求体逻辑写在这里。默认不需要改。

    例：
        # 某些厂商要求缺省 ratio 时显式传 'adaptive'
        # payload.setdefault("ratio", "adaptive")
    """
    return payload


def _extract_task_id(resp: Dict[str, Any], create_cfg: Dict[str, Any]) -> str:
    candidates = [
        create_cfg.get("task_id_path"),
        "task_id",
        "data.task_id",
        "id",
        "task.id",
    ]
    for path in candidates:
        if not path:
            continue
        value = dig(resp, path)
        if isinstance(value, (str, int)) and str(value).strip():
            return str(value)
    raise RuntimeError(
        "创建成功但没解析出 task_id，响应: "
        + json.dumps(resp, ensure_ascii=False)[:600]
    )


def _map_status(raw: Any) -> str:
    if raw is None:
        return "unknown"
    key = str(raw).strip().lower()
    return CONFIG.get("status_map", {}).get(key, key)


# --------------------------------------------------------------------------
# 工具
# --------------------------------------------------------------------------
@mcp.tool()
def submit_video_generation(
    prompt: str,
    model: Optional[str] = None,
    duration: Optional[int] = None,
    resolution: Optional[str] = None,
    ratio: Optional[str] = None,
    input_image: Optional[str] = None,
    last_frame_image: Optional[str] = None,
    reference_images: Optional[List[str]] = None,
    reference_videos: Optional[List[str]] = None,
    reference_audios: Optional[List[str]] = None,
    callback_url: Optional[str] = None,
) -> Dict[str, Any]:
    """提交一个异步视频生成任务，返回 task_id。

    这是"创建"动作，不会阻塞等待成片。提交后用 query_video_generation 轮询。

    参数:
        prompt: 视频描述（必填）。
        model: 模型名。默认 MiniMax-H3（质量最好）。
        duration: 视频时长（秒，整数）。
        resolution: 输出分辨率档位，如 768P / 1080P / 2K。
        ratio: 宽高比。文生视频必填且不能是 adaptive（如 16:9 / 9:16 / 1:1）。
        input_image: 首帧图，URL 或本地文件路径。
        last_frame_image: 尾帧图。本平台要求与首帧同时提供。
        reference_images: 参考图列表（多模态参考模式）。
        reference_videos: 参考视频列表（只接受公网 URL）。
        reference_audios: 参考音频列表。
        callback_url: 可选回调地址。

    返回: {"task_id", "status": "queued", "model", "provider", "request_payload"}
    """
    args = {
        "prompt": prompt,
        "model": model,
        "duration": duration,
        "resolution": resolution,
        "ratio": ratio,
        "input_image": input_image,
        "last_frame_image": last_frame_image,
        "reference_images": reference_images,
        "reference_videos": reference_videos,
        "reference_audios": reference_audios,
        "callback_url": callback_url,
    }

    create_cfg = CONFIG.get("create", {})
    payload = _build_payload(args)
    resp = _request(
        create_cfg.get("method", "POST"),
        create_cfg.get("path", "/v2/video_generation"),
        json_body=payload,
        timeout=create_cfg.get("timeout_seconds", 60),
    )
    task_id = _extract_task_id(resp, create_cfg)
    return {
        "task_id": task_id,
        "status": "queued",
        "model": payload.get("model"),
        "provider": CONFIG.get("name"),
        "request_payload": payload,
    }


@mcp.tool()
def query_video_generation(task_id: str, model: Optional[str] = None) -> Dict[str, Any]:
    """查询一个视频生成任务的当前状态与结果。

    状态统一归一化为: queued / running / succeeded / failed / cancelled。
    succeeded 时 video_url 即成片直链（拿到请尽快下载或转存）。

    参数:
        task_id: submit_video_generation 返回的任务 ID。
        model: 模型名（部分站点查询需要回传）。

    返回: {"task_id", "status", "video_url", "error", "raw_status", "usage"}
    """
    query_cfg = CONFIG.get("query", {})
    path = str(query_cfg.get("path_template", "/v2/query/video_generation/{task_id}")).replace(
        "{task_id}", task_id
    )
    params: Dict[str, Any] = {}
    for key, value in (query_cfg.get("params") or {}).items():
        if isinstance(value, str):
            value = value.replace("{model}", model or "").replace("{task_id}", task_id)
            if value == "":
                continue
        params[key] = value
    if model:
        params.setdefault(query_cfg.get("model_param", "model"), model)

    resp = _request(
        query_cfg.get("method", "GET"),
        path,
        params=params or None,
        timeout=query_cfg.get("timeout_seconds", 30),
    )

    res_cfg = CONFIG.get("result", {})
    raw_status = dig(resp, res_cfg.get("status_path", "task.status"))
    status = _map_status(raw_status)

    out: Dict[str, Any] = {
        "task_id": task_id,
        "status": status,
        "raw_status": raw_status,
        "video_url": dig(resp, res_cfg.get("video_url_path", "task.content.url")),
        "model": dig(resp, res_cfg.get("model_path", "task.model")) or model,
    }
    error_code = dig(resp, res_cfg.get("error_code_path", "task.error.code"))
    error_message = dig(resp, res_cfg.get("error_message_path", "task.error.message"))
    if error_code or error_message:
        out["error"] = {"code": error_code, "message": error_message}
    usage = dig(resp, res_cfg.get("usage_path", "task.usage"))
    if usage:
        out["usage"] = usage
    if status in TERMINAL_BAD and "error" not in out:
        out["error"] = {"code": None, "message": "任务失败，未返回具体原因"}
    return out


@mcp.tool()
def list_video_tasks(
    page_num: int = 1,
    page_size: int = 20,
    status: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """分页列出本账号近期建的视频生成任务。

    参数:
        page_num: 页码，从 1 开始。
        page_size: 每页数量（站点上限 50）。
        status: 按状态过滤，queued / running / succeeded / failed / cancelled。
        model: 按模型过滤。

    返回: {"items": [...], "total": n}
    """
    spec = (CONFIG.get("extra_endpoints") or {}).get("list_tasks")
    if not spec:
        return {"items": [], "total": 0, "reason": "provider.json 未配置 list_tasks"}
    params: Dict[str, Any] = {"page_num": str(page_num), "page_size": str(page_size)}
    for k, v in (spec.get("params") or {}).items():
        if isinstance(v, str):
            v = v.replace("{model}", model or "")
            if v == "":
                continue
        params[k] = v
    if status:
        params["filter.status"] = status
    if model:
        params["filter.model"] = model
    resp = _request(
        spec.get("method", "GET"),
        spec["path"],
        params=params,
        timeout=spec.get("timeout_seconds", 30),
    )
    res_cfg = CONFIG.get("result", {})
    items = dig(resp, res_cfg.get("list_path", "items")) or []
    normalized = []
    for item in items:
        normalized.append(
            {
                "task_id": dig(item, "id") or dig(item, "task_id"),
                "status": _map_status(dig(item, "status")),
                "video_url": dig(item, res_cfg.get("video_url_path", "task.content.url"))
                or dig(item, "content.url"),
                "model": dig(item, "model"),
                "created_at": dig(item, "created_at"),
            }
        )
    return {"items": normalized, "total": dig(resp, "total", 0)}


@mcp.tool()
def list_video_models(keyword: Optional[str] = None, video_only: bool = True) -> Dict[str, Any]:
    """列出当前站点上可用的视频模型。

    拿不准"该用哪个模型"时先调这个。返回的 id 直接传给 submit_video_generation。

    参数:
        keyword: 过滤关键词，如 hailuo / minimax / kling / vidu / seedance。
        video_only: 只返回视频类模型（默认 True）。站点不一定标注模型类型，
            这里用名称启发式识别；识别不到时会退回返回全部并标 "video?"。

    返回: {"models": [{"id", "hint"}]}
    """
    spec = (CONFIG.get("extra_endpoints") or {}).get("list_models")
    if not spec:
        return {"models": [], "reason": "provider.json 未配置 list_models"}
    resp = _request(
        spec.get("method", "GET"),
        spec["path"],
        timeout=spec.get("timeout_seconds", 30),
    )
    data = dig(resp, "data") or []
    hints = [h.lower() for h in (CONFIG.get("video_model_hints") or [])]
    known = {str(x).lower() for x in (CONFIG.get("known_video_models") or [])}
    kw = (keyword or "").strip().lower()

    entries: List[Dict[str, Any]] = []
    for item in data:
        mid = dig(item, "id") or dig(item, "model_name")
        if not mid:
            continue
        low = str(mid).lower()
        is_video = low in known or any(h in low for h in hints)
        entries.append({"id": mid, "hint": "video" if is_video else ""})

    if kw:
        entries = [e for e in entries if kw in str(e["id"]).lower()]

    if video_only:
        picked = [e for e in entries if e["hint"]]
        if picked:
            entries = picked
        else:
            for e in entries:
                e["hint"] = "video?"

    entries.sort(key=lambda e: (0 if e["hint"] == "video" else 1, e["id"]))
    return {"models": entries, "total": len(entries)}


@mcp.tool()
def regenerate_video_2k(
    source_task_id: Optional[str] = None,
    base_video_url: Optional[str] = None,
    resolution: str = "2K",
) -> Dict[str, Any]:
    """把已完成的 768P 成片升到 2K。

    两个来源二选一：
        source_task_id —— 本平台已完成的 768P 任务 id（推荐）
        base_video_url —— 源视频直链

    参数:
        source_task_id: 已完成的 768P 任务 ID。
        base_video_url: 源视频公网直链。
        resolution: 固定 2K。

    返回: {"task_id", "status": "queued"}
    """
    spec = (CONFIG.get("extra_endpoints") or {}).get("regenerate_2k")
    if not spec:
        raise RuntimeError("provider.json 未配置 regenerate_2k")
    if not source_task_id and not base_video_url:
        raise RuntimeError("source_task_id 与 base_video_url 必须提供其中一个")

    body: Dict[str, Any] = {
        "model": CONFIG.get("regeneration_model", "MiniMax-H3"),
        "resolution": resolution,
    }
    if source_task_id:
        body["source_task_id"] = str(source_task_id)
    else:
        body["content"] = [
            {"type": "video_url", "role": "base_video", "video_url": {"url": base_video_url}}
        ]

    resp = _request(
        spec.get("method", "POST"),
        spec["path"],
        json_body=body,
        timeout=spec.get("timeout_seconds", 60),
    )
    task_id = _extract_task_id(resp, CONFIG.get("create", {}))
    return {"task_id": task_id, "status": "queued", "request_payload": body}


@mcp.tool()
def delete_video_task(task_id: str) -> Dict[str, Any]:
    """删除一个**已结束**的任务记录（成功或失败）。

    处理中的任务不能取消（站点限制），只会提示。

    参数:
        task_id: 要删除的任务 ID。
    """
    spec = (CONFIG.get("extra_endpoints") or {}).get("delete_task")
    if not spec:
        return {"task_id": task_id, "deleted": False, "reason": "provider.json 未配置 delete_task"}
    path = str(spec.get("path_template", "/v2/video_generation/{task_id}")).replace(
        "{task_id}", task_id
    )
    resp = _request(
        spec.get("method", "DELETE"),
        path,
        timeout=spec.get("timeout_seconds", 30),
    )
    return {"task_id": task_id, "deleted": True, "response": resp}


@mcp.tool()
def describe_provider() -> Dict[str, Any]:
    """返回当前适配器的配置概览：端点、支持的字段、规则、状态映射、key 来源。

    拿不准"某个参数传了会不会被拒"时，先调用这个。
    """
    key_result = _key_result()
    return {
        "name": CONFIG.get("name"),
        "base_urls": _base_candidates(),
        "auth": {k: v for k, v in (CONFIG.get("auth") or {}).items() if k != "api_key"},
        "api_key_present": key_result.found,
        "api_key_source": key_result.source,
        "api_key_warnings": key_result.warnings,
        "media_mode": CONFIG.get("media_mode", "base64"),
        "default_model": CONFIG.get("default_model"),
        "model_aliases": CONFIG.get("model_aliases"),
        "create": CONFIG.get("create"),
        "query": CONFIG.get("query"),
        "roles": CONFIG.get("roles"),
        "payload_fields": CONFIG.get("payload"),
        "status_map": CONFIG.get("status_map"),
        "result_paths": CONFIG.get("result"),
        "rules": CONFIG.get("rules"),
    }


if __name__ == "__main__":
    mcp.run()
