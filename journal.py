#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务台账 —— 铁律一「task_id 立刻落库」的实现。

设计：追加式事件日志（JSONL）。每次状态变化就往后写一条，同一个 task_id
的记录读出来时按时间顺序**折叠合并**，等价于一张可变的任务表。

为什么不用 SQLite：
  - 单文件、零依赖、人可读
  - 追加写是原子的，进程被 kill 也不会写坏
  - 需要时可以直接 cat 出来看

为什么不用"改写整表"：
  - 视频任务动辄 15~30 分钟，中间可能重启多次
  - 事件日志天然保留历史（什么时候提交、轮询了几次、什么时候成功）
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}

# 折叠时保留的字段
_MERGE_FIELDS = (
    "status", "raw_status", "video_url", "local_path", "error", "usage",
    "model", "duration", "resolution", "ratio", "cost", "downloaded_at",
)


class TaskJournal:
    """本地任务台账。"""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- 写
    def record(self, task_id: str, **fields: Any) -> Dict[str, Any]:
        """追加一条事件。返回写入的记录。"""
        entry: Dict[str, Any] = {"ts": int(time.time()), "task_id": str(task_id)}
        for key, value in fields.items():
            if value is not None:
                entry[key] = value
        line = json.dumps(entry, ensure_ascii=False, default=str)
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except OSError:
                # 台账写失败不该让整个工具调用挂掉
                pass
        return entry

    # ---------------------------------------------------------------- 读
    def _read_all(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            raw = self.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        out: List[Dict[str, Any]] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue  # 半行 / 损坏行，跳过
            if isinstance(obj, dict) and obj.get("task_id"):
                out.append(obj)
        return out

    def list(self, status: Optional[str] = None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """列出任务（按首次出现时间倒序），可按状态过滤。"""
        merged = self._fold(self._read_all())
        if status:
            merged = [t for t in merged if t.get("status") == status]
        merged.sort(key=lambda t: t.get("first_ts", 0), reverse=True)
        if limit:
            merged = merged[:limit]
        return merged

    def get(self, task_id: str) -> Optional[Dict[str, Any]]:
        """取单个任务的最新状态。"""
        for task in self._fold(self._read_all()):
            if task.get("task_id") == str(task_id):
                return task
        return None

    def pending(self) -> List[Dict[str, Any]]:
        """所有未到终态的任务。"""
        return [t for t in self.list() if t.get("status") not in TERMINAL_STATUSES]

    def find_similar(
        self,
        *,
        model: Optional[str] = None,
        prompt: Optional[str] = None,
        duration: Optional[int] = None,
        resolution: Optional[str] = None,
        ratio: Optional[str] = None,
        within_seconds: int = 3600,
    ) -> List[Dict[str, Any]]:
        """找参数相同的近期任务 —— 用来提示"你是不是在重建任务重复扣费"。"""
        now = int(time.time())
        out = []
        for task in self.list():
            if now - int(task.get("first_ts", 0)) > within_seconds:
                continue
            if model and task.get("model") != model:
                continue
            if duration is not None and task.get("duration") != duration:
                continue
            if resolution and task.get("resolution") != resolution:
                continue
            if ratio and task.get("ratio") != ratio:
                continue
            if prompt is not None and task.get("prompt") != prompt:
                continue
            out.append(task)
        return out

    # ------------------------------------------------------------ 内部
    @staticmethod
    def _fold(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """把事件流折叠成任务列表。"""
        order: List[str] = []
        merged: Dict[str, Dict[str, Any]] = {}

        for entry in entries:
            tid = str(entry.get("task_id"))
            if tid not in merged:
                order.append(tid)
                merged[tid] = {"task_id": tid}
            task = merged[tid]
            task["first_ts"] = min(task.get("first_ts", entry.get("ts", 0)), entry.get("ts", 0))
            task["last_ts"] = max(task.get("last_ts", 0), entry.get("ts", 0))
            for field in _MERGE_FIELDS:
                if field in entry:
                    task[field] = entry[field]
            if "prompt" in entry:
                task["prompt"] = entry["prompt"]
            if "request_payload" in entry:
                task["request_payload"] = entry["request_payload"]
            if entry.get("event"):
                task["event"] = entry["event"]
        return [merged[t] for t in order]
