#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""HLS 赛道的工具面。

**这一层的存在理由**：官方 example 智能体只拿 csynth 当反馈，而 csynth 编译的是
**DUT 单独、不含测试台**（`example/agent/tools.py:62-104`）。而判定是**严格阶梯**，
且 L1/L2 恰恰是「DUT **与官方测试台一并**编译出 csim.exe」（`selftest/judge/hls-judge:250-285`）。

⇒ 官方 example 对这两类失败**全盲**：
      签名写错 / 少一个参数   → csynth 照样成功 → 它以为做完了 → 判定落 **L1**（系数 0.1）
      算法写错               → csynth 照样成功 → 它以为做完了 → 判定落 **L2**（系数 0.2）
   而正确的解是 L4（系数 1.0）。**这两级加起来是 0.6 的系数落差，是 L3→L4 那 0.2 的三倍**
   （`SCORING.md` §3.1.3 原话：「L2 到 L3 的 0.6 反映了『编译通过』到『算得对』这一步的实际难度」）。

本模块给智能体两件工具去补这个洞：

  check_signature()  **零 EDA 成本**的确定性检查。只读 interface.txt 与模型产出，
                     比对顶层函数的形参类型/个数/顺序。§3.1.2 明写「签名被改动的提交在
                     L2 失败」；而实测该失败落在 **L1**（见下「签名不符为什么是 L1」）。
  HlsToolchain.run() **与判分器逐字相同的工具链调用**（同一个 tcl 模板、同一个 part、
                     同一个 clock），把测试台换成模型自己写的那份。于是 L1/L2（csim_design
                     -setup）、L3（跑 csim.exe）、L4（csynth_design）三关都能在环内自测。

★ 关于「签名不符为什么是 L1」—— 这是读 judge 代码得出的，不是推测：
  `hls-judge:270-278`，csim.exe 没生成时按两条分支定性：
      `^ERROR.*<dut源码名>` 命中         → L0（源码本身不可解析）
      否则若日志里有 `Compiling <dut源码名>` → **L1**（「待测源码可解析，但未能与测试台编译出 csim.exe」）
  签名与 header 里的声明不一致时，源码**自己编译得过**（那只是另一个重载），
  死在**链接**——测试台调的是声明那个符号，没人定义。所以落 L1，不是 L2。

★ 本模块**不读** input 目录里的 `*_tb.cpp` 与 `reference/`。理由见 main.py 文件头。
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import tempfile
import time

# 与判分器同源。判分器默认值见 hls-judge:33-34。
PART = os.environ.get("HLS_PART", "xczu3eg-sbva484-1-e")
PERIOD_NS = os.environ.get("HLS_PERIOD_NS", "5")

# --------------------------------------------------------------------- 环境判别

# 授权失败必须与「选手做错」分开。词表取自 `hls-judge:55-61`（它自己在注释里写明
# 是 2026.1 实测采集、非推断），不重新发明：拿不到 seat 时 vitis-run 会把授权问题
# 说成「器件不受支持」，极具误导性。
#
# ★ 但**词与词之间是 `\s+` 而不是一个字面空格** —— 这一处是有意偏离判定器的原文。
#   理由是可核对的：判定器自己那段注释里，这行报错就是**折过行**的
#
#       ERROR: Vivado Design Suite cannot be launched because a valid license
#              was not found.
#
#   `valid license was not found` 要求这几个词连续且单空格，**匹配不了上面这份
#   唯一的实物样本**。本机 `results/` 与 `tmp/` 全量 grep `valid license` /
#   `licensing information` / `200-1023` —— **零命中**，没有第二份样本可用来
#   判定哪种写法是真的。所以取能同时吃下两种写法的那个。
#   （判定器那边若实物真是折行的，它的 LICENSE_RE 会漏，然后落进 FIXTURE_ERROR
#    分支、被讲成「题目缺陷」—— 方向正好相反。这条只记录，不改官方文件。）
#
#   宽松的代价：`\s+` 只会让匹配**更容易**，而这个短语本身足够特定，不会把
#   一条普通编译错误卷进来（见 tests 里那根负对照）。
LICENSE_RE = re.compile(
    r"valid\s+license\s+was\s+not\s+found"
    r"|could\s+not\s+obtain\s+the\s+necessary\s+license"
    r"|unable\s+to\s+get\s+licensing\s+information"
    r"|license\s+checkout\s+failure"
    r"|does\s+not\s+have\s+an\s+appropriate\s+license",
    re.I)

# 本机 `_run()` 超时的标记。用 `.*?` 而不是 `\S+` 匹配命令名：cmd[0] 可能是带空格的绝对路径。
TIMEOUT_RE = re.compile(r"\[agent\] .*?timed out after \d+s")

# 模型自写测试台的文件名：csim() 按这个名字写进工作目录、tcl 按这个名字收它。
# 写成常量，因为「日志里是谁挨骂」的判据要跟着这个名字走 —— 两处各写一份字面量、
# 漂掉一处，判据就会静默失效（读错字段名不报错、只给出很像真的假数）。
TB_SRC = "agent_tb.cpp"

# 模型自写测试台的**编译错**：编译器自己给的文件:行:列，指着 TB 文件。
# ★ 它**单独不构成结论** —— 只有放在 classify_no_exe() 的顺序里（csim.exe 没生成
#   且日志里没有 `Compiling <src>` ⇒ kernel 根本没编到）才意味着「TB 先挂了」。
#   `(?:fatal )?` 吃下 «fatal error: 'x.h' file not found» 那一形（缺 include 是
#   本题材最常见的 TB 错之一）。
TB_COMPILE_ERR_RE = re.compile(
    r"^\s*\S*%s:\d+:\d+: (?:fatal )?error: .*$" % re.escape(TB_SRC), re.M)

# fix8 改动 A：测试台里的 `#include "<名字>.cpp"`。这一行**在任何情况下都不可能对**：
# 构建目录里只有两件源码 —— 待测源码与测试台 —— 而它们在**同一次 csim** 里各自编成
# 一个 TU 再链接，谁也不 include 谁。实测（RESULTS fix7 §1.1）：aes 的第 2/3/4 轮全烧在
# 同一句 `agent_tb.cpp:9:10: fatal error: 'aes256_encrypt.cpp' file not found` 上，
# 三轮之间 kernel 的 sha16 一个字符都没变 —— 模型学不到任何东西，因为错误行说的
# 那个文件**不存在、也不会存在**（构建目录里根本没有 .cpp 可供 include）。
TB_CPP_INCLUDE_RE = re.compile(
    r'^[ \t]*#[ \t]*include[ \t]*[<"]([^">\n]+\.(?:cpp|cc|cxx|CPP|CC|CXX))[>"]', re.M)


def strip_cpp_includes(tb: str) -> tuple[str, list[str]]:
    """把测试台里的 `#include "*.cpp"` 改写成一行的注释，**行数保持不变**。

    ★ 行数必须不变：下一轮的编译错是拿 `agent_tb.cpp:<行>:<列>` 讲给模型的，
      删行会让行号整体上移，模型照错误行去改就会改到别的位置。
    ★ 纯函数：单测与 csim() 走同一份实现（旁路另抄一份判据，迟早与这份漂开）。
    """
    removed: list[str] = []
    out_lines = []
    for line in tb.splitlines(keepends=True):
        m = TB_CPP_INCLUDE_RE.match(line)
        if m:
            removed.append(m.group(1))
            out_lines.append(
                "// [harness] removed: %s is not in the build directory; the kernel "
                "and this testbench are compiled separately and linked.\n" % m.group(1))
        else:
            out_lines.append(line)
    return "".join(out_lines), removed

# E1：**编译器的**诊断行（小写 `error:`、带 `文件:行:列` 前缀），指着待测源码。
# ★ 与上面那条 TB 的**同形**，只是文件名由 `classify_no_exe()` 的实参给出 ——
#   `src` 不是常量，所以每次现拼。为什么必须有这一支：Vitis 的编译诊断长这样
#   （`../../../../kernel.cpp:9:5: error: unknown type name 'uint64_t'`），
#   而 `^ERROR.*<src>` 那一支认的是**工具自己的**大写 `ERROR:` 消息 —— 两回事，
#   实测 kernel 自己编不过时落进的是 `Compiling` 支，只给一句猜测（PREREG §1②）。
def kernel_diags(out: str, src: str) -> list[str]:
    """日志里指向待测源码的**编译器诊断行**（≤ 全部，调用方自己截断）。"""
    return re.findall(r"^\s*\S*%s:\d+:\d+:\s*(?:fatal )?error: .*$"
                      % re.escape(src), out, re.M)


# H5（fix4，2026-10-25）：**链接期**缺符号。`undefined reference to 'mmul(...)'`
# 与编译错是两种不同的错，改法也不同 —— 编译错改那一行，缺符号是「**谁**没定义」
# （题目 Sub-Components 里要求自己实现的辅助函数、或测试台调了个不存在的参考例程）。
# ★ 它必须排在 `Compiling <src>` 之前：链接发生在编译之后，两者会同时在场，
#   而 `Compiling` 支只会给一句「形参不符/符号缺失最常见」的猜测（实测 2mm 的
#   `no matching function for call to 'mmul'` 就是这么被讲成了泛化 note）。
LINK_UNDEF_RE = re.compile(
    r"undefined reference to [`'\"]([^`'\"]{1,160})[`'\"]", re.M)

