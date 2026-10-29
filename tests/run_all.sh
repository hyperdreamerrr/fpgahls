#!/usr/bin/env bash
# 跑 HLS 智能体的全部离线守卫。**不需要 EDA、不需要模型、不需要联网。**
#
#     bash tests/run_all.sh [task_dir]
#
# ★ 负对照是这份脚本的一部分，不是「我手工验过一次」的记忆。
#   一台不会报红的仪器比没有更糟：它会一直报绿，而你在它报的绿上继续盖东西。
#   所以下面每根负对照都要求**抓住**；抓不住就 exit 1，整轮判失败。
#
# ★ 不接管道判成败。子命令的退出码单独接（此前踩过：`| tail` 会把退出码吃掉，
#   于是「崩了」与「跑完了」在终端上长得一样）。

set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
TASK="${1:-B:/fpga2026-agent/dataset/hls-eval-tasks/polybench__2mm}"

export PYTHONDONTWRITEBYTECODE=1
export PYTHONIOENCODING=utf-8
cd "$ROOT"

fails=0
run() {  # run <说明> <期望退出码> <命令...>
    local what="$1" want="$2"; shift 2
    "$@"
    local rc=$?
    if [ "$rc" -eq "$want" ]; then
        echo "  ok    $what (rc=$rc)"
    else
        echo "  FAIL  $what (rc=$rc，期望 $want)"
        fails=$((fails + 1))
    fi
}

echo "=== 1/2 单元测试（纯 Python）"
# ★ 不在这里写死条数。写死的话，加了用例它就开始说谎 ——
#   而一个说谎的守卫比没有守卫更糟（你会照着它的读数判断覆盖到了没有）。
#   条数从 unittest 自己的输出里读。
unit_out="$(python tests/test_hls_agent.py 2>&1)"
rc=$?
printf '%s\n' "$unit_out"
if [ "$rc" -eq 0 ]; then
    echo "  ok    单元测试 $(printf '%s\n' "$unit_out" | sed -n 's/^Ran \([0-9]*\) tests\?.*/\1/p' | head -1) 条"
else
    echo "  FAIL  单元测试 rc=$rc"
    fails=$((fails + 1))
fi

echo
echo "=== 2/2 读域守卫 #116（题目目录 $TASK）"
if [ ! -d "$TASK" ]; then
    echo "  FAIL  没有这个题目目录：$TASK"
    exit 1
fi

# 干净运行：必须 0 越界、0 列目录。
run "干净运行：只读三个文件" 0 \
    python tests/readscope_probe.py --task "$TASK"
# 负对照：抓不住 ⇒ 退出 2 ⇒ 这一轮报 FAIL。
run "负对照A：读测试台被抓住" 0 \
    python tests/readscope_probe.py --task "$TASK" --inject 2mm_tb.cpp
run "负对照B：读参考解被抓住" 0 \
    python tests/readscope_probe.py --task "$TASK" --inject reference/2mm.cpp
run "负对照C：不存在的名字读不动" 2 \
    python tests/readscope_probe.py --task "$TASK" --inject __no_such_file__
run "负对照D：列目录被抓住" 0 \
    python tests/readscope_probe.py --task "$TASK" --inject-list

echo
if [ "$fails" -eq 0 ]; then
    echo "全部通过。"
    exit 0
fi
echo "失败 $fails 项。"
exit 1
