#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
请求体组装与平台规则的单元测试（不联网）。

覆盖：content[] 组装、媒体转码、9 条平台规则、状态归一化、model 别名。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.helpers import load_server, make_env, tmpdir


class ServerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tmpdir()
        self.env, _ = make_env("http://127.0.0.1:1", self.tmp)
        self.server = load_server(self.env)

    def payload(self, **kwargs):
        args = {
            "prompt": kwargs.pop("prompt", "测试提示词"),
            "model": kwargs.pop("model", "MiniMax-H3"),
            "duration": kwargs.pop("duration", 5),
            "resolution": kwargs.pop("resolution", "768P"),
            "ratio": kwargs.pop("ratio", "16:9"),
            "input_image": kwargs.pop("input_image", None),
            "last_frame_image": kwargs.pop("last_frame_image", None),
            "reference_images": kwargs.pop("reference_images", None),
            "reference_videos": kwargs.pop("reference_videos", None),
            "reference_audios": kwargs.pop("reference_audios", None),
            "callback_url": kwargs.pop("callback_url", None),
        }
        args.update(kwargs)
        return self.server._build_payload(args)


class TestDig(unittest.TestCase):
    def test_nested(self):
        s = load_server(make_env("http://127.0.0.1:1", tmpdir())[0])
        self.assertEqual(s.dig({"a": {"b": 1}}, "a.b"), 1)
        self.assertEqual(s.dig({"a": {"b": [{"c": 2}]}}, "a.b.0.c"), 2)
        self.assertEqual(s.dig({"a": 1}, "a.b.c"), None)
        self.assertEqual(s.dig({"a": [1, 2]}, "a.5"), None)
        self.assertEqual(s.dig({"a": [1, 2]}, "a.-1"), 2)
        self.assertEqual(s.dig({"a": None}, "a.b"), None)
        self.assertEqual(s.dig({}, "", "d"), "d")