ENV_REASON = {
    "timeout": "工具在给定预算内没跑完（机器负载或工具自身卡住）",
    "license": "工具签不出授权（license checkout 失败）",
    "tool-missing": "找不到 vitis-run，或它起不来",
    # 对应判定器的 FIXTURE_ERROR：csim.exe 没生成，而日志里既没有指向待测源码的
    # ERROR，也没有 `Compiling <src>` —— 判定器把这种情形算作**固定装置**的问题、
    # 不给分级（`hls-judge` 的 `result["verdict"] = "FIXTURE_ERROR"`）。
    "fixture": "csim.exe 未生成，且日志没有指向待测源码 —— 固定装置问题，不是设计结论",
}


def env_failure_kind(log: str) -> str | None:
    """日志说的是**工具的问题**还是**设计的问题**？

    返回 None 表示「工具跑完了、结论是针对设计的」，调用方按设计故障处理。
    返回非 None 表示**没有取得关于设计的任何结论** —— 这种结果**不能**当
    「编译失败」讲给模型听，否则它会去修一份本来正确的代码。

    ★ 这里**只**认判定器认的那一支（`hls-judge` 的 `LICENSE_RE`），加上本层自己的
      超时/起不来两种。不再自造第三个词表：判定器的环境词表只有 `LICENSE_ERROR`
      与 `FIXTURE_ERROR` 两项，**凡是它没归到环境里的，就是关于设计的结论**。
      自己另发明一套（比如「器件没装」「综合基础设施故障」）会让同一份日志在两个
      地方得到两种定性 —— 而这两处读数是要拿来互相解释的，定性不一致就没法解释。

    顺序有讲究：超时排最前（`_run()` 超时时会把工具输出整个丢掉、只回这一句，
    两者不可能同时出现）；授权其次，因为拿不到授权时后续所有诊断都不可信。
    """
    if TIMEOUT_RE.search(log):
        return "timeout"
    if LICENSE_RE.search(log):
        return "license"
    return None


# --------------------------------------------------------------------- 子进程

def _run(cmd: list[str], cwd: str, timeout_s: float) -> tuple[int, str]:
    """跑一条命令。返回值语义与判分器对齐：

        rc >= 0   工具跑完了（0 通过，非 0 否掉设计）
        rc == 124 超时，没跑完
        rc == -1  进程压根没起来

    ★ Windows 上 `subprocess.run(timeout=)` **界定不了墙钟**：kill() 只杀直接子进程，
      而干活的 vitis-run.exe 是孙进程，攥着 stdout 管道不放 ⇒ 超时后那次读取永久阻塞。
      开发位靠 PYTHONPATH 注入的平台垫片（把 Popen.kill 换成树杀）中和；赛事方的
      Linux 容器里 POSIX 分支走 process.wait()，没有这个毛病 ⇒ 它是平台假象，
      **不是**本智能体的设计。运行环境不带垫片时，超时会退化成「卡住」而不是 124。
    """
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, timeout=timeout_s,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            errors="replace",
        )
        return proc.returncode, proc.stdout or ""
    except subprocess.TimeoutExpired:
        return 124, f"[agent] {cmd[0]} timed out after {timeout_s:.0f}s"
    except OSError as exc:
        return -1, f"[agent] could not launch {cmd[0]}: {exc}"


def _scratch_dir() -> str:
    """工具的工作目录：**本地盘，绝不是网络存储**。

    一次 csim/csynth 会生成上万个碎文件，在 NFS 上是最慢的 IO 形态。
    `docs/API_CONTRACT.md` 第 9 节给了 `EDA_TMP`（旧名 `TRACK_TMP`）；
    `AGENT_TMP` 是 serve_api.py 传进来的，优先级最高。四个都没有才落到 `/tmp`。

    `mkdtemp(dir=...)` 要求**父目录已存在**，而上面几个变量都是调用方给的路径——
    没有任何东西保证它被建出来过。不存在时抛 FileNotFoundError，反馈环整条退化成
    rc=-1，而 run.sh 的契约要求退 0 ⇒ 表现为**一个 0 字节的 solution.cpp**，
    判分器读成 L0——又一次把环境故障报成设计错误。在这里建一次即可。
    """
    d = (os.environ.get("AGENT_TMP")
         or os.environ.get("EDA_TMP")
         or os.environ.get("TRACK_TMP")
         or "/tmp")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


# --------------------------------------------------------------- 宿主语法体检

#: 宿主编译器的一条诊断：`文件:行:列: error: 消息`（clang 与 g++ 同形）。
CXX_ERROR_RE = re.compile(r"^\s*(\S+?):(\d+):(\d+):\s*(?:fatal )?error:\s*(.*)$", re.M)
#: 缺头/找不到文件。**出现即不作结论** —— 宿主没有 `ap_int.h` 不代表 kernel 错。
MISSING_HDR_RE = re.compile(r"No such file or directory|file not found", re.I)


def host_kernel_probe(work: str, src: str, timeout_s: float = 60.0,
                      cxx: str | None = None, strict: bool = False) -> dict:
    """用**宿主**的 C++ 编译器给 kernel 单独做一次语法体检（`-fsyntax-only`）。

    返回 `{"status": "ok"|"fail"|"skipped", "why": str, "diags": [≤5 行],
    "rc": int|None, "elapsed_s": float}`。

    ★ `strict=True`（fix21 改动 A）：量的是**模型候选**时，口径必须对齐官方
      csim —— 拿现场 `csim.mk:71/75` 的两条提升：
          `-c -std=c++14 -Werror=return-type -Werror=uninitialized -I. src -o <tmp.o>`
      **不能**再用 `-fsyntax-only`：GCC 的 `-Wreturn-type` 在生成代码阶段才发出，
      `-fsyntax-only` 走不到那里（ADDENDUM A.11 §1⑥ 第三/四行实测：同一份
      「掉出末尾」的 kernel，`-fsyntax-only` + 两条旗标 rc=0，`-c` + 两条旗标 rc=1）。
      临时 `.o` 在返回前删掉；`strict=False`（缺省）逐字节保留旧命令形。

    ★ 它是**补充信号，绝不代替 Vitis**。四条保守规则，顺序即语义：

      1. 找不到编译器 / 超时 / 起不来  → skipped（宿主不给结论）；
      2. 任何「找不到头」的诊断        → skipped（宿主环境不完整。典型是
         `ap_int.h`/`ap_fixed.h`/`hls_stream.h` 这类 Vitis 专有头 —— 全量 20 题
         里有 6 题的接口头就含它们。**不许**因为宿主缺头把一份正确的 kernel
         锁死在 L1）；
      3. 有 error 行、但没有一行指着 `src` → skipped（错误全在别处）；
      4. 以上都不是                    → fail（rc>0 且 error 行指着 kernel）。

    为什么值得做：Vitis 的 csim setup 一次几十秒到几分钟，而 kernel 自己编不过
    时，这一层**几秒钟**就能把编译器原文交给模型（PREREG §1② 的两份逐字证据），
    省下的是整轮 EDA 墙钟；另外 TB 失败时它能独立回答「kernel 自身编得过吗」，
    消除分类器不查就讲「改测试台」的误导（§1③ 的 block_mm/popcount）。

    失败模式（必须在读数里查）：g++ 比 clang 严/松造成的**假阴性** —— 某题官方
    判 L2+，而本层说 fail。出现即记一次并归因（PREREG §3 E2 末条）。
    """
    name = (cxx or os.environ.get("AGENT_HOST_CXX", "").strip() or "g++")
    exe = shutil.which(name)
    if exe is None:
        return {"status": "skipped", "why": "宿主没有 %s" % name, "diags": [],
                "rc": None, "elapsed_s": 0.0}
    t0 = time.time()
    obj = None
    if strict:
        # 官方口径：两条提升 + 真编译（`-c`）。`-I.` 与旧形一致 —— header 由
        # `_seed()` 落在 work 里，cwd 也是 work。
        obj = os.path.join(work, ".hostprobe.%d.o" % os.getpid())
        argv = [exe, "-c", "-std=c++14", "-Werror=return-type",
                "-Werror=uninitialized", "-I.", src, "-o", obj]
    else:
        argv = [exe, "-fsyntax-only", "-std=c++14", "-I.", src]
    try:
        rc, out = _run(argv, work, timeout_s)
    finally:
        if obj and os.path.exists(obj):
            try:
                os.remove(obj)
            except OSError:
                pass
    res = {"status": "skipped", "why": "", "diags": [], "rc": rc,
           "elapsed_s": round(time.time() - t0, 2)}
    if rc in (124, -1):
        res["why"] = "宿主编译器超时或起不来"
        return res
    if rc == 0:
        res.update(status="ok", why="")
        return res
    errs = CXX_ERROR_RE.findall(out)
    if not errs:
        res["why"] = "宿主编译器非零退出，但没有 error 行"
        return res
    if any(MISSING_HDR_RE.search(msg) for _, _, _, msg in errs):
        res["why"] = "缺头（宿主环境不完整，不作结论）"
        return res
    base = os.path.basename(src)
    mine = ["%s:%s:%s: error: %s" % (f, ln, col, msg)
            for f, ln, col, msg in errs if re.split(r"[\\/]", f)[-1] == base]
    if not mine:
        res["why"] = "错误行都不指着 kernel"
        return res
    res.update(status="fail", diags=mine[:5], why="")
    return res


# --------------------------------------------------------------------- 工具链

