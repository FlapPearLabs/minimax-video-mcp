#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
keyfile.py 的单元测试 —— 覆盖"用户随便怎么粘贴都能认出来"的全部边界情况。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.helpers import ROOT  # noqa: F401  (确保 sys.path 就位)

import keyfile


class TestParseKeyText(unittest.TestCase):
    """文本解析。"""

    def test_plain_key(self):
        key, warns, cands = keyfile.parse_key_text("sk-abcdefgh12345678")
        self.assertEqual(key, "sk-abcdefgh12345678")
        self.assertEqual(warns, [])
        self.assertEqual(len(cands), 1)

    def test_key_with_trailing_whitespace_and_tab(self):
        key, _, _ = keyfile.parse_key_text("sk-abcdefgh12345678  \t ")
        self.assertEqual(key, "sk-abcdefgh12345678")

    def test_empty_string(self):
        key, warns, _ = keyfile.parse_key_text("")
        self.assertIsNone(key)
        self.assertTrue(warns)

    def test_only_whitespace(self):
        key, warns, _ = keyfile.parse_key_text("   \n\t\n  ")
        self.assertIsNone(key)
        self.assertTrue(warns)

    def test_only_comments(self):
        key, warns, _ = keyfile.parse_key_text("# 这是注释\n# 还是注释\n")
        self.assertIsNone(key)
        self.assertTrue(warns)

    def test_leading_comments_then_key(self):
        key, _, _ = keyfile.parse_key_text("# 注释\nsk-abcdefgh12345678\n")
        self.assertEqual(key, "sk-abcdefgh12345678")

    def test_slash_comments_skipped(self):
        key, _, _ = keyfile.parse_key_text("// 注释\nsk-abcdefgh12345678\n")
        self.assertEqual(key, "sk-abcdefgh12345678")

    def test_bom_prefixed(self):
        key, _, _ = keyfile.parse_key_text("\ufeffsk-abcdefgh12345678\n")
        self.assertEqual(key, "sk-abcdefgh12345678")

    def test_crlf_line_endings(self):
        key, _, _ = keyfile.parse_key_text("sk-abcdefgh12345678\r\nsk-second-key-999999\r\n")
        self.assertEqual(key, "sk-abcdefgh12345678")

    def test_double_quotes(self):
        key, _, _ = keyfile.parse_key_text('"sk-abcdefgh12345678"')
        self.assertEqual(key, "sk-abcdefgh12345678")

    def test_single_quotes(self):
        key, _, _ = keyfile.parse_key_text("'sk-abcdefgh12345678'")
        self.assertEqual(key, "sk-abcdefgh12345678")

    def test_bearer_prefix(self):
        key, _, _ = keyfile.parse_key_text("Bearer sk-abcdefgh12345678")
        self.assertEqual(key, "sk-abcdefgh12345678")

    def test_bearer_prefix_lowercase(self):
        key, _, _ = keyfile.parse_key_text("bearer sk-abcdefgh12345678")
        self.assertEqual(key, "sk-abcdefgh12345678")

    def test_authorization_header_line(self):
        key, _, _ = keyfile.parse_key_text("Authorization: Bearer sk-abcdefgh12345678")
        self.assertEqual(key, "sk-abcdefgh12345678")

    def test_authorization_header_equals(self):
        key, _, _ = keyfile.parse_key_text("Authorization=Bearer sk-abcdefgh12345678")
        self.assertEqual(key, "sk-abcdefgh12345678")

    def test_quoted_bearer(self):
        """引号套着 Bearer 前缀 —— 剥引号必须发生在认前缀之前。"""
        key, _, _ = keyfile.parse_key_text('"Bearer sk-abcdefgh12345678"')
        self.assertEqual(key, "sk-abcdefgh12345678")

    def test_quoted_authorization_header(self):
        key, _, _ = keyfile.parse_key_text('"Authorization: Bearer sk-abcdefgh12345678"')
        self.assertEqual(key, "sk-abcdefgh12345678")

    def test_single_quoted_bearer(self):
        key, _, _ = keyfile.parse_key_text("'bearer sk-abcdefgh12345678'")
        self.assertEqual(key, "sk-abcdefgh12345678")

    def test_bearer_with_surrounding_spaces(self):
        key, _, _ = keyfile.parse_key_text("   Bearer    sk-abcdefgh12345678   ")
        self.assertEqual(key, "sk-abcdefgh12345678")

    def test_json_format(self):
        key, warns, _ = keyfile.parse_key_text('{"api_key": "sk-abcdefgh12345678"}')
        self.assertEqual(key, "sk-abcdefgh12345678")
        self.assertTrue(any("JSON" in w for w in warns))

    def test_json_format_alt_field(self):
        key, _, _ = keyfile.parse_key_text('{"token": "sk-abcdefgh12345678"}')
        self.assertEqual(key, "sk-abcdefgh12345678")

    def test_json_without_known_field(self):
        key, warns, _ = keyfile.parse_key_text('{"foo": "bar"}')
        self.assertIsNone(key)
        self.assertTrue(warns)

    def test_broken_json_falls_back_to_lines(self):
        key, _, _ = keyfile.parse_key_text('{"api_key": "sk-abcdefgh12345678"')
        self.assertIsNone(key)  # 这一行含空格且含 { ，不算有效 key

    def test_multiple_keys_prefers_first_sk(self):
        text = "random-not-a-key\nsk-first-key-11111111\nsk-second-key-2222222\n"
        key, warns, _ = keyfile.parse_key_text(text)
        self.assertEqual(key, "sk-first-key-11111111")
        self.assertTrue(warns)

    def test_multiple_keys_without_sk_takes_first(self):
        text = "abcdefgh12345678\nzyxwvuts87654321\n"
        key, warns, _ = keyfile.parse_key_text(text)
        self.assertEqual(key, "abcdefgh12345678")
        self.assertTrue(warns)

    def test_non_sk_prefix_warns_but_usable(self):
        key, warns, _ = keyfile.parse_key_text("abc123def456ghi789")
        self.assertEqual(key, "abc123def456ghi789")
        self.assertTrue(any("sk-" in w for w in warns))

    def test_line_with_internal_space_is_skipped(self):
        text = "sk-good-key-12345678\nhello world this is a sentence\n"
        key, warns, _ = keyfile.parse_key_text(text)
        self.assertEqual(key, "sk-good-key-12345678")
        self.assertTrue(any("空格" in w for w in warns))

    def test_too_short_is_skipped(self):
        text = "sk-good-key-12345678\nabc\n"
        key, warns, _ = keyfile.parse_key_text(text)
        self.assertEqual(key, "sk-good-key-12345678")
        self.assertTrue(any("过短" in w for w in warns))

    def test_only_invalid_lines(self):
        key, warns, _ = keyfile.parse_key_text("abc\nhello world\n")
        self.assertIsNone(key)
        self.assertTrue(warns)

    def test_min_length_boundary(self):
        # 少于 8 个字符判定为误粘贴
        self.assertIsNone(keyfile.parse_key_text("sk-1234")[0])
        self.assertIsNone(keyfile.parse_key_text("abcdefg")[0])
        # 达到 8 个字符即认
        self.assertEqual(keyfile.parse_key_text("sk-12345")[0], "sk-12345")
        self.assertEqual(keyfile.parse_key_text("sk-12345678")[0], "sk-12345678")

    def test_unicode_surrounding_noise(self):
        key, _, _ = keyfile.parse_key_text("sk-abcdefgh12345678")
        self.assertEqual(key, "sk-abcdefgh12345678")