class TestContentAssembly(ServerCase):
    def test_text_only_shape(self):
        p = self.payload()
        self.assertEqual(p["content"], [{"type": "text", "text": "测试提示词"}])
        self.assertEqual(p["model"], "MiniMax-H3")
        self.assertEqual(p["resolution"], "768P")
        self.assertEqual(p["duration"], 5)
        self.assertEqual(p["ratio"], "16:9")

    def test_first_frame_role(self):
        p = self.payload(input_image="https://e.com/a.png")
        self.assertEqual(len(p["content"]), 2)
        item = p["content"][1]
        self.assertEqual(item["type"], "image_url")
        self.assertEqual(item["role"], "first_frame")
        self.assertEqual(item["image_url"]["url"], "https://e.com/a.png")

    def test_last_frame_role(self):
        p = self.payload(
            input_image="https://e.com/a.png", last_frame_image="https://e.com/b.png"
        )
        roles = [c.get("role") for c in p["content"]]
        # 第 0 项是 text，没有 role
        self.assertEqual(roles[0], None)
        self.assertEqual(roles[1:], ["first_frame", "last_frame"])

    def test_reference_roles(self):
        p = self.payload(
            reference_images=["https://e.com/a.png"],
            reference_videos=["https://e.com/a.mp4"],
            reference_audios=["https://e.com/a.mp3"],
        )
        roles = [x.get("role") for x in p["content"]]
        # 第 0 项是 text，没有 role
        self.assertEqual(roles[0], None)
        self.assertEqual(roles[1:], ["reference_image", "reference_video", "reference_audio"])
        self.assertEqual(p["content"][1]["type"], "image_url")
        self.assertEqual(p["content"][2]["type"], "video_url")
        self.assertEqual(p["content"][3]["type"], "audio_url")

    def test_callback_url_top_level(self):
        p = self.payload(callback_url="https://hook.example.com/cb")
        self.assertEqual(p["callback_url"], "https://hook.example.com/cb")

    def test_local_image_becomes_data_uri(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as fh:
            fh.write(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
            path = fh.name
        p = self.payload(input_image=path)
        self.assertTrue(p["content"][1]["image_url"]["url"].startswith("data:image/png;base64,"))
        Path(path).unlink()

    def test_local_audio_becomes_data_uri(self):
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as fh:
            fh.write(b"ID3" + b"0" * 32)
            path = fh.name
        p = self.payload(reference_audios=[path])
        self.assertTrue(p["content"][1]["audio_url"]["url"].startswith("data:audio/mpeg;base64,"))
        Path(path).unlink()

    def test_missing_local_file_raises(self):
        with self.assertRaises(RuntimeError) as ctx:
            self.payload(input_image="/definitely/not/here.png")
        self.assertIn("不存在", str(ctx.exception))

    def test_data_uri_passthrough(self):
        uri = "data:image/png;base64,AAAA"
        p = self.payload(input_image=uri)
        self.assertEqual(p["content"][1]["image_url"]["url"], uri)

    def test_model_alias_applied(self):
        p = self.payload(model="MiniMax-H3-Max")
        self.assertEqual(p["model"], "MiniMax-H3-Max")

    def test_default_model_used(self):
        args = {
            "prompt": "x", "model": None, "duration": 5, "resolution": "768P",
            "ratio": "16:9", "input_image": None, "last_frame_image": None,
            "reference_images": None, "reference_videos": None,
            "reference_audios": None, "callback_url": None,
        }
        p = self.server._build_payload(args)
        self.assertEqual(p["model"], "MiniMax-H3")


class TestPlatformRules(ServerCase):
    """9 条平台规则必须全部在提交前拦下。"""

    def assertBlocked(self, **kwargs):
        with self.assertRaises(RuntimeError) as ctx:
            self.payload(**kwargs)
        return str(ctx.exception)

    def test_text_without_ratio_blocked(self):
        self.assertIn("ratio", self.assertBlocked(ratio=None))

    def test_text_with_adaptive_blocked(self):
        self.assertIn("adaptive", self.assertBlocked(ratio="adaptive"))

    def test_last_frame_without_first_frame_blocked(self):
        self.assertIn("last_frame", self.assertBlocked(last_frame_image="https://e.com/b.png"))

    def test_frame_and_reference_mix_blocked(self):
        self.assertIn(
            "互斥",
            self.assertBlocked(
                input_image="https://e.com/a.png", reference_images=["https://e.com/b.png"]
            ),
        )

    def test_missing_resolution_blocked(self):
        self.assertIn("resolution", self.assertBlocked(resolution=None))

    def test_missing_duration_blocked(self):
        self.assertIn("duration", self.assertBlocked(duration=None))

    def test_duration_out_of_range_blocked(self):
        self.assertIn("duration", self.assertBlocked(duration=3))
        self.assertIn("duration", self.assertBlocked(duration=16))

    def test_empty_prompt_blocked(self):
        self.assertIn("prompt", self.assertBlocked(prompt="   "))

    def test_prompt_too_long_blocked(self):
        self.assertIn("超长", self.assertBlocked(prompt="字" * 7001))

    def test_prompt_at_limit_allowed(self):
        p = self.payload(prompt="字" * 7000)
        self.assertEqual(len(p["content"][0]["text"]), 7000)

    def test_too_many_reference_images_blocked(self):
        urls = [f"https://e.com/{i}.png" for i in range(10)]
        self.assertIn("参考图", self.assertBlocked(reference_images=urls))

    def test_too_many_reference_videos_blocked(self):
        urls = [f"https://e.com/{i}.mp4" for i in range(4)]
        self.assertIn("参考视频", self.assertBlocked(reference_videos=urls))

    def test_too_many_reference_audios_blocked(self):
        urls = [f"https://e.com/{i}.mp3" for i in range(4)]
        self.assertIn("参考音频", self.assertBlocked(reference_audios=urls))

    def test_exactly_at_limits_allowed(self):
        p = self.payload(
            reference_images=[f"https://e.com/{i}.png" for i in range(9)],
            reference_videos=[f"https://e.com/{i}.mp4" for i in range(3)],
            reference_audios=[f"https://e.com/{i}.mp3" for i in range(3)],
        )
        # 1 段 text + 9 图 + 3 视频 + 3 音频
        self.assertEqual(len(p["content"]), 16)

    def test_image_mode_ratio_ignored_not_blocked(self):
        """图生视频传了具体 ratio 也不该报错（服务端按 adaptive 处理）。"""
        p = self.payload(input_image="https://e.com/a.png", ratio="16:9")
        self.assertEqual(p["ratio"], "16:9")


class TestStatusAndMeta(ServerCase):
    def test_status_mapping(self):
        s = self.server
        self.assertEqual(s._map_status("queued"), "queued")
        self.assertEqual(s._map_status("running"), "running")
        self.assertEqual(s._map_status("succeeded"), "succeeded")
        self.assertEqual(s._map_status("failed"), "failed")
        self.assertEqual(s._map_status("cancelled"), "cancelled")
        self.assertEqual(s._map_status("Processing"), "running")
        self.assertEqual(s._map_status(None), "unknown")

    def test_describe_provider_shape(self):
        d = self.server.describe_provider()
        self.assertTrue(d["api_key_present"])
        self.assertEqual(d["api_key_source"], "file:api.txt")
        self.assertIn("base_urls", d)
        self.assertIn("rules", d)
        self.assertIn("roles", d)
        self.assertNotIn("api_key", d["auth"])

    def test_describe_provider_missing_key(self):
        (self.tmp / "api.txt").unlink()
        d = self.server.describe_provider()
        self.assertFalse(d["api_key_present"])
        self.assertEqual(d["api_key_source"], "missing")

    def test_base_url_fallbacks_used(self):
        cfg = self.server.CONFIG
        self.assertEqual(cfg["base_url"], "http://127.0.0.1:1")
        self.assertEqual(self.server._base_candidates(), ["http://127.0.0.1:1"])


if __name__ == "__main__":
    unittest.main()