def write_tcl(work: str, name: str, src: str, tb: str | None, top: str,
              commands: list[str], part: str | None = None,
              clock_ns=None) -> str:
    """生成 HLS 工程 tcl。

    ★ 与判分器 `hls-judge:191-205` **逐行同构**：同一个工程名 `proj`、同一个
      solution 名 `sol`、同一组 cflags、同样的 set_part / create_clock。
      不一样就测的不是同一条链，自验的结论也就不能外推到判定。

    `part` / `clock_ns` 由调用方从 `task.json` 取 —— 判定器正是这么做的
    （`selftest/judge.py:96-97`：`task.get("part", "xczu3eg-sbva484-1-e")`、
    `float(task.get("period_ns", 5))`）。本机 126 道题实测两者全一致，
    但**一致是这台机器上的事实，不是契约**，所以照样往下传。
    """
    tcl = os.path.join(work, name)
    with open(tcl, "w", encoding="utf-8") as f:
        f.write("open_project proj\n")
        f.write("add_files -cflags {-I. -std=c++14} %s\n" % src)
        if tb:
            f.write("add_files -tb -cflags {-I. -std=c++14} %s\n" % tb)
        f.write("set_top %s\n" % top)
        f.write("open_solution sol -flow_target vivado\n")
        f.write("set_part %s\n" % (part or PART))
        f.write("create_clock -period %s -name clk_default\n"
                % (clock_ns if clock_ns is not None else PERIOD_NS))
        for c in commands:
            f.write(c + "\n")
        f.write("exit\n")
    return os.path.basename(tcl)


CSIM_EXE = os.path.join("proj", "sol", "csim", "build", "csim.exe")


def classify_no_exe(out: str, src: str) -> dict:
    """csim.exe 没生成时，日志到底说的是**谁**的问题 —— 返回要并进结果 dict 的字段。

    这是一条**有序**判定，顺序本身是语义的一部分：

      1. 环境故障（license/timeout）—— 没有取得关于设计的结论；
      2. 指向待测源码的 ERROR —— kernel 自己不可解析（level 0）；
      2b. **编译器的**小写诊断指着待测源码 —— kernel 自己编不过（level 1，
         `kind="kernel-compile"`，编译器原文进 note；E1，2026-10-25）。它必须
         排在 3 之前：两支会同时在场，而诊断行比进度行更接近事实；
      3. `Compiling <src>` 在场 —— kernel 编到了，是与 TB 合不到一起（level 1）；
      4. **TB 编译错且 kernel 没编到** —— 模型自己的测试台先挂了（#153）：
         这是**模型的产物错**，不是固定装置故障。错误行有文件:行:列、可反馈、可修，
         所以既不报 env（那会让 main.py 停机、白丢一轮 kernel），也不报 level
         （那会把「TB 错」讲成「kernel 错」，模型会去改一份本来正确的实现）；
      5. 兜底：与判定器同一条分支 —— 没有指向待测源码的 ERROR、也没有
         `Compiling <src>`，判定器给 FIXTURE_ERROR、**不给分级**，这里同样落 env。
         4b（fix8，2026-10-25）：日志**明说**编译失败（`compilation error(s)`）却
         没有任何指向待测源码的诊断 ⇒ `kind="build-unlocalized"`，**不报 env**
         （环境是好的，只是这一轮的错误不指向某一行；报 env 会让 main.py 停机、
         白丢剩下三轮）。它必须排在 5 之前，否则又被兜底吞掉。

    ★ 本函数是纯函数，csim() 与单测走的是**同一份判定**（测试不许另抄一份判据）。
    """
    kind = env_failure_kind(out)
    if kind:
        return {"env": kind, "log": summarize_log(out), "note": ENV_REASON[kind]}
    # 区分「DUT 本身不可解析」与「与测试台编不到一起」——与判分器同口径。
    dut_err = re.search(r"^ERROR.*" + re.escape(src), out, re.M | re.I)
    if dut_err:
        return {"level": 0, "note": dut_err.group(0)[:200], "log": summarize_log(out)}
    # ★ E1：编译器的**小写** `error:` 诊断指着待测源码 ⇒ kernel 自己编不过。
    #   必须排在 `Compiling <src>` **之前**：那两支会同时在场（进度行 + 诊断行，
    #   packFloat64 r2 / gnnbuilder r3 逐字如此），而诊断行是一手证据，进度行不是。
    #   level=1 而不是 0：官方判分器对这种形状给的就是 L1（packFloat64 的交付
    #   kernel 编不过、官方 L1）—— 自验等级要与官方阶梯说同一种话。
    kdiag = kernel_diags(out, src)
    if kdiag:
        return {"level": 1, "kind": "kernel-compile", "log": summarize_log(out),
                "note": ("待测源码**自己编不过**（编译器原文指着 %s）——"
                         "先照原文改这一处，不要整份重写：\n%s"
                         % (src, "\n".join(kdiag[:5])))[:500]}
    # H5：链接期缺符号 —— kernel 编过了，但某个被调用的名字没有任何定义。
    lin = LINK_UNDEF_RE.findall(out)
    if lin:
        uniq = []
        for s in lin:
            if s not in uniq:
                uniq.append(s)
        return {"level": 1, "kind": "link-undefined", "log": summarize_log(out),
                "note": (("链接期缺符号：%s 被调用，但没有任何一处定义它。"
                          "任务书里 Sub-Components 列的函数**不是库**，要在 kernel 里"
                          "自己写出来；测试台里调用的参考例程也必须在测试台里定义。"
                          "**补上定义即可，不要重写算法。**"
                          % "、".join("`%s`" % s for s in uniq[:5])))[:500]}
    if re.search(r"Compiling .*" + re.escape(src), out):
        return {"level": 1, "log": summarize_log(out),
                "note": "待测源码可解析，但没能与测试台编译出 csim.exe"
                        "（形参不符/符号缺失最常见）"}
    tb_errs = TB_COMPILE_ERR_RE.findall(out)
    if tb_errs:
        return {"level": None, "env": None, "kind": "testbench-compile",
                "log": summarize_log(out),
                "note": ("模型自写的测试台**编译没过**（错误行指着 %s，kernel 还没编到）——"
                         "要修的是测试台本身，不是 kernel。编译器说：\n%s"
                         % (TB_SRC, "\n".join(tb_errs[:3])))[:500]}
    # fix8 改动 B：构建**确实**失败了，但日志里没有一条诊断指得到待测源码。
    #   实测（RESULTS fix7 §1.2）：sort_radix 的 r1 只有一句
    #   `ERROR: [SIM 211-100] CSim file generation failed: compilation error(s).`，
    #   而 `host_syntax rc=0`（kernel 在宿主 g++ 上编得过）。旧代码把它落进下面的
    #   兜底 `env="fixture"` ⇒ main.py 停机，四轮预算只用了一轮。
    # ★ 为什么不能报 env：环境是好的 —— 同一份 kernel 在官方臂上编出了 csim.exe
    #   （L2）。构建目录里只有 kernel 与测试台两件源码，kernel 已被宿主 g++ 排除
    #   ⇒ 没被排除的只剩测试台。判定器**可以**说「我没法分级」（它不猜），
    #   agent 不该跟着说「我只能交白卷」：这一轮仍有可反馈的结论，只是不指向某一行。
    if re.search(r"compilation error\(s\)", out, re.I):
        return {"level": None, "env": None, "kind": "build-unlocalized",
                "log": summarize_log(out),
                "note": ("构建失败，但日志里**没有一条诊断指得到待测源码的某一行**。"
                         "构建目录里只有 kernel 与测试台两个文件；kernel 的源码若已"
                         "单独编过，这个错就在测试台。把测试台砍到最小 —— 只 include "
                         "头文件、只调用一次顶层函数、只比较一个元素 —— "
                         "**不要改 kernel，更不要重写算法**。")[:500]}
    # ★ 与判定器同一条分支：到这儿说明既没有指向待测源码的 ERROR，
    #   也没有 `Compiling <src>`。判定器在这里给 FIXTURE_ERROR、**不给分级**
    #   （`hls-judge` 的 else 支），所以这里也必须落进 env 而不是 level。
    #   报成 L1 会让模型照着一份它没犯的错去改代码。
    m = re.search(r"^ERROR.*", out, re.M)
    return {"env": "fixture", "log": summarize_log(out),
            "note": (m.group(0)[:200] if m
                     else "csim.exe 未生成，原因不明（判定器对此同样不给分级）")}


