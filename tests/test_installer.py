#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
install.py 的行为测试 + 仓库完整性护栏。
"""

from __future__ import annotations

import io
import contextlib
import subprocess
import sys
import unittest
from pathlib import Path

from tests.helpers import ROOT

import install
import keyfile


class TestRepoIntegrity(unittest.TestCase):
    """仓库必须自带这些文件，缺一 friend 就装不上。"""

    REQUIRED = [
        "README.md",
        "AGENTS.md",
        "接入提示词.md",
        "api.txt.example",
        "requirements.txt",
        ".gitignore",
        "provider.json",
        "provider.example.json",
        "server.py",
        "keyfile.py",
        "install.py",
        "mock_provider.py",
    ]

    def test_required_files_exist(self):
        for name in self.REQUIRED:
            with self.subTest(name=name):
                self.assertTrue((ROOT / name).exists(), f"缺少 {name}")

    def test_gitignore_protects_key_files(self):
        text = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for name in ("api.txt", "apikey.txt", "api_key.txt"):
            self.assertIn(name, text)

    def test_example_key_file_is_ignored_by_git(self):
        import subprocess as sp

        if not (ROOT / ".git").exists():
            self.skipTest("不是 git 仓库（zip 下载场景跳过）")
        proc = sp.run(
            ["git", "check-ignore", "-q", "api.txt"],
            cwd=str(ROOT), capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, "api.txt 必须被 .gitignore 忽略")

    def test_requirements_lists_runtime_deps(self):
        text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("mcp", text)
        self.assertIn("requests", text)

    def test_provider_json_points_at_expected_endpoints(self):
        import json

        cfg = json.loads((ROOT / "provider.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["create"]["path"], "/v2/video_generation")
        self.assertEqual(
            cfg["query"]["path_template"], "/v2/query/video_generation/{task_id}"
        )
        self.assertIn("roles", cfg)
        self.assertIn("rules", cfg)

    def test_server_uses_api_txt_by_default(self):
        import json

        cfg = json.loads((ROOT / "provider.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["auth"]["api_key_file"], "api.txt")


class TestInstallKeyStep(unittest.TestCase):
    """缺 key / key 有问题时，必须给出可照做的提示，而不是崩。"""

    def setUp(self):
        self.tmp = Path(__import__("tempfile").mkdtemp(prefix="install-test-"))

    def _run_step_key(self, cfg=None):
        """跑 install.step_key，返回它的输出。调用方负责捕获 stdout。"""
        if cfg is None:
            cfg = {
                "auth": {
                    "type": "bearer",
                    "api_key_file": str(self.tmp / "api.txt"),
                    "api_key_env": "VIDEO_API_KEY",
                }
            }
        import os

        saved = os.environ.pop("VIDEO_API_KEY", None)
        try:
            return install.step_key(cfg)
        finally:
            if saved is not None:
                os.environ["VIDEO_API_KEY"] = saved

    def test_missing_key_exits_with_help(self):
        with self.assertRaises(SystemExit) as ctx:
            self._run_step_key()
        self.assertEqual(ctx.exception.code, 1)

    def test_missing_key_message_mentions_api_txt(self):
        import os

        buf = io.StringIO()
        saved = os.environ.pop("VIDEO_API_KEY", None)
        try:
            with contextlib.redirect_stdout(buf):
                with self.assertRaises(SystemExit):
                    self._run_step_key()
        finally:
            if saved is not None:
                os.environ["VIDEO_API_KEY"] = saved
        out = buf.getvalue()
        self.assertIn("api.txt", out)
        self.assertIn("中转站", out)

    def test_empty_api_txt_exits(self):
        (self.tmp / "api.txt").write_text("", encoding="utf-8")
        cfg = {"auth": {"api_key_file": str(self.tmp / "api.txt")}}
        with self.assertRaises(SystemExit):
            install.step_key(cfg)

    def test_valid_api_txt_returns_result(self):
        (self.tmp / "api.txt").write_text("sk-abcdefgh12345678\n", encoding="utf-8")
        cfg = {"auth": {"api_key_file": str(self.tmp / "api.txt")}}
        result = install.step_key(cfg)
        self.assertEqual(result.key, "sk-abcdefgh12345678")
        self.assertTrue(result.source.startswith("file:"))

    def test_env_var_takes_precedence(self):
        import os

        (self.tmp / "api.txt").write_text("sk-fromfile-11111111\n", encoding="utf-8")
        cfg = {"auth": {"api_key_file": str(self.tmp / "api.txt"),
                        "api_key_env": "VIDEO_API_KEY"}}
        os.environ["VIDEO_API_KEY"] = "sk-fromenv-22222222"
        try:
            result = install.step_key(cfg)
            self.assertEqual(result.key, "sk-fromenv-22222222")
        finally:
            os.environ.pop("VIDEO_API_KEY", None)


class TestInstallCli(unittest.TestCase):
    def test_help_works(self):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "install.py"), "--help"],
            capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("--skip-tests", proc.stdout)
        self.assertIn("--no-install", proc.stdout)

    def test_missing_key_exits_nonzero_with_guidance(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            proc = subprocess.run(
                [sys.executable, str(ROOT / "install.py"), "--no-install", "--skip-tests"],
                capture_output=True, text=True, encoding="utf-8", cwd=d,
                env={**os.environ, "VIDEO_API_KEY": ""},
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("api.txt", proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
