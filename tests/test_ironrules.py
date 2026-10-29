#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三条铁律的专项测试。

铁律一  task_id 立刻落库      —— 换会话还能找回任务
铁律二  终态不要自动重试      —— 失败的任务不会被偷偷重建（不重复扣费）
铁律三  直链拿到就转存        —— 产物落到本地磁盘，不等直链过期
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests.helpers import load_server, make_env, tmpdir

import mock_provider


class IronRuleCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv, _, cls.base = mock_provider.start(0)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        self.tmp = tmpdir()
        self.env, self.provider_path = make_env(self.base, self.tmp)
        self.server = load_server(self.env)
        mock_provider.STATS["creates"] = 0
        mock_provider.STATS["queries"] = 0
        mock_provider.STATS["downloads"] = 0

    def submit(self, prompt="铁律测试", **kwargs):
        args = {
            "prompt": prompt, "model": "MiniMax-H3", "duration": 4,
            "resolution": "768P", "ratio": "16:9", "input_image": None,
            "last_frame_image": None, "reference_images": None,
            "reference_videos": None, "reference_audios": None,
            "callback_url": None,
        }
        args.update(kwargs)
        return self.server.submit_video_generation(**args)

    def journal_path(self) -> Path:
        return self.tmp / ".video-tasks.jsonl"


# --------------------------------------------------------------------------
class TestRule1TaskIdPersisted(IronRuleCase):
    """铁律一：task_id 立刻落库。"""

    def test_submit_writes_journal_immediately(self):
        sub = self.submit()
        self.assertTrue(self.journal_path().exists(), "提交后台账文件必须立刻存在")
        lines = [
            json.loads(l)
            for l in self.journal_path().read_text(encoding="utf-8").splitlines()
            if l.strip()
        ]
        rows = [r for r in lines if r["task_id"] == sub["task_id"]]
        self.assertTrue(rows, "task_id 必须立刻落库")
        self.assertEqual(rows[0]["status"], "queued")
        self.assertEqual(rows[0]["event"], "submitted")
        # 另外还有「提交尝试」记录（上游可能受理但响应丢了时靠它判断）
        attempt_rows = [r for r in lines if r.get("kind") == "attempt"]
        attempt_ids = {r["task_id"] for r in attempt_rows}
        self.assertEqual(len(attempt_ids), 1, "应有且只有一个提交尝试号")
        self.assertEqual(attempt_rows[0]["status"], "submitting")
        self.assertEqual(attempt_rows[-1]["status"], "resolved")
        self.assertEqual(attempt_rows[-1]["resolved_task_id"], sub["task_id"])

    def test_query_updates_journal_status(self):
        sub = self.submit()
        self.server.query_video_generation(task_id=sub["task_id"], model="MiniMax-H3")
        rec = self.server._journal().get(sub["task_id"])
        self.assertIsNotNone(rec)
        self.assertIn(rec["status"], {"running", "succeeded"})

    def test_task_survives_new_server_instance(self):
        """换会话（新的 server 实例）后仍能找回任务。"""
        sub = self.submit()
        fresh = load_server(self.env)          # 模拟重开 MCP server
        rec = fresh._journal().get(sub["task_id"])
        self.assertIsNotNone(rec, "换实例后必须还能查到 task")
        self.assertEqual(rec["task_id"], sub["task_id"])

    def test_list_local_tasks_finds_task(self):
        sub = self.submit()
        result = self.server.list_local_tasks()
        self.assertGreaterEqual(result["total"], 1)
        self.assertIn(sub["task_id"], [t["task_id"] for t in result["tasks"]])

    def test_list_local_tasks_filter_by_status(self):
        sub = self.submit()
        running = self.server.list_local_tasks(status="queued")
        self.assertIn(sub["task_id"], [t["task_id"] for t in running["tasks"]])
        none = self.server.list_local_tasks(status="succeeded")
        self.assertNotIn(sub["task_id"], [t["task_id"] for t in none["tasks"]])

    def test_resume_pending_tasks_polls_unfinished(self):
        sub = self.submit()
        result = self.server.resume_pending_tasks()
        self.assertIn(sub["task_id"], [r["task_id"] for r in result["resumed"]])

    def test_journal_file_is_not_in_git(self):
        """台账是本地状态，不能进仓库。"""
        import subprocess as sp

        from tests.helpers import ROOT

        if not (ROOT / ".git").exists():
            self.skipTest("不是 git 仓库")
        proc = sp.run(
            ["git", "check-ignore", "-q", ".video-tasks.jsonl"],
            cwd=str(ROOT), capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, ".video-tasks.jsonl 必须被 .gitignore 忽略")