class HlsToolchain:
    """Vitis HLS 的定位与三种调用。

    `vitis-run --mode hls --tcl` 是同一条入口，csim 与 csynth 只是 tcl 里命令不同。
    ★ 2025.1 / 2025.2 / 2026.1 里都**没有** `vitis_hls` 这个可执行文件
      （`Vitis/scripts/vitis_hls` 是个只含 hls.tcl 的目录）。
    """

    def __init__(self, part: str | None = None, period_ns=None) -> None:
        self.part = str(part or PART)
        self.period_ns = period_ns if period_ns is not None else PERIOD_NS
        self.reason = ""
        self.exe: str | None = None
        override = os.environ.get("VITIS_RUN_CMD", "").strip()
        if override:
            self.exe = shutil.which(override) or (override if os.path.isfile(override) else None)
            if self.exe is None:
                self.reason = "VITIS_RUN_CMD=%r 找不到" % override
            return
        # ★ 必须解析成**带扩展名的全路径**再交给 subprocess：Windows 的 CreateProcess
        #   只给名字时只补 `.exe`、不补 `.bat`，而 Vitis 的 `vitis-run` 在 Windows 上
        #   是 `.bat` ⇒ 裸名直接 FileNotFoundError，被 _run 记成 rc=-1，整题静默落 L0。
        #   这与判分器自己的 tool() 修补（hls-judge:87-88）同源、同理由。
        self.exe = shutil.which("vitis-run")
        if self.exe is None:
            self.reason = "PATH 上没有 vitis-run；先 source Vitis 的 settings64.sh，或设 VITIS_RUN_CMD"

    @property
    def available(self) -> bool:
        return self.exe is not None

    # ------------------------------------------------------------------ 内部

    def _workdir(self, prefix: str) -> str:
        return tempfile.mkdtemp(prefix=prefix, dir=_scratch_dir())

    def _seed(self, work: str, source: str, headers: dict[str, str] | None,
              src_name: str = "kernel.cpp") -> str:
        """把 header 与 DUT 落进工作目录。返回 DUT 的文件名。

        header 必须在位：生成的代码 `#include "<foo>.h"`，而工作目录里没有它的话，
        每一次检查都死在 `'foo.h' file not found`，整个 generate-check-repair 环
        变成空转。header 的内容由 main.py 从 interface.txt 还原。
        """
        for name, body in (headers or {}).items():
            with open(os.path.join(work, os.path.basename(name)), "w",
                      encoding="utf-8") as fh:
                fh.write(body)
        with open(os.path.join(work, src_name), "w", encoding="utf-8") as fh:
            fh.write(source)
        return src_name

    def kernel_syntax(self, source: str, headers: dict[str, str] | None = None,
                      timeout_s: float = 60.0, strict: bool = True) -> dict:
        """**只做宿主语法体检**：落一份 kernel（带 header）→ `g++ -fsyntax-only`。

        ★ fix21 改动 A：缺省 `strict=True` —— 这条路的输入是**模型候选**，口径要
          对齐官方 csim（`-c` + `-Werror=return-type/-Wuninitialized`，见
          `host_kernel_probe` 的 docstring）；只有兜底桩的两处探针显式传
          `strict=False`（桩的判定口径不动，ADDENDUM A.11 §5）。

        ★ 为什么需要它（fix9 改动 B）：`host_kernel_probe` 原来只被 `csim()` 调用，
          而 `csim()` 需要测试台。模型连着几轮只回 kernel 时，环里**一次编译都不跑**
          —— 实测 `machsuite__aes_aes`（fix8 面板 p12）三轮 `kinds=none`、零 EDA、
          零检查，交出去的 4,504 B kernel 本地 `g++ -fsyntax-only` 直接报
          `error: 'aes_addRoundKey' was not declared in this scope`。

        返回值就是 `host_kernel_probe` 的字典（ok/fail/skipped + why/diags/rc），
        调用方按 `kernel_check` 的口径记账（与 `csim()` 里挂的那份**同形**）。
        """
        work = self._workdir("agent_syntax_")
        try:
            src = self._seed(work, source, headers)
            return host_kernel_probe(work, src, timeout_s=timeout_s, strict=strict)
        finally:
            self._cleanup(work)

    def _stub_kernel_probe(self, source: str, headers: dict[str, str] | None,
                           top: str, timeout_s: float = 90.0) -> dict:
        """★ fix10（改动 T）：测试台编不过时，用**桩测试台**把 kernel 单独过一遍真工具链。

        返回值 `{"status": "ok"|"fail"|"skipped", "why", "diags", "rc",
        "elapsed_s", "timeout_s"}`。

        ★ 判据只有一条：**诊断行指着 kernel 源文件**才判 fail（并在调用方那边把
          kind 改判 `kernel-compile`，把编译器原文交给模型）。其余一切 —— 超时、
          缺头、诊断不指任何一行、工具起不来、以及**桩测试台编译成功**（ok，
          只作观测、不改进注记）—— 行为都回到 fix9。
          T 只能在「多给一条信息」与「什么也没多给」之间取值，不许有第三条路。
        ★ 整段包在 try/except 里：任何异常 ⇒ skipped（不许让探针把一轮自验搞崩）。

        为什么需要它（fix8 面板 `2mm` / `doitgen` 各 3 轮）：这两题的接口头含
        Vitis 专有头，宿主 g++ 一律 `skipped`，于是「kernel 到底编不编得过」在
        **整个环里没有任何仪器给过结论**，模型只能盲改测试台。
        """
        res = {"status": "skipped", "why": "", "diags": [], "rc": None,
               "elapsed_s": 0.0, "timeout_s": round(timeout_s, 1)}
        t0 = time.time()
        work = None
        try:
            work = self._workdir("agent_stub_")
            src = self._seed(work, source, headers)
            with open(os.path.join(work, TB_SRC), "w", encoding="utf-8") as fh:
                # 桩：只要能编能链能跑，不验证任何语义。
                fh.write("int main(void){return 0;}\n")
            tcl = write_tcl(work, "csim.tcl", src, TB_SRC, top,
                            ["csim_design -setup"], self.part, self.period_ns)
            rc, out = _run([self.exe, "--mode", "hls", "--tcl", tcl], work, timeout_s)
            res["rc"] = rc
            res["elapsed_s"] = round(time.time() - t0, 2)
            if rc == 124:
                res["why"] = "桩测试台探针超时（不作结论）"
                return res
            if rc == -1:
                res["why"] = "Vitis 起不来（不作结论）"
                return res
            if os.path.isfile(os.path.join(work, CSIM_EXE)):
                res.update(status="ok", why="")
                return res
            errs = CXX_ERROR_RE.findall(out)
            if not errs:
                res["why"] = "日志里没有编译器 error 行（不作结论）"
                return res
            if any(MISSING_HDR_RE.search(msg) for _, _, _, msg in errs):
                res["why"] = "缺头（构建环境不完整，不作结论）"
                return res
            base = os.path.basename(src)
            mine = ["%s:%s:%s: error: %s" % (f, ln, col, msg)
                    for f, ln, col, msg in errs if re.split(r"[\\/]", f)[-1] == base]
            if not mine:
                res["why"] = "错误行都不指着 kernel（不作结论）"
                return res
            res.update(status="fail", diags=mine[:5], why="")
            return res
        except Exception as exc:          # noqa: BLE001 —— 见 docstring 第 4 条
            res["why"] = "探针异常：%s" % exc
            res["elapsed_s"] = round(time.time() - t0, 2)
            return res
        finally:
            if work:
                self._cleanup(work)

    # -------------------------------------------------------------- csynth

    def csynth(self, source: str, top: str, timeout_s: float = 900.0,
               headers: dict[str, str] | None = None) -> tuple[int, str]:
        """只综合 DUT（不带测试台）。L4 闸门。

        rc = 0  综合完成并产出报告     rc = 1  工具否掉了设计
        rc = -1 环境故障或没跑完（调用方按 env_failure_kind 区分）
        """
        if not self.available:
            return -1, "vitis hls unavailable: %s" % self.reason
        work = self._workdir("agent_csynth_")
        try:
            src = self._seed(work, source, headers)
            tcl = write_tcl(work, "csynth.tcl", src, None, top, ["csynth_design"],
                            self.part, self.period_ns)
            rc, out = _run([self.exe, "--mode", "hls", "--tcl", tcl], work, timeout_s)
            rc, log = _verdict_or_env(out, "csynth", rc)
            if rc != 0:
                return rc, log
            return (0 if self._csynth_report(work, top) else 1), summarize_log(out)
        finally:
            self._cleanup(work)

    @staticmethod
    def _csynth_report(work: str, top: str) -> bool:
        """判有没有产出，看**产物**不看日志行。

        `vitis-run --mode hls` **从不打印** "Finished C synthesis" —— 那句话属于
        已经不存在的旧 `vitis_hls` 二进制。按它判会让每一次运行都看起来失败，
        于是修复环把全部轮次烧在改一份本来就能综合的代码上。
        """
        return bool(glob.glob(os.path.join(work, "proj", "sol", "syn", "report",
                                           "*csynth*.rpt"))
                    or glob.glob(os.path.join(work, "proj", "sol", "syn", "verilog", "*.v"))
                    or glob.glob(os.path.join(work, "proj", "sol", "syn", "vhdl", "*.vhd")))

    # -------------------------------------------------- csim（自验：setup + run）

    def csim(self, source: str, tb: str, top: str, headers: dict[str, str] | None = None,
             setup_timeout_s: float = 600.0, run_timeout_s: float = 300.0,
             keep: bool = False) -> dict:
        """把 DUT 与**自写测试台**一起编译并运行 —— 复刻判分器的 L1/L2/L3 三关。

        判分器那三关用的是**官方**测试台；这里用的是模型自己写的。两者之间那道
        差就是本自验的**残差风险**，写进 trace 里如实记，不许说成「已验证正确」。

        返回 dict：
            {"level": 0..3 | None,   # 自验等级，**不是**判定的 level
             "stages": {"csim_setup": {...}, "csim_run": {...}},
             "rc": int|None,         # 测试台退出码
             "stdout": str,          # 测试台自己的 stdout（判分器也拿它比金标）
             "note": str, "log": str, "env": str|None, "work": str|None}
        """
        r: dict = {"level": None, "stages": {}, "rc": None, "stdout": "",
                   "note": "", "log": "", "env": None, "work": None}
        if not self.available:
            r.update(level=None, env="tool-missing", log="vitis hls unavailable: %s" % self.reason)
            return r

        work = self._workdir("agent_csim_")
        try:
            src = self._seed(work, source, headers)

            # ★ E2：先让**宿主编译器**给 kernel 单独过一遍语法。两条用法：
            #   ① 编不过 ⇒ 立刻用编译器原文回话，**不起 Vitis**（省一轮 EDA 墙钟）；
            #   ② 编得过 ⇒ 后面 TB 挂时 note 里能加一句独立证据（消 §1③ 的误导）。
            kc = host_kernel_probe(work, src, strict=True)
            r["kernel_check"] = kc
            r["stages"]["host_syntax"] = {"rc": kc.get("rc"),
                                          "status": kc["status"],
                                          "elapsed_s": kc.get("elapsed_s", 0.0)}
            if kc["status"] == "fail":
                r.update(level=1, kind="kernel-compile",
                         log="\n".join(kc["diags"]),
                         note=("待测源码**自己编不过**（宿主 g++ 的编译原文指着 %s）——"
                               "先照原文改这一处，不要整份重写：\n%s"
                               % (src, "\n".join(kc["diags"])))[:500])
                return r

            # fix8 改动 A：写盘之前先把 `#include "*.cpp"` 拿掉（行数不变，见
            # strip_cpp_includes 的注释）。行使事实记进结果 dict ⇒ 进 trace。
            tb_eff, tb_removed = strip_cpp_includes(tb)
            if tb_removed:
                r["tb_fix"] = {"cpp_includes": tb_removed}
            with open(os.path.join(work, TB_SRC), "w", encoding="utf-8") as fh:
                fh.write(tb_eff)

            tcl = write_tcl(work, "csim.tcl", src, TB_SRC, top,
                            ["csim_design -setup"], self.part, self.period_ns)
            rc, out = _run([self.exe, "--mode", "hls", "--tcl", tcl], work, setup_timeout_s)
            r["stages"]["csim_setup"] = {"rc": rc}
            if rc == 124:
                r.update(env="timeout", log=summarize_log(out),
                         note="csim_setup 超时，未取得关于设计的结论")
                return r
            if rc == -1:
                # ★ 工具**根本没起来**。不接这一支的话会一路掉到底下的 `env="fixture"`，
                #   于是「vitis-run 找不到」被记成「固定装置有问题」—— 两者都是环境故障
                #   （所以不会去赖模型），但**归因标签是复核时要看的**：把「起不来」
                #   记成「题目缺陷」，方向就错了。ENV_REASON 里本来就有这一支。
                r.update(env="tool-missing", log=summarize_log(out),
                         note=ENV_REASON["tool-missing"])
                return r

            exe = os.path.join(work, CSIM_EXE)
            if not os.path.isfile(exe):
                # ★ 判定链搬到 classify_no_exe()：单测要能驱动**闸真正读的那份判据**，
                #   而不是在旁边另抄一份（抄的那份迟早与这份漂开）。
                r.update(classify_no_exe(out, src))
                # ★ fix10（改动 T）：测试台编不过、而宿主又给不出 kernel 的结论
                #   （缺头/无编译器）⇒ 用**桩测试台**把 kernel 单独过一遍真工具链。
                #   只在 `skipped` 时才花这一次 EDA；`ok` 时没必要（已能回答）。
                #   判 fail 的条件由 `_stub_kernel_probe` 自己保证：诊断必须指着
                #   kernel 源文件 —— 测试台的错不许记到 kernel 头上（PREREG §4 (h)）。
                if (r.get("kind") in ("testbench-compile", "build-unlocalized")
                        and (r.get("kernel_check") or {}).get("status") == "skipped"):
                    sp = self._stub_kernel_probe(
                        source, headers, top,
                        timeout_s=min(90.0, max(20.0, setup_timeout_s * 0.3)))
                    r["stub_probe"] = sp
                    if sp["status"] == "fail":
                        r.update(level=1, kind="kernel-compile",
                                 log="\n".join(sp["diags"]),
                                 note=("测试台编不过，但用桩测试台把 kernel 单独过真工具链时，"
                                       "**kernel 自己编不过**（编译器原文指着 %s）——"
                                       "先按原文把 kernel 改好，再谈测试台：\n%s"
                                       % (src, "\n".join(sp["diags"])))[:500])
                # ★ E2②：kernel 单独编得过时，把这条**独立证据**补进 note。
                #   只在 `ok` 时说 —— `skipped`（宿主缺头/无编译器）时什么都不说，
                #   否则就是用一句没根据的话替换另一句没根据的话。
                #   fix8 改动 B：`build-unlocalized`（日志只说「编译失败」、
                #   不指向任何一行）与 `testbench-compile` 是同一条推断的两种证据强度：
                #   构建目录只有两件源码，kernel 已被宿主 g++ 排除 ⇒ 剩下的是测试台。
                if (r.get("kind") in ("testbench-compile", "build-unlocalized")
                        and (r.get("kernel_check") or {}).get("status") == "ok"):
                    r["note"] = (r["note"]
                                 + "\n（宿主 g++ 的语法体检：**kernel 自身编得过**，"
                                   "这一轮的错误全部来自测试台。）")[:600]
                if r.get("tb_fix"):
                    r["note"] = (r["note"]
                                 + "\n（harness 已从测试台里删掉 %s：构建目录只有 kernel 与"
                                   "测试台两个文件，它们在同一个 csim 里分别编译再链接，"
                                   "谁也不 include 谁。）"
                                 % "、".join("`%s`" % s
                                             for s in r["tb_fix"]["cpp_includes"]))[:700]
                return r

            r["level"] = 2                       # 与测试台编过了

            # ★ cwd 必须是工作目录：machsuite 的测试台用相对路径 open("input.data")。
            rc3, out3 = _run([exe], work, run_timeout_s)
            r["stages"]["csim_run"] = {"rc": rc3}
            r["rc"] = rc3
            r["stdout"] = out3
            if rc3 == 124:
                # ★ 这里**不**报 env，与上游那个 setup 超时区别对待。
                #   setup 超时 = 工具自己卡住，那是环境。
                #   跑 csim.exe 超时 = 工具干完了活，**是我们让跑的那个程序没跑完** ——
                #   这是关于程序的一句话，不是关于机器的一句话。
                #   报成 env 会让 main.py 直接 break、交出当前结果；
                #   而超时最常见的原因是**模型自己写的测试台死循环**，
                #   那恰恰是下一轮该修的东西 —— 报成 env 就把这次机会扔了。
                #   level=2 是**已经确立**的事实（编过、链过），不含糊其辞；
                #   同时明写「这不构成关于 kernel 的结论」，免得模型去改算法。
                r.update(level=2, kind="testbench-timeout", log=summarize_log(out3),
                         note="测试台编译链接都过了，但**运行没跑完**（%.0f 秒上限）。"
                              "最常见的原因是测试台自己死循环 —— 请检查它的循环边界。"
                              "这**不构成关于 kernel 的结论**，不要因此重写算法。"
                              % run_timeout_s)
                return r
            if rc3 != 0:
                r.update(note="测试台返回非零退出码 %d —— 功能不对" % rc3,
                         log=summarize_log(out3))
                return r
            r["level"] = 3                       # 自写测试台全过
            r["note"] = "自写测试台通过（**不是**官方测试台，官方那关仍可能挂）"
            r["log"] = summarize_log(out3)
            return r
        finally:
            if keep or os.environ.get("AGENT_KEEP_WORK") == "1":
                r["work"] = work
            else:
                self._cleanup(work)

    @staticmethod
    def _cleanup(work: str) -> None:
        if os.environ.get("AGENT_KEEP_WORK") != "1":
            shutil.rmtree(work, ignore_errors=True)


