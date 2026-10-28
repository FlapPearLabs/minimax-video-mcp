#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
真实 MCP stdio 协议测试：起一个 server.py 子进程，走 initialize / tools/list / tools/call。

其中一条是**回归护栏**：工具名必须与 MiniMax 内置 matrix 连接器保持一致，
否则 Agent 侧的调用习惯会断。
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest

from tests.helpers import ROOT, make_env, tmpdir

import mock_provider

# 与官方 connector__matrix__* 对齐的工具名（回归护栏）
OFFICIAL_TOOL_NAMES = {
    "submit_video_generation",
    "query_video_generation",
}


class McpProtocolCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv, _, cls.base = mock_provider.start(0)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        self.tmp = tmpdir()
        self.env, _ = make_env(self.base, self.tmp)
        self.env["PYTHONUNBUFFERED"] = "1"
        self.env["PYTHONWARNINGS"] = "ignore::ResourceWarning"
        self.proc = subprocess.Popen(
            [sys.executable, str(ROOT / "server.py")],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=self.env,
            bufsize=1,
        )

    def tearDown(self):
        try:
            self.proc.terminate()
            self.proc.wait(timeout=10)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
        for pipe in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
            try:
                if pipe and not pipe.closed:
                    pipe.close()
            except Exception:
                pass

    def rpc(self, payload: dict, expect_id: bool = True):
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()
        if not expect_id:
            return None
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError("MCP server closed stdout")
            line = line.strip()
            if not line:
                continue
            msg = json.loads(line)
            if msg.get("id") == payload.get("id"):
                return msg

    def handshake(self):
        init = self.rpc({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "test", "version": "1.0"}},
        })
        self.rpc({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
                 expect_id=False)
        return init

    def test_initialize(self):
        init = self.handshake()
        self.assertIn("result", init)
        self.assertIn("protocolVersion", init["result"])

    def test_tools_list_contains_official_names(self):
        self.handshake()
        listed = self.rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        names = {t["name"] for t in listed["result"]["tools"]}
        self.assertTrue(OFFICIAL_TOOL_NAMES.issubset(names), names)
        for expected in ("list_video_models", "list_video_tasks",
                         "regenerate_video_2k", "delete_video_task", "describe_provider",
                         "download_video", "list_local_tasks", "resume_pending_tasks"):
            self.assertIn(expected, names)

    def test_tool_schemas_have_required_prompt(self):
        self.handshake()
        listed = self.rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools = {t["name"]: t for t in listed["result"]["tools"]}
        submit = tools["submit_video_generation"]
        self.assertIn("prompt", submit["inputSchema"]["required"])
        self.assertIn("model", submit["inputSchema"]["properties"])
        self.assertIn("input_image", submit["inputSchema"]["properties"])
        self.assertIn("last_frame_image", submit["inputSchema"]["properties"])

    def test_call_submit_and_query(self):
        self.handshake()
        called = self.rpc({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "submit_video_generation",
                       "arguments": {"prompt": "协议测试", "duration": 4,
                                     "resolution": "768P", "ratio": "16:9"}},
        })
        text = json.dumps(called, ensure_ascii=False)
        self.assertIn("task_id", text)
        self.assertFalse(called.get("result", {}).get("isError", False))

    def test_call_describe_provider(self):
        self.handshake()
        called = self.rpc({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "describe_provider", "arguments": {}},
        })
        text = json.dumps(called, ensure_ascii=False)
        self.assertIn("MiniMax-H3", text)
        self.assertIn("api_key_present", text)

    def test_call_list_video_models(self):
        self.handshake()
        called = self.rpc({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "list_video_models", "arguments": {}},
        })
        self.assertIn("MiniMax-H3", json.dumps(called, ensure_ascii=False))

    def test_invalid_arguments_return_error_not_crash(self):
        self.handshake()
        called = self.rpc({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "submit_video_generation", "arguments": {}},
        })
        result = called.get("result", {})
        self.assertTrue(result.get("isError") or "error" in result)
        # 进程还活着
        self.assertIsNone(self.proc.poll())


if __name__ == "__main__":
    unittest.main()
