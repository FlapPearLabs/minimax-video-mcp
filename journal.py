#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
任务台账 —— 铁律一「task_id 立刻落库」的实现。

设计：追加式事件日志（JSONL）。每次状态变化就往后写一条，同一个 task_id
的记录读出来时按时间顺序**折叠合并**，等价于一张可变的任务表。

并发安全（这是被对抗式审查打出来的坑，务必保留）：
  - 进程内：用**模块级**全局锁。曾经的 bug 是锁挂在 TaskJournal 实例上，
    而 server._journal() 每次调用都新建实例 → 锁等于没有 → 并发丢记录。
  - 跨进程：用**文件锁**（Windows msvcrt / POSIX fcntl），多个 MCP server
    同时写同一个台账也不会互相覆盖。
  - 写入用 O_APPEND + 单次 os.write（O_APPEND 的追加写是原子的），
    避免"半行"和"半行粘上下行"。

为什么不用 SQLite：
  - 单文件、零依赖、人可读
  - 追加写是原子的，进程被 kill 也不会写坏整张表
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}

# 折叠时保留的字段
_MERGE_FIELDS = (
    "status", "raw_status", "video_url", "local_path", "error", "usage",
    "model", "duration", "resolution", "ratio", "cost", "downloaded_at",
    "download_error", "kind", "attempt_id", "resolved_task_id",
)

# 进程内全局锁 —— 所有 TaskJournal 实例共用
_GLOBAL_LOCK = threading.Lock()


# --------------------------------------------------------------------------
# 文件锁（跨进程）
# --------------------------------------------------------------------------
if os.name == "nt":
    import msvcrt

    def _lock_file(fh) -> None:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)

    def _unlock_file(fh) -> None:
        try:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
else:  # pragma: no cover - Windows 主路径
    import fcntl

    def _lock_file(fh) -> None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)

    def _unlock_file(fh) -> None:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass


class TaskJournal:
    """本地任务台账。"""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.last_error: Optional[str] = None

    # ---------------------------------------------------------------- 写
    def record(self, task_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
        """追加一条事件。

        返回写入的记录；**写失败返回 None**（并把原因放进 last_error）。
        绝不静默失败 —— 调用方必须知道"这条 task_id 到底有没有落库"。
        """
        entry: Dict[str, Any] = {"ts": int(time.time()), "task_id": str(task_id)}
        for key, value in fields.items():
            if value is not None:
                entry[key] = value
        line = (json.dumps(entry, ensure_ascii=False, default=str) + "\n").encode("utf-8")

        self.last_error = None
        with _GLOBAL_LOCK:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                # 锁用**独立的 .lock 文件**，不能往台账里塞占位字节 ——
                # 那会让第一条记录变成非法 JSON，读的时候直接丢掉。
                lock_path = self.path.with_name(self.path.name + ".lock")
                with lock_path.open("a+b") as lock_fh:
                    if lock_fh.seek(0, os.SEEK_END) == 0:
                        lock_fh.write(b"\0")   # msvcrt 要有字节才能锁
                        lock_fh.flush()
                    _lock_file(lock_fh)
                    try:
                        # a+b：可读可追加。读最后 1 字节判断上一行是否完整，
                        # 写仍然落在文件尾（O_APPEND）。
                        with self.path.open("a+b") as fh:
                            # 上一次若被 kill 留下了半行（没以 \n 结尾），
                            # 先补一个换行把它封住，**别让它粘住下一条记录**
                            if fh.seek(0, os.SEEK_END) > 0:
                                fh.seek(-1, os.SEEK_END)
                                if fh.read(1) != b"\n":
                                    fh.write(b"\n")
                            fh.seek(0, os.SEEK_END)
                            fh.write(line)   # 单次追加写
                            fh.flush()
                            os.fsync(fh.fileno())
                    finally:
                        _unlock_file(lock_fh)
            except OSError as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                return None
        return entry

    def new_attempt_id(self) -> str:
        """生成一个本地提交尝试号（还没拿到上游 task_id 时用）。"""
        return f"attempt-{uuid.uuid4().hex[:12]}"

    # ---------------------------------------------------------------- 读
    def _read_all(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            raw = self.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        out: List[Dict[str, Any]] = []
        for line in raw.split("\n"):
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

    def list(
        self,
        status: Optional[str] = None,
        limit: Optional[int] = None,
        include_attempts: bool = False,
    ) -> List[Dict[str, Any]]:
        """列出任务（按首次出现时间倒序），可按状态过滤。

        默认不返回 kind=attempt 的提交尝试记录（那些还没拿到 task_id）。
        """
        merged = self._fold(self._read_all())
        if not include_attempts:
            merged = [t for t in merged if t.get("kind") != "attempt"]
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
        return [
            t for t in self.list()
            if t.get("status") not in TERMINAL_STATUSES
        ]

    def unresolved_attempts(self) -> List[Dict[str, Any]]:
        """提交了但还没拿到 task_id 的尝试 —— 可能上游其实受理了，只是响应丢了。

        这些任务**不要盲目重提**，应该先去平台侧的任务列表里查。
        """
        out = []
        for task in self._fold(self._read_all()):
            if task.get("kind") == "attempt" and task.get("status") == "submitting":
                out.append(task)
        return out

    def needs_download(self) -> List[Dict[str, Any]]:
        """已成功但成片还没存下来的任务（转存失败待重试）。"""
        out = []
        for task in self.list():
            if task.get("status") == "succeeded" and task.get("video_url"):
                local = task.get("local_path")
                if not local or not Path(str(local)).exists():
                    out.append(task)
        return out

    def find_similar(
        self,
        *,
        exclude_task_id: Optional[str] = None,
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
            if exclude_task_id and task.get("task_id") == exclude_task_id:
                continue
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