def _verdict_or_env(log: str, tool: str, rc: int) -> tuple[int, str]:
    """只有 rc>0 才是「工具跑完了并否掉了设计」。

    rc 的四种来源里只有第一种是设计的问题：
        rc  > 0    工具跑完了，并且否掉了设计（真诊断）
        rc == 124  超时，没跑完
        rc == -1   进程压根没起来（OSError）
        rc  < 0    Unix 下被信号打死（-9 OOM / -11 SIGSEGV），没出结论
    后三种必须落到 rc<0 那条路 —— 调用方停止重试并交出当前代码。此前它们会被
    统一改写成 (1, ...)，于是既让模型照着「你的设计没过」去改一份本来正确的代码，
    也让 trace.jsonl（判分证据）记成一个它并不掌握的设计结论。
    """
    kind = env_failure_kind(log)
    if kind is not None:
        return -1, ("[env:%s] %s：%s —— 本轮没有取得关于设计的结论，"
                    "不要当编译错误处理。\n\n%s"
                    % (kind, tool, ENV_REASON[kind], summarize_log(log)))
    return rc, summarize_log(log)


# ------------------------------------------------------- 确定性签名检查（零 EDA）

# C++ 里一个函数声明/定义的大致形状：`(...)` 吃参数表。
# ★ 两个字符类都**必须**排除 `(`，只排除 `)` 不够 —— 第一段是贪婪的，
#   `[^;{)]` 允许 `(`，它会把 `(*` 一起吞掉，交替段根本没机会上场，于是在
#   `(*)` 的那个 `)` 处提前收尾：`unsigned char (*)[4][4]` 之后的形参全丢。
#   add_round_key 的三轮假红（题目要求：(unsigned, unsigned char ( *)）就是
#   这条造成的 —— 模型怎么写都对不上，而它照着改的是一份**正确**的签名。
#   排除 `(` 之后，内层括号交给交替段 `\([^)]*\)` 整段吃掉（`(*)`/`(void)` 都是它的活）。
_SIG_PARAMS = r"([^;{()]*(?:\([^)]*\)[^;{()]*)*)"
_SIG_RE = r"\b%s\s*\(" + _SIG_PARAMS + r"\)"

# 产出侧要**定义**：`)` 后紧跟 `{` 才算函数体。声明柱（只有原型、没有体）在
# 文本上与定义只差这个花括号，而它必然在链接期 undefined symbol（L1）—— 官方
# 判 L1 的三份产物（gnnbuilder / gemm_ncubed / 2mm）全是这种，此前它们全过闸。
_SIG_DEF_RE = r"\b%s\s*\(" + _SIG_PARAMS + r"\)\s*\{"

_WS = re.compile(r"\s+")

