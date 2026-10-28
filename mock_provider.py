#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一个假的 MiniMax 官方 V2 视频 API，用来本地验证 server.py。

行为完全照着七七八AI 透传的官方 V2 规格来，**包括那些会 400 的规则**，
所以自测能真正验证到"规则拦截"而不是只测 happy path。

  POST   /v2/video_generation         -> {"task_id": "12345"}
  GET    /v2/query/video_generation/{id}
         第一次 running，第二次 succeeded + content.url
  GET    /v2/query/video_generation    -> {"items": [...], "total": n}
  DELETE /v2/video_generation/{id}     -> {"task_id":..., "action":"deleted", "status":"deleted"}
  POST   /v2/video_regeneration        -> {"task_id": "12346"}
  GET    /v1/models                    -> 模型列表
  POST   /v2/h3_context_ir             -> 400（平台未接入）

只用于自测，不要拿去生产。
"""

from __future__ import annotations

import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict
from urllib.parse import urlsplit

STATE: Dict[str, Dict[str, Any]] = {}
_counter = {"n": 0}
_lock = threading.Lock()

# 请求计数 —— 测试用它来证明"终态不会被自动重提"
STATS = {"creates": 0, "queries": 0, "downloads": 0}

MODELS = [
    {"id": "MiniMax-H3", "object": "model"},
    {"id": "MiniMax-H3-Max", "object": "model"},
    {"id": "hailuo-h3-cankaosheng", "object": "model"},
    {"id": "hailuo-h3-shouweizhen", "object": "model"},
    {"id": "kling-v3-omni-cankao", "object": "model"},
    {"id": "viduq4-preview", "object": "model"},
    {"id": "seedance-2.0-guanfang", "object": "model"},
    {"id": "gpt-4o-mini", "object": "model"},
]


def _err(status: int, code: str, message: str):
    return status, {"error": {"code": code, "message": message, "type": "invalid_request_error"}}


def _validate_video_body(body: Dict[str, Any]):
    """照官方 V2 规则校验，返回 (error_payload or None)。"""
    if not body.get("model"):
        return _err(400, "2013", "缺少 model 参数")
    if not body.get("resolution"):
        return _err(400, "2013", "缺少 resolution 参数")
    if body.get("duration") is None:
        return _err(400, "2013", "缺少 duration 参数")
    if not (4 <= int(body.get("duration", 0)) <= 15):
        return _err(400, "2013", "duration 必须是 4~15 之间的整数")

    content = body.get("content")
    if not isinstance(content, list) or not content:
        return _err(400, "2013", "content 必须是非空数组")
    if not any(c.get("type") == "text" and c.get("text") for c in content):
        return _err(400, "2013", "content 必须包含非空 text 项 (prompt is required)")

    roles = {c.get("role") for c in content if c.get("role")}
    frame = {"first_frame", "last_frame"}
    ref = {"reference_image", "reference_video", "reference_audio"}
    if roles & frame and roles & ref:
        return _err(400, "2013", "首尾帧模式与多模态参考模式互斥")
    if "last_frame" in roles and "first_frame" not in roles:
        return _err(400, "2013", "本平台暂不支持只传 last_frame，需与 first_frame 同传")

    only_text = all(c.get("type") == "text" for c in content)
    ratio = body.get("ratio")
    if only_text:
        if not ratio:
            return _err(400, "2013", "文生视频必须指定 ratio")
        if ratio == "adaptive":
            return _err(400, "2013", "文生视频的 ratio 不能是 adaptive")
    return None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # 静音
        pass

    @property
    def route(self) -> str:
        return urlsplit(self.path).path

    def _send(self, code: int, body: Dict[str, Any]) -> None:
        raw = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def _authed(self) -> bool:
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and len(auth) > 14:
            return True
        return bool(self.headers.get("x-api-key"))

    # ---------------------------------------------------------------- POST
    def do_POST(self) -> None:  # noqa: N802
        body = self._read_json()

        if not self._authed():
            self._send(401, {"error": {"code": "missing_api_key", "message": "缺少 API key", "type": "authentication_error"}})
            return

        if self.route == "/v2/video_generation":
            err = _validate_video_body(body)
            if err:
                self._send(err[0], err[1])
                return
            with _lock:
                _counter["n"] += 1
                STATS["creates"] += 1
                tid = str(10000 + _counter["n"])
                STATE[tid] = {"polls": 0, "payload": body}
            self._send(200, {"task_id": tid})
            return

        if self.route == "/v2/video_regeneration":
            if not body.get("source_task_id") and not body.get("content"):
                self._send(400, {"error": {"code": "2013", "message": "需要 source_task_id 或 content", "type": "invalid_request_error"}})
                return
            with _lock:
                _counter["n"] += 1
                tid = str(10000 + _counter["n"])
                STATE[tid] = {"polls": 0, "payload": body}
            self._send(200, {"task_id": tid})
            return

        if self.route == "/v2/h3_context_ir":
            self._send(400, {"error": {"code": "2013", "message": "本平台未接入 H3-Context-IR", "type": "invalid_request_error"}})
            return

        self._send(404, {"error": {"code": "not_found", "message": f"not found: {self.route}", "type": "not_found"}})

    # ----------------------------------------------------------------- GET
    def do_GET(self) -> None:  # noqa: N802
        if not self._authed():
            self._send(401, {"error": {"code": "missing_api_key", "message": "缺少 API key", "type": "authentication_error"}})
            return

        # 成片文件（供自动转存测试下载）
        m = re.match(r"^/files/([\w.-]+\.mp4)$", self.route)
        if m:
            STATS["downloads"] += 1
            body = b"FAKEMP4" + b"0" * 2048
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.route == "/v1/models":
            self._send(200, {"object": "list", "data": MODELS})
            return

        m = re.match(r"^/v2/query/video_generation/(\w+)$", self.route)
        if m:
            tid = m.group(1)
            with _lock:
                rec = STATE.get(tid)
                if rec is None:
                    self._send(404, {"error": {"code": "2013", "message": "invalid task_id", "type": "not_found"}})
                    return
                rec["polls"] += 1
                polls = rec["polls"]
                payload = rec["payload"]
            STATS["queries"] += 1
            base = f"http://127.0.0.1:{self.server.server_address[1]}"
            if polls < 2:
                self._send(200, {"task": {
                    "id": tid, "model": payload.get("model"), "status": "running",
                    "task_type": "generation", "modality": "video",
                    "resolution": payload.get("resolution"), "ratio": payload.get("ratio"),
                    "duration": payload.get("duration"), "usage": {},
                    "created_at": 1788463493, "updated_at": 1788463493,
                }})
                return
            # prompt 里带 FAILME 的任务直接判失败（用于测试终态不重试）
            if "FAILME" in str(payload.get("content", "")):
                self._send(200, {"task": {
                    "id": tid, "model": payload.get("model"), "status": "failed",
                    "task_type": "generation", "modality": "video",
                    "error": {"code": "1026", "message": "内容审核不通过"},
                    "resolution": payload.get("resolution"), "duration": payload.get("duration"),
                    "usage": {}, "created_at": 1788463493, "updated_at": 1788463751,
                }})
                return
            self._send(200, {"task": {
                "id": tid, "model": payload.get("model"), "status": "succeeded",
                "task_type": "generation", "modality": "video",
                "content": {"url": f"{base}/files/{tid}.mp4"},
                "resolution": payload.get("resolution"), "ratio": payload.get("ratio"),
                "duration": payload.get("duration"),
                "usage": {"output_seconds": payload.get("duration"), "input_seconds": 0,
                          "input_image_count": 0, "total_seconds": payload.get("duration")},
                "created_at": 1788463493, "updated_at": 1788463751,
            }})
            return

        if self.route == "/v2/query/video_generation":
            base = f"http://127.0.0.1:{self.server.server_address[1]}"
            with _lock:
                items = [
                    {
                        "id": tid, "model": rec["payload"].get("model"), "status": "succeeded",
                        "task_type": "generation", "modality": "video",
                        "content": {"url": f"{base}/files/{tid}.mp4"},
                        "resolution": rec["payload"].get("resolution"),
                        "duration": rec["payload"].get("duration"),
                        "usage": {"output_seconds": rec["payload"].get("duration")},
                        "created_at": 1788463493, "updated_at": 1788463751,
                    }
                    for tid, rec in STATE.items()
                ]
            self._send(200, {"items": items, "total": len(items)})
            return

        self._send(404, {"error": {"code": "not_found", "message": f"not found: {self.route}", "type": "not_found"}})

    # -------------------------------------------------------------- DELETE
    def do_DELETE(self) -> None:  # noqa: N802
        if not self._authed():
            self._send(401, {"error": {"code": "missing_api_key", "message": "缺少 API key", "type": "authentication_error"}})
            return
        m = re.match(r"^/v2/video_generation/(\w+)$", self.route)
        if m:
            self._send(200, {"task_id": m.group(1), "action": "deleted", "status": "deleted"})
            return
        self._send(404, {"error": {"code": "not_found", "message": f"not found: {self.route}", "type": "not_found"}})


class MockServer(ThreadingHTTPServer):
    """线程守护 + 允许端口复用，避免测试结束时残留 socket 警告。"""

    daemon_threads = True
    allow_reuse_address = True


def start(port: int = 0):
    """启动 mock 服务，返回 (server, thread, base_url)。"""
    server = MockServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    return server, thread, base


if __name__ == "__main__":
    srv, _, url = start(8931)
    print(f"mock provider running at {url}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        srv.shutdown()
