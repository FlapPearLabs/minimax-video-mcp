#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
防烧钱专项测试 —— 针对对抗式审查打出来的每一个"可能多扣钱"的洞。

每条测试都对应一个真实缺陷，修复前必须失败、修复后必须通过。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from tests.helpers import ROOT, load_server, make_env, tmpdir

import mock_provider


# --------------------------------------------------------------------------
# 可配置的假上游
# --------------------------------------------------------------------------
class Configurable(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    stats = {"posts": 0, "auth_headers": []}

    def log_message(self, *a):
        pass

    @property
    def mode(self):
        return getattr(self.server, "mode", "ok")

    def _send(self, code, body):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(n)
        Configurable.stats["posts"] += 1
        if self.mode == "error500":
            self._send(500, {"error": {"code": "1000", "message": "internal error"}})
            return
        if self.mode == "slow":
            time.sleep(5)
        self._send(200, {"task_id": "T-1"})

    def do_GET(self):
        Configurable.stats["auth_headers"].append(
            self.headers.get("Authorization") or self.headers.get("x-api-key") or ""
        )
        body = b"MP4DATA" + b"0" * 512
        self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_configurable(mode: str):
    Configurable.stats = {"posts": 0, "auth_headers": []}
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Configurable)
    srv.mode = mode          # 每个 server 独立的行为，别用类属性
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


class MoneySafetyCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tmpdir()

    def _load(self, base_url, fallbacks=None, extra_cfg=None):
        cfg = json.loads((ROOT / "provider.json").read_text(encoding="utf-8"))
        cfg["base_url"] = base_url
        cfg["base_url_fallbacks"] = fallbacks or []
        cfg["connect_timeout_seconds"] = 1
        cfg.setdefault("journal", {})["auto_download"] = False
        if extra_cfg:
            extra_cfg(cfg)
        provider_path = self.tmp / "provider.json"
        provider_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        (self.tmp / "api.txt").write_text("sk-money-test-0123456789\n", encoding="utf-8")
        env = dict(os.environ)
        env["VIDEO_PROVIDER_DIR"] = str(self.tmp)
        env["VIDEO_PROVIDER_CONFIG"] = str(provider_path)
        env.pop("VIDEO_API_KEY", None)
        return load_server(env)


# --------------------------------------------------------------------------
class TestNoDuplicateBilling(MoneySafetyCase):
    """一次调用只能产生一个计费任务。"""

    def test_create_is_not_retried_on_500(self):
        """上游返回 500 时，绝不能再发第二次 POST（可能多出一个计费任务）。"""
        srv, base = start_configurable("error500")
        try:
            server = self._load(base)
            with self.assertRaises(RuntimeError):
                server.submit_video_generation(
                    prompt="x", duration=4, resolution="768P", ratio="16:9"
                )
            self.assertEqual(
                Configurable.stats["posts"], 1,
                f"一次 submit 发了 {Configurable.stats['posts']} 次 POST —— 会重复扣费",
            )
        finally:
            srv.shutdown()

    def test_create_does_not_fall_back_to_another_host(self):
        """主域名超时后，不得换域名重发（第一个任务可能已被受理并计费）。"""
        slow_srv, slow_base = start_configurable("slow")
        ok_srv, ok_base = start_configurable("ok")
        try:
            server = self._load(slow_base, fallbacks=[ok_base])
            with self.assertRaises(RuntimeError):
                server.submit_video_generation(
                    prompt="x", duration=4, resolution="768P", ratio="16:9"
                )
            # 慢的那个算 1 次；快的那个必须是 0
            self.assertEqual(
                Configurable.stats["posts"], 1,
                "超时后换域名重发了创建请求 —— 第一个任务可能已计费",
            )
        finally:
            slow_srv.shutdown()
            ok_srv.shutdown()

    def test_regenerate_2k_is_not_retried(self):
        srv, base = start_configurable("error500")
        try:
            server = self._load(base)
            with self.assertRaises(RuntimeError):
                server.regenerate_video_2k(source_task_id="SRC-1")
            self.assertEqual(Configurable.stats["posts"], 1)
        finally:
            srv.shutdown()

    def test_duplicate_hint_does_not_match_itself(self):
        """第一次提交不该被自己判成"重复提交"。"""
        srv, base = start_configurable("ok")
        try:
            server = self._load(base)
            server.submit_video_generation(
                prompt="唯一的一次", duration=4, resolution="768P", ratio="16:9"
            )
            similar = server._journal().find_similar(
                exclude_task_id="T-1",
                model="MiniMax-H3", prompt="唯一的一次",
                duration=4, resolution="768P", ratio="16:9",
            )
            self.assertEqual(similar, [], "把自己算成重复提交了")
        finally:
            srv.shutdown()


