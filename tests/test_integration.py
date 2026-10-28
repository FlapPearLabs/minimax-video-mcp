#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
端到端集成测试：对着本地 mock（形状 = MiniMax 官方 V2）跑完整流程。
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests.helpers import ROOT, load_server, make_env, tmpdir

import mock_provider


class MockCase(unittest.TestCase):
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

    def _submit(self, **kwargs):
        args = {
            "prompt": "集成测试", "model": "MiniMax-H3", "duration": 4,
            "resolution": "768P", "ratio": "16:9", "input_image": None,
            "last_frame_image": None, "reference_images": None,
            "reference_videos": None, "reference_audios": None,
            "callback_url": None,
        }
        args.update(kwargs)
        return self.server.submit_video_generation(**args)


class TestHappyPath(MockCase):
    def test_submit_and_poll_to_success(self):
        sub = self._submit()
        self.assertTrue(sub["task_id"])
        self.assertEqual(sub["status"], "queued")
        self.assertEqual(sub["model"], "MiniMax-H3")

        q1 = self.server.query_video_generation(task_id=sub["task_id"], model="MiniMax-H3")
        self.assertEqual(q1["status"], "running")
        self.assertIsNone(q1.get("video_url"))

        q2 = self.server.query_video_generation(task_id=sub["task_id"], model="MiniMax-H3")
        self.assertEqual(q2["status"], "succeeded")
        self.assertTrue(q2["video_url"].endswith(".mp4"))
        self.assertIsInstance(q2["usage"], dict)

    def test_list_tasks(self):
        sub = self._submit()
        lst = self.server.list_video_tasks(page_size=10)
        self.assertGreaterEqual(lst["total"], 1)
        self.assertTrue(any(i["task_id"] == sub["task_id"] for i in lst["items"]))
        self.assertEqual(lst["items"][0]["status"], "succeeded")

    def test_list_video_models_filters_chat(self):
        models = self.server.list_video_models()
        ids = [m["id"] for m in models["models"]]
        self.assertIn("MiniMax-H3", ids)
        self.assertNotIn("gpt-4o-mini", ids)

    def test_list_video_models_with_keyword(self):
        models = self.server.list_video_models(keyword="hailuo")
        ids = [m["id"] for m in models["models"]]
        self.assertTrue(ids)
        self.assertTrue(all("hailuo" in i for i in ids))

    def test_regenerate_2k(self):
        sub = self._submit()
        up = self.server.regenerate_video_2k(source_task_id=sub["task_id"])
        self.assertTrue(up["task_id"])
        self.assertEqual(up["request_payload"]["resolution"], "2K")
        self.assertEqual(up["request_payload"]["model"], "MiniMax-H3")

    def test_regenerate_requires_source(self):
        with self.assertRaises(RuntimeError):
            self.server.regenerate_video_2k()

    def test_delete_task(self):
        sub = self._submit()
        res = self.server.delete_video_task(sub["task_id"])
        self.assertTrue(res["deleted"])


class TestErrorPaths(MockCase):
    def test_missing_key_returns_401(self):
        (self.tmp / "api.txt").unlink()
        self.server = load_server(self.env)
        with self.assertRaises(RuntimeError) as ctx:
            self._submit()
        self.assertIn("401", str(ctx.exception))

    def test_client_blocks_text_without_ratio(self):
        """客户端就该拦下：连请求都不该发出去。"""
        args = {
            "prompt": "x", "model": "MiniMax-H3", "duration": 4, "resolution": "768P",
            "ratio": None, "input_image": None, "last_frame_image": None,
            "reference_images": None, "reference_videos": None,
            "reference_audios": None, "callback_url": None,
        }
        with self.assertRaises(RuntimeError) as ctx:
            self.server.submit_video_generation(**args)
        self.assertIn("ratio", str(ctx.exception))

    def test_client_blocks_last_frame_only(self):
        """客户端就该拦下只传尾帧。"""
        with self.assertRaises(RuntimeError) as ctx:
            self._submit(last_frame_image="https://e.com/b.png")
        self.assertIn("last_frame", str(ctx.exception))

    def test_server_also_rejects_bad_bodies(self):
        """绕过客户端直接打服务端，服务端同样必须 400（防绕过）。"""
        import requests

        headers = {"Authorization": "Bearer sk-test-key-0123456789"}
        bad_bodies = [
            {   # 文生视频没给 ratio
                "model": "MiniMax-H3", "content": [{"type": "text", "text": "x"}],
                "resolution": "768P", "duration": 4,
            },
            {   # 只传尾帧
                "model": "MiniMax-H3",
                "content": [
                    {"type": "text", "text": "x"},
                    {"type": "image_url", "role": "last_frame",
                     "image_url": {"url": "https://e.com/b.png"}},
                ],
                "resolution": "768P", "duration": 4,
            },
            {   # 缺 duration
                "model": "MiniMax-H3", "content": [{"type": "text", "text": "x"}],
                "resolution": "768P", "ratio": "16:9",
            },
            {   # content 里没有 text
                "model": "MiniMax-H3", "content": [], "resolution": "768P", "duration": 4,
            },
        ]
        for body in bad_bodies:
            with self.subTest(body=body):
                resp = requests.post(
                    f"{self.base}/v2/video_generation",
                    headers=headers, json=body, timeout=15,
                )
                self.assertEqual(resp.status_code, 400, resp.text)
                self.assertIn("error", resp.json())

    def test_unknown_task_id_is_404(self):
        with self.assertRaises(RuntimeError) as ctx:
            self.server.query_video_generation(task_id="99999999", model="MiniMax-H3")
        self.assertIn("404", str(ctx.exception))


class TestBaseUrlFallback(MockCase):
    def test_falls_back_to_second_base_url(self):
        """主域名连不上时自动切到备用域名。"""
        cfg = json.loads(self.provider_path.read_text(encoding="utf-8"))
        cfg["base_url"] = "http://127.0.0.1:9"        # 必然连不上的 discard 端口
        cfg["base_url_fallbacks"] = [self.base]
        self.provider_path.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.server = load_server(self.env)
        self.assertEqual(self.server._base_candidates(), ["http://127.0.0.1:9", self.base])
        sub = self._submit()
        self.assertTrue(sub["task_id"])

    def test_all_base_urls_dead_raises(self):
        cfg = json.loads(self.provider_path.read_text(encoding="utf-8"))
        cfg["base_url"] = "http://127.0.0.1:9"
        cfg["base_url_fallbacks"] = ["http://127.0.0.1:10"]
        self.provider_path.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.server = load_server(self.env)
        with self.assertRaises(RuntimeError) as ctx:
            self._submit()
        self.assertIn("failed on all base urls", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
