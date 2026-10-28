#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
便捷入口：跑完整测试套件。

    python smoke_test.py

等价于：
    python -m unittest discover -s tests -t . -v
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

if __name__ == "__main__":
    raise SystemExit(
        subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-v"],
            cwd=str(HERE),
        ).returncode
    )
