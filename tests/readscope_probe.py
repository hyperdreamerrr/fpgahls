#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#116 红线守卫：智能体**只**读输入目录里的 prompt.txt / interface.txt / top.txt。

    python tests/readscope_probe.py --task <task_dir>              # 干净 ⇒ 退出 0
    python tests/readscope_probe.py --task <task_dir> --inject X   # 必须报违规 ⇒ 退出 0
                                                                   # 报不出来 ⇒ 退出 2

★ 为什么不是 grep 源码。grep 只能证明「我写过的那几行里没有坏文件名字面量」，
  证明不了**这次运行**读了什么。而真正会出事的是第三种情况：某天有人加了一行
  `for p in glob.glob(join(d, "*_tb.cpp"))`，字面量在，模式对，grep 命中不了，
  读数却已经虚高了。所以这里**跑一遍真的**，记录真实发生的打开动作。

★ 负对照（`--inject`）是本仪器的**全部价值所在**。一台把 `open` 挂钩挂错的
  记录器，与一台诚实的记录器，在「什么都没发生」时的输出**逐字节相同** ——
  都是空。只有让它去看一次它本该看见的东西，才能把两者分开。
  所以 `--inject` 时若没抓到违规，退出码是 2（**仪器坏了**），不是 0（干净）。

★ 本仪器**覆盖不到**的（写在明处，别把它的绿读成比它实际能担保的更多）：
    - `os.stat` / `os.path.exists`：只看得到**存在性**，看不到内容。不挂钩。
    - C 扩展自己读文件（numpy/pandas 之流）。本智能体不用。
    - 子进程读文件。本智能体起的子进程只有 EDA 工具，而这里**根本不启动 EDA**
      （`VITIS_RUN_CMD` 指向不存在的路径 ⇒ `HlsToolchain.available` 为假 ⇒
       自验那一步直接返回 tool-missing，一次工具都不起）。

★ 无 EDA、无网络、无模型：`LLM_BACKEND=mock` 且工具链不可用，整条路径纯 Python。
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from agent.main import Task  # noqa: E402