# --------------------------------------------------------------------------
class TestJournalDurability(MoneySafetyCase):
    """台账不能丢记录 —— 丢了 task_id 就等于逼用户重提 = 再扣一次钱。"""

    def test_concurrent_writes_lose_nothing(self):
        """并发写（真实路径：每次调用新建实例）不能丢记录。"""
        srv, base = start_configurable("ok")
        try:
            server = self._load(base)
            journal = server._journal()
            journal.path = self.tmp / "conc.jsonl"
            journal.path.unlink(missing_ok=True)

            N = 300

            def w(i):
                # 复刻真实代码路径：server._journal() 每次都新建实例
                fresh = server._journal()
                fresh.path = journal.path
                fresh.record(f"T{i:04d}", kind="task", event="submitted", status="queued")

            threads = [threading.Thread(target=w, args=(i,)) for i in range(N)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            ids = set()
            for line in journal.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    ids.add(json.loads(line)["task_id"])
            self.assertEqual(
                len(ids), N,
                f"并发写丢了 {N - len(ids)} 条 —— 那些 task_id 返回给用户却没落库",
            )
        finally:
            srv.shutdown()

    def test_write_failure_is_reported_not_swallowed(self):
        """写失败必须让调用方知道，不能静默。"""
        srv, base = start_configurable("ok")
        try:
            server = self._load(base)
            journal = server._journal()
            journal.path = Path("Z:/definitely/not/writable/journal.jsonl")
            result = journal.record("X1", kind="task", event="submitted", status="queued")
            self.assertIsNone(result, "写失败却返回了记录 —— 调用方会以为落库了")
            self.assertTrue(journal.last_error)
        finally:
            srv.shutdown()

    def test_torn_line_does_not_poison_next_record(self):
        """半行不能把下一条好记录一起废掉。"""
        srv, base = start_configurable("ok")
        try:
            server = self._load(base)
            journal = server._journal()
            journal.path = self.tmp / "torn.jsonl"
            journal.path.unlink(missing_ok=True)
            journal.record("GOOD1", kind="task", event="submitted", status="queued")
            with journal.path.open("a", encoding="utf-8") as fh:
                fh.write('{"task_id": "TORN", "sta')     # 模拟写到一半被杀
            journal.record("GOOD2", kind="task", event="submitted", status="queued")
            ids = {
                json.loads(l)["task_id"]
                for l in journal.path.read_text(encoding="utf-8").splitlines()
                if l.strip() and l.strip().startswith("{") and l.strip().endswith("}")
            }
            self.assertIn("GOOD2", ids, "半行把下一条好记录一起废了")
        finally:
            srv.shutdown()

    def test_submission_attempt_is_recorded_before_post(self):
        """提交前先记一笔 attempt —— 上游受理但响应丢了时，别盲目重提。"""
        srv, base = start_configurable("error500")
        try:
            server = self._load(base)
            with self.assertRaises(RuntimeError):
                server.submit_video_generation(
                    prompt="x", duration=4, resolution="768P", ratio="16:9"
                )
            attempts = server._journal().unresolved_attempts()
            self.assertEqual(
                len(attempts), 1,
                "提交失败时没有留下 attempt 记录 —— 下次无法判断是不是已经受理",
            )
        finally:
            srv.shutdown()


# --------------------------------------------------------------------------
class TestSecretSafety(MoneySafetyCase):
    """key 不能外泄。"""

    def test_download_does_not_send_key_to_foreign_host(self):
        """download_video 传第三方 URL 时，绝不能带上 Authorization。"""
        foreign_srv, foreign_base = start_configurable("ok")
        try:
            server = self._load("https://api.lk888.ai")
            server.download_video(video_url=f"{foreign_base}/files/x.mp4")
            for header in Configurable.stats["auth_headers"]:
                self.assertEqual(
                    header, "",
                    f"第三方主机收到了鉴权头：{header!r} —— 你的中转站 key 泄露了",
                )
        finally:
            foreign_srv.shutdown()

    def test_download_filename_does_not_collide(self):
        """两个同名文件不能互相覆盖。"""
        foreign_srv, foreign_base = start_configurable("ok")
        try:
            server = self._load("https://api.lk888.ai")
            a = server.download_video(video_url=f"{foreign_base}/output.mp4")
            b = server.download_video(video_url=f"{foreign_base}/files/output.mp4")
            self.assertNotEqual(
                a["local_path"], b["local_path"],
                "两个不同来源的视频存成了同一个文件名 —— 后一个把前一个覆盖了",
            )
            self.assertTrue(Path(a["local_path"]).exists())
            self.assertTrue(Path(b["local_path"]).exists())
        finally:
            foreign_srv.shutdown()


# --------------------------------------------------------------------------
class TestOfficialParity(MoneySafetyCase):
    """请求体要和官方 V2 一致。"""

    def test_query_does_not_send_model_param(self):
        """官方查询接口只认路径参数 task_id，不接受 model。"""
        seen = {}

        class Spy(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_GET(self):
                seen["path"] = self.path
                body = json.dumps({"task": {"id": "1", "status": "succeeded"}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        srv = ThreadingHTTPServer(("127.0.0.1", 0), Spy)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        try:
            server = self._load(base)
            server.query_video_generation(task_id="123", model="MiniMax-H3")
            self.assertNotIn(
                "model=", seen.get("path", ""),
                f"查询请求多带了官方没有的 model 参数：{seen.get('path')}",
            )
        finally:
            srv.shutdown()

    def test_extra_and_watermark_pass_through(self):
        """官方 V2 的 extra / aigc_watermark 要能传。"""
        captured = {}

        class Spy(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                captured["body"] = json.loads(self.rfile.read(n).decode())
                body = json.dumps({"task_id": "T-9"}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        srv = ThreadingHTTPServer(("127.0.0.1", 0), Spy)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        try:
            server = self._load(base)
            server.submit_video_generation(
                prompt="x", duration=4, resolution="768P", ratio="16:9",
                model="MiniMax-H3-Max",
                extra={"prompt_expansion_mode": "quality"},
                aigc_watermark=True,
            )
            body = captured["body"]
            self.assertEqual(body.get("extra"), {"prompt_expansion_mode": "quality"})
            self.assertIs(body.get("aigc_watermark"), True)
        finally:
            srv.shutdown()

    def test_content_mode_has_no_flat_prompt_field(self):
        """content 数组模式下不多发平铺 prompt（官方 V2 没有这个字段）。"""
        srv, base = start_configurable("ok")
        try:
            server = self._load(base)
            payload = server._build_payload({
                "prompt": "x", "model": "MiniMax-H3", "duration": 4,
                "resolution": "768P", "ratio": "16:9", "input_image": None,
                "last_frame_image": None, "reference_images": None,
                "reference_videos": None, "reference_audios": None,
                "callback_url": None, "extra": None, "aigc_watermark": None,
            })
            self.assertNotIn("prompt", payload)
            self.assertEqual(payload["content"], [{"type": "text", "text": "x"}])
        finally:
            srv.shutdown()


# --------------------------------------------------------------------------
class TestInstallerOutput(MoneySafetyCase):
    """install.py 印出来的东西不能坑人。"""

    def test_printed_payload_has_no_env_placeholder(self):
        """不能印 env 占位符 —— 它会顶掉 api.txt 里的真 key。"""
        text = (ROOT / "install.py").read_text(encoding="utf-8")
        self.assertNotIn(
            '"env"', text,
            "install.py 还在印 env 字段 —— 占位符会盖掉 api.txt 里的真 key",
        )

    def test_printed_payload_uses_sys_executable(self):
        """必须用当前解释器的绝对路径，不能写死 'python'。"""
        text = (ROOT / "install.py").read_text(encoding="utf-8")
        self.assertIn('"command": sys.executable', text)
        self.assertNotIn('"command": "python"', text)

    def test_installed_json_has_no_env_key(self):
        import importlib

        sys.path.insert(0, str(ROOT))
        import install

        importlib.reload(install)
        import io
        import contextlib

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            install.step_register_hint({})
        printed = buf.getvalue()
        payload = json.loads(printed[printed.index("{"):printed.rindex("}") + 1])
        self.assertNotIn("env", payload)
        self.assertTrue(Path(payload["args"][0]).exists())


if __name__ == "__main__":
    unittest.main()