class TestReadTextSafe(unittest.TestCase):
    """文件读取容错。"""

    def test_reads_bom_and_crlf(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "k.txt"
            p.write_bytes("\ufeffsk-abcdefgh12345678\r\n".encode("utf-8"))
            text = keyfile.read_text_safe(p)
            self.assertNotIn("\ufeff", text)
            self.assertNotIn("\r", text)

    def test_reads_gbk(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "k.txt"
            p.write_bytes("sk-abcdefgh12345678".encode("gbk"))
            self.assertIn("sk-abcdefgh", keyfile.read_text_safe(p))

    def test_missing_file_returns_empty(self):
        self.assertEqual(keyfile.read_text_safe(Path("/nope/nope/nope.txt")), "")


class TestResolveKey(unittest.TestCase):
    """优先级与文件查找。"""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="keyfile-test-"))

    def test_inline_config_wins(self):
        r = keyfile.resolve_key(
            {"api_key": "sk-inline-1111111111", "api_key_file": "api.txt"}, self.dir, env={}
        )
        self.assertEqual(r.key, "sk-inline-1111111111")
        self.assertEqual(r.source, "config")

    def test_env_beats_file(self):
        (self.dir / "api.txt").write_text("sk-fromfile-11111111\n", encoding="utf-8")
        r = keyfile.resolve_key(
            {"api_key_env": "MY_KEY", "api_key_file": "api.txt"},
            self.dir,
            env={"MY_KEY": "sk-fromenv-22222222"},
        )
        self.assertEqual(r.key, "sk-fromenv-22222222")
        self.assertEqual(r.source, "env:MY_KEY")

    def test_empty_env_falls_through_to_file(self):
        (self.dir / "api.txt").write_text("sk-fromfile-11111111\n", encoding="utf-8")
        r = keyfile.resolve_key(
            {"api_key_env": "MY_KEY", "api_key_file": "api.txt"}, self.dir, env={"MY_KEY": "  "}
        )
        self.assertEqual(r.key, "sk-fromfile-11111111")
        self.assertEqual(r.source, "file:api.txt")

    def test_api_txt_is_default(self):
        (self.dir / "api.txt").write_text("sk-fromfile-11111111\n", encoding="utf-8")
        r = keyfile.resolve_key({}, self.dir, env={})
        self.assertEqual(r.key, "sk-fromfile-11111111")

    def test_apikey_txt_fallback(self):
        (self.dir / "apikey.txt").write_text("sk-legacyfile-11111\n", encoding="utf-8")
        r = keyfile.resolve_key({}, self.dir, env={})
        self.assertEqual(r.key, "sk-legacyfile-11111")
        self.assertEqual(r.source, "file:apikey.txt")

    def test_api_txt_wins_over_apikey_txt(self):
        (self.dir / "api.txt").write_text("sk-primary-1111111111\n", encoding="utf-8")
        (self.dir / "apikey.txt").write_text("sk-secondary-22222222\n", encoding="utf-8")
        r = keyfile.resolve_key({}, self.dir, env={})
        self.assertEqual(r.key, "sk-primary-1111111111")

    def test_explicit_file_takes_precedence(self):
        (self.dir / "api.txt").write_text("sk-primary-1111111111\n", encoding="utf-8")
        (self.dir / "custom.txt").write_text("sk-custom-333333333\n", encoding="utf-8")
        r = keyfile.resolve_key({"api_key_file": "custom.txt"}, self.dir, env={})
        self.assertEqual(r.key, "sk-custom-333333333")

    def test_missing_explicit_file_falls_back_to_defaults(self):
        (self.dir / "api.txt").write_text("sk-fallback-111111111\n", encoding="utf-8")
        r = keyfile.resolve_key({"api_key_file": "nope.txt"}, self.dir, env={})
        self.assertEqual(r.key, "sk-fallback-111111111")

    def test_no_key_anywhere(self):
        r = keyfile.resolve_key({}, self.dir, env={})
        self.assertIsNone(r.key)
        self.assertFalse(r.found)
        self.assertTrue(r.warnings)

    def test_empty_api_txt_warns_and_continues(self):
        (self.dir / "api.txt").write_text("", encoding="utf-8")
        r = keyfile.resolve_key({}, self.dir, env={})
        self.assertIsNone(r.key)
        self.assertTrue(any("api.txt" in w for w in r.warnings))

    def test_absolute_key_file_path(self):
        other = Path(tempfile.mkdtemp(prefix="keyfile-abs-"))
        kp = other / "abs.txt"
        kp.write_text("sk-absolute-1111111111\n", encoding="utf-8")
        r = keyfile.resolve_key({"api_key_file": str(kp)}, self.dir, env={})
        self.assertEqual(r.key, "sk-absolute-1111111111")

    def test_dir_is_not_a_file(self):
        (self.dir / "api.txt").mkdir()
        r = keyfile.resolve_key({}, self.dir, env={})
        self.assertIsNone(r.key)


if __name__ == "__main__":
    unittest.main()