class Recorder:
    """把 `open` / `listdir` / `scandir` 换成记账版。"""

    def __init__(self, task_dir: str):
        self.task_dir = os.path.abspath(task_dir)
        self.opened: list[str] = []       # 从输入目录里打开的文件（绝对路径）
        self.listed: list[str] = []       # 被列过的目录
        self._saved: list = []

    def _patch(self, obj, name, wrap):
        orig = getattr(obj, name)
        self._saved.append((obj, name, orig))
        setattr(obj, name, wrap(orig))

    def __enter__(self):
        import builtins

        def abs_in_task(path) -> str | None:
            """path 落在输入目录里就返回它的绝对路径，否则 None。"""
            try:
                p = os.fspath(path)
            except TypeError:
                return None
            if isinstance(p, bytes):
                try:
                    p = p.decode()
                except UnicodeDecodeError:
                    return None
            if not isinstance(p, str):
                return None
            a = os.path.abspath(p)
            if a == self.task_dir or a.startswith(self.task_dir + os.sep):
                return a
            return None

        def wrap_open(orig):
            def _open(file, *a, **kw):
                a2 = abs_in_task(file)
                if a2:
                    self.opened.append(a2)
                return orig(file, *a, **kw)
            return _open

        def wrap_listdir(orig):
            def _listdir(path="."):
                a2 = abs_in_task(path)
                if a2:
                    self.listed.append(a2)
                return orig(path)
            return _listdir

        def wrap_scandir(orig):
            def _scandir(path="."):
                a2 = abs_in_task(path)
                if a2:
                    self.listed.append(a2)
                return orig(path)
            return _scandir

        self._patch(builtins, "open", wrap_open)
        self._patch(os, "listdir", wrap_listdir)
        self._patch(os, "scandir", wrap_scandir)
        return self

    def __exit__(self, *exc):
        for obj, name, orig in reversed(self._saved):
            setattr(obj, name, orig)
        return False

    def violations(self) -> list[str]:
        allowed = set(Task.READABLE)
        return sorted({p for p in self.opened
                       if os.path.basename(p) not in allowed})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="read-scope guard for the HLS agent (#116)")
    ap.add_argument("--task", required=True, help="题目目录（裁判挂给智能体的那个）")
    ap.add_argument("--inject", default="",
                    help="负对照：先按这个名字读一次输入目录里的文件。"
                         "抓不到 ⇒ 仪器坏了 ⇒ 退出 2")
    ap.add_argument("--inject-list", action="store_true",
                    help="负对照（第二条通道）：先列一次输入目录。"
                         "抓不到 ⇒ listdir/scandir 那对钩子没生效 ⇒ 退出 2")
    args = ap.parse_args(argv)

    task_dir = os.path.abspath(args.task)
    if not os.path.isdir(task_dir):
        print("readscope: 没有这个目录: %s" % task_dir, file=sys.stderr)
        return 2

    # 不启动任何 EDA：工具链不可用 ⇒ 自验那一步返回 tool-missing 并收尾。
    os.environ["VITIS_RUN_CMD"] = os.path.join(task_dir, "__no_such_tool__")
    os.environ["LLM_BACKEND"] = "mock"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.environ.setdefault("AGENT_DEADLINE_S", "60")

    # 输出目录放在输入目录**外面** —— 放里面的话我们自己写 solution.cpp
    # 会被记成一次违规打开，红得毫无意义。
    with tempfile.TemporaryDirectory(prefix="readscope_") as out:
        with Recorder(task_dir) as rec:
            if args.inject:
                # 走同一个钩子读一次禁读文件：模拟「智能体伸手去拿测试台」。
                victim = os.path.join(task_dir, args.inject)
                try:
                    with open(victim, "rb") as fh:
                        fh.read(1)
                except OSError as exc:
                    print("readscope: --inject %s 读不动: %s" % (args.inject, exc),
                          file=sys.stderr)
                    return 2

            if args.inject_list:
                # 第二条通道：列目录。走的是**同一个** abs_in_task 记账路径。
                os.listdir(task_dir)

            from agent.main import main as agent_main
            rc = agent_main(["--input", task_dir, "--output", out])

    bad = rec.violations()
    listed_bad = sorted(set(rec.listed))

    print("readscope: 输入目录 %s" % task_dir)
    print("readscope: 读了 %d 个文件，其中越界 %d 个" % (len(set(rec.opened)), len(bad)))
    for p in bad:
        print("  越界: %s" % os.path.relpath(p, task_dir))
    for p in listed_bad:
        print("  列目录: %s" % os.path.relpath(p, task_dir))
    print("readscope: agent rc=%d" % rc)

    if args.inject or args.inject_list:
        # 负对照：抓到了才算仪器活着。抓不到说明钩子没生效，
        # 那么「没抓到」这件事本身**不含任何信息**。
        caught = (bool(bad) if args.inject else bool(listed_bad))
        if not caught:
            what = ("注入了 %s 却没读进来" % args.inject if args.inject
                    else "列了目录却没记下来")
            print("readscope: 仪器自检失败 —— %s。本次运行的绿是假的。" % what,
                  file=sys.stderr)
            return 2
        what = ("注入了 %s" % args.inject if args.inject else "列了一次目录")
        print("readscope: 负对照通过（%s，被抓住了）" % what)
        return 0

    if listed_bad:
        print("readscope: 违规 —— 智能体列了输入目录，文件名本身就是信息"
              "（reference/ 与 *_tb.cpp 会就此暴露）", file=sys.stderr)
        return 1
    if bad:
        print("readscope: 违规 —— 读了输入目录里除 %s 之外的文件"
              % " / ".join(Task.READABLE), file=sys.stderr)
        return 1
    print("readscope: 干净")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