# 形参里要抹掉的东西：形参名（第二个标识符）、默认值、注释。
_LINE_COMMENT = re.compile(r"//[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


def _strip_comments(text: str) -> str:
    return _WS.sub(" ", _LINE_COMMENT.sub(" ", _BLOCK_COMMENT.sub(" ", text))).strip()


def declared_signatures(text: str, top: str) -> list[str]:
    """取出 `text` 里 `top` 的**全部**候选参数表（按出现顺序）。

    为什么不只取第一个：题面是散文，「Top-Level Function」段之外也可能先出现
    别处的 `top(`。prompt 侧要拿全部候选去比，任一命中即一致 —— 只认第一个
    会把一次正确的提交判红，而假红会驱动模型去改对的东西。
    """
    if not text or not top:
        return []
    return [m.group(1) for m in re.finditer(_SIG_RE % re.escape(top),
                                            _strip_comments(text))]


def declared_signature(interface: str, top: str) -> str | None:
    """从 interface.txt 里取出 `top` 的**声明**（第一条，参数表原文）。取不到返回 None。"""
    sigs = declared_signatures(interface, top)
    return sigs[0] if sigs else None


# 形参名抹除的例外表，两处用：① 最后一个 token 是**类型关键字/标准类型名**时不能
# 当名字抹 —— 题目头文件里形参名会被生成器剥掉，于是 `unsigned char`（无名形参）
# 会被「抹最后一个标识符」误伤成 `unsigned`（add_round_key 第一形参的红就是这么来的）；
# ② 类型说明符段的排序只用这些词做边界。表要保守：只收「做类型时不可能同时是形参名」
# 的名字 —— 表小一点只是少归一点，不会把不同类型排成相等。
_TYPE_WORDS = frozenset("""
    void bool char short int long float double signed unsigned
    const volatile auto struct union enum class typename
    wchar_t char8_t char16_t char32_t
    size_t ssize_t ptrdiff_t intptr_t uintptr_t
    int8_t int16_t int32_t int64_t uint8_t uint16_t uint32_t uint64_t
""".split())


def _canon_type_run(toks: list[str]) -> list[str]:
    """把**开头那段全是类型关键字**的 token 排序（`unsigned char const` ≡ `const unsigned char`）。

    C 标准里类型说明符/限定符的顺序不影响类型同一性（C11 6.7.2、6.7.3），所以
    `unsigned char const *` 与 `const unsigned char *` 是同一个类型 —— 文本比对
    分不清它俩会把**正确**的代码判红，而假红会驱动模型去改对的东西。
    只排开头那段：声明符部分（`(*)`、数组维度）顺序是有意义的，保持原序。
    排的是同一个多重集合，只会让「本来就相等」的多一种写法命中，
    **不可能把两个不同的类型排成相等** —— 这是不造新假绿的前提。
    """
    i = 0
    while i < len(toks) and toks[i] in _TYPE_WORDS:
        i += 1
    return sorted(toks[:i]) + toks[i:]

_DIM_RE = re.compile(r"\[([^\]]*)\]")
# 维度里只允许数字与运算符 —— **没有字母 ⇒ 求值时没有名字可查**，eval 是安全的。
_DIM_EXPR = re.compile(r"^[\d\s()+\-*/.]+$")


def _norm_dim(inner: str) -> str:
    """`[ 40 + 0]` 与 `[40]` 是同一个维度，按**值**归一；宏/标识符维度保持文本。

    生成器给 small-* 族的 interface 写 `[ 40 + 0]` 这种表达式形态，模型写 `[40]` ——
    纯文本比对把它判成不一致，而那两个产物官方判 **L2**（签名数值一字不差）。
    求值失败、非整数、含标识符的一律退化为去空白文本：**宁可少归一，不许多归一**
    —— 多归一会把真错的维度抹平，那正是 `test_changed_trailing_dimension` 守的假绿。
    """
    t = inner.strip()
    if t and _DIM_EXPR.fullmatch(t):
        try:
            v = eval(t, {"__builtins__": {}}, {})      # noqa: S307 —— 字符集里没有字母
            if isinstance(v, int):
                return "[%d]" % v
            if isinstance(v, float) and v.is_integer():
                return "[%d]" % int(v)
        except Exception:
            pass
    return "[" + _WS.sub("", t) + "]"


def _norm_params(params: str) -> list[str]:
    """把参数表拆成一个个形参，并抹掉**形参名**与默认值。

    为什么要抹名字：测试台按**位置**调用，形参名进不了链接。名字不同不该报红，
    否则模型会被逼着去改一个根本不影响判定的东西 —— 一次假的红比漏报更危险，
    它会驱动你去改对的东西。

    抹不掉的（类型、顺序、个数、数组维度）才是真会改链接结果的东西，全保留。
    """
    out = []
    for raw in _split_top_level(params):
        p = raw.strip()
        if not p or p == "void":
            continue
        p = p.split("=")[0].strip()          # 默认实参
        # 数组/函数指针形参里的声明符名字在括号里（`(*state)`），上面那条
        # 「抹最后一个标识符」够不着它 —— 先剥成 `(*)`，两边才可比。
        p = re.sub(r"\(\s*([*&])\s*[A-Za-z_]\w*\s*\)", r"(\1)", p)
        # 维度先按值归一（`[ 40 + 0]` ≡ `[40]`；宏维度只去空白），再抹第一维。
        p = _DIM_RE.sub(lambda m: _norm_dim(m.group(1)), p)
        # ★ 只抹**第一维**，后面的维度必须原样留着。
        #   C++ 里 `double A[16][22]` 形参会退化成 `double (*)[22]` —— 所以第一维
        #   写 16 还是写空是同一个类型，抹掉不会漏报。
        #   但把每一维都抹成 `[]` 是**过度归一**：`double A[16][20]` 与 `[16][22]`
        #   是**不兼容**的两个类型，测试台那一侧会直接编译失败。抹平了就会把一次
        #   必落 L1 的错报成「签名一致」，也就是一条**假绿**。
        #   而假绿比漏报危险：它会让自验通过、让递交带着这个错出去。
        p = re.sub(r"\[[^\]]*\]", "[]", p, count=1)
        toks = p.replace("*", " * ").replace("&", " & ").split()
        # 抹形参名：最后一个**纯标识符**，且它前面还有别的 token、且它不是类型名。
        if (len(toks) >= 2 and re.fullmatch(r"[A-Za-z_]\w*", toks[-1])
                and toks[-1] not in _TYPE_WORDS):
            toks = toks[:-1]
        out.append(" ".join(_canon_type_run(toks)))
    return out


def param_names(params: str) -> list[str]:
    """形参表 → 每个形参的**名字**（取不到就是 `""`），切分与 `_norm_params` 同源。

    ★ 为什么需要它：`_norm_params` 按设计**抹掉**名字（官方测试台按位置调用，
      名字不同不该报红）。于是「函数体里引用了不在作用域里的名字」这类错它
      **看不见** —— 本函数走同一套步骤，只在最后一步把名字**记下来**而不是抹掉。

    与 `_norm_params` 只有两处**必要**差异，都写在用例旁边
    （`tests/test_hls_agent.py::TestFix22HelperParamScope` 同时钉住两边）：

      ① 数组后缀**先剥**再判标识符：`char SEQA[ALEN]` 归一后的最后一段是
         `SEQA[]`，不剥就一个名字也取不到（实测 6 个形参全变空串）；
      ② 函数指针形参的名字在归一化**之前**捕获：`void (*cb)(int)` 会被归一成
         `(*)`，之后就再也看不到 `cb` 了。

    取不到名字的形参（`unsigned char` 这种无名形参、`void`）返回 `""`，位置保留 ——
    调用方据此与 `_norm_params` 的返回一一对账。
    """
    out = []
    for raw in _split_top_level(params or ""):
        p = raw.strip()
        if not p or p == "void":
            out.append("")
            continue
        p = p.split("=")[0].strip()          # 默认实参
        fp = re.search(r"\(\s*[*&]\s*([A-Za-z_]\w*)\s*\)", p)
        fp_name = fp.group(1) if fp else ""  # ★ 差异 ②：剥之前先记
        p = re.sub(r"\(\s*([*&])\s*[A-Za-z_]\w*\s*\)", r"(\1)", p)
        p = _DIM_RE.sub(lambda m: _norm_dim(m.group(1)), p)
        p = re.sub(r"\[[^\]]*\]", "[]", p, count=1)
        toks = p.replace("*", " * ").replace("&", " & ").split()
        nm = ""
        if len(toks) >= 2:
            base = re.sub(r"(\[[^\]]*\])+$", "", toks[-1])   # ★ 差异 ①
            if re.fullmatch(r"[A-Za-z_]\w*", base) and base not in _TYPE_WORDS:
                nm = base
        out.append(nm or fp_name)
    return out


def _split_top_level(params: str) -> list[str]:
    """按顶层逗号切分参数表，忽略模板实参/函数指针里的逗号与括号。"""
    parts, depth, cur = [], 0, ""
    for ch in params:
        if ch in "(<[":
            depth += 1
        elif ch in ")>]":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return parts


def check_signature(code: str, interface: str, top: str,
                    prompt: str | None = None) -> tuple[bool, str]:
    """模型产出的顶层函数签名与题目给的接口是否一致？

    返回 (ok, 说明)。**ok=True 只在两种情况**：确认一致，或**无法判定**。
    无法判定时说明里写明「跳过检查」——少查一次，好过把正确的代码改坏。

    `prompt` 是题面原文（可选）。interface.txt 与题面里的原型是**同一个签名的
    两种拼写**（题目生成器把 typedef 展开写进了头文件，题面里保留原拼写：
    add_round_key 的 `unsigned char (*)[4][4]` vs `state_t *`）——按任一种写都对，
    只有两边都对不上才红。

    ★ 这台检查**只能**做文本比对，抓不住语义等价但写法不同的类型别名
      （`typedef int* ptr; void f(ptr)` vs `void f(int*)`）。它不是判分器，
      是**反馈环的第一道闸**：零成本、覆盖最常见的那类错（少参数、改类型、改顺序）。
      真正的 L2 判据是 `HlsToolchain.csim()` 拿真实工具链编一次。
    """
    want = declared_signature(interface, top)
    if want is None:
        return True, "interface.txt 里解析不出 `%s` 的声明 —— 跳过签名检查" % top
    text = _strip_comments(code)
    got_m = re.search(_SIG_DEF_RE % re.escape(top), text)
    if got_m is None:
        # 有原型没函数体：这是**声明柱**，链接期必然 undefined symbol。
        # 只说「找不到」会掩盖真实原因（东西在，只是没实现），模型会去查名字。
        decl_m = re.search(_SIG_RE % re.escape(top), text)
        if decl_m is not None:
            return False, (
                "顶层函数 `%s` 只有**声明**没有**定义** —— 产出里找不到函数体。\n"
                "测试台链接的是函数体；只写原型会在链接期报 undefined symbol，"
                "判 L1（系数 0.1 而不是 1.0）。请给出完整实现（函数体），不是原型。\n"
                "  你写的原型：%s"
                % (top, "(" + ", ".join(_norm_params(decl_m.group(1))) + ")"))
        return False, ("产出里找不到 `%s` 的**定义**。题目要求顶层函数就叫这个名字，"
                       "测试台按这个名字调用；改名或包进 namespace/class 都会在链接期失败。"
                       % top)
    a, b = _norm_params(want), _norm_params(got_m.group(1))
    if a == b:
        return True, "签名与题目接口一致（%d 个形参）" % len(a)
    if prompt and any(_norm_params(c) == b
                      for c in declared_signatures(prompt, top)):
        return True, ("签名与题面 `prompt.txt` 给出的原型一致（%d 个形参）——"
                      "interface.txt 里是同一签名的另一种拼写（typedef/宏别名）。"
                      % len(b))
    return False, (
        "顶层函数 `%s` 的形参与题目给的接口**不一致**。\n"
        "  题目要求：%s\n"
        "  你写的  ：%s\n"
        "签名不一致的提交在判定时**连 L2 都到不了**（测试台按原签名调用，链接期找不到符号，"
        "落 L1，系数 0.1 而不是 1.0）。请**照题目给的接口逐字**改回来，不要改题目。"
        % (top, "(" + ", ".join(a) + ")", "(" + ", ".join(b) + ")"))


# --------------------------------------------------------------- 别名转发包壳
# 病灶（fix10 全量 122 题实测）：模型把实现写对了，函数名却写成 `ref_spmv` /
# `stencil3d_ref` / `ref_ellpack` —— 参数表与题目接口逐项相同，只有名字不同。
# 签名闸只看名字，于是四轮全红、连一次 csynth 都没跑过（L1，系数 0.1）。
# 闸本身没有错判：顶层符号确实不存在。但「把已有实现接到要求的名字上」是一个
# **确定性的**机械改写（补一个转发包壳），不猜语义、不调模型、与题目无关。
#
# 保守边界（每条都是「宁可不动」）：
#   * 只在 `top` **没有任何定义**时出手（形参不一致的情况不动 —— 那是真错误）；
#   * 必须**恰好一个**参数表等价的候选函数；0 个或多个一律不动；
#   * 返回类型必须同 void 性；形参名必须能安全生成（函数指针也能生成 `(*p0)`）；
#   * 花括号必须平衡（否则包壳会落进 namespace / extern "C" 块里）；
#   * 产物里对 interface 宏的重定义一律拒绝（`#define TYPE` 冲突会悄悄换类型）。

_CTRL_WORDS = frozenset("if for while switch catch return sizeof do else".split())

_DEFINE_RE = re.compile(r"^\s*#\s*define\s+([A-Za-z_]\w*)\s+([^\n]+)$", re.M)
_BLOCK_COMMENT_NL = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT_NL = re.compile(r"//[^\n]*")


def _strip_comments_nl(text: str) -> str:
    """去掉注释但**保留换行**（取返回类型要按行切，_strip_comments 会把行压平）。"""
    def _blank(m: "re.Match[str]") -> str:
        return "\n" * m.group(0).count("\n")
    return _LINE_COMMENT_NL.sub("", _BLOCK_COMMENT_NL.sub(_blank, text))


def _object_macros(text: str) -> dict[str, str]:
    """只收对象宏，且值里没有括号/斜杠/井号 —— 保守，够覆盖 `#define TYPE double`。"""
    out: dict[str, str] = {}
    for name, val in _DEFINE_RE.findall(text or ""):
        v = val.strip()
        if any(ch in v for ch in "()/#"):
            continue
        if not re.fullmatch(r"[A-Za-z0-9_\s]+", v):
            continue
        out[name] = v
    return out


def _expand_macros(text: str, macros: dict[str, str], rounds: int = 4) -> str:
    """整词替换到不动点。只用来**比较**，从不写回产物。"""
    if not macros:
        return text
    for _ in range(rounds):
        new = re.sub(r"\b[A-Za-z_]\w*\b",
                     lambda m: macros.get(m.group(0), m.group(0)), text)
        if new == text:
            break
        text = new
    return text


def _type_key(param: str) -> str:
    """把一个形参化成**纯类型**键：抹掉形参名/默认值，维度按值归一、只抹第一维。

    与 `_norm_params` 的差别只有一处、但正是 fix11 的靶：数组形参的名字
    （`TYPE out_ref[N]` 里的 `out_ref`）也要抹。`_norm_params` 只抹「最后一个
    token 是纯标识符」的情形，数组名后面跟着 `[]` 所以抹不掉 —— 这正是
    spmv_crs / spmv_ellpack 四轮假红的直接机制。
    这里**只用于别名判定**，不改 `check_signature` 的判定语义。
    """
    p = param.split("=")[0].strip()
    # 命名函数指针 `(*fp)` → `(*)`
    p = re.sub(r"\(\s*([*&])\s*[A-Za-z_]\w*\s*\)", r"(\1)", p)
    p = _DIM_RE.sub(lambda m: _norm_dim(m.group(1)), p)
    i = p.find("[")
    if i >= 0:                                  # 数组：名字在第一维前
        head, dims = p[:i].rstrip(), p[i:]
        toks = head.split()
        if (len(toks) >= 2 and re.fullmatch(r"[A-Za-z_]\w*", toks[-1])
                and toks[-1] not in _TYPE_WORDS):
            toks = toks[:-1]
        p = " ".join(toks) + " " + dims if toks else dims
    else:
        toks = p.replace("*", " * ").replace("&", " & ").split()
        if (len(toks) >= 2 and re.fullmatch(r"[A-Za-z_]\w*", toks[-1])
                and toks[-1] not in _TYPE_WORDS):
            toks = toks[:-1]
        p = " ".join(toks)
    p = re.sub(r"\[[^\]]*\]", "[]", p, count=1)   # 只抹第一维
    return " ".join(_canon_type_run(p.split()))


def _type_sig(params: str, macros: dict[str, str] | None = None) -> tuple[str, ...]:
    """整张参数表的纯类型键序列。"""
    text = _expand_macros(params, macros or {})
    return tuple(_type_key(p) for p in _split_top_level(text)
                 if p.strip() and p.strip() != "void")


def _ret_type(text: str, pos: int) -> str | None:
    """从 `pos` 往前取「同一行里」的返回类型；跨行签名往上找非空行。"""
    seg = text[:pos]
    cand = ""
    for _ in range(6):
        cut = max(seg.rfind(ch) for ch in ";\n{}")
        cand = " ".join(seg[cut + 1:].split())
        if cand:
            break
        if cut < 0:
            return None
        seg = seg[:cut]
    if not cand or len(cand) > 80:
        return None
    if any(ch in cand for ch in '#"=()'):
        return None
    toks = cand.split()
    if len(toks) > 6:
        return None
    if any(not re.fullmatch(r"[A-Za-z_][\w:<>,\*&]*|[<>,\*&]+", t) for t in toks):
        return None
    if toks[-1] in _CTRL_WORDS or toks[-1] in ("else", "do"):
        return None
    return cand


def _function_defs(code: str) -> list[tuple[str, str, str]]:
    """产物里的 (返回类型, 函数名, 参数表原文)，只认带函数体的定义。"""
    text = _strip_comments_nl(code)
    out = []
    for m in re.finditer(r"\b([A-Za-z_]\w*)\s*\(" + _SIG_PARAMS + r"\)\s*\{", text):
        name = m.group(1)
        if name in _CTRL_WORDS:
            continue
        ret = _ret_type(text, m.start())
        if ret is None:
            continue
        out.append((ret, name, m.group(2)))
    return out


def _name_param(raw: str, fallback: str) -> tuple[str, str] | None:
    """(带名字的形参原文, 名字)；`void`/空返回 None。

    **原名一律原样保留**：包壳的形参表与 interface.txt 逐字相同时，签名闸
    （`_norm_params` 不抹数组名）才必然放行 —— 这对「补壳之后闸要转绿」
    是必要条件，也是探针的正面证据。
    """
    p = raw.split("=")[0].strip()
    if not p or p == "void":
        return None
    m = re.search(r"\(\s*[*&]\s*([A-Za-z_]\w*)\s*\)", p)      # 已命名的函数指针
    if m:
        return p, m.group(1)
    if re.search(r"\(\s*[*&]\s*\)", p):                       # 抽象函数指针
        return (re.sub(r"\(\s*([*&])\s*\)",
                       lambda mm: "(%s%s)" % (mm.group(1), fallback), p, count=1),
                fallback)
    i = p.find("[")
    if i >= 0:
        toks = p[:i].split()
        if (len(toks) >= 2 and re.fullmatch(r"[A-Za-z_]\w*", toks[-1])
                and toks[-1] not in _TYPE_WORDS):
            return p, toks[-1]                                # 原名可用，原样返回
        return None                                           # 无名数组：闸对不上，放弃
    toks = p.replace("*", " * ").replace("&", " & ").split()
    if (len(toks) >= 2 and re.fullmatch(r"[A-Za-z_]\w*", toks[-1])
            and toks[-1] not in _TYPE_WORDS):
        return p, toks[-1]                                    # 原名可用，原样返回
    return " ".join(toks) + " " + fallback, fallback


def _braces_balanced(text: str) -> bool:
    depth = 0
    for ch in _strip_comments_nl(text):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _scan_delims(code: str) -> tuple[list[tuple[str, int]], str]:
    """逐字符扫定界符，返回 `(未闭合栈, 错误)`；栈元素是 `(字符, 行号)`。

    必须认字符串/字符字面量与注释：`puts("}")` 里的花括号不算数，`// }` 也不算。
    `_strip_comments_nl()` 是正则版、不认行内字符串里的 `//` —— 用它扫
    `puts("http://x") {` 会把 `{` 一起吞掉。所以这里按字符走一遍。
    """
    stack: list[tuple[str, int]] = []
    i, n, line = 0, len(code), 1
    while i < n:
        c = code[i]
        if c == "\n":
            line += 1
            i += 1
            continue
        if c == "/" and i + 1 < n and code[i + 1] == "/":
            j = code.find("\n", i)
            i = n if j < 0 else j
            continue
        if c == "/" and i + 1 < n and code[i + 1] == "*":
            j = code.find("*/", i + 2)
            if j < 0:
                return stack, "块注释没有闭合（第 %d 行起）" % line
            line += code.count("\n", i, j)
            i = j + 2
            continue
        if c in "\"'":
            q, i = c, i + 1
            while i < n:
                if code[i] == "\\":
                    i += 2
                    continue
                if code[i] == q:
                    i += 1
                    break
                if code[i] == "\n":
                    line += 1
                i += 1
            continue
        if c in "{[(":
            stack.append((c, line))
        elif c in "}])":
            want = {"}": "{", ")": "(", "]": "["}[c]
            if not stack or stack[-1][0] != want:
                return stack, "第 %d 行多出一个 `%s`（没有与之配对的 `%s`）" % (
                    line, c, want)
            stack.pop()
        i += 1
    return stack, ""


#: `close_unbalanced_braces()` 最多补几个 `}`。模型漏一处收尾是常态；一口气缺 5 个以上
#: 更像整段没写完（或抽取器切错），那种残稿补起来只会骗过编译闸 —— 不修。
_CLOSE_MAX = 4


def close_unbalanced_braces(code: str) -> tuple[str, int, str]:
    """模型写完却漏掉收尾花括号时，在**文件末尾**补上缺的 `}`。

    返回 `(新代码, 补了几个, 说明)`；不该出手时原样返回，说明里写原因。

    只做一件事：把打开着、且**全是 `{`** 的定界符在末尾补齐。不删字、不改缩进、
    不动中间任何一行 —— 花括号不平衡的文件在官方判分里必定 L1（`csim_design`
    编不过），所以它不可能把一份本来就对的代码改坏。

    边角情形一律**不修**（原样返回并写明原因）：
      * 有 `(` 或 `[` 没闭合 —— 那不是「少一个收尾」，是签名/下标断了，补 `)` 会把
        一处真错掩盖成编译得过的样子；
      * 多出一个 `}`（不匹配）—— 只能删，删除超出本函数的权限；
      * 缺口 > `_CLOSE_MAX` —— 多半是整段没写完，补了只是骗过编译闸。

    出处（2026-10-28 自适应轮 k=10，`hls_polybench__fixed__small__gramschmidt`）：
    模型四轮交付的 kernel 全都把 `extern "C" {` 打开着收尾（花括号深度 +1），
    自验把编译器原文 `expected '}' ... to match this '{' extern "C" {` 逐字喂回
    四遍，一次都没补上。缺的是机械的括号，不是能靠提示词讲清的东西。
    """
    if not code or not code.strip():
        return code, 0, ""
    stack, err = _scan_delims(code)
    if err:
        return code, 0, "不补：%s" % err
    if not stack:
        return code, 0, ""
    opens = [c for c, _ in stack]
    if any(c != "{" for c in opens):
        return code, 0, "不补：未闭合的定界符里有 `(`/`[`（不是少收尾）"
    if len(opens) > _CLOSE_MAX:
        return code, 0, "不补：缺 %d 个 `}`，超过上限 %d" % (len(opens), _CLOSE_MAX)
    new = code.rstrip("\n") + "\n" + "}" * len(opens) + "\n"
    return new, len(opens), (
        "回复里 `{` 未闭合 %d 处（最内层在第 %d 行打开），已在文件末尾补上 %d 个 `}`"
        % (len(opens), stack[-1][1], len(opens)))


def signature_alias_shim(code: str, interface: str, top: str,
                         prompt: str | None = None) -> tuple[str, str]:
    """顶层函数改了名、参数表却与题目一致时，补一个转发包壳。

    返回 (新代码, 说明)。不能/不该出手时返回 ("", 原因) —— 调用方继续走原来的
    失败路径，语义不变。
    """
    if not code or not top:
        return "", "空输入"
    if not _braces_balanced(code):
        return "", "产物花括号不平衡，不追加包壳"
    text = _strip_comments_nl(code)
    if re.search(_SIG_DEF_RE % re.escape(top), text):
        return "", "`%s` 已有定义" % top

    want_raw = declared_signature(interface, top)
    if want_raw is None:
        return "", "interface 里取不到 `%s` 的声明" % top
    iface_m = re.search(_SIG_RE % re.escape(top), _strip_comments_nl(interface))
    ret_iface = _ret_type(_strip_comments_nl(interface),
                          iface_m.start()) if iface_m else None
    if ret_iface is None:
        return "", "取不到接口的返回类型"

    iface_macros = _object_macros(interface)
    code_macros = _object_macros(code)
    conflict = sorted(k for k in code_macros
                      if k in iface_macros and code_macros[k] != iface_macros[k])
    if conflict:
        return "", "产物重定义了接口宏：%s" % ", ".join(conflict)
    merged = dict(iface_macros)
    merged.update({k: v for k, v in code_macros.items() if k not in iface_macros})

    want = [_type_sig(want_raw, iface_macros)]
    for alt in declared_signatures(prompt or "", top):
        sig = _type_sig(alt, iface_macros)
        if sig not in want:                 # 题面拼法也算数（typedef 展开 vs 原拼写）
            want.append(sig)

    hits = [d for d in _function_defs(code)
            if d[1] != top and _type_sig(d[2], merged) in want]
    names = sorted({d[1] for d in hits})
    if not names:
        return "", "没有参数表等价的候选函数"
    if len(names) > 1:
        return "", "候选函数不唯一：%s" % ", ".join(names)

    ret_found, name_found, _ = hits[0]
    if ret_iface.split()[-1] != "void" and ret_found.split()[-1] == "void":
        return "", "接口返回非 void，而 %s 返回 void" % name_found

    named, args = [], []
    for raw in _split_top_level(want_raw):
        got = _name_param(raw, "p%d" % len(args))
        if got is None:
            continue
        decl, nm = got
        named.append(decl)
        args.append(nm)
    call = "%s(%s)" % (name_found, ", ".join(args))
    body = ("return %s;" % call) if ret_iface.split()[-1] != "void" else ("%s;" % call)
    wrapper = (
        "\n\n/* fix11 同名转发包壳：实现见 %s()，形参表与题目接口逐项等价。 */\n"
        "%s %s(%s)\n{\n    %s\n}\n"
        % (name_found, ret_iface, top, ", ".join(named), body))
    return code.rstrip() + "\n" + wrapper, (
        "已把 `%s` 接到 `%s`（%d 个形参，返回类型 %s）"
        % (name_found, top, len(args), ret_iface))


# --------------------------------------------------------------------- 日志摘要

# 值得再给模型看的行。一次 csynth 日志上万行，整份贴回去会挤掉代码本身、
# 把唯一要紧的那一行埋掉。
_INTERESTING = (
    "ERROR", "error:", "CRITICAL WARNING", "Unsupported", "undefined",
    "cannot", "failed", "Compiling", "Linking",
    "[HLS 200-", "[HLS 207-", "[Device 21-436]",
    "Finished", "II = ", "Latency",
)


def summarize_log(log: str, budget: int = 3000) -> str:
    """把工具日志压成模型读得动的一小段。

    匹配不到任何关键词时**回落到尾部 40 行** —— 空摘要什么信息都不给，
    而「工具没说什么能认出来的话」本身就是线索。
    """
    lines = [ln.rstrip() for ln in log.splitlines()]
    keep = [ln for ln in lines if any(k in ln for k in _INTERESTING)]
    if not keep:
        keep = lines[-40:]
    text = "\n".join(dict.fromkeys(ln for ln in keep if ln))
    if len(text) > budget:
        text = text[:budget] + "\n... [截断，还有 %d 字符]" % (len(text) - budget)
    return text
