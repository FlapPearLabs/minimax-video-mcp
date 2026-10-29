#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
针对对抗式审查（Codex gpt-6.1-sol@high / WorkBuddy claude-opus-4-6-thinking）
打出来的具体缺陷的回归测试。

每个用例对应一条被独立复现过的缺陷，修复前必须失败、修复后必须通过。
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from tests.helpers import ROOT, load_server, make_env, tmpdir


class ReviewFixCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tmpdir()
        cfg = json.loads((ROOT / "provider.json").read_text(encoding="utf-8"))
        cfg["base_url"] = "http://127.0.0.1:1"
        cfg["base_url_fallbacks"] = []
        (self.tmp / "provider.json").write_text(
            json.dumps(cfg, ensure_ascii=False), encoding="utf-8"
        )
        (self.tmp / "api.txt").write_text("sk-reviewfix-0123456789\n", encoding="utf-8")
        env = dict(os.environ)
        env["VIDEO_PROVIDER_DIR"] = str(self.tmp)
        env["VIDEO_PROVIDER_CONFIG"] = str(self.tmp / "provider.json")
        env.pop("VIDEO_API_KEY", None)
        self.server = load_server(env)


class TestPaginationNotOverwritten(ReviewFixCase):
    """审查发现：list_video_tasks 的分页参数被配置里的固定值盖掉。"""

    def test_page_args_reach_the_wire(self):
        sent = {}
        original = self.server._request

        def spy(method, path, **kw):
            sent["params"] = dict(kw.get("params") or {})
            sent["path"] = path

            return {"items": [], "total": 0}

        self.server._request = spy
        try:
            self.server.list_video_tasks(page_num=3, page_size=7)
        finally:
            self.server._request = original

        self.assertEqual(sent["params"].get("page_num"), "3", "page_num 被配置覆盖了")
        self.assertEqual(sent["params"].get("page_size"), "7", "page_size 被配置覆盖了")

    def test_defaults_still_work(self):
        sent = {}
        original = self.server._request

        def spy(method, path, **kw):
            sent["params"] = dict(kw.get("params") or {})

            return {"items": [], "total": 0}

        self.server._request = spy
        try:
            self.server.list_video_tasks()
        finally:
            self.server._request = original
        self.assertEqual(sent["params"].get("page_num"), "1")
        self.assertEqual(sent["params"].get("page_size"), "20")


class TestJournalFailureBlocksSubmission(ReviewFixCase):
    """审查发现：台账写失败时仍然发出创建请求 —— 受理了就再也找不回 task_id。"""

    def _break_journal(self):
        class Broken:
            path = self.tmp / "broken.jsonl"
            last_error = "simulated failure"

            def new_attempt_id(self):
                return "attempt-broken"

            def record(self, task_id, **fields):
                return None

            def get(self, task_id):
                return None

            def list(self, **kw):
                return []

        self.server._journal = lambda: Broken()

    def test_submit_aborts_when_journal_unwritable(self):
        self._break_journal()
        posted = []
        original = self.server._request

        def spy(method, path, **kw):
            posted.append(path)

            return {"task_id": "T-SHOULD-NOT-HAPPEN"}

        self.server._request = spy
        try:
            with self.assertRaises(RuntimeError) as ctx:
                self.server.submit_video_generation(
                    prompt="x", duration=4, resolution="768P", ratio="16:9"
                )
        finally:
            self.server._request = original

        self.assertIn("台账", str(ctx.exception))
        self.assertEqual(
            posted, [],
            "台账写失败却仍然提交了任务 —— 这个 task_id 丢了就是白花钱",
        )

    def test_regenerate_aborts_when_journal_unwritable(self):
        self._break_journal()
        posted = []
        original = self.server._request

        def spy(method, path, **kw):
            posted.append(path)

            return {"task_id": "R-SHOULD-NOT-HAPPEN"}

        self.server._request = spy
        try:
            with self.assertRaises(RuntimeError):
                self.server.regenerate_video_2k(source_task_id="SRC-1")
        finally:
            self.server._request = original
        self.assertEqual(posted, [], "升 2K 也在台账写失败时提交了")


class TestRegenerateRecordsAttempt(ReviewFixCase):
    """审查发现：升 2K 没有提交前 attempt 记录，受理后超时就查不回来。"""

    def test_attempt_recorded_before_post(self):
        events = []
        original_request = self.server._request
        original_journal = self.server._journal

        class SpyJournal:
            path = original_journal().path
            last_error = None

            def new_attempt_id(self):
                return "attempt-regen"

            def record(self, task_id, **fields):
                events.append((task_id, fields.get("event")))
                return {"task_id": task_id}

            def get(self, task_id):
                return None

            def list(self, **kw):
                return []

        self.server._journal = lambda: SpyJournal()

        def spy(method, path, **kw):
            events.append(("__POST__", path))

            return {"task_id": "R-1"}

        self.server._request = spy
        try:
            self.server.regenerate_video_2k(source_task_id="SRC-1")
        finally:
            self.server._request = original_request
            self.server._journal = original_journal

        post_idx = next(i for i, e in enumerate(events) if e[0] == "__POST__")
        attempt_idx = next(
            (i for i, e in enumerate(events) if e[1] == "regenerate_attempt"), None
        )
        self.assertIsNotNone(attempt_idx, "升 2K 没有记录提交前 attempt")
        self.assertLess(
            attempt_idx, post_idx,
            "attempt 记录必须发生在 POST 之前，否则受理后超时就查不回来",
        )


class TestOfficialNameAliases(ReviewFixCase):
    """审查发现：工具名不带官方命名空间，按 connector__matrix__* 查找的 Agent 命中不了。"""

    def test_aliases_registered(self):
        import asyncio

        tools = asyncio.run(self.server.mcp.list_tools())
        names = {t.name for t in tools}
        self.assertIn("submit_video_generation", names)
        self.assertIn("query_video_generation", names)
        self.assertIn("connector__matrix__submit_video_generation", names)
        self.assertIn("connector__matrix__query_video_generation", names)

    def test_aliases_have_same_schema(self):
        import asyncio

        tools = {t.name: t for t in asyncio.run(self.server.mcp.list_tools())}
        self.assertEqual(
            set(tools["submit_video_generation"].inputSchema["properties"]),
            set(tools["connector__matrix__submit_video_generation"].inputSchema["properties"]),
        )


if __name__ == "__main__":
    unittest.main()