# --------------------------------------------------------------------------
class TestRule2NoAutoRetry(IronRuleCase):
    """铁律二：终态不要自动重试。"""

    def test_failed_task_is_never_resubmitted(self):
        sub = self.submit(prompt="FAILME 触发失败")
        self.server.query_video_generation(task_id=sub["task_id"], model="MiniMax-H3")
        self.server.query_video_generation(task_id=sub["task_id"], model="MiniMax-H3")

        creates_after_first = mock_provider.STATS["creates"]
        self.assertEqual(creates_after_first, 1, "整个流程只应创建过 1 个任务")

        # 再查很多次，mock 侧的任务创建计数不能涨
        for _ in range(5):
            self.server.query_video_generation(task_id=sub["task_id"], model="MiniMax-H3")
        self.assertEqual(
            mock_provider.STATS["creates"], 1,
            "终态任务被自动重提了 —— 这会重复扣费",
        )

    def test_terminal_task_not_in_pending(self):
        sub = self.submit(prompt="FAILME 触发失败")
        self.server.query_video_generation(task_id=sub["task_id"], model="MiniMax-H3")
        self.server.query_video_generation(task_id=sub["task_id"], model="MiniMax-H3")
        pending = [t["task_id"] for t in self.server._journal().pending()]
        self.assertNotIn(sub["task_id"], pending, "终态任务不该出现在待续跑列表里")

    def test_resume_does_not_touch_terminal_tasks(self):
        sub = self.submit(prompt="FAILME 触发失败")
        self.server.query_video_generation(task_id=sub["task_id"], model="MiniMax-H3")
        self.server.query_video_generation(task_id=sub["task_id"], model="MiniMax-H3")
        before = mock_provider.STATS["queries"]
        self.server.resume_pending_tasks()
        self.assertEqual(mock_provider.STATS["queries"], before, "续跑不该再去查终态任务")

    def test_failed_status_and_error_are_recorded(self):
        sub = self.submit(prompt="FAILME 触发失败")
        self.server.query_video_generation(task_id=sub["task_id"], model="MiniMax-H3")
        self.server.query_video_generation(task_id=sub["task_id"], model="MiniMax-H3")
        rec = self.server._journal().get(sub["task_id"])
        self.assertEqual(rec["status"], "failed")
        self.assertEqual(rec["error"]["code"], "1026")


# --------------------------------------------------------------------------
class TestRule3DownloadOnSuccess(IronRuleCase):
    """铁律三：直链拿到就转存。"""

    def _succeed(self, prompt="成功任务"):
        sub = self.submit(prompt=prompt)
        self.server.query_video_generation(task_id=sub["task_id"], model="MiniMax-H3")
        res = self.server.query_video_generation(task_id=sub["task_id"], model="MiniMax-H3")
        self.assertEqual(res["status"], "succeeded")
        # 转存在后台线程里跑，等它落定
        self.server._wait_for_downloads(30)
        rec = self.server._journal().get(sub["task_id"]) or {}
        return sub, res, rec

    def test_success_triggers_automatic_download(self):
        sub, res, rec = self._succeed()
        self.assertEqual(res.get("download_status"), "started")
        self.assertIn("local_path", rec, "成功后必须自动转存并记进台账")
        local = Path(rec["local_path"])
        self.assertTrue(local.exists(), "成片文件必须真的落盘")
        self.assertGreater(local.stat().st_size, 0)
        self.assertEqual(local.parent.name, "videos")

    def test_download_is_idempotent(self):
        sub, res, rec = self._succeed()
        downloads_after_first = mock_provider.STATS["downloads"]
        self.assertEqual(downloads_after_first, 1)

        # 再查一次，不该重复下载
        self.server.query_video_generation(task_id=sub["task_id"], model="MiniMax-H3")
        self.server._wait_for_downloads(30)
        self.assertEqual(
            mock_provider.STATS["downloads"], downloads_after_first,
            "同一个任务不该重复下载",
        )

    def test_journal_records_local_path(self):
        sub, res, rec = self._succeed()
        self.assertTrue(Path(rec["local_path"]).exists())

    def test_download_video_tool(self):
        sub, res, rec = self._succeed()
        again = self.server.download_video(video_url=res["video_url"], task_id=sub["task_id"])
        self.assertTrue(Path(again["local_path"]).exists())
        self.assertGreater(again["bytes"], 0)

    def test_download_video_without_task_id_uses_url_stem(self):
        sub, res, rec = self._succeed()
        out = self.server.download_video(video_url=res["video_url"])
        self.assertTrue(Path(out["local_path"]).exists())
        self.assertTrue(Path(out["local_path"]).name.endswith(".mp4"))

    def test_download_video_requires_url(self):
        with self.assertRaises(RuntimeError):
            self.server.download_video(video_url="")

    def test_auto_download_can_be_disabled(self):
        import json as _json

        cfg = _json.loads(self.provider_path.read_text(encoding="utf-8"))
        cfg["journal"]["auto_download"] = False
        self.provider_path.write_text(_json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        self.server = load_server(self.env)
        sub, res, rec = self._succeed()
        self.assertNotIn("local_path", rec)
        self.assertEqual(mock_provider.STATS["downloads"], 0)


if __name__ == "__main__":
    unittest.main()
