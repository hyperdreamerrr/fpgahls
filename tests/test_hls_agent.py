#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HLS 智能体的单元测试。**不需要 EDA、不需要模型、不需要联网。**

    python tests/test_hls_agent.py            # 跑全部
    python -m pytest tests/test_hls_agent.py  # 也可以用 pytest

★ 每条断言都配一根**负对照**（下面对应 `# 负对照` 那几行）：改掉被测代码里的一个字面量，
  必须有且只有那一条转红。没有负对照的守卫比没有守卫更糟 —— 它会一直报绿，
  而你会在它报绿的基础上继续往上盖东西。

★ 「假绿」比「假红」危险：假红只是让你白改一次，假绿会让你带着错交出去。
  所以这里**两端都测**：该红的必须红（`[16][20]` 那一组），
  该绿的也必须绿（第一维省略那一组）—— 后者防的是**过度归一**，
  它会把一次正确的提交判成错的，然后驱动模型去改对的东西。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from agent.llm import (LLM, LLMResult, LLMSlowError, extract_blocks,  # noqa: E402
                       split_main, strip_think)
from agent.main import (_classify, _classify_base, _classify_detail,  # noqa: E402
                        _diagnosis_tail, _is_better, _kernel_ok,
                        _rule_for_error, _rule_for_param_scope,
                        _rule_for_runtime_streak,
                        _better, _empty_best,
                        BEST_KOK_EMPTY, split_interface, save_solution)
from agent.tools import (env_failure_kind, declared_signature,  # noqa: E402
                         check_signature, _norm_params, _run,
                         classify_no_exe, host_kernel_probe, param_names,
                         strip_cpp_includes, TB_SRC)

# 真实的题目接口。默认指向本机的题集；找不到就跳过依赖它的用例
# （而不是让整份测试崩掉 —— 崩掉的测试会被忽略，跳过会被看见）。
TASK_DIR = os.environ.get(
    "HLS_TEST_TASK",
    "B:/fpga2026-agent/dataset/hls-eval-tasks/polybench__2mm")


def _interface() -> str:
    p = os.path.join(TASK_DIR, "interface.txt")
    if not os.path.isfile(p):
        return ""
    with open(p, encoding="utf-8") as fh:
        return fh.read()


IFACE = _interface()
TOP = "kernel_2mm"

# 与 interface.txt 逐字一致的 kernel。下面每个用例都从它出发改一处。
KERNEL_OK = """\
#include "2mm.h"

void kernel_2mm(double alpha, double beta,
                double tmp[16][18], double A[16][22], double B[22][18],
                double C[18][24], double D[16][24]) {
  for (int i = 0; i < 16; i++)
    for (int j = 0; j < 18; j++) {
      double s = 0.0;
      for (int k = 0; k < 22; k++) s += A[i][k] * B[k][j];
      tmp[i][j] = s;
    }
}
"""


@unittest.skipUnless(IFACE, "找不到 %s/interface.txt" % TASK_DIR)
class TestSignature(unittest.TestCase):
    """闸门 1：0 秒、0 次 EDA 的那道闸。它挡住的是必落 L1 的一整类错。"""

    def test_exact_copy_passes(self):
        ok, why = check_signature(KERNEL_OK, IFACE, TOP)
        self.assertTrue(ok, why)

    # 负对照 ①：改参数类型。必须红。
    # 断言的是**消息里报出了两边**（题目要求的 vs 你写的）——
    # 只说「不一致」而不说哪儿不一致，模型就只能靠猜，然后重写整份代码。
    def test_wrong_param_type_goes_red(self):
        ok, why = check_signature(KERNEL_OK.replace("double alpha", "float alpha"),
                                  IFACE, TOP)
        self.assertFalse(ok)
        self.assertIn("float", why, "报错没说出模型写的是什么")
        self.assertIn("double", why, "报错没说出题目要求的是什么")

    # 负对照 ②：少一个参数。必须红。
    def test_dropped_param_goes_red(self):
        ok, _ = check_signature(KERNEL_OK.replace("double beta,\n", ""), IFACE, TOP)
        self.assertFalse(ok)

    # 负对照 ③：改函数名。必须红。
    def test_renamed_function_goes_red(self):
        ok, why = check_signature(KERNEL_OK.replace("kernel_2mm", "kernel_2mm_v2"),
                                  IFACE, TOP)
        self.assertFalse(ok)
        self.assertIn("找不到", why)

    # 负对照 ④ —— 这一条是我修过的那个 bug 的钉子。
    # `D[16][24]` → `D[16][20]` 改的是**尾维**，而尾维是类型的一部分
    # （形参退化成 `double (*)[24]`）。CI 会在测试台那一侧编译失败 ⇒ L1。
    # 之前的实现把每一维都抹成 `[]`，于是这个改动**看不出来** —— 一条假绿。
    def test_changed_trailing_dimension_goes_red(self):
        ok, why = check_signature(KERNEL_OK.replace("D[16][24]", "D[16][20]"),
                                  IFACE, TOP)
        self.assertFalse(ok, "尾维改了却没报红 —— 过度归一，这是假绿")
        self.assertIn("D", why)

    # 与上一条配对：第一维**可以**省略。这是真等价（数组到指针的退化），
    # 报红就是假红，会驱动模型去改一份本来正确的代码。
    def test_omitted_first_dimension_stays_green(self):
        ok, why = check_signature(
            KERNEL_OK.replace("tmp[16][18]", "tmp[][18]")
                     .replace("A[16][22]", "A[][22]")
                     .replace("B[22][18]", "B[][18]")
                     .replace("C[18][24]", "C[][24]")
                     .replace("D[16][24]", "D[][24]"),
            IFACE, TOP)
        self.assertTrue(ok, "省略第一维被报红了（假红）：%s" % why)

    # 形参名改了不该报红：测试台按**位置**调用，名字进不了链接。
    def test_renamed_parameter_stays_green(self):
        ok, why = check_signature(KERNEL_OK.replace("double alpha", "double a"),
                                  IFACE, TOP)
        self.assertTrue(ok, "只改了形参名就报红（假红）：%s" % why)

    def test_no_interface_is_not_a_failure(self):
        ok, why = check_signature("void anything() {}", "", TOP)
        self.assertTrue(ok)
        self.assertIn("跳过", why)

    def test_declared_signature_of_real_interface(self):
        sig = declared_signature(IFACE, TOP)
        self.assertIsNotNone(sig)
        self.assertIn("alpha", sig)
        self.assertEqual(len(_norm_params(sig)), 7)


# ── FIX1（PREREG 臂 G1）的钉子：每一条都对着一次**实测过的**假红/假绿，──────
#    证据落点 results/hls-agent-20261001/gate-fix1-20261004/PREREG-FIX1.md
#    与 offline-attrib-4task-20261004/NOTE-offline-attrib-4task.md。

ARK_DIR = os.environ.get(
    "HLS_TEST_ARK",
    "B:/fpga2026-agent/dataset/hls-eval-tasks/c2hlsc__add_round_key")
SMALL2MM_DIR = os.environ.get(
    "HLS_TEST_SMALL2MM",
    "B:/fpga2026-agent/dataset/hls-eval-tasks/hls_polybench__fixed__small__2mm")


def _read(path: str) -> str:
    if not os.path.isfile(path):
        return ""
    with open(path, encoding="utf-8") as fh:
        return fh.read()


ARK_IFACE = _read(os.path.join(ARK_DIR, "interface.txt"))
ARK_PROMPT = _read(os.path.join(ARK_DIR, "prompt.txt"))
S2MM_IFACE = _read(os.path.join(SMALL2MM_DIR, "interface.txt"))


@unittest.skipUnless(ARK_IFACE and ARK_PROMPT, "找不到 %s 的题面" % ARK_DIR)
class TestSignatureFix1(unittest.TestCase):
    """add_round_key 与 small-2mm：闸自己造出来的那些假红（以及一条假绿）的钉子。

    add_round_key 的 interface 声明是
    `void AddRoundKey(unsigned char, unsigned char (*)[4][4], unsigned char const *);`
    —— 三处同时在扎旧闸：`(*)` 括号截断、无名形参 `unsigned char` 被当名字剥、
    题面（prompt.txt）与 interface 是同一签名的两种拼写。官方判它 L4 的 baseline
    产物（写 `unsigned char const *RoundKey`）因此被旧闸误红 —— 这就是要钉的假红。
    """

    TOP = "AddRoundKey"

    # 与 interface.txt 逐字同拼写（baseline 那份官方 L4 产物就是这一族）
    CODE_IFACE_SPELLING = """\
#include "add_round_key.h"

void AddRoundKey(unsigned char round, unsigned char (*state)[4][4],
                 unsigned char const *RoundKey) {
  for (int i = 0; i < 4; i++)
    for (int j = 0; j < 4; j++)
      (*state)[i][j] = RoundKey[i * 4 + j];
}
"""

    def test_pointer_array_param_and_unnamed_param_pass(self):
        """(a)(b)(c)：`(*)` 不再截断、形参名剥得进括号、`unsigned char` 不被当名字。"""
        ok, why = check_signature(self.CODE_IFACE_SPELLING, ARK_IFACE, self.TOP)
        self.assertTrue(ok, "interface 原拼写被误红（#156 的三轮假红之一）：%s" % why)

    def test_const_order_is_not_a_difference(self):
        """(g)：`const unsigned char *` ≡ `unsigned char const *`（C11 6.7.2）。"""
        ok, why = check_signature(
            self.CODE_IFACE_SPELLING.replace("unsigned char const *RoundKey",
                                             "const unsigned char *RoundKey"),
            ARK_IFACE, self.TOP)
        self.assertTrue(ok, "同一类型的另一种写法被误红：%s" % why)

    def test_prompt_spelling_needs_prompt(self):
        """(e)：题面拼写（uint8_t/state_t）在**给了 prompt** 时绿、不给时必须红。

        前半是假红钉子（369 B agent 产物就是这一族）；后半是负对照 ——
        没有它，一个「什么都放行」的坏实现也能过前半条。
        """
        code = self.CODE_IFACE_SPELLING.replace(
            "unsigned char round, unsigned char (*state)[4][4],\n"
            "                 unsigned char const *RoundKey",
            "uint8_t round, state_t *state, const uint8_t *RoundKey")
        ok, why = check_signature(code, ARK_IFACE, self.TOP, ARK_PROMPT)
        self.assertTrue(ok, "题面拼写被误红：%s" % why)
        ok2, _ = check_signature(code, ARK_IFACE, self.TOP)
        self.assertFalse(ok2, "没给 prompt 也放行 —— (e) 的负对照失效")

    def test_declaration_only_goes_red(self):
        """(d)：声明柱（有原型、无函数体）必须红，且理由要点名「只有声明」。

        这是**假绿**钉子：gnnbuilder/gemm_ncubed/2mm 三份声明柱此前全过闸，
        官方判 L1 —— 假绿比假红危险，它让递交带着 undefined symbol 出去。
        """
        decl = self.CODE_IFACE_SPELLING.split("\n", 2)[2]      # 只留声明行
        decl = decl.split("{")[0].rstrip() + ";"
        ok, why = check_signature(decl, ARK_IFACE, self.TOP)
        self.assertFalse(ok, "声明柱过闸（假绿）")
        self.assertIn("只有", why)
        self.assertIn("声明", why)

    def test_same_declaration_with_body_passes(self):
        """上一条的配对正控：同一份声明**补上函数体**必须转绿。"""
        ok, why = check_signature(self.CODE_IFACE_SPELLING, ARK_IFACE, self.TOP)
        self.assertTrue(ok, why)


@unittest.skipUnless(S2MM_IFACE, "找不到 %s/interface.txt" % SMALL2MM_DIR)
class TestSignatureFix1Dims(unittest.TestCase):
    """(f)：维度数值表达式。small-2mm 的 interface 写成 `[ 40 + 0]`，模型写 `[40]`。

    两个方向都钉：数值一致必须绿（官方判 L2 的 agent 产物就是被这条误红），
    数值**不一致**必须仍红（baseline 的 `tmp[40][80]` 对 `[40][50]` 是真错，
    官方也判 L1 —— 归一不许把真错抹平）。
    """

    TOP = "kernel_2mm"

    CODE = """\
#include "2mm.h"

extern "C" {
void kernel_2mm(t_ap_fixed alpha, t_ap_fixed beta,
                t_ap_fixed tmp[40][50], t_ap_fixed A[40][70],
                t_ap_fixed B[70][50], t_ap_fixed C[50][80],
                t_ap_fixed D[40][80]) {
  for (int i = 0; i < 40; i++) { tmp[i][0] = alpha; }
}
}
"""

    def test_numeric_dim_expression_matches_plain_number(self):
        ok, why = check_signature(self.CODE, S2MM_IFACE, self.TOP)
        self.assertTrue(ok, "`[ 40 + 0]` ≡ `[40]` 没认出来（#156 的 L2 假红）：%s" % why)

    def test_wrong_dim_value_stays_red(self):
        ok, why = check_signature(self.CODE.replace("tmp[40][50]", "tmp[40][80]"),
                                  S2MM_IFACE, self.TOP)
        self.assertFalse(ok, "80≠50 的真错被归一抹平（假绿）")
        self.assertIn("tmp[][80]", why)


class TestSplitInterface(unittest.TestCase):
    """从头文件还原出「该往工作目录里放哪个名字的头文件」。

    这一件事做错**不会报错**，只会让模型 `#include` 的东西永远找不到 ——
    每一轮都死在同一个假的编译错上，环变成空转。空转是看不出来的。
    """

    # 负对照 ⑧：**文件名以数字开头**。题集里 2mm/3mm 两族共 4 题。
    # 原版正则是 `[A-Za-z_][\w.\-]*\.(?:h|hpp)`，在 `2mm.h` 上从 `m` 起匹配，
    # 得到 `mm.h` —— 一个看着完全合理、因此谁也不会怀疑的错名字。
    def test_header_name_starting_with_a_digit(self):
        iface = "// header: 2mm.h\n\n#pragma once\nvoid f();\n"
        got = split_interface(iface)
        self.assertEqual(list(got), ["2mm.h"], "首字符是数字的头文件名被截掉了")
        self.assertIn("void f();", got["2mm.h"])
        self.assertNotIn("// header:", got["2mm.h"], "注释行没被剥掉")

    def test_ordinary_header_name(self):
        got = split_interface("// header: gemm.h\n\n#pragma once\n")
        self.assertEqual(list(got), ["gemm.h"])

    def test_include_guard_fallback(self):
        got = split_interface("#ifndef FIR11_H\n#define FIR11_H\nvoid f();\n#endif\n")
        self.assertEqual(list(got), ["fir11.h"])

    def test_empty_interface_yields_nothing(self):
        self.assertEqual(split_interface(""), {})
        self.assertEqual(split_interface("   \n\n"), {})

    # 真实题目：这条是把 4 道受影响题里的那一道钉死。
    @unittest.skipUnless(IFACE, "找不到 %s/interface.txt" % TASK_DIR)
    def test_real_2mm_interface(self):
        got = split_interface(IFACE)
        self.assertEqual(list(got), ["2mm.h"])
        self.assertIn("kernel_2mm", got["2mm.h"])


class TestSplitMain(unittest.TestCase):
    """切 main。不切的话提交里就多一个 main ⇒ 与官方测试台重复定义 ⇒ L1。"""

    def test_combined_block_is_split(self):
        src = ("#include <cstdio>\n\nvoid helper() {}\n\n"
               "int main() {\n  helper();\n  return 0;\n}\n")
        kernel, tb = split_main(src)
        self.assertNotIn("int main", kernel)
        self.assertIn("int main", tb)
        self.assertIn("void helper", kernel)

    # 负对照 ⑤：注释里那句 `// int main() ...` 不是真 main。
    # 非锚定版的正则会在这里切下去，把注释以下的整段代码当成测试台 ——
    # 于是 kernel 被拦腰截断，而错误信息会指向一个根本不存在的语法问题。
    def test_main_inside_a_line_comment_is_not_a_main(self):
        src = ("// int main() is supplied by the official testbench\n"
               "void kernel_2mm() {}\n")
        kernel, tb = split_main(src)
        self.assertEqual(tb, "", "把注释里的 main 当成了真 main")
        self.assertEqual(kernel, src)

    def test_unbalanced_braces_leave_code_alone(self):
        src = "int main() {\n  for (;;) {\n"
        kernel, tb = split_main(src)
        self.assertEqual(tb, "", "括号配不上还硬切")
        self.assertEqual(kernel, src)

    def test_no_main_returns_unchanged(self):
        src = "void f() {}\n"
        self.assertEqual(split_main(src), (src, ""))

    def test_braces_inside_strings_do_not_confuse_it(self):
        src = ('#include <cstdio>\nint main() {\n  printf("}{");\n  return 0;\n}\n'
               'void after() {}\n')
        kernel, tb = split_main(src)
        self.assertIn("void after", kernel, "字符串里的花括号把自己配平了")
        self.assertNotIn("after", tb)


class TestExtractBlocks(unittest.TestCase):
    """抽码。模型的围栏标签千奇百怪，顺序也不定，所以判别靠结构不靠标签。"""

    TWO = ("here you go\n\n```cpp\nvoid kernel_2mm(double a) {}\n```\n\n"
           "and the testbench\n\n```cpp\nint main() { return 0; }\n```\n")

    KERNEL = '```cpp\n#include "2mm.h"\nvoid kernel_2mm(double a) { (void)a; }\n```\n'

    # 差分测试台（system.md 要求的形状）：自带一份参考实现，用**同一组输入**
    # 跑两边再比对。它比 kernel 长得多，而且**它自己也要调用 `kernel_2mm(`**。
    TB_THAT_CALLS_KERNEL = (
        "```cpp\n#include <cstdio>\n#include \"2mm.h\"\n\n"
        "static void ref_kernel_2mm(double a) { (void)a; }\n\n"
        "int main() {\n"
        "    double a[64];\n"
        "    for (int i = 0; i < 64; ++i) a[i] = i * 0.5 + 1.0;\n"
        "    kernel_2mm(a[0]);\n"
        "    ref_kernel_2mm(a[1]);\n"
        "    printf(\"first %f %f\\n\", a[0], a[1]);\n"
        "    return 0;\n}\n```\n")

    def test_two_blocks_kernel_then_tb(self):
        k, tb, _ = extract_blocks(self.TWO, TOP)
        self.assertIn("void kernel_2mm", k)
        self.assertNotIn("main", k)
        self.assertIn("int main", tb)

    # 顺序不定：测试台写在前面也必须认出来。
    def test_testbench_first_is_still_recognised(self):
        text = ("```cpp\nint main() { return 0; }\n```\n\n"
                "```cpp\nvoid kernel_2mm(double a) {}\n```\n")
        k, tb, _ = extract_blocks(text, TOP)
        self.assertIn("void kernel_2mm", k)
        self.assertIn("int main", tb)

    def test_single_combined_block_is_split(self):
        text = "```cpp\n#include <cstdio>\nvoid kernel_2mm(double a) {}\nint main() { return 0; }\n```\n"
        k, tb, note = extract_blocks(text, TOP)
        self.assertIn("void kernel_2mm", k)
        self.assertNotIn("int main", k, "合并块没有把 main 切出去")
        self.assertIn("main", tb)
        self.assertIn("切", note)

    # 只有 kernel 时不能瞎编一个测试台出来 —— extract 返回空 tb，
    # main.py 据此**不花 EDA** 并去要测试台。编一个空测试台会伪造一次
    # 「自验通过」：桩测试台必然 return 0，于是 L3 被凭空报出来。
    # 这里不断言提示词的措辞（那是 main.py 的事，改了措辞不该让这条红）；
    # 只钉住契约：**tb 必须是空的**。
    def test_kernel_only_yields_empty_tb(self):
        k, tb, _ = extract_blocks("```cpp\nvoid kernel_2mm(double a) {}\n```\n", TOP)
        self.assertIn("void kernel_2mm", k)
        self.assertEqual(tb, "", "只有 kernel 时凭空造出了测试台")

    def test_no_fences_but_looks_like_code(self):
        k, tb, note = extract_blocks(
            "#include \"2mm.h\"\nvoid kernel_2mm(double a) {}\n", TOP)
        self.assertIn("kernel_2mm", k)
        self.assertIn("没有代码围栏", note)

    def test_garbage_yields_nothing(self):
        k, tb, note = extract_blocks("I cannot help with that request.", TOP)
        self.assertEqual(k, "")
        self.assertEqual(tb, "")
        self.assertIn("没取到任何代码", note)

    # ★ 纯注释「块」不算代码。真实形状，逐字取自
    #   results/agent-fix4-20261025/pair20-fix4-20261025/agent/out/
    #   machsuite__aes_aes/trace.jsonl r1 的 `raw_excerpt` 开头三行：
    #   模型连开两个围栏，`_FENCE` 非贪婪配对把前三行配成块（17 B 的
    #   `// kernel block 1`），真正的代码在第二个**未闭合**围栏之后。
    #   旧行为：17 B 注释当 kernel 交出去 ⇒ 签名闸「找不到定义」⇒
    #   修复提示把 `// kernel block 1` 当成模型上一版的内核 ⇒ 后两轮只回散文。
    #   终局 L1。这条钉的是：**拿回来的必须是那段真代码**。
    AES_DOUBLED_FENCE = (
        "```cpp\n// kernel block 1\n```cpp\n"
        "#include \"aes_aes.h\"\n#include <stdint.h>\n\n"
        "static const uint8_t sbox[256] = {0x63, 0x7c};\n"
        "void aes256_encrypt_ecb(aes256_ctx *ctx) {\n"
        "    uint8_t s[4][4];\n"
        "    for (int i = 0; i < 4; ++i)\n"
        "        for (int j = 0; j < 4; ++j) s[i][j] = 0;\n"
        "    (void)sbox;\n"
        "    // ... 被 max_tokens 截断在这里\n")

    def test_comment_only_block_does_not_beat_the_real_tail(self):
        k, _tb, note = extract_blocks(self.AES_DOUBLED_FENCE, "aes256_encrypt_ecb")
        self.assertNotEqual(k.strip(), "// kernel block 1",
                            "17 B 的注释块又被当成 kernel 了")
        self.assertIn("aes256_encrypt_ecb", k, "第二个未闭合围栏之后的真代码没有取回来")
        self.assertIn("#include", k)
        self.assertIn("围栏", note)

    # 负对照：正常的、含代码的块不受这道闸影响（不许为了修上面那条
    # 把「块里带注释」也一起判掉）。
    def test_block_with_leading_comment_is_still_code(self):
        text = "```cpp\n// kernel block 1\nvoid kernel_2mm(double a) { (void)a; }\n```\n"
        k, _tb, _note = extract_blocks(text, TOP)
        self.assertIn("// kernel block 1", k)
        self.assertIn("void kernel_2mm", k)

    # ★ 试点的真实形状（逐字取自存档回复
    #   results/hls-agent-20261001/pilot-diag-rawreply/chstone__df_add128/attempt5）：
    #   两块 —— kernel 265 B（无 main、含 1 次 `add128(`），测试台 1111 B。
    #   关键在测试台**更长**，而且**它自己也要调用 kernel**（差分测试台里
    #   有参考实现 + 遍历用例，这是 system.md 明确要求的形状）。
    #   于是「含 `top(`」这条判据两块都命中，`max(named, key=len)` 每次都选中测试台；
    #   再被 split_main 切掉 main，剩下的是**一次 `top(` 都没有的残渣** ⇒
    #   签名闸报「找不到定义」⇒ 一份好端端的 265 B kernel 被自己的抽取器扔了。
    #   这不是合成用例：试点 3 题全 0 字节，这条是主因。
    def test_longer_testbench_that_calls_kernel_does_not_win(self):
        text = self.KERNEL + "\n" + self.TB_THAT_CALLS_KERNEL
        k, tb, _ = extract_blocks(text, TOP)
        self.assertIn("void kernel_2mm", k, "更长的测试台把 kernel 抢走了")
        self.assertNotIn("ref_kernel_2mm", k, "把测试台里的参考实现当成了 kernel")
        self.assertIn("int main", tb)

    # 负对照：测试台更长但**不含** `top(`（既有形状）—— 必须仍然选 kernel。
    # 这条在改动前后都该绿；它挡的是「为了修上面那条，把选择规则改成按 main 一刀切」。
    def test_long_testbench_without_the_name_still_yields_kernel(self):
        text = (self.KERNEL + "\n```cpp\n#include <cstdio>\nint main() {\n"
                "    double a[64] = {0};\n"
                "    for (int i = 0; i < 64; ++i) { a[i] = i; }\n"
                "    printf(\"%f\\n\", a[0]);\n"
                "    return 0;\n}\n```\n")
        k, tb, _ = extract_blocks(text, TOP)
        self.assertIn("void kernel_2mm", k)
        self.assertIn("int main", tb)


class TestEnvFailureKind(unittest.TestCase):
    """环境故障 vs 设计故障。**判错方向比漏判更贵**：
    把环境故障讲成编译失败，模型就会去改一份本来正确的代码。"""

    # 负对照 ⑥：判定器 2026.1 实测采集的原文（hls-judge 的注释里逐字留着）。
    # 注意它同时含「器件不受支持」那句极具误导性的话 —— 判别必须认出来。
    def test_real_license_text_is_detected(self):
        log = ("ERROR: Vivado Design Suite cannot be launched because a valid license\n"
               "       was not found.\n"
               "ERROR: [HLS 200-1023] Part 'xczu3eg-sbva484-1-e' is not supported.\n"
               "       It is either unknown, not installed or does not have an\n"
               "       appropriate license.\n")
        self.assertEqual(env_failure_kind(log), "license")

    def test_timeout_marker_is_detected(self):
        self.assertEqual(env_failure_kind("[agent] vitis-run timed out after 120s"),
                         "timeout")

    def test_timeout_wins_over_license_when_both_present(self):
        # 超时那一路会把工具输出整个丢掉、只回这一句，两者不可能真同时出现；
        # 万一同时出现，超时是更靠近事实的那条。
        log = ("[agent] v++ timed out after 60s\n"
               "valid license was not found\n")
        self.assertEqual(env_failure_kind(log), "timeout")

    # 负对照 ⑦：一条普通的编译错误**必须**返回 None。
    # 若它也返回非 None，模型永远收不到真诊断，整个环变成空转。
    def test_ordinary_compile_error_is_not_an_env_failure(self):
        log = ("ERROR: [HLS 214-157] 'x' is not a member of 'std'\n"
               "INFO: [HLS 200-10] Compiling kernel.cpp\n")
        self.assertIsNone(env_failure_kind(log))

    def test_unknown_error_is_not_an_env_failure(self):
        self.assertIsNone(env_failure_kind("ERROR: [HLS 200-70] something broke\n"))


class TestClassifyNoExe(unittest.TestCase):
    """`csim.exe` 没生成时的有序判定（#153）。

    ★ 判据本体是 `classify_no_exe()` —— 与 `csim()` 走的是**同一份**函数；
      这里不另抄判据，抄的那份迟早与它漂开（「匹配到 0 件的 glob 与成功的搜索
      长得一样」）。下面所有日志行都是**归档产物逐字**：
      `results/hls-agent-20261001/online-rescue-20261003/<task>/out/agent/*/s0/trace.jsonl`
      的 selfcheck `excerpt`（2026-10-03 补跑，4 题同型）。

    方向性：「TB 编译错」记成环境故障 ⇒ 环停机交白卷（#153 的病灶）；
    记成 kernel 错 ⇒ 模型去改一份本来正确的实现。两个方向都贵，所以两支都要有
    负对照把边界钉住。
    """

    SRC = "kernel.cpp"

    @staticmethod
    def _log(error_lines, extra=""):
        """真实日志的骨架（行文逐字取自归档），错误行由各用例给。"""
        return (
            "INFO: [HLS 200-1510] Running: add_files -cflags -I. -std=c++14 kernel.cpp\n"
            "INFO: [HLS 200-10] Adding design file 'kernel.cpp' to the project\n"
            "INFO: [HLS 200-1510] Running: add_files -tb -cflags -I. -std=c++14 agent_tb.cpp\n"
            "INFO: [HLS 200-10] Adding test bench file 'agent_tb.cpp' to the project\n"
            "INFO: [HLS 200-1510] Running: csim_design -setup\n"
            "INFO: [HLS 200-2191] C-Simulation will use clang-16 as the compiler\n"
            "INFO: [HLS 200-2036] Building debug C Simulation binaries\n"
            "   Compiling ../../../../agent_tb.cpp in debug mode\n"
            + error_lines + extra +
            "ERROR: [SIM 211-100] CSim file generation failed: compilation error(s).\n")

    #: 4 题归档错误行，逐字。kernel 全都没编到（日志里没有 `Compiling kernel.cpp`）。
    ARCHIVED = {
        "fgnn_linear": (
            "../../../../agent_tb.cpp:6:15: error: expected unqualified-id\n"
            "../../../../agent_tb.cpp:7:15: error: expected unqualified-id\n"
            "../../../../agent_tb.cpp:8:15: error: expected unqualified-id\n"
            "../../../../agent_tb.cpp:9:15: error: expected unqualified-id\n"),
        "2mm": ("../../../../agent_tb.cpp:65:17: error: call to 'abs' is ambiguous\n"),
        "gramschmidt": (
            "../../../../agent_tb.cpp:19:54: error: use of overloaded operator '/' is ambiguous"
            " (with operand types 't_ap_fixed' (aka 'ap_fixed<32, 16>') and 'double')\n"
            "../../../../agent_tb.cpp:48:41: error: use of overloaded operator '*' is ambiguous"
            " (with operand types 'double' and 't_ap_fixed' (aka 'ap_fixed<32, 16>'))\n"),
    }

    def test_archived_tb_errors_go_to_testbench_compile(self):
        for name, errs in self.ARCHIVED.items():
            with self.subTest(task=name):
                got = classify_no_exe(self._log(errs), self.SRC)
                self.assertEqual(got.get("kind"), "testbench-compile", name)
                self.assertIsNone(got.get("env"), "%s：TB 错被判成了环境故障" % name)
                self.assertIsNone(got.get("level"), "%s：TB 错被判成了 kernel 的 level" % name)
                self.assertIn(errs.splitlines()[0], got.get("note", ""), name)

    # 负对照 ⑩：**kernel 编到了**的日志不归这一支 —— 那时 `Compiling <src>` 在场，
    # 已有 level=1 的诊断在用，新支不许抢。
    def test_kernel_compiled_stays_level1(self):
        out = self._log(
            "../../../../agent_tb.cpp:9:15: error: expected unqualified-id\n",
            extra="INFO: [HLS 200-10] Compiling kernel.cpp\n")
        got = classify_no_exe(out, self.SRC)
        self.assertEqual(got.get("level"), 1)
        self.assertIsNone(got.get("kind"), "kernel 编到了还被记成 testbench-compile")

    # 负对照 ⑪：真 fixture 仍落 env=fixture —— 不许被新支吞掉。
    # ★ fix8（2026-10-25）改了这条控制的**前提**，改动本身有据：`_log()` 末尾恒定
    #   带一句 `ERROR: [SIM 211-100] CSim file generation failed: compilation
    #   error(s).`，而那句话自述的是「构建**跑到了**并失败了」——与环境故障是两回事。
    #   fix8 改动 B 正是把「有这句话、却没有任何指向源码的诊断」从 fixture 里分出来
    #   （kind=build-unlocalized）。所以真 fixture 的控制必须是不含这句话的形状：
    #   csim 根本没走到构建那一步。
    def test_fixture_without_build_failure_stays_fixture(self):
        out = ("INFO: [HLS 200-1510] Running: csim_design -setup\n"
               "ERROR: [HLS 200-70] something in the fixture broke\n")
        got = classify_no_exe(out, self.SRC)
        self.assertEqual(got.get("env"), "fixture")
        self.assertIsNone(got.get("kind"))

    # 负对照 ⑫：授权故障与 TB 错误行同时在场 ⇒ 环境优先（顺序是语义的一部分：
    # 拿不到授权时后续一切诊断都不可信，更不该去指挥模型改测试台）。
    def test_license_beats_tb_errors(self):
        out = self._log(
            "../../../../agent_tb.cpp:6:15: error: expected unqualified-id\n",
            extra="ERROR: Vivado Design Suite cannot be launched because a valid license\n"
                  "       was not found.\n")
        got = classify_no_exe(out, self.SRC)
        self.assertEqual(got.get("env"), "license")
        self.assertIsNone(got.get("kind"))


class TestClassify(unittest.TestCase):
    """把自验结果翻成**给模型看的失败类别**。

    分类不是修辞：不同的类别要走不同的修法。分类错了，模型就会去改一份
    本来正确的东西 —— 而且改完还看不出来，因为下一轮的报错换了一个样子。
    """

    def _sc(self, **kw):
        sc = {"level": 2, "env": None, "rc": 1, "note": "", "log": "", "stages": {}}
        sc.update(kw)
        return sc

    def test_plain_level2_blames_the_algorithm(self):
        out = _classify(2, self._sc(note="mismatches: 3"))
        self.assertIn("算法", out)

    # 负对照 ⑨：测试台**跑不完**时，绝不能套用 level=2 那句「算法或边界错了」。
    # 那句话是一道明确的指令，模型会照做 —— 然后重写一份本来就对的 kernel。
    def test_testbench_timeout_does_not_blame_the_algorithm(self):
        out = _classify(2, self._sc(kind="testbench-timeout",
                                    note="测试台运行没跑完"))
        self.assertIn("测试台", out)
        self.assertNotIn("算法或边界错", out,
                         "测试台死循环被讲成了算法错 —— 模型会去改 kernel")

    def test_level0_and_1_and_none(self):
        self.assertIn("不可解析", _classify(0, self._sc()))
        self.assertIn("编不到一起", _classify(1, self._sc()))
        self.assertIn("没能给出", _classify(None, self._sc()))

    # #153：TB 编译错的反馈必须指向**测试台**。这是环里唯一能把这轮救回来的
    # 一句话 —— 说成「算法或边界错了」，模型就会去重写一份本来正确的 kernel。
    def test_testbench_compile_does_not_blame_the_algorithm(self):
        out = _classify(None, self._sc(kind="testbench-compile",
                                       note="agent_tb.cpp:6:15: error: ..."))
        self.assertIn("测试台", out)
        self.assertNotIn("算法或边界错", out,
                         "TB 编译错被讲成了算法错 —— 模型会去改 kernel")


class TestFix7GiveBackTheEvidence(unittest.TestCase):
    """fix7（2026-10-25）：**把已经拿到、却没交出去的失败证据交出去**。

    病灶逐字来自 `results/agent-fix5-20261025/pair20-fix5b-20261025/agent/out/*/trace.jsonl`
    （普查仪器 `tmp/census_logloss.py`：52 轮自验里 12 轮的诊断文本只落在 trace 里）。

    这一组测试的意义在于**两端都钉**：交出去的必须是新信息（`_classify` 里没有），
    已经说过的必须**不重复**（重复只会挤掉预算），不相关的错误必须**一个字都不加**
    —— 否则改动会在整块面板上从「补充证据」变成「加噪」。

    ★ 引号那条是真踩过的坑：归档里 g++ 用的是排版引号 ``‘’``，而按 ASCII ``'`` 写的
      正则在本面板上**一次都不会命中**，而「命中 0 次」与「全部命中」在单测里
      长得一模一样 —— 只有拿归档原文跑一遍才看得出来。
    """

    #: `tools.py:499-501` 的 note 头（逐字）。
    HEAD = ("待测源码**自己编不过**（宿主 g++ 的编译原文指着 kernel.cpp）——"
            "先照原文改这一处，不要整份重写：")

    #: `c2hlsc__add_round_key` r1 的 note 正文（逐字，含排版引号与 {aka}）。
    ADD_ROUND_KEY = (
        "kernel.cpp:9:25: error: invalid operands of types ‘uint8_t [4]’ "
        "{aka ‘unsigned char [4]’} and ‘uint8_t’ {aka ‘unsigned char’} "
        "to binary ‘operator^’")

    #: `machsuite__sort_radix` r2 的 note 正文（逐字；r2–r4 都是这条形状）。
    SORT_RADIX = ("kernel.cpp:85:15: error: invalid operands of types ‘int*’ "
                  "and ‘int*’ to binary ‘operator^’")

    @staticmethod
    def _sc(**kw):
        sc = {"level": 2, "env": None, "rc": 1, "kind": None,
              "note": "", "log": "", "stages": {}}
        sc.update(kw)
        return sc

    # ---------------------------------------------------------------- 改动 A
    def test_level2_carries_what_the_testbench_printed(self):
        """`polybench__doitgen` r2 逐字：模型自己的测试台早就说了下标错位。"""
        line = "Mismatch at [0][0][1]: kernel=12167 ref=6084"
        sc = self._sc(note="测试台返回非零退出码 1 —— 功能不对", log=line)
        facts, text = _classify_detail(2, sc)
        self.assertIn(line, text)
        self.assertGreater(facts["add_log_bytes"], 0)
        # 负对照：证明这**确实是新信息** —— 拿 fix7 **之前**的那段文本
        # （`_classify_base`，逐字保留）比，那里没有它。
        self.assertNotIn(line, _classify_base(2, sc),
                         "诊断文本本来就在原文里 ⇒ 改动 A 是空转")

    def test_no_duplication_of_what_the_note_already_says(self):
        """note 里已经逐字有的行不许再说一遍（重复只挤预算）。

        负对照：把同一行从 note 里拿掉，它就必须被交出去（上一条）；
        留在 note 里就必须全文一个字都不加。
        """
        line = "Mismatch at [0][0][1]: kernel=12167 ref=6084"
        sc = self._sc(note="测试台返回非零退出码 1 —— 功能不对\n" + line, log=line)
        facts, text = _classify_detail(2, sc)
        self.assertNotIn("add_log_bytes", facts)
        self.assertEqual(text, _classify(2, sc), "已经说过的内容被重复追加了")

    def test_negative_rc_explains_the_signal(self):
        """`machsuite__sort_radix` 逐字：rc=-11、日志**为空**。

        日志空时唯一的证据就是信号本身 —— 而原来那一句只说「返回非零退出码 -11」，
        模型没法知道 -11 是什么。
        """
        sc = self._sc(rc=-11, note="测试台返回非零退出码 -11 —— 功能不对", log="")
        facts, text = _classify_detail(2, sc)
        self.assertIn("SIGSEGV", text)
        self.assertGreater(facts["add_log_bytes"], 0)
        self.assertNotIn("SIGSEGV", _classify_base(2, sc))    # 负对照

    def test_positive_rc_gets_no_signal_line(self):
        """rc>0 是**程序自己退出**，不是被杀 —— 不许套用信号解释（会指向错的方向）。"""
        self.assertEqual(_diagnosis_tail(self._sc(rc=1, log=""), ""), "")

    def test_level1_gets_no_log_tail(self):
        """level 1 的编译器原文**已经**在 note 里（`kdiag[:5]`）—— 重复无益。"""
        sc = self._sc(level=1, kind="kernel-compile",
                      note=self.HEAD + "\n" + self.ADD_ROUND_KEY,
                      log=self.ADD_ROUND_KEY)
        facts, _text = _classify_detail(1, sc)
        self.assertNotIn("add_log_bytes", facts)

    # ---------------------------------------------------------------- 改动 B
    def test_rule_names_the_array_bitop(self):
        """`c2hlsc__add_round_key` r1/r2/r3/r4 逐字：数组整体 XOR，四轮不改想法。"""
        rule, text = _rule_for_error(self.HEAD + "\n" + self.ADD_ROUND_KEY)
        self.assertEqual(rule, "array-bitop")
        self.assertIn("不能整体做位运算", text)
        self.assertIn("按下标循环", text)
        # 规则里不许出现题目名/顶层函数名（反硬编码口径 V6）。
        self.assertNotIn("add_round_key", text)

    def test_rule_names_the_pointer_bitop(self):
        """`machsuite__sort_radix` r2 逐字：两个 `int*` 直接 XOR。"""
        rule, text = _rule_for_error(self.HEAD + "\n" + self.SORT_RADIX)
        self.assertEqual(rule, "array-bitop")
        self.assertIn("指针", text)

    def test_rule_matches_ascii_quotes_too(self):
        """C locale 下 g++ 打 ASCII 引号；两套引号都要认。

        负对照：删掉正则里任一-套引号，这一条或上一条必然转红。
        """
        ascii_form = ("kernel.cpp:9:25: error: invalid operands of types "
                      "'uint8_t [4]' and 'uint8_t' to binary 'operator^'")
        self.assertEqual(_rule_for_error(ascii_form)[0], "array-bitop")

    def test_rule_is_silent_on_scalar_operands(self):
        """**标量**类型不匹配不是「数组整体运算」—— 加那句话会把模型带偏。"""
        scalar = ("kernel.cpp:12:9: error: invalid operands of types 'float' "
                  "and 'int' to binary 'operator&'")
        self.assertEqual(_rule_for_error(scalar), ("", ""))

    def test_rule_is_silent_on_unrelated_errors(self):
        for note in ("kernel.cpp:3:1: error: unknown type name 'ap_int'",
                     "kernel.cpp:7:5: error: expected ';' before '}' token",
                     ""):
            self.assertEqual(_rule_for_error(note), ("", ""), note)

    def test_rule_only_fires_on_kernel_compile_rounds(self):
        """同一条原文落在 level 2（运行错）时不许追加编译规则 —— 那一轮的错不是它。"""
        sc = self._sc(level=2, kind=None, log="",
                      note=self.HEAD + "\n" + self.ADD_ROUND_KEY)
        facts, _text = _classify_detail(2, sc)
        self.assertEqual(facts.get("rule", ""), "")

    # ----------------------------------------------------------- 文本不分叉
    def test_classify_is_a_thin_wrapper(self):
        """`_classify()` 与 `_classify_detail()[1]` 必须逐字相同。

        负对照：两处各算一遍文本、只改其中一处的字面量 ⇒ 这里转红。
        """
        cases = [
            self._sc(note="mismatches: 3", log="Mismatch at [0]: 1 2"),
            self._sc(kind="testbench-timeout", note="测试台运行没跑完", log="loop"),
            self._sc(level=1, kind="kernel-compile",
                     note=self.HEAD + "\n" + self.SORT_RADIX, log=self.SORT_RADIX),
            self._sc(level=0, note="parse error", log=""),
            self._sc(level=None, kind="testbench-compile", note="tb err", log=""),
        ]
        for sc in cases:
            _facts, text = _classify_detail(sc["level"], sc)
            self.assertEqual(text, _classify(sc["level"], sc))


class TestFix7FactsCannotGoStale(unittest.TestCase):
    """`last_facts` 必须与 `last_log` **同一次赋值**。

    行使计数是归因的唯一依据：若某处只改 `last_log` 而不改 `last_facts`，
    下一轮 `repair-log` 就会给一段与事实无关的文本记上上一轮的 `tbl=true`
    —— trace 里看不出来，只会让归因表凭空多出几个「C 命中」。

    这里是**源码级守卫**（结构断言，不是行为断言）：`solve()` 里已经收成
    唯一入口 `_set_repair()`，这条测试防的是以后有人再加一个裸赋值。
    """

    def test_no_bare_assignment_of_last_log(self):
        path = os.path.join(ROOT, "agent", "main.py")
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        bad = []
        for i, ln in enumerate(lines, 1):
            s = ln.strip()
            if not (s.startswith("last_log") or s.startswith("last_kind")):
                continue
            if "=" not in s:
                continue
            if s == 'last_log, last_kind = "", ""':        # 循环前的初值
                continue
            if "last_facts" in s:                          # `_set_repair` 本体
                continue
            bad.append("%d: %s" % (i, s))
        self.assertEqual(bad, [],
                         "有裸赋值绕过了 `_set_repair()`（行使事实会与文本漂开）")


class TestIsBetter(unittest.TestCase):
    """兜底阶梯的比较器。`solve()` 的每一次「存不存」都问它。#153 的 A 支
    （env 停机前存 level 0）正落在这条语义上。"""

    def test_higher_level_replaces(self):
        self.assertTrue(_is_better(2, 0))
        self.assertTrue(_is_better(0, -2))
        self.assertTrue(_is_better(0, -3))

    def test_same_level_does_not_replace(self):
        # 同等级不替换 —— 先到的那份已经验过，新的还没验。
        self.assertFalse(_is_better(0, 0))

    def test_lower_level_never_replaces(self):
        self.assertFalse(_is_better(0, 2))
        self.assertFalse(_is_better(-2, 0))


class TestKernelOk(unittest.TestCase):
    """fix5 改动 A 的三值证据。**两种失败形状各自有单测**：
    宿主体检报 fail / Vitis 报 kernel 编不过（`kind=kernel-compile`，
    `kernel_check` 可能是 `skipped`）—— 后者是审计口径漏掉的那一例。"""

    def _sc(self, kc=None, kind=None):
        sc = {"kind": kind, "kernel_check": kc}
        return sc

    def test_probe_ok_is_plus_one(self):
        self.assertEqual(_kernel_ok(self._sc({"status": "ok"}), None), 1)
        # level 也可能同时给 1（自写 TB 编不过），但 kernel 编得过就是 +1
        self.assertEqual(_kernel_ok(self._sc({"status": "ok"}), 1), 1)

    def test_probe_fail_is_minus_one(self):
        self.assertEqual(_kernel_ok(self._sc({"status": "fail"}), None), -1)

    def test_kernel_compile_kind_wins_over_skipped_probe(self):
        # ★ 2mm 那一例：宿主缺 ap_int.h ⇒ probe=skipped，但 Vitis 把 kernel
        #   判成编不过 ⇒ kind=kernel-compile。必须给 -1，否则它压不过 r1。
        self.assertEqual(
            _kernel_ok(self._sc({"status": "skipped"}, kind="kernel-compile"), 1),
            -1)

    def test_level_2_or_more_is_plus_one(self):
        # Vitis 自己把 kernel 编出来了 —— 比宿主体检更强的证据。
        self.assertEqual(_kernel_ok(self._sc({"status": "skipped"}), 2), 1)
        self.assertEqual(_kernel_ok(self._sc(None), 4), 1)

    def test_no_evidence_is_zero(self):
        # TB 编不过、宿主又没参加体检：既不给正面也不给反面证据。
        self.assertEqual(
            _kernel_ok(self._sc({"status": "skipped"}, kind="testbench-compile"), None), 0)
        self.assertEqual(_kernel_ok(self._sc(None, kind="parse"), None), 0)


class TestBetter(unittest.TestCase):
    """fix5 的选材偏序 `(kernel 自己编得过?, 自验等级)`。

    **两条逆序各有一个用例**（`results/agent-fix5-20261025/PREREG.md` §1）：
    只比等级时 `1 > 0`，交出去的是一份**已被证明编不过**的源码。"""

    def test_kernel_ok_beats_higher_level(self):
        # §1.1 add_round_key：r2 (kok=+1, level 0) 必须压过 r1 (kok=-1, level 1)
        self.assertTrue(_better(0, 1, 1, -1))
        # §1.2 2mm：r2 (kok=0, level 0) 也必须压过 r1 (kok=-1, level 1)
        self.assertTrue(_better(0, 0, 1, -1))

    def test_known_bad_never_replaces_better_evidence(self):
        # 反向：编不过的那份压不过任何非负证据 —— 这正是 fix5 要防的
        self.assertFalse(_better(1, -1, 0, 0))
        self.assertFalse(_better(1, -1, 0, 1))

    def test_same_kok_falls_back_to_level(self):
        self.assertTrue(_better(2, 0, 1, 0))
        self.assertFalse(_better(1, 0, 2, 0))
        self.assertTrue(_better(0, 1, -2, 1))

    def test_identical_does_not_replace(self):
        self.assertFalse(_better(0, 0, 0, 0))
        self.assertFalse(_better(-2, 1, -2, 1))

    def test_empty_state_loses_to_every_real_candidate(self):
        """★ fix5b 回归锁：空手（best_level=-3, best_kok=-2）必须输给**任何**真候选。

        病：fix5 首跑把 `best_kok` 初值写成 0（=「没有证据」），于是
        `_better(1, -1, -3, 0)` 为 False —— `-1 > 0` 不成立 —— 全轮 `kernel-compile`
        的题**一份都存不下**，`solution.cpp` 写 0 字节，判词 L0。
        实测：`c2hlsc__add_round_key` 2026-10-24T22:45Z，4 轮全 `kind=kernel-compile`，
        `sol=e3b0c44298fc1c14`（0 B），agent L0；fix4 同题 L1。
        候选格 = kok 三值 × 各自可能的最低等级。锁的是 `_empty_best()` 而不是字面量，
        所以把常量改回 0 也会红。
        """
        _, elvl, _, ekok = _empty_best()
        self.assertEqual(ekok, BEST_KOK_EMPTY)
        grid = [(1, -1), (-2, -1), (0, 0), (-2, 0), (0, 1), (4, 1)]
        for lvl, kok in grid:
            self.assertTrue(_better(lvl, kok, elvl, ekok), (lvl, kok))
            self.assertFalse(_better(elvl, ekok, lvl, kok), (lvl, kok))

    def test_ordering_is_transitive_on_the_prereg_grid(self):
        # 偏序全序化后的格：(+1,L4) > (+1,L0) > (0,L3) > (0,L0) > (-1,L4) > (-1,L1)
        grid = [(4, 1), (0, 1), (3, 0), (0, 0), (4, -1), (1, -1)]
        for i in range(len(grid) - 1):
            hi_l, hi_k = grid[i]
            lo_l, lo_k = grid[i + 1]
            self.assertTrue(_better(hi_l, hi_k, lo_l, lo_k), (hi_l, hi_k, lo_l, lo_k))
            self.assertFalse(_better(lo_l, lo_k, hi_l, hi_k), (lo_l, lo_k, hi_l, hi_k))


class TestRoundBudget(unittest.TestCase):
    """fix5 改动 B：轮次预算 3 → 4（`results/agent-fix5-20261025/PREREG.md` §3）。

    默认值是一份**被预登记的承诺**：fix4 面板里有 8 题把 3 轮全用尽仍停在 L1/L2，
    其中 `sort_radix` 三轮给了三份不同的 kernel（在逼近、没到时）。当成常量钉住，
    改它就得先改 PREREG。env 覆盖是给探针用的，不算进这条。"""

    def test_default_budget_is_four(self):
        import agent.main as m
        if os.environ.get("AGENT_MAX_ROUNDS"):
            self.skipTest("env 覆盖在场，默认值不可观测")
        self.assertEqual(m.MAX_ROUNDS, 4, "轮次预算不是预登记的 4")


class TestRunSemantics(unittest.TestCase):
    """`_run` 的三种返回码。把它们的含义搞混，就会把环境故障讲成设计错误。"""

    def test_launch_failure_is_minus_one(self):
        rc, out = _run(["__no_such_executable_anywhere__"], os.getcwd(), 5.0)
        self.assertEqual(rc, -1, "起不来必须是 -1，不能混成别的码")
        self.assertIn("could not launch", out)

    def test_normal_command_returns_its_exit_code(self):
        rc, _ = _run([sys.executable, "-c", "raise SystemExit(3)"], os.getcwd(), 30.0)
        self.assertEqual(rc, 3)

    def test_timeout_is_124_and_never_negative(self):
        rc, out = _run([sys.executable, "-c", "import time; time.sleep(30)"],
                       os.getcwd(), 2.0)
        self.assertEqual(rc, 124)
        self.assertIn("timed out", out)


class _StubLLM:
    """按脚本逐轮回话的假 LLM。不联网、不花时间。"""

    #: `solve()` 会读它当**硬上限**（`plan_round(..., llm.max_tokens)`）——
    #: 真 `LLM.__init__` 里也有这个属性，桩要把接口补齐，否则测的不是真路径。
    max_tokens = 8192

    def __init__(self, replies):
        # 只给一段文本也行（默认 finish_reason="stop"）；要演截断就给 (text, "length")。
        self.replies = [(r, "stop") if isinstance(r, str) else tuple(r)
                        for r in replies]
        self.rounds = 0
        # ★ 把每轮**实际收到的帽**记下来（#143 §3.6）。`solve()` 现在逐轮传
        #   `max_tokens=`，不给它记一列，就无法分辨「传了 8192」与「没传」。
        self.caps = []
        #: 每轮实际收到的 messages —— 用来验**反馈话真的送到模型面前了**
        #: （#153：TB 编译错那轮之后，下一轮的话必须指着测试台）。
        self.seen = []

    def chat(self, messages, budget_s=0.0, max_tokens=None):
        self.rounds += 1
        self.caps.append(max_tokens)
        self.seen.append(messages)
        text, finish = self.replies.pop(0) if self.replies else ("", "stop")
        return LLMResult(text, tokens_in=1, tokens_out=10, finish_reason=finish)


class _StubHls:
    """替代 HlsToolchain：**一次 EDA 都不跑**。csim 固定返回「编译不过」。

    它只负责让 `solve()` 走到「拿到了关于设计的结论」那一支；
    本类是给**兜底阶梯**做测试的，不是给判定链做测试的。
    """

    available = False
    exe = None
    reason = "stub"
    part = "xczu3eg-sbva484-1-e"
    period_ns = 5.0

    def __init__(self, *a, **kw):
        pass

    def csim(self, kernel, tb, top, headers=None, setup_timeout_s=0.0,
             run_timeout_s=0.0):
        return {"level": 1, "env": "", "rc": 1, "note": "stub：编译不过",
                "stages": [], "kind": "compile", "log": "stub"}

    def csynth(self, kernel, top, timeout_s=0.0, headers=None):
        return 1, "stub"

    #: fix9（改动 B）：没有测试台的轮次也会做一次宿主语法体检。默认 `skipped`
    #: = 宿主不给结论 ⇒ 这一支的行为与 fix8 **逐字节相同**（既有用例全走这里）。
    syntax_status = "skipped"
    syntax_diags: list = []

    def kernel_syntax(self, kernel, headers=None, timeout_s=0.0):
        st = type(self).syntax_status
        return {"status": st, "why": "stub", "diags": list(type(self).syntax_diags),
                "rc": (1 if st == "fail" else 0), "elapsed_s": 0.0}


def _scripted(results):
    """造一个「按脚本逐轮返回 csim 结果」的假工具链**类**（solve() 会 new 它，
    所以给的必须是类不是实例）。返回的类上挂 `calls` 计数 —— 验「停不停机」。
    同样一次 EDA 都不跑。"""

    class _StubScripted(_StubHls):
        calls = 0
        script: list = []

        def __init__(self, *a, **kw):
            pass

        def csim(self, kernel, tb, top, headers=None, setup_timeout_s=0.0,
                 run_timeout_s=0.0):
            type(self).calls += 1
            r = (self.script.pop(0) if self.script else {"level": None, "env": None})
            base = {"level": None, "env": None, "rc": 0, "kind": None, "note": "",
                    "stages": {}, "log": "stub"}
            base.update(r)
            return base

    _StubScripted.script = list(results)
    return _StubScripted


def _scripted_l4(results):
    """`_scripted` 的 L4 版：`csynth` 返回 **rc=0** —— 一份「真的拿到 L4」的稿子。

    `_StubHls.csynth` 恒返回 rc=1（它是给兜底阶梯做测试的），而 fix16 的自审闸
    挂在 `rc4 == 0` 里面：不换这一层，自审轮**在测试里永远走不到**。
    """
    base = _scripted(results)

    class _StubScriptedL4(base):
        synth_calls = 0

        def csynth(self, kernel, top, timeout_s=0.0, headers=None):
            type(self).synth_calls += 1
            return 0, "stub: synth ok"

    _StubScriptedL4.script = list(results)
    return _StubScriptedL4


class TestSolveKeepsSomething(unittest.TestCase):
    """`solve()` 的兜底阶梯：**空手而归是最后一名，不是并列第一。**

    三条机制是同一句话的三种写法 —— 模型给了能用的东西，是我们自己的环把它丢了。
    每条都在 `results/hls-agent-20261001/pilot-diag-rawreply/` 里有逐字存档
    （真实模型回复的原始响应体 `raw_body.json`），不是合成出来的场景：

      A 抽取误选   attempt5：两块，测试台更长且也调用 `top(` ⇒ `max(key=len)` 选中测试台
      B 截断丢弃   attempt2：围栏完整、签名逐字通过（6 形参），仅因 finish=length 被整轮丢
      C 签名假红   签名闸只做**文本**比对，等价写法会被判红（见 tools.check_signature 的说明）
                   —— 一次假的红比漏报更危险，它会让环把唯一的候选也扔掉

    下面最后两条是**负对照**：兜底不许把「什么都没拿到」兜成一份假产物。
    """

    INTERFACE = ('typedef unsigned long long int bits64;\n'
                 'void add128(bits64 a0, bits64 a1, bits64 b0, bits64 b1,\n'
                 '            bits64 *z0Ptr, bits64 *z1Ptr);\n')
    TOP = "add128"
    KERNEL = ('```cpp\n#include "add128.h"\n\n'
              'void add128(bits64 a0, bits64 a1, bits64 b0, bits64 b1,\n'
              '            bits64 *z0Ptr, bits64 *z1Ptr) {\n'
              '    bits64 z1 = a1 + b1;\n'
              '    *z1Ptr = z1;\n'
              '    *z0Ptr = a0 + b0 + ((z1 < a1) ? 1 : 0);\n'
              '}\n```\n')
    # 与 KERNEL 同形状，但**形参少了两个** ⇒ 签名闸必红。
    BAD_SIG = ('```cpp\n#include "add128.h"\n\n'
               'void add128(bits64 a0, bits64 a1) { (void)a0; (void)a1; }\n```\n')
    TB_LONG = ('```cpp\n#include <cstdio>\n#include "add128.h"\n\n'
               'static void ref_add128(bits64 a0, bits64 a1, bits64 b0, bits64 b1,\n'
               '                       bits64 *z0, bits64 *z1) {\n'
               '    *z1 = a1 + b1;\n'
               '    *z0 = a0 + b0 + ((*z1) < a1 ? 1 : 0);\n'
               '}\n\n'
               'int main() {\n'
               '    bits64 z0, z1, r0, r1;\n'
               '    add128(1ULL, 2ULL, 3ULL, 4ULL, &z0, &z1);\n'
               '    ref_add128(1ULL, 2ULL, 3ULL, 4ULL, &r0, &r1);\n'
               '    printf("got %llx %llx want %llx %llx\\n", z0, z1, r0, r1);\n'
               '    return (z0 == r0 && z1 == r1) ? 0 : 1;\n}\n```\n')

    def _solve(self, replies, stub=None, save=None):
        import agent.main as m

        with tempfile.TemporaryDirectory() as d:
            for fname, text in (("prompt.txt", "Top-Level Function : `add128`\n"),
                                ("interface.txt", self.INTERFACE),
                                ("top.txt", "add128\n")):
                with open(os.path.join(d, fname), "w", encoding="utf-8") as fh:
                    fh.write(text)
            task = m.Task(d)
            top, _src = task.resolve_top()
            trace = m.Trace(os.path.join(d, "trace.jsonl"))
            real = m.HlsToolchain
            m.HlsToolchain = stub or _StubHls   # ★ 一次 EDA 都不跑
            llm = _StubLLM(replies)
            self.last_llm = llm                # 供「每轮都传了帽吗」那条读
            try:
                return m.solve(llm, trace, task, top, save=save)
            finally:
                m.HlsToolchain = real
                trace.close()

    # ── A：抽取误选。产物必须是那块**含定义**的 kernel，不是残渣、也不是参考实现。
    def test_longer_testbench_does_not_steal_the_kernel(self):
        reply = self.KERNEL + "\n" + self.TB_LONG
        out = self._solve([reply, reply, reply])
        self.assertIn("void add128", out, "更长且调用 top( 的测试台把 kernel 抢走了")
        self.assertNotIn("ref_add128", out, "把测试台里的参考实现当成 kernel 交了出去")

    # ── B：截断丢弃。**撞帽 ≠ 废稿**：模型常已写完并闭合 kernel 那块，
    #    只是接着写测试台时撞了帽。整轮丢弃会把一份完整、签名通过的 kernel 一起扔。
    def test_truncated_round_still_yields_a_candidate(self):
        out = self._solve([(self.KERNEL, "length"), ("", "stop"), ("", "stop")])
        self.assertIn("void add128", out,
                      "一份围栏完整、签名逐字通过的 kernel 被 max_tokens 截断连坐丢了")

    # ── C：签名闸只做文本比对，可能是**假红**。真红与假红在这里无法区分，
    #    所以闸只能当「先验概率」，不能当**唯一**的取舍依据：交了总比交白卷强。
    def test_signature_gate_does_not_veto_everything(self):
        out = self._solve([self.BAD_SIG, self.BAD_SIG, self.BAD_SIG])
        self.assertIn("void add128", out,
                      "签名闸把唯一一份能解析的候选也扔了，最后交了白卷")

    # ── 负对照 ①：三轮全是废话 —— **模型产出的东西一个字都不许进交付件**。
    #    fix13（PREREG A.3 §10）把「空手」的含义从**白卷**改成了**编译桩**：
    #    0 B 是实测的 L0，而一份形参逐字对齐的空体定义能编过 ⇒ 官方 L2。
    #    这条负对照因此改说两件事：废话不许进交付件；交付件只能是桩。
    def test_all_rounds_garbage_never_reaches_the_deliverable(self):
        out = self._solve([("I cannot help with that request.", "stop")] * 3)
        self.assertNotIn("I cannot help", out, "兜底把模型回复里的废话交上去了")
        self.assertTrue(out.startswith("// compile-only fallback"),
                        "空手时交的既不是白卷也不是编译桩：%r" % out[:120])

    # ── 负对照 ②：截断的是**废话**而不是代码 —— 同样不许被当成候选。
    #    它挡的是「B 那条改成了『截断就保留』」这种一刀切；fix13 之后交付件
    #    换成桩，但**废话仍然不许在里面**。
    def test_truncated_garbage_is_not_kept(self):
        out = self._solve([("I will now think about the problem step", "length")] * 3)
        self.assertNotIn("I will now think", out,
                         "截断这条兜底把没有代码的回复也留下来了")
        self.assertTrue(out.startswith("// compile-only fallback"),
                        "空手时交的既不是白卷也不是编译桩：%r" % out[:120])

    # ── 2026-10-25 §3 改动 B：空回复**同轮**重试（换问法、不换预算、不占轮次）。
    #    成因与输入无关（思考把帽吃光），所以原样重发只会重演同一个空 ——
    #    10-23 面板 7 题三轮全零就是这么来的。
    def test_empty_reply_is_retried_with_a_nudge_in_the_same_round(self):
        import agent.main as m
        out = self._solve([("", "length"), self.KERNEL])
        self.assertIn("void add128", out, "空回复没有被同轮重试救回来")
        llm = self.last_llm
        # 第 1、2 次调用属于**同一轮** ⇒ 帽必须相同（降档只会更空）。
        # 总调用数 = 轮数 + 1（那一次同轮重试）—— 轮数从 main 读，不写死预算。
        self.assertEqual(len(llm.caps), m.MAX_ROUNDS + 1,
                         "期望 %d 次调用：r1 首试+重试、其余 %d 轮各一次"
                         % (m.MAX_ROUNDS + 1, m.MAX_ROUNDS - 1))
        self.assertEqual(llm.caps[0], llm.caps[1], "空回复重试降了档 —— 只会更空")
        # 第二次的 user 消息带着输出契约；第一次那条**没被就地改写**（下一轮不该带上它）。
        self.assertIn("Output contract", llm.seen[1][-1]["content"])
        self.assertNotIn("Output contract", llm.seen[0][-1]["content"])
        # 配额是**每题**一次：后面几轮再空也不再加问，否则单题调用数翻倍。
        n = sum(1 for msgs in llm.seen if "Output contract" in msgs[-1]["content"])
        self.assertEqual(n, 1, "空回复重试按轮各给了一次 —— 单题调用数会翻倍")

    # ── #143 §3.6：`describe()` 记的是**配置**帽，逐轮实际帽必须另有一列。
    #    这里钉的是「**每一轮**都显式传了帽」—— 漏传一轮，那一轮就悄悄用配置值，
    #    而 trace 上看不出区别（它申报的本来就是配置值）。
    def test_every_round_passes_an_explicit_cap(self):
        self._solve([self.KERNEL] * 3)
        caps = self.last_llm.caps
        self.assertEqual(len(caps), self.last_llm.rounds,
                         "有轮次没走到 LLM，这条测试的前提不成立")
        self.assertTrue(all(c is not None for c in caps),
                        "有一轮没传 max_tokens ⇒ 那一轮静默用了配置值")

    # ── #153 接线（判据本体在 TestClassifyNoExe；这里测 solve() 拿到结果后
    #    **做了什么**：交什么、停不停、下一轮回什么话）。
    def test_env_stop_still_hands_over_the_signed_kernel(self):
        """环境故障停机不再是白卷：交出本轮已过签名闸的 kernel。
        改前这里返回 ""（存 best 只在 `lvl is not None` 支，而 env 支 lvl 恒 None）。
        证据：online-rescue-20261003 的 4 题 `stop: environment failure: fixture`
        + `done bytes=0`。"""
        stub = _scripted([{"level": None, "env": "fixture",
                           "note": "csim.exe 未生成，原因不明"}])
        out = self._solve([self.KERNEL + "\n" + self.TB_LONG], stub=stub)
        self.assertIn("void add128", out, "env 停机把已过签名的 kernel 扔了（#153）")
        self.assertEqual(stub.calls, 1, "env 故障必须停机 —— 不许拿它去指挥模型改代码")

    def test_tb_compile_error_keeps_the_loop_going(self):
        """TB 编译错不是环境故障：**不停机**，且下一轮喂给模型的话指着测试台。"""
        stub = _scripted([
            {"level": None, "env": None, "kind": "testbench-compile",
             "note": "agent_tb.cpp:6:15: error: expected unqualified-id"},
            {"level": 2, "env": None, "note": "mismatches: 3"},
        ])
        reply = self.KERNEL + "\n" + self.TB_LONG
        self._solve([reply, reply], stub=stub)
        self.assertGreaterEqual(stub.calls, 2, "TB 编译错把环停掉了（#153 病灶）")
        blob = "\n".join(m["content"] for m in self.last_llm.seen[1])
        self.assertIn("testbench-compile", blob, "反馈里没带上失败类别")
        self.assertIn("测试台", blob, "反馈没指着测试台")
        self.assertNotIn("算法或边界错", blob, "TB 编译错被讲成了算法错")

    # ── 官方 2026-10-19 的 save_solution：**每改善一次就落盘**。
    #    异步协议下评测方到 deadline 就杀进程；只在收尾写一次，被杀时盘上是空的，
    #    而分数只读盘上那份。这里钉两件事：真的写过、最后写的就是返回值。
    def test_every_improvement_is_saved(self):
        saved = []
        out = self._solve([(self.KERNEL, "length"), ("", "stop"), ("", "stop")],
                          save=saved.append)
        self.assertTrue(saved, "一次都没落盘 —— 进程被杀时盘上是空的")
        self.assertEqual(saved[-1], out,
                         "盘上最后一份与返回值不同：收尾时交出去的会是另一份")


class _FakeResp:
    """`requests.post` 的最小替身：只提供 `_chat_openai` 真正读的那几个字段。

    2026-10-22：流式路径读 `iter_lines()` / `close()`，所以同一个 `body` 也要能
    编成 SSE —— 替身不许替调用方选路径（`LLM_STREAM=0` 的用例走 `json()`，
    流式用例走 `iter_lines()`，两者拿到的是**同一段文本**）。
    """

    def __init__(self, body, status=200):
        self._body = body
        self.status_code = status
        self.text = json.dumps(body)
        self.closed = False

    def json(self):
        return self._body

    def iter_lines(self, decode_unicode=False):
        msg = ((self._body.get("choices") or [{}])[0]).get("message") or {}
        chunk = {"choices": [{"delta": {"content": msg.get("content") or ""},
                              "finish_reason": None}]}
        yield "data: " + json.dumps(chunk)
        usage = self._body.get("usage")
        if usage:
            yield "data: " + json.dumps(
                {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": usage})
        yield "data: [DONE]"

    def close(self):
        self.closed = True


class _FakeStreamResp:
    """流式替身：`iter_lines()` 逐行吐调用方给的 SSE 行（`delay` 让块间有真墙钟）。"""

    def __init__(self, lines, status=200, delay=0.0):
        self._lines = lines
        self.status_code = status
        self.text = ""
        self.closed = False
        self._delay = delay

    def iter_lines(self, decode_unicode=False):
        for line in self._lines:
            if self._delay:
                time.sleep(self._delay)
            yield line

    def close(self):
        self.closed = True


_OK_BODY = {"choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 22}}


class TestMaxTokensOverride(unittest.TestCase):
    """`LLM.chat(..., max_tokens=)` 必须**逐轮**改帽，且不动配置值。

    ★ 两件事要同时成立（#143 §3.6）：请求体里是**当轮实际值**，
      `describe()` 里仍是**配置值**。少任何一半，trace 都会申报一个
      **从未发出的帽** —— 而 trace 是判分与复核都读的证据。
    """

    def setUp(self):
        import requests
        self._saved_post = requests.post
        self.requests = requests
        outer = self

        def fake_post(url, headers=None, data=None, timeout=None, stream=False):
            outer.sent.append(json.loads(data))
            outer.timeouts.append(timeout)
            return _FakeResp(_OK_BODY)

        self.sent, self.timeouts = [], []
        requests.post = fake_post

    def tearDown(self):
        self.requests.post = self._saved_post

    def _client(self, **env):
        """造一个 openai 后端的 LLM，跑完把环境还原（不留残留给别的用例）。"""
        saved = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            return LLM()
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def _new(self, **extra):
        # LLM_STREAM=0：这一组钉的是**非流式回退路径**的请求体与墙钟闸，
        # 与流式路径共用同一份 `_OK_BODY`（见 `_FakeResp`）。流式本身在
        # `TestStreaming` 里单独钉。
        env = {"LLM_BACKEND": "openai", "LLM_BASE_URL": "http://127.0.0.1:1/v1",
               "LLM_MAX_TOKENS": "8192", "LLM_STREAM": "0"}
        env.update(extra)
        return self._client(**env)

    def test_override_goes_into_the_payload(self):
        llm = self._new()
        llm.chat([{"role": "user", "content": "hi"}], budget_s=100.0, max_tokens=5250)
        self.assertEqual(self.sent[-1]["max_tokens"], 5250,
                         "逐轮帽没进请求体 ⇒ 削帽这件事等于没做")

    # 负对照：不给覆盖值时**必须发配置值**。没有这条，一个「无论传什么都发
    # 5250」的实现也能让上面那条变绿。
    def test_no_override_sends_the_configured_value(self):
        llm = self._new()
        llm.chat([{"role": "user", "content": "hi"}], budget_s=100.0)
        self.assertEqual(self.sent[-1]["max_tokens"], 8192)

    # 负对照：覆盖**不许**改到配置值本身。改了的话每一轮都会继承上一轮的帽，
    # 而 `describe()`/start 行还在申报 8192 —— 一个很像真的假数。
    def test_describe_still_reports_the_configured_cap(self):
        llm = self._new()
        llm.chat([{"role": "user", "content": "hi"}], budget_s=100.0, max_tokens=5000)
        self.assertEqual(llm.describe()["max_tokens"], 8192,
                         "覆盖值污染了配置值 —— start 行会申报一个从未发出的帽")
        self.assertEqual(llm.max_tokens, 8192)

    # 与上一轮无关：墙钟闸仍是 min(timeout_s, budget_s)。
    def test_budget_still_caps_the_timeout(self):
        llm = self._new(LLM_TIMEOUT_S="300")
        llm.chat([{"role": "user", "content": "hi"}], budget_s=100.0,
                 max_tokens=5250)
        self.assertEqual(self.timeouts[-1], 100.0)


class TestStreaming(unittest.TestCase):
    """流式路径 + 两个止损闸（2026-10-22 PREREG §2.5–§2.8）。

    为什么单独一组：流式是**缺省路径**，别的用例都用 `LLM_STREAM=0` 显式回落，
    所以这里若断了，跑动期每次调用都会悄悄变回旧行为，而 trace 里只有 `stream`
    一列能看出来。四件事必须同时钉住：SSE 拼装、慢流早断、降档帽不受闸、
    停摆（块间超时）与总时限也归 `LLMSlowError` 而不是裸 `ReadTimeout`。
    """

    KEYS = ("LLM_BACKEND", "LLM_BASE_URL", "LLM_MAX_TOKENS", "LLM_STREAM",
            "LLM_RATE_MIN_TPS", "LLM_RATE_GATE_MIN_S", "LLM_RATE_GATE_MIN_TOKENS",
            "LLM_RATE_GATE_MIN_CAP", "LLM_STREAM_IDLE_S", "LLM_TIMEOUT_S")

    def setUp(self):
        import requests
        self.requests = requests
        self._saved_post = requests.post
        self.posts = []
        self._env = {k: os.environ.pop(k, None) for k in self.KEYS}

    def tearDown(self):
        self.requests.post = self._saved_post
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def install(self, resp):
        outer = self

        def fake_post(url, headers=None, data=None, timeout=None, stream=False):
            outer.posts.append({"payload": json.loads(data), "timeout": timeout,
                                "stream": stream})
            return resp

        self.requests.post = fake_post

    def client(self, **env):
        base = {"LLM_BACKEND": "openai", "LLM_BASE_URL": "http://127.0.0.1:1/v1"}
        base.update(env)
        os.environ.update(base)
        return LLM()

    @staticmethod
    def sse(content=None, finish=None, usage=None, reasoning=None):
        """一块 SSE 行。`reasoning` 走思考通道：要计入块数，但**不进正文**。"""
        delta = {}
        if content is not None:
            delta["content"] = content
        if reasoning is not None:
            delta["reasoning_content"] = reasoning
        obj = {"choices": [{"delta": delta, "finish_reason": finish}]}
        if usage is not None:
            obj["usage"] = usage
        return "data: " + json.dumps(obj)

    def test_stream_is_the_default_and_the_payload_says_so(self):
        resp = _FakeStreamResp([self.sse("hel"), self.sse("lo", finish="stop"),
                                "data: [DONE]"])
        self.install(resp)
        llm = self.client()
        self.assertTrue(llm.stream, "流式成了非缺省 —— 慢调用又会被读超时整段烧掉")
        r = llm.chat([{"role": "user", "content": "hi"}],
                     budget_s=100.0, max_tokens=8192)
        self.assertTrue(self.posts[-1]["stream"], "requests.post 没接到 stream=True")
        self.assertTrue(self.posts[-1]["payload"]["stream"],
                        "请求体里没有 stream ⇒ 服务端仍按非流式攒完整段再回")
        self.assertEqual(r.text, "hello")
        self.assertEqual(r.finish_reason, "stop")
        self.assertTrue(r.streamed)
        # 服务端不给 usage 时按块计（Ollama / llama.cpp 均 1 token = 1 块）
        self.assertEqual((r.tokens_in, r.tokens_out, r.tokens_src),
                         (0, 2, "chunks"))
        self.assertTrue(resp.closed, "连接没关 —— 流会一直占着服务端的 slot")

    def test_usage_chunk_wins_over_chunk_count(self):
        resp = _FakeStreamResp([
            self.sse(reasoning="想一想", content=None),
            self.sse("hi", finish="length",
                     usage={"prompt_tokens": 7, "completion_tokens": 33}),
            "data: [DONE]"])
        self.install(resp)
        r = self.client().chat([{"role": "user", "content": "hi"}],
                               budget_s=100.0, max_tokens=8192)
        self.assertEqual(r.text, "hi", "思考块被拼进了正文")
        self.assertEqual((r.tokens_in, r.tokens_out, r.tokens_src),
                         (7, 33, "usage"))
        self.assertEqual(r.finish_reason, "length",
                         "finish_reason 丢了 ⇒ trace 分不出撞帽与自然结束")

    def test_slow_stream_aborts_and_closes_the_connection(self):
        # min_s=0.005 而块间隔 0.01：第一块的 el 恰为 0（跳过），第二块才有
        # 真速率 —— 顺带钉住「el 为 0 时 rate 报 0」那条分支不会误伤生产档
        # （生产档 min_s=30，el=0 根本到不了闸）。
        resp = _FakeStreamResp([self.sse("x") for _ in range(10)], delay=0.01)
        self.install(resp)
        llm = self.client(LLM_RATE_MIN_TPS="1e6", LLM_RATE_GATE_MIN_S="0.005",
                          LLM_RATE_GATE_MIN_TOKENS="1")
        with self.assertRaises(LLMSlowError) as ctx:
            llm.chat([{"role": "user", "content": "hi"}],
                     budget_s=100.0, max_tokens=8192)
        self.assertEqual(ctx.exception.reason, "slow-stream")
        self.assertGreater(ctx.exception.rate, 0.0)
        self.assertTrue(resp.closed,
                        "早断时没关连接 —— 服务端会继续生成到撞帽（这正是要止损的钱）")

    # 负对照：同一套「掐死一切」的闸参数下，降档帽（≤4096）**必须不被掐**。
    # 没有这条，一个「无论帽多少都掐」的实现也能让上面那条变绿 —— 而那样
    # 慢模型的重试轮会被反复掐死，永远写不完正文（PREREG §2.8）。
    def test_downgraded_cap_is_not_gated(self):
        resp = _FakeStreamResp([self.sse("x") for _ in range(10)], delay=0.01)
        self.install(resp)
        llm = self.client(LLM_RATE_MIN_TPS="1e6", LLM_RATE_GATE_MIN_S="0.005",
                          LLM_RATE_GATE_MIN_TOKENS="1")
        r = llm.chat([{"role": "user", "content": "hi"}],
                     budget_s=100.0, max_tokens=4096)
        self.assertEqual(r.text, "x" * 10)
        self.assertEqual(r.tokens_src, "chunks")

    def test_idle_timeout_becomes_a_slow_error(self):
        resp = _FakeStreamResp([])

        def boom(decode_unicode=False):
            raise self.requests.Timeout("read timed out")
            yield  # pragma: no cover

        resp.iter_lines = boom
        self.install(resp)
        llm = self.client(LLM_STREAM_IDLE_S="1")
        with self.assertRaises(LLMSlowError) as ctx:
            llm.chat([{"role": "user", "content": "hi"}],
                     budget_s=100.0, max_tokens=8192)
        self.assertEqual(ctx.exception.reason, "idle-timeout",
                         "块间超时没归到 LLMSlowError —— main.py 会把它记成传输失败")
        self.assertTrue(resp.closed)

    def test_total_timeout_is_checked_between_chunks(self):
        # 预算给 0 ⇒ timeout = min(timeout_s, budget_s) = 0；块隔 0.05 s 让
        # 「已超时」在 Windows 的粗时钟（~15.6 ms 一跳）下也确定成立。
        resp = _FakeStreamResp([self.sse("x")], delay=0.05)
        self.install(resp)
        llm = self.client()
        with self.assertRaises(LLMSlowError) as ctx:
            llm.chat([{"role": "user", "content": "hi"}],
                     budget_s=0.0, max_tokens=8192)
        self.assertEqual(ctx.exception.reason, "total-timeout")

    def test_stream_zero_falls_back_to_one_shot(self):
        resp = _FakeResp(_OK_BODY)
        self.install(resp)
        llm = self.client(LLM_STREAM="0")
        self.assertFalse(llm.stream)
        r = llm.chat([{"role": "user", "content": "hi"}], budget_s=100.0)
        self.assertFalse(self.posts[-1]["stream"])
        self.assertFalse(self.posts[-1]["payload"]["stream"])
        self.assertEqual(r.text, "hello")
        self.assertFalse(r.streamed)


class TestRoundBudgetPlan(unittest.TestCase):
    """#143 §3.3.1 的逐轮份额算式：**`k` 是「打算真买几轮」，不是「还剩几轮」**。

    病灶（实测）：r1 恒吃满 8192（~197 s）却取不出东西，r2 只拿到「r1 吃剩的 ~141 s」，
    三题的 r2 全部贴着预算上限（余量 5.58 / 0.43 / 负数）。

    ★ 下面每个数都逐字取自 PREREG-143 §3.3.1 的演算表；**换回「`rounds_left` 恒等于
      剩余轮数」的字面版，前两条立刻转红** —— 它们就是这个算式的守卫。
    """

    #: 与 §3.3.1 演算表逐字同参
    KNOBS = {"TPS_EST": 42.0, "CAP_MIN": 5000,
             "MIN_TOOL_S": 45.0, "MIN_LLM_S": 5000 / 42.0}

    def setUp(self):
        import agent.main as m
        self.m = m
        self._saved = {k: getattr(m, k) for k in self.KNOBS}
        for k, v in self.KNOBS.items():
            setattr(m, k, v)

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(self.m, k, v)

    def plan(self, remaining_s, rounds_left, cap_hard=8192):
        return self.m.plan_round(remaining_s, rounds_left, cap_hard)

    # ── 生产档（deadline_s=360 ⇒ remaining()=340）：r1 买两轮，帽 5250
    def test_production_first_round(self):
        k, fair, cap = self.plan(340.0, 3)
        self.assertEqual(k, 2, "第 1 轮该按「两轮」分，不是按「还剩三轮」分")
        self.assertAlmostEqual(fair, 125.0, places=6)
        self.assertEqual(cap, 5250)

    # ── 闭环：同一轮数、不同的 remaining()，帽跟着变。
    #    T=0（自检被跳过）⇒ 215 s ⇒ 7140；T=45（自检吃满）⇒ 170 s ⇒ 5250。
    #    ★ 我第一版演算把 T 当成 0，把 7140 报成唯一值 —— 这条把两端都钉住。
    def test_second_round_is_closed_loop(self):
        self.assertEqual(self.plan(215.0, 2), (1, 170.0, 7140))
        self.assertEqual(self.plan(170.0, 2), (1, 125.0, 5250))

    # ── 长 deadline（900）：三轮全拿满帽 —— A3 档的行为不变。
    def test_long_deadline_keeps_full_cap(self):
        self.assertEqual(self.plan(880.0, 3), (3, 880.0 / 3 - 45.0, 8192))
        self.assertEqual(self.plan(640.0, 2), (2, 275.0, 8192))
        self.assertEqual(self.plan(400.0, 1), (1, 355.0, 8192))

    # ── 极短 deadline（180）：一轮都装不下 ⇒ 回退到 k=1，帽被 CAP_MIN 抬到 5000。
    #    ⚠ 这是**判断**（白卷 vs 碰运气），不是读数；出处只有 attempt5 一次成功。
    def test_short_deadline_falls_back_to_one_round(self):
        k, fair, cap = self.plan(160.0, 3)
        self.assertEqual(k, 1, "装不下一整轮时应回退到 1，而不是直接放弃")
        self.assertAlmostEqual(fair, 115.0, places=6)
        self.assertEqual(cap, 5000, "帽该被 CAP_MIN 抬起来（42*115=4830 < 5000）")

    # ── 份额算成负数才是真的没得开。**这道闸的用途与 §3.3 登记的完全一致**：
    #    它防的是**负数份额**，不是「份额偏小」。
    def test_no_room_breaks(self):
        for remaining, rounds_left in ((45.0, 3), (41.0, 2)):
            k, fair, cap = self.plan(remaining, rounds_left)
            self.assertEqual(k, 0, "份额为负还开轮 —— 白烧一轮")
            self.assertLessEqual(fair, 0.0)
            self.assertEqual(cap, 0)

    # ── 帽不许超过硬上限（配置的 LLM_MAX_TOKENS）：超了就是超发请求，
    #    对方可能 400，而那一轮整轮丢掉。
    def test_cap_never_exceeds_the_hard_limit(self):
        for remaining_s in (170.0, 340.0, 880.0):
            _k, _fair, cap = self.plan(remaining_s, 1, cap_hard=4096)
            self.assertLessEqual(cap, 4096)

    # ── 前提守卫（不是实现守卫）：§3.3.1 那条论证靠的是
    #    「字面版在生产档第 1 轮就 break」。**常数漂了，这条要红** ——
    #    红了就说明该回去重看那段论证，而不是继续照着它实现。
    #    （实现守卫是上面那两条：换回字面版，它们立刻红。）
    def test_literal_rounds_left_would_have_starved(self):
        remaining, rounds_left = 340.0, 3
        fair_literal = remaining / rounds_left - self.m.MIN_TOOL_S
        self.assertLess(fair_literal, self.m.MIN_LLM_S,
                        "字面版居然开得出轮？§3.3.1 的整个论证要重来")


class TestStripThink(unittest.TestCase):
    """思考段的三种形态 —— 与官方 `example/agent/llm.py` 的 `strip_think()` 同语义。

    为什么这是功能而不是格式：思考段里也会出现 ```cpp 围栏。不先剥掉，
    `extract_blocks` 会把**思考过程中的代码草稿**当成答案取走；那种草稿常常
    围栏完整、签名也对，签名闸会放行 —— 于是白得一个「看起来像解出来」的产物。
    """

    def test_complete_think_block_is_stripped(self):
        text = "<think>draft\n```cpp\nvoid bad() {}\n```\n</think>\n```cpp\nvoid good() {}\n```"
        self.assertEqual(strip_think(text), "\n```cpp\nvoid good() {}\n```",
                         "完整的思考段没被剥掉 —— 草稿会被当答案")

    def test_close_tag_only_keeps_the_answer(self):
        # 模板已预填 `<think>`，回复里只有结束标记
        self.assertEqual(strip_think("thinking...\n</think>\nANSWER"), "\nANSWER")

    def test_truncated_think_yields_empty(self):
        # 输出帽全耗在思考里：回复以 `<think>` 开头且没有答案 ⇒ 如实交空
        self.assertEqual(strip_think("<think>still thinking, cut off"), "",
                         "被截断的思考段应当交出空串，而不是交出半截思考")

    def test_last_close_tag_wins(self):
        self.assertEqual(strip_think("<think>a</think>mid<think>b</think>ans"), "ans")

    def test_no_marker_is_untouched(self):
        # 只减不增：没有标记的回复必须逐字节不变
        self.assertEqual(strip_think("plain answer"), "plain answer")

    def test_extract_blocks_does_not_take_thought_drafts(self):
        text = ("<think>let me draft\n```cpp\n#include \"add128.h\"\n"
                "void add128(int wrong) {}\n```\n</think>\n"
                "```cpp\n#include \"add128.h\"\nvoid add128() {}\n```\n")
        k, _tb, _note = extract_blocks(text, "add128")
        self.assertIn("void add128()", k)
        self.assertNotIn("int wrong", k, "思考段里的草稿被当成答案取走了")


class TestGenerationSettings(unittest.TestCase):
    """manifest 的 `generation` 块 → 请求体；优先级 **申报 < LLM_THINK < LLM_EXTRA_BODY**。

    官方 `baseline.py` 读同一块，所以分子分母在**同一种模型模式**下跑。这里钉的是
    本智能体这一侧：申报的值必须真的进请求（没人读 = 申报了不执行），而且
    `LLM_THINK`/`LLM_EXTRA_BODY` 只能在开发期探针里**显式**覆盖它。
    """

    def setUp(self):
        import agent.llm as llm_mod
        import requests
        self.llm_mod = llm_mod
        self.requests = requests
        self._saved_post = requests.post
        outer = self

        def fake_post(url, headers=None, data=None, timeout=None, stream=False):
            outer.sent.append(json.loads(data))
            return _FakeResp(_OK_BODY)

        self.sent = []
        requests.post = fake_post

    def tearDown(self):
        self.requests.post = self._saved_post

    def _client(self, **env):
        # 这一组只钉请求体字段；走非流式回退路径（流式见 `TestStreaming`），
        # 否则 `fake_post` 得同时演两种响应形状，用例会跟着实现一起漂。
        env.setdefault("LLM_STREAM", "0")
        saved = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            return LLM()
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def _payload(self, llm):
        llm.chat([{"role": "user", "content": "hi"}], budget_s=100.0)
        return self.sent[-1]

    def test_declared_generation_goes_into_the_payload(self):
        llm = self._client(LLM_BACKEND="openai",
                           LLM_BASE_URL="http://127.0.0.1:1/v1")
        llm.generation = {"chat_template_kwargs": {"enable_thinking": False},
                          "reasoning_effort": "low"}
        p = self._payload(llm)
        self.assertEqual(p.get("chat_template_kwargs"), {"enable_thinking": False},
                         "manifest 申报的思考设置没进请求 ⇒ 申报了不执行")
        self.assertEqual(p.get("reasoning_effort"), "low")

    def test_empty_generation_sends_no_vendor_field(self):
        # 本用例的**前置条件**是「什么都没申报」，所以要显式把申报清空 ——
        # `LLM()` 会从随包的 manifest.json 读 `generation`，那份文件一旦申报了
        # 字段（2026-10-25 起申报 `enable_thinking: false`），这里再靠「没设
        # 环境变量」就不等于「没申报」。靠包数据隐式满足前置的用例会随数据一起漂。
        llm = self._client(LLM_BACKEND="openai",
                           LLM_BASE_URL="http://127.0.0.1:1/v1",
                           LLM_THINK="", LLM_EXTRA_BODY="")
        llm.generation = {}
        p = self._payload(llm)
        self.assertNotIn("chat_template_kwargs", p,
                         "没申报却发了模板参数 —— 请求不再是标准 OpenAI 形态")
        self.assertNotIn("reasoning_effort", p)

    def test_shipped_manifest_declares_thinking_off(self):
        """随包的 manifest 必须**真的**申报关思考，并且这份申报要读得出来。

        为什么钉在包数据上：`enable_thinking: false` 是 2026-10-25 那次修复的
        全部抓手（`results/agent-fix-20261025/PREREG.md` §2–§3）——
        思考与正文共用 `max_tokens`，8,192 的帽被思考吃光时正文**零字节**。
        申报被误删/被改回 `{}` 时，智能体会静默回到「三轮全零」的形态，
        而**没有任何一层会报错**。这条用例就是那一层的红。
        """
        gen = self.llm_mod._load_generation()
        self.assertEqual(gen.get("chat_template_kwargs"), {"enable_thinking": False},
                         "manifest.json 不再申报关思考 —— 8192 帽会被思考吃光")

    def test_think_override_beats_the_declaration(self):
        llm = self._client(LLM_BACKEND="openai",
                           LLM_BASE_URL="http://127.0.0.1:1/v1", LLM_THINK="true")
        llm.generation = {"chat_template_kwargs": {"enable_thinking": False}}
        p = self._payload(llm)
        self.assertEqual(p["chat_template_kwargs"], {"enable_thinking": True},
                         "LLM_THINK 没压过申报值 —— 探针臂会跑在与宣称不同的口径上")

    def test_extra_body_is_the_last_word(self):
        llm = self._client(LLM_BACKEND="openai",
                           LLM_BASE_URL="http://127.0.0.1:1/v1")
        llm.generation = {"reasoning_effort": "low"}
        llm.extra_body = {"reasoning_effort": "high"}
        self.assertEqual(self._payload(llm).get("reasoning_effort"), "high",
                         "LLM_EXTRA_BODY 不是最后生效 —— 通用逃生口失效")

    def test_allowlist_drops_non_scalar_values(self):
        """读 manifest 时只收标量：list/dict 值原样发出去，服务端可能直接 400，
        而那是**整轮丢失**（官方 example 也按这个白名单读）。"""
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "agent"))
            with open(os.path.join(d, "manifest.json"), "w", encoding="utf-8") as fh:
                json.dump({"generation": {
                    "chat_template_kwargs": {"enable_thinking": False, "x": 1,
                                             "bad": [1], "worse": {"a": 1}},
                    "reasoning_effort": "medium", "ignored": 1}}, fh)
            saved = self.llm_mod.__file__
            self.llm_mod.__file__ = os.path.join(d, "agent", "llm.py")
            try:
                gen = self.llm_mod._load_generation()
            finally:
                self.llm_mod.__file__ = saved
        self.assertEqual(gen, {"chat_template_kwargs": {"enable_thinking": False, "x": 1},
                               "reasoning_effort": "medium"},
                         "白名单没把非标量/未知键滤掉")

    def test_missing_manifest_degrades_to_no_fields(self):
        with tempfile.TemporaryDirectory() as d:
            saved = self.llm_mod.__file__
            self.llm_mod.__file__ = os.path.join(d, "agent", "llm.py")
            try:
                self.assertEqual(self.llm_mod._load_generation(), {},
                                 "读不到 manifest 应当退成「不发该字段」，不是抛错")
            finally:
                self.llm_mod.__file__ = saved


class TestSaveSolution(unittest.TestCase):
    """原子落盘：先写 `.tmp` 再 `os.replace` —— 被杀时盘上要么是旧候选、要么是新候选。"""

    def test_lf_survives_the_platform(self):
        """`newline="\\n"` 挡的是 **Windows 文本模式的自动翻译**：默认模式下写
        `"a\\nb"` 会在盘上变成 `a\\r\\nb`。同一份产物在两台机器上字节不同，
        「逐字节相等」类的比对全部失效 —— 本仓库已经在这上面栽过。
        （输入里自带的 CR 不在本函数职责内：官方版本也是原样透传。）"""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "solution.cpp")
            save_solution(path, "int a;\nint b;\n")
            with open(path, "rb") as fh:
                body = fh.read()
            self.assertEqual(body, b"int a;\nint b;\n",
                             "落盘被平台翻译成了 CRLF（或改了内容）")
            self.assertFalse(os.path.exists(path + ".tmp"),
                             "留下了 .tmp —— 下次运行会把陈旧内容当成候选")

    def test_overwrite_replaces_content(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "solution.cpp")
            save_solution(path, "first\n")
            save_solution(path, "second\n")
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), "second\n")


class TestCaliberDefaults(unittest.TestCase):
    """出厂默认的**采样口径**必须与官方 baseline.py 的常量同值（`serve/test_package_hls.py
    §4` 查 env.sh，这里查**代码**：评测方直接调 run.sh 时 env.sh 不一定被 source）。

    ★ `max_tokens` / `timeout_s` **不是采样口径**，本包这两个值与基线**故意不同**
      （2026-10-22 起 8192 / 900；基线侧仍是 `MAX_TOKENS=16384 / TIMEOUT_S=840`，
      `baseline.py` 一个字节不动）：
        - `max_tokens` 是**每轮预算旋钮**（本包一题内有多轮，基线一次写到底）；
        - `timeout_s` 是**客户端读超时**，同一段 (prompt, 采样口径) 生成什么，
          与等多久放弃无关。
      出处在 `results/deadline-removal-20261022/PREREG.md` §2.3/§2.4。
      采样轴（temperature / top_p）仍必须逐字相等 —— 那两个动了，分子分母就
      不在同一条件下测，增益解释不了。
    """

    KEYS = ("LLM_MAX_TOKENS", "LLM_TEMPERATURE", "LLM_TOP_P", "LLM_TIMEOUT_S",
            "LLM_THINK", "LLM_EXTRA_BODY", "LLM_STREAM")

    def test_sampling_caliber_matches_and_budget_knobs_are_ours(self):
        saved = {k: os.environ.pop(k, None) for k in self.KEYS}
        try:
            llm = LLM()
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v
        # 采样口径：与 baseline.py 逐字相同（动了 = 分子分母不可比）
        self.assertEqual(llm.temperature, 0.0)
        self.assertEqual(llm.top_p, 1.0)
        # 每轮预算 / 读超时：本包自己的值（2026-10-22 预登记 §2.3/§2.4）
        self.assertEqual(llm.max_tokens, 8192)
        self.assertEqual(llm.timeout_s, 900.0)
        self.assertIsNone(llm.think, "未设 LLM_THINK 时必须是「不发」而不是 False")
        # 流式缺省开（PREREG §2.5）；LLM_STREAM=0 才回落旧路径
        self.assertTrue(llm.stream)


# ---------------------------------------------------------------------------
# E1/E2（2026-10-25，PREREG results/agent-fix2-20261025/）
# ---------------------------------------------------------------------------

class TestKernelCompileClassify(unittest.TestCase):
    """E1：`classify_no_exe` 认**编译器的小写诊断**指着待测源码（kernel 编不过）。

    逐字证据（#278 归档 trace，PREREG §1②）：
      packFloat64 r2  `../../../../kernel.cpp:9:5: error: unknown type name 'uint64_t'`
      gnnbuilder r3   `../../../../kernel.cpp:43:19: error: use of undeclared identifier
                       'neighbor_table_offsets_temp'; did you mean 'neightbor_…'?`
    两轮的 `level` 都是 1、`kind` 都是空 —— 因为它们落进了 `Compiling <src>` 支，
    模型只拿到一句「形参不符/符号缺失最常见」的猜测，编译器原文被丢掉。
    """

    SRC = "kernel.cpp"

    @staticmethod
    def _log(lines, compiling=True):
        head = ("INFO: [HLS 200-2191] C-Simulation will use clang-16 as the compiler\n")
        if compiling:
            head += "INFO: [HLS 200-10] Compiling kernel.cpp in debug mode\n"
        return head + lines + (
            "ERROR: [SIM 211-100] CSim file generation failed: compilation error(s).\n")

    def test_lowercase_kernel_diagnostic_is_kernel_compile(self):
        out = self._log(
            "../../../../kernel.cpp:9:5: error: unknown type name 'uint64_t'\n"
            "../../../../kernel.cpp:13:5: error: unknown type name 'uint64_t'\n")
        got = classify_no_exe(out, self.SRC)
        self.assertEqual(got.get("kind"), "kernel-compile",
                         "kernel 自己编不过，却被归成了「与测试台合不来」")
        self.assertEqual(got.get("level"), 1, "官方判分对这种形状给 L1")
        self.assertIsNone(got.get("env"), "编译错不是环境故障")
        self.assertIn("unknown type name", got.get("note", ""),
                      "编译器原文没进 note —— 模型只会收到一句猜测")
        self.assertIn("kernel.cpp:9:5", got.get("note", ""))

    # 负对照 ⑬：`Compiling <src>` 的**进度行**必须在场也赢不了诊断行 ——
    # 这正是 packFloat64 r2 与 gnnbuilder r3 的真实形状（两支同时出现）。
    def test_diagnostic_wins_over_the_progress_line(self):
        out = self._log(
            "../../../../kernel.cpp:43:19: error: use of undeclared identifier "
            "'neighbor_table_offsets_temp'; did you mean 'neightbor_table_offsets_temp'?\n")
        got = classify_no_exe(out, self.SRC)
        self.assertIn("neightbor", got.get("note", ""),
                      "拼写建议被丢了 —— 那条建议就是改法")
        self.assertEqual(got.get("kind"), "kernel-compile")

    # 负对照 ⑭：只有进度行、没有诊断行 ⇒ 仍是既有的 level 1（无 kind）。
    def test_progress_line_alone_stays_level1(self):
        got = classify_no_exe(self._log(""), self.SRC)
        self.assertEqual(got.get("level"), 1)
        self.assertIsNone(got.get("kind"), "kernel 编到了还被记成 kernel-compile")

    # 负对照 ⑮：诊断行指着**别的文件**（TB 的）不许被这一支抢走。
    # ★ 这条日志**不能**带 `Compiling kernel.cpp`：TB 先挂时 kernel 根本没编到，
    #   带进度行的日志是「kernel 编过了、合不到一起」那一形，另一支的领地。
    def test_diagnostic_pointing_at_testbench_stays_testbench_compile(self):
        got = classify_no_exe(self._log(
            "../../../../agent_tb.cpp:7:1: error: expected ';'\n",
            compiling=False), self.SRC)
        self.assertEqual(got.get("kind"), "testbench-compile")
        self.assertNotEqual(got.get("kind"), "kernel-compile")

    # 负对照 ⑯：大写 `ERROR: … kernel.cpp …`（工具自己的消息）仍走 level 0 ——
    # 两支不是同一件事，抢过去会把「源码不可解析」降级成「编译错」。
    def test_uppercase_tool_error_still_level0(self):
        got = classify_no_exe(
            "ERROR: [HLS 214-157] cannot open kernel.cpp\n", self.SRC)
        self.assertEqual(got.get("level"), 0)
        self.assertIsNone(got.get("kind"))


class TestHostKernelProbe(unittest.TestCase):
    """E2：宿主 g++ 的语法体检。**它是补充信号，不是判据的替代品。**

    四条保守规则的每一条都要有负对照（PREREG §3 E2）：
      ok / fail / skipped（缺头）/ skipped（无编译器）。
    最贵的方向是**假阴性**：把一份正确的 kernel 判成编不过 —— 那会把模型锁死在
    为它编出来的错误上，而且它每一轮都会得到同一句话。
    """

    NEED_GXX = shutil.which("g++") is not None

    def _probe(self, kernel, **kw):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "kernel.cpp"), "w", encoding="utf-8") as fh:
                fh.write(kernel)
            return host_kernel_probe(d, "kernel.cpp", timeout_s=60.0, **kw)

    @unittest.skipUnless(NEED_GXX, "本机没有 g++（宿主探测在这台机器上只能 skipped）")
    def test_clean_kernel_is_ok(self):
        got = self._probe("int add(int a, int b) { return a + b; }\n")
        self.assertEqual(got["status"], "ok", got)
        self.assertEqual(got["diags"], [])

    @unittest.skipUnless(NEED_GXX, "本机没有 g++")
    def test_missing_stdint_include_is_fail(self):
        # 逐字复刻 packFloat64 的病：用 uint64_t 而不 include <stdint.h>。
        got = self._probe(
            "uint64_t pack(double x) { return (uint64_t)x; }\n")
        self.assertEqual(got["status"], "fail", got)
        self.assertTrue(any("kernel.cpp:" in d for d in got["diags"]),
                        "诊断行没有指着 kernel：%r" % (got["diags"],))

    @unittest.skipUnless(NEED_GXX, "本机没有 g++")
    def test_vitis_only_header_is_skipped_not_fail(self):
        # 6/20 题（fixed__small 四件、block_mm、popcount）的接口头含 ap_int.h。
        # 宿主没有它 ⇒ **不许**判 kernel 编不过（PREREG §1⑤）。
        got = self._probe('#include <ap_int.h>\nint f() { return 0; }\n')
        self.assertEqual(got["status"], "skipped", got)
        self.assertIn("缺头", got.get("why", ""))

    def test_no_host_compiler_is_skipped(self):
        got = self._probe("int f() { return 0; }\n",
                          cxx="__no_such_cxx_anywhere_xyz__")
        self.assertEqual(got["status"], "skipped")
        self.assertEqual(got["diags"], [])

    @unittest.skipUnless(NEED_GXX, "本机没有 g++")
    def test_other_files_errors_do_not_count(self):
        # 体检只编 kernel.cpp；旁边一个坏文件不构成关于 kernel 的结论。
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "kernel.cpp"), "w", encoding="utf-8") as fh:
                fh.write("int f() { return 0; }\n")
            with open(os.path.join(d, "tb.cpp"), "w", encoding="utf-8") as fh:
                fh.write("int main() { return nope; }\n")
            got = host_kernel_probe(d, "kernel.cpp", timeout_s=60.0)
        self.assertEqual(got["status"], "ok", got)


class TestCsimHostGate(unittest.TestCase):
    """E2 的接线：probe=fail 时**不起 Vitis**；probe=skipped 时照常起。

    桩只替换 `tools._run`，`csim()` 本体一行不改 —— 测的是它真正会走的路径。
    """

    NEED_GXX = shutil.which("g++") is not None
    TB = "int main() { return 0; }\n"

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="hls_test_")
        self._old = os.environ.get("AGENT_TMP")
        os.environ["AGENT_TMP"] = self.tmp

    def tearDown(self):
        if self._old is None:
            os.environ.pop("AGENT_TMP", None)
        else:
            os.environ["AGENT_TMP"] = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _csim(self, kernel):
        import agent.tools as T
        t = T.HlsToolchain.__new__(T.HlsToolchain)   # 不跑 __init__（那会找 vitis-run）
        t.part, t.period_ns, t.reason = T.PART, T.PERIOD_NS, ""
        t.exe = "vitis-run-stub"                      # available=True
        calls = []
        real = T._run

        def fake(cmd, cwd, timeout_s):
            # ★ 只拦 Vitis 那一条。宿主的 g++ 体检也走 `_run` —— 全拦下来的话
            #   probe 会看到 rc=0，于是「编不过的 kernel」被判成 ok，两个用例
            #   就都变成了对同一句话的自证。
            if str(cmd[0]) != "vitis-run-stub":
                return real(cmd, cwd, timeout_s)
            calls.append(cmd)
            return 0, ""                              # 没有 csim.exe ⇒ 走分类链

        T._run = fake
        try:
            r = t.csim(kernel, self.TB, "f")
        finally:
            T._run = real
        return r, calls

    @unittest.skipUnless(NEED_GXX, "本机没有 g++")
    def test_broken_kernel_never_starts_vitis(self):
        r, calls = self._csim("uint64_t f(double x) { return (uint64_t)x; }\n")
        self.assertEqual(r.get("kind"), "kernel-compile")
        self.assertEqual(r.get("level"), 1)
        self.assertEqual(calls, [], "kernel 编不过时仍然起了 Vitis —— 白烧一轮 EDA")
        self.assertEqual(r["kernel_check"]["status"], "fail")

    @unittest.skipUnless(NEED_GXX, "本机没有 g++")
    def test_vitis_only_kernel_still_goes_to_vitis(self):
        # 缺头 ⇒ skipped ⇒ 必须照常起 Vitis（不许短路）。
        r, calls = self._csim('#include <ap_int.h>\nint f() { return 0; }\n')
        self.assertEqual(r["kernel_check"]["status"], "skipped")
        self.assertEqual(len(calls), 1, "skipped 时短路了 —— 正确的 kernel 会被锁死")
        self.assertEqual(r["stages"]["host_syntax"]["status"], "skipped")


class TestKernelCompileWording(unittest.TestCase):
    """E3：kind → 给模型看的话。分类错，模型就会去改一份本来正确的东西。"""

    def _sc(self, **kw):
        sc = {"level": 1, "env": None, "rc": 1, "note": "", "log": "", "stages": {}}
        sc.update(kw)
        return sc

    def test_kernel_compile_head_talks_about_the_kernel(self):
        out = _classify(1, self._sc(kind="kernel-compile",
                                    note="kernel.cpp:9:5: error: unknown type name"))
        self.assertIn("kernel 自己编不过", out)
        self.assertNotIn("编不到一起", out,
                         "kernel 编不过被讲成「与测试台合不来」—— 模型会去改测试台")

    def test_testbench_compile_head_names_the_overload_exception(self):
        # block_mm 的坑：TB 报 `no matching function for call to 'blockmatmul'`，
        # 而真凶是 kernel 的形参类型（交付 kernel 官方 L4）。
        out = _classify(None, self._sc(kind="testbench-compile", note="x"))
        self.assertIn("例外", out)
        self.assertIn("形参", out)


class TestFix3NoPinnedRounds(unittest.TestCase):
    """fix3（2026-10-25）：**修复轮的提示词不许逐字节重复**。

    病灶有逐字存档（`results/agent-fix2-20261025/pair20-fix2-20261025/` 的逐轮 trace）：
    修复轮的 user 消息 = 题面 + repair({{KIND}}/{{LOG}}/{{CODE}})，**不带对话历史**。
    一轮失败而 `best` 没变时三个替换值一个都没变 ⇒ 提示词逐字节相同 ⇒ 温度 0.0
    下输出也逐字节相同 ⇒ 那一轮必然白烧。两例：

        c2hlsc__add_round_key  repair-log r2 == r3（`5f878a92b16674d3`），
                               llm 输出 r2/r3 都是 1,345 B / 448 tok
        machsuite__aes_aes     repair-log r2 == r3（`c1adcf7d15a432f5`），
                               llm 输出 r2/r3 都是 9,183 B / 8,192 tok

    每条都配负对照：**该红的必须红**（同一份文件要被抓出来、插入符不许指到别的代码上），
    **该绿的必须绿**（不同的文件不许被误报成重复、正常的闭合围栏不许被截错）。
    """

    INTERFACE = TestSolveKeepsSomething.INTERFACE
    TOP = TestSolveKeepsSomething.TOP
    KERNEL = TestSolveKeepsSomething.KERNEL
    TB_LONG = TestSolveKeepsSomething.TB_LONG

    def _solve(self, replies, stub=None):
        import agent.main as m
        with tempfile.TemporaryDirectory() as d:
            for fname, text in (("prompt.txt", "Top-Level Function : `add128`\n"),
                                ("interface.txt", self.INTERFACE),
                                ("top.txt", "add128\n")):
                with open(os.path.join(d, fname), "w", encoding="utf-8") as fh:
                    fh.write(text)
            task = m.Task(d)
            top, _src = task.resolve_top()
            tpath = os.path.join(d, "trace.jsonl")
            trace = m.Trace(tpath)
            real = m.HlsToolchain
            m.HlsToolchain = stub or _StubHls      # ★ 一次 EDA 都不跑
            llm = _StubLLM(replies)
            try:
                out = m.solve(llm, trace, task, top, save=lambda c: None)
            finally:
                m.HlsToolchain = real
                trace.close()
            self.last_llm = llm
            with open(tpath, encoding="utf-8") as fh:
                self.last_trace = [json.loads(ln) for ln in fh if ln.strip()]
        return out

    def _rows(self, tool):
        return [r for r in self.last_trace if r.get("tool") == tool]

    # ── {{HISTORY}}：重复提交必须被讲出来 ──────────────────────────────────
    def test_history_flags_the_same_file_sent_twice(self):
        import agent.main as m
        blk = m._history_block([
            {"round": 1, "kind": "kernel-compile", "sha16": "aaaaaaaaaaaaaaaa"},
            {"round": 2, "kind": "kernel-compile", "sha16": "aaaaaaaaaaaaaaaa"},
        ])
        self.assertIn("exact same kernel file", blk)
        self.assertIn("(= round 1)", blk)

    def test_history_is_empty_before_the_first_failure(self):
        import agent.main as m
        self.assertEqual(m._history_block([]), "",
                         "第 2 轮就塞历史 —— 那会把题面本身挤掉")

    # 负对照：两个**不同**的文件不许被讲成重复（假的红会驱动模型去改对的东西）。
    def test_history_does_not_cry_repeat_on_different_files(self):
        import agent.main as m
        blk = m._history_block([
            {"round": 1, "kind": "kernel-compile", "sha16": "aaaaaaaaaaaaaaaa"},
            {"round": 2, "kind": "kernel-compile", "sha16": "bbbbbbbbbbbbbbbb"},
        ])
        self.assertIn("Attempts so far", blk)
        self.assertNotIn("exact same kernel file", blk)

    # 负对照：抽取失败那轮没有 kernel（sha16=None）—— 不许把两个空轮判成重复。
    def test_history_treats_missing_kernel_as_unknown(self):
        import agent.main as m
        blk = m._history_block([
            {"round": 1, "kind": "no-code", "sha16": None},
            {"round": 2, "kind": "no-code", "sha16": None},
        ])
        self.assertIn("Attempts so far", blk)
        self.assertNotIn("exact same kernel file", blk)

    # ── {{FOCUS}}：编译器指着的那一行 ─────────────────────────────────────
    def test_error_focus_underlines_the_reported_line(self):
        import agent.main as m
        code = ('#include "x.h"\n'
                'void f() {\n'
                '    state[i][j] ^= key[idx];\n'
                '}\n')
        out = m._error_focus("../../../../kernel.cpp:3:17: error: bad operands", code)
        self.assertIn("line 3, column 17", out)
        self.assertIn("state[i][j] ^= key[idx];", out)
        self.assertIn("^", out)

    # 负对照：行号越界 ⇒ 什么都不画（画出来就是一条**看起来很像真的**指引）。
    def test_error_focus_is_silent_when_the_line_is_out_of_range(self):
        import agent.main as m
        self.assertEqual(m._error_focus("kernel.cpp:99:1: error: boom", "int a;\n"), "")

    # 负对照：错误行指着**测试台** ⇒ 不出插入符（要改的不是 kernel）。
    def test_error_focus_is_silent_for_testbench_errors(self):
        import agent.main as m
        self.assertEqual(
            m._error_focus("agent_tb.cpp:6:15: error: expected unqualified-id",
                           "int a;\nint b;\n"), "")

    # ── solve() 端到端：同一份文件连交两轮，提示词必须变 ────────────────────
    def test_a_repeated_file_no_longer_repeats_the_prompt(self):
        import agent.main as m
        reply = self.KERNEL + "\n" + self.TB_LONG
        stub = _scripted([{"level": 1, "env": None, "kind": "kernel-compile",
                           "note": "kernel.cpp:3:1: error: boom"}] * m.MAX_ROUNDS)
        self._solve([reply] * m.MAX_ROUNDS, stub=stub)
        seen = [msgs[-1]["content"] for msgs in self.last_llm.seen]
        self.assertEqual(len(seen), m.MAX_ROUNDS, "没走满轮次，这条测试的前提不成立")
        self.assertNotIn("Attempts so far", seen[0], "第 1 轮就带了修复历史")
        # 台账每轮长一条 ⇒ **每一对相邻轮**都必须逐字节不同（不许只查 r2/r3）。
        for i in range(1, len(seen)):
            self.assertIn("Attempts so far", seen[i], "第 %d 轮没带前一轮的台账" % (i + 1))
            self.assertNotEqual(seen[i - 1], seen[i],
                                "第 %d/%d 轮提示词仍然逐字节相同 —— 定点空转没破"
                                % (i, i + 1))
        self.assertIn("exact same kernel file", seen[2],
                      "同一份文件连交两轮，第 3 轮没被告知")
        self.assertIn("The compiler points at line 3", seen[2],
                      "编译器指着的行没画给模型（= 插入符闸恒假的老毛病）")
        # G6：trace 里的提示词指纹必须同样说明这件事。
        shas = [r["sha16"] for r in self._rows("prompt")]
        self.assertEqual(len(shas), m.MAX_ROUNDS)
        for i in range(1, len(shas)):
            self.assertNotEqual(shas[i - 1], shas[i],
                                "trace 里 r%d/r%d 提示词指纹相同" % (i, i + 1))

    # 负对照：**没重复提交**时不该出现那句警告（否则它变成噪音）。
    def test_changing_kernel_does_not_trigger_the_repeat_warning(self):
        other = self.KERNEL.replace("(z1 < a1) ? 1 : 0", "(z1 >= a1) ? 0 : 1")
        stub = _scripted([{"level": 1, "env": None, "kind": "kernel-compile",
                           "note": "kernel.cpp:3:1: error: boom"}] * 3)
        self._solve([self.KERNEL + "\n" + self.TB_LONG,
                     other + "\n" + self.TB_LONG,
                     other + "\n" + self.TB_LONG], stub=stub)
        seen = [msgs[-1]["content"] for msgs in self.last_llm.seen]
        self.assertNotIn("exact same kernel file", seen[2])

    # ── 截断 + 抽不出可用 kernel：不许交白卷，且下一轮换问法 ─────────────────
    def test_truncated_unusable_kernel_is_kept_and_asks_for_the_kernel_only(self):
        # 围栏没闭合（= 被截断），里面是个**名字不对**的实现 ⇒ 签名闸必红。
        bad = ('```cpp\n#include <cstdio>\n'
               'void add128_v2(int a) { (void)a; }\n')
        out = self._solve([(bad, "length")] * 3)
        # ★ fix20（A.10 §3 B）：交付件从「那份签名不过的截断原文」换成了**接口桩**。
        #   签名闸不过现在记 kok=-1（原 0），`_stub_fallback` 因此不再静默跳过。
        #   G1 的不变量没变（**不许交白卷**）—— 见下面那条桩编不过的负对照。
        self.assertNotIn("void add128_v2", out, "签名闸不过的截断稿仍然被交了出去")
        self.assertIn("compile-only fallback", out)
        self.assertIn("void add128(", out)
        self.assertNotIn("```", out, "未闭合的围栏行被当成 kernel 交了出去")
        seen = [msgs[-1]["content"] for msgs in self.last_llm.seen]
        self.assertIn("truncated-bad-kernel", seen[1],
                      "截断+抽不出 kernel 仍被讲成「测试台太长」")
        self.assertIn("只输出一个", seen[1], "没有换成「只要 kernel」的答题形状")
        # G5：抽取失败那一轮必须留下原文（fix2 的 aes 9 KB 一字节都没留）。
        ext = self._rows("extract")
        self.assertTrue(ext and ext[0]["diag"], "截断轮没落 diag")
        self.assertIn("add128_v2", ext[0]["raw_excerpt"] or "")

    # 负对照：桩自己编不过 ⇒ fix3 G1 的场景原样保留（**不许交白卷**）。
    def test_truncated_unusable_kernel_survives_a_failing_stub(self):
        """fix20 只换掉了「谁赢」，没有取消「非空候选必须留下」。

        G1 的账（ADDENDUM A.3）：0 B 是实测过的 L0，而一份能解析的源码至少 L1。
        桩编不过时 `_stub_fallback` 必须**不动**那份截断稿，并落 `applied=false`。
        """
        bad = ('```cpp\n#include <cstdio>\n'
               'void add128_v2(int a) { (void)a; }\n')
        old = _StubHls.syntax_status
        _StubHls.syntax_status = "fail"
        try:
            out = self._solve([(bad, "length")] * 3)
        finally:
            _StubHls.syntax_status = old
        self.assertIn("void add128_v2", out,
                      "桩编不过时把能解析的截断稿扔了 ⇒ 交白卷（实测过的 L0）")
        fb = self._rows("fallback")
        self.assertTrue(fb, "兜底没落任何 trace 行（fix20 之后这本身就是缺陷）")
        self.assertIs(fb[-1]["applied"], False)

    # 负对照：**抽得出、签名过**的截断轮仍走原话术（别把好轮也改问法）。
    def test_truncated_good_kernel_keeps_the_old_wording(self):
        self._solve([(self.KERNEL, "length")] * 3)
        seen = [msgs[-1]["content"] for msgs in self.last_llm.seen]
        self.assertIn("truncated", seen[1])
        self.assertNotIn("truncated-bad-kernel", seen[1])
        self.assertNotIn("只输出一个", seen[1])
        # ★ fix12 的边界（ADDENDUM A.3 更正）：体检 `skipped`（宿主不给结论）⇒
        #   **提示词与 best 记账与 fix11 逐字节相同**，只多一行 `kernel-syntax` 观测痕
        #   （「跑过没有」不许靠推断）。**不许**落 selfcheck 失败行。
        ks = self._rows("kernel-syntax")
        self.assertTrue(ks, "体检跑没跑又只能靠推断了")
        self.assertEqual({r.get("status") for r in ks}, {"skipped"})
        self.assertFalse(self._rows("selfcheck"), "skipped 被记成了失败")

    # ★ fix12（改动 A，ADDENDUM A.3）：截断轮**也要有一次编译器证据**。
    #   病灶（run3 k=12 `machsuite__aes_aes`）：四轮全 `finish_reason=length` ⇒
    #   四轮全从截断支 `continue`，而宿主体检只挂在「没有测试台」支上 ⇒ 环里一次
    #   编译都没跑；交出的 7,879 B kernel 在判分链上是 13 条
    #   `use of undeclared identifier 'ctx'`，模型四轮只收到「把测试台写短」。
    def test_truncated_kernel_that_fails_host_compile_brings_the_compiler_text(self):
        stub = type("_StubSyntaxFail", (_StubHls,), {
            "syntax_status": "fail",
            "syntax_diags": ["kernel.cpp:146:34: error: 'ctx' was not declared in this scope"],
        })
        out = self._solve([(self.KERNEL, "length")] * 3, stub=stub)
        seen = [msgs[-1]["content"] for msgs in self.last_llm.seen]
        self.assertIn("was not declared in this scope", seen[1],
                      "截断轮的编译器原文没进下一轮提示词（= k=12 的病灶）")
        self.assertIn("kernel 自己编不过", seen[1], "负证据没按 kernel-compile 归类")
        self.assertIn("只输出一个", seen[1], "没有换成「只要 kernel」的答题形状")
        self.assertIn("max_tokens", seen[1], "没告诉模型这是**撞帽**、不是格式错")
        sc = self._rows("selfcheck")
        self.assertTrue(sc and sc[0].get("kind") == "kernel-compile",
                        "截断轮的宿主体检没落 selfcheck 行")
        self.assertEqual(sc[0].get("kok"), -1, "编不过的稿子没记 kok=-1")
        self.assertIn("void add128", out, "截断支的兜底候选被这条改动弄丢了")
        self.assertNotIn("```", out)

    # 负对照：体检说 **ok** 时不许换话术（截断仍是「预算不够」），但「跑过没有」
    #   必须落痕（`tool="kernel-syntax"`），否则又是靠推断。
    def test_truncated_kernel_with_clean_host_compile_keeps_the_old_wording(self):
        stub = type("_StubSyntaxOk", (_StubHls,), {"syntax_status": "ok"})
        self._solve([(self.KERNEL, "length")] * 3, stub=stub)
        seen = [msgs[-1]["content"] for msgs in self.last_llm.seen]
        self.assertIn("truncated", seen[1])
        self.assertNotIn("只输出一个", seen[1], "编得过的截断轮也被改问法了")
        ks = self._rows("kernel-syntax")
        self.assertTrue(ks, "体检没落痕 —— 「跑没跑」又只能靠推断")
        self.assertEqual(ks[0].get("status"), "ok")
        self.assertFalse(self._rows("selfcheck"), "编得过却落了 selfcheck 失败行")

    # ── 未闭合围栏：不许把 ```cpp 那行带进 kernel ───────────────────────────
    def test_unclosed_fence_is_stripped_from_the_kernel(self):
        text = ('```cpp\n#include "add128.h"\n'
                'void add128(bits64 a0) { (void)a0; }\n')
        k, _tb, note = extract_blocks(text, "add128")
        self.assertFalse(k.lstrip().startswith("```"),
                         "未闭合的围栏行被原样当成 kernel 交了出去")
        self.assertIn("void add128", k)
        self.assertIn("没有闭合", note)

    # 负对照：**闭合**的围栏照旧走原路（防的是把正常回复也截错）。
    def test_closed_fence_still_extracts_normally(self):
        k, tb, note = extract_blocks(self.KERNEL + "\n" + self.TB_LONG, "add128")
        self.assertIn("void add128", k)
        self.assertIn("int main", tb)
        self.assertNotIn("没有闭合", note or "")

    # ── 诊断：抽取失败要留下原文，否则「它在写什么」只能猜 ───────────────────
    def test_reply_diag_separates_looping_from_normal_text(self):
        import agent.main as m
        d = m._reply_diag("x\n" * 200, "add128")
        self.assertGreater(d["max_line_repeat"], 1, "复读的行没被读出来")
        self.assertEqual(d["lines"], 200)
        ok = m._reply_diag("int a;\nint b;\nint c;\n", "add128")
        self.assertEqual(ok["max_line_repeat"], 1)
        self.assertEqual(ok["uniq_lines"], 3)

    # 负对照：no-code 那一支的 `excerpt` 是**已有字段**，离线仪器读它（kb_mine）。
    # 原文只能进新字段 `raw_excerpt`，不许把旧字段的语义改掉。
    def test_no_code_branch_keeps_the_old_excerpt_and_adds_raw(self):
        self._solve([("I cannot help with that request.", "stop")] * 3)
        ext = self._rows("extract")
        self.assertTrue(ext)
        self.assertEqual(ext[0]["excerpt"], "no code block in reply")
        self.assertIn("cannot help", ext[0]["raw_excerpt"] or "")


class TestFix4CarriedContext(unittest.TestCase):
    """fix4（2026-10-25）：修复轮**续写**，并且摆出来的是「刚被编译的那份」。

    病灶有逐轮存档（`results/agent-fix3-20261025/pair20-fix3-20261025/`）：

      · `agent/prompts/repair.md` 只回灌 kernel，**测试台从不回灌**。于是模型每轮
        靠记忆重写测试台：`gramschmidt` 的 `hls_sqrt`、`2mm` 的 `ref_mmul`、
        `doitgen` 的 `no matching function`，同一处错在三轮里逐字重复。
      · `{{CODE}}` 摆的是 `best`，而日志行号相对的是**刚才被编译的那一份**。两者
        一旦不是同一个文件，插入符就画在别人的代码上（假的红比漏报更危险）。

    每条都配负对照：第 1 轮不许带历史；没失败时不许凭空冒出修复段。
    """

    INTERFACE = TestSolveKeepsSomething.INTERFACE
    TOP = TestSolveKeepsSomething.TOP
    KERNEL = TestSolveKeepsSomething.KERNEL
    TB_LONG = TestSolveKeepsSomething.TB_LONG

    def _solve(self, replies, stub=None):
        import agent.main as m
        with tempfile.TemporaryDirectory() as d:
            for fname, text in (("prompt.txt", "Top-Level Function : `add128`\n"),
                                ("interface.txt", self.INTERFACE),
                                ("top.txt", "add128\n")):
                with open(os.path.join(d, fname), "w", encoding="utf-8") as fh:
                    fh.write(text)
            task = m.Task(d)
            top, _src = task.resolve_top()
            tpath = os.path.join(d, "trace.jsonl")
            trace = m.Trace(tpath)
            real = m.HlsToolchain
            m.HlsToolchain = stub or _StubHls      # ★ 一次 EDA 都不跑
            llm = _StubLLM(replies)
            try:
                out = m.solve(llm, trace, task, top, save=lambda c: None)
            finally:
                m.HlsToolchain = real
                trace.close()
            self.last_llm = llm
            with open(tpath, encoding="utf-8") as fh:
                self.last_trace = [json.loads(ln) for ln in fh if ln.strip()]
        return out

    def _rows(self, tool):
        return [r for r in self.last_trace if r.get("tool") == tool]

    # ── H1：模型能看见**自己的**测试台 ──────────────────────────────────────
    def test_previous_reply_is_carried_verbatim(self):
        reply = self.KERNEL + "\n" + self.TB_LONG
        stub = _scripted([{"level": 1, "env": None, "kind": "kernel-compile",
                           "note": "kernel.cpp:3:1: error: boom"}] * 3)
        self._solve([reply, reply, reply], stub=stub)
        msgs = self.last_llm.seen
        self.assertEqual(len(msgs[0]), 2, "第 1 轮就带了对话历史")
        self.assertGreaterEqual(len(msgs[1]), 4,
                                "第 2 轮没有把上一轮的原话接上（模型只能靠记忆重写测试台）")
        asst = [m for m in msgs[1] if m["role"] == "assistant"]
        self.assertEqual(len(asst), 1, "assistant 段不是恰好一条")
        # 这条是 H1 的全部内容：它自己的测试台（`ref_add128`）得真的在它眼前。
        self.assertIn("ref_add128", asst[0]["content"],
                      "上一轮原话里没有测试台 —— 回灌仍然只有 kernel")
        self.assertNotIn("ref_add128", msgs[0][-1]["content"],
                         "第 1 轮凭空出现了参考实现（负对照）")

    # 负对照：任何一轮都不许发**空的** assistant 段（部分服务栈直接 400）。
    def test_no_round_sends_an_empty_assistant_message(self):
        self._solve([self.KERNEL + "\n" + self.TB_LONG] * 3,
                    stub=_scripted([{"level": 1, "env": None,
                                     "kind": "kernel-compile",
                                     "note": "kernel.cpp:3:1: error: boom"}] * 3))
        for i, msgs in enumerate(self.last_llm.seen):
            for m in msgs:
                self.assertTrue(m["content"].strip(),
                                "第 %d 轮发了一条空的 %s 消息" % (i + 1, m["role"]))

    # ★ 快照：`conv` 是就地追加的，交给调用方的必须是**这一轮**的副本。
    #   实测教训：三条 prompt 记录指向同一个 list，第 1 轮被读成了第 3 轮。
    def test_each_round_gets_its_own_snapshot(self):
        self._solve([self.KERNEL + "\n" + self.TB_LONG] * 3,
                    stub=_scripted([{"level": 1, "env": None,
                                     "kind": "kernel-compile",
                                     "note": "kernel.cpp:3:1: error: boom"}] * 3))
        seen = self.last_llm.seen
        self.assertIsNot(seen[0], seen[1], "两轮拿到的是同一个 list 对象")
        self.assertEqual(len(seen[0]), 2, "第 1 轮的记录被后续轮次就地改写了")

    # ── H3：`{{CODE}}` 摆的是**上一轮真正被编译的**那份，不是 `best` ──────────
    def test_shown_code_is_the_file_that_was_actually_compiled(self):
        other = self.KERNEL.replace("(z1 < a1) ? 1 : 0", "(z1 >= a1) ? 0 : 1")
        stub = _scripted([{"level": 1, "env": None, "kind": "kernel-compile",
                           "note": "kernel.cpp:3:1: error: boom"}] * 3)
        self._solve([self.KERNEL + "\n" + self.TB_LONG,
                     other + "\n" + self.TB_LONG,
                     other + "\n" + self.TB_LONG], stub=stub)
        seen = [msgs[-1]["content"] for msgs in self.last_llm.seen]
        self.assertIn("(z1 < a1) ? 1 : 0", seen[1], "第 2 轮没摆出第 1 轮的 kernel")
        # 第 2 轮的 kernel 与第 1 轮同为 level 1 ⇒ `best` 仍是第 1 轮那份；
        # 但第 3 轮摆的必须是**第 2 轮刚编译过的**那份。
        self.assertIn("(z1 >= a1) ? 0 : 1", seen[2],
                      "摆的是 best 而不是刚被编译的那份 —— 行号会对到别人的代码上")
        self.assertNotIn("(z1 < a1) ? 1 : 0", seen[2],
                         "第 3 轮仍摆着第 1 轮的 kernel（= best 覆盖了刚编译的那份）")

    # ── H4：每轮成功抽取都要落一行读数（原来只有失败轮才落） ─────────────────
    def test_every_successful_extraction_writes_a_trace_row(self):
        self._solve([self.KERNEL + "\n" + self.TB_LONG] * 3)
        ext = [r for r in self._rows("extract") if r.get("truncated") is False]
        self.assertEqual(len(ext), 3, "成功轮没有逐轮落抽取读数")
        for r in ext:
            self.assertTrue(r.get("kernel_sha16"), "抽取行没记 kernel 的 sha16")
            self.assertGreater(r.get("kernel_bytes") or 0, 0)

    # ── H3/H1 的**读数**：标签必须和提示词里真的摆了什么一致 ──────────────────
    #   这两列是运行时唯一的机制证据（面板 CHECK 直接数它们）。读数器读错字段名
    #   不会报错，只会给出一个很像真的数 —— 所以至少在这一层把它钉住：
    #   `code_src != "-"` ⟺ 提示词里真的有一段 kernel；`ctx` 对得上消息条数。
    def test_mechanism_labels_match_what_was_actually_sent(self):
        import agent.main as m
        self._solve([self.KERNEL + "\n" + self.TB_LONG] * m.MAX_ROUNDS)
        rows = self._rows("prompt")
        self.assertEqual(len(rows), m.MAX_ROUNDS, "prompt 行数 ≠ 轮数")
        marker = "(z1 < a1) ? 1 : 0"      # 只在 kernel 正文里，接口/题面里没有
        for i, (row, msgs) in enumerate(zip(rows, self.last_llm.seen)):
            has_code = marker in msgs[-1]["content"]
            self.assertEqual(
                row.get("code_src") != "-", has_code,
                "第 %d 轮 code_src=%r，而提示词里%s kernel" %
                (i + 1, row.get("code_src"), "有" if has_code else "没有"))
            self.assertEqual(
                row.get("ctx"), "fresh" if len(msgs) == 2 else "conv",
                "第 %d 轮 ctx=%r 与消息条数 %d 对不上（读数与实物分岔）" %
                (i + 1, row.get("ctx"), len(msgs)))
        self.assertEqual(rows[0].get("code_src"), "-",
                         "第 1 轮根本没有修复段，却标了摆代码（负对照）")
        self.assertEqual([r.get("ctx") for r in rows],
                         ["fresh"] + ["conv"] * (m.MAX_ROUNDS - 1),
                         "H1 没有从第 2 轮起续写")


class TestFix4LinkUndefined(unittest.TestCase):
    """H5：`undefined reference` 是**自己的一类**，不是「与测试台合不来」的泛化猜测。

    实测（fix3 面板）：`2mm` 第 2 轮的 kernel-compile 是
    `no matching function for call to 'mmul'`，而三次修复都没把 `mmul` 补出来 ——
    泛化 note 说的是「形参不符/符号缺失最常见」，模型读成了「改形参」。
    链接期缺符号的解法只有一种：**把那个定义补上**。
    """

    LOG = ("INFO: [SIM 211-1] CSim simulation started\n"
           "Compiling ../../../../kernel.cpp in csim mode\n"
           "kernel.o: In function `kernel_2mm(double*)':\n"
           "kernel.cpp:(.text+0x1a): undefined reference to `mmul(double*, double*)'\n"
           "collect2: error: ld returned 1 exit status\n")

    def test_undefined_reference_is_its_own_kind(self):
        r = classify_no_exe(self.LOG, "kernel.cpp")
        self.assertEqual(r.get("kind"), "link-undefined")
        self.assertEqual(r["level"], 1, "缺符号被报成了别的等级")
        self.assertIn("mmul", r["note"], "没告诉模型是哪个符号缺定义")
        self.assertIn("补上定义", r["note"])

    # 负对照：只有进度行、没有缺符号 ⇒ 不许被讲成缺符号。
    def test_compiling_alone_is_not_a_link_error(self):
        r = classify_no_exe("Compiling ../../../../kernel.cpp in csim mode\n"
                            "ERROR: [HLS 200-1715] no csim.exe\n", "kernel.cpp")
        self.assertNotEqual(r.get("kind"), "link-undefined")

    # 负对照：编译错与缺符号同时在场 ⇒ 编译错是**因**，缺符号是它没走到链接的果。
    def test_a_compile_error_outranks_the_link_error(self):
        log = ("Compiling ../../../../kernel.cpp in csim mode\n"
               "../../../../kernel.cpp:10:5: error: unknown type name 'foo'\n"
               "kernel.cpp:(.text+0x1a): undefined reference to `bar()'\n")
        r = classify_no_exe(log, "kernel.cpp")
        self.assertEqual(r.get("kind"), "kernel-compile")

    def test_wording_tells_the_model_to_add_a_definition(self):
        out = _classify(1, {"level": 1, "env": None, "kind": "link-undefined",
                            "note": "缺 `mmul`", "log": ""})
        self.assertIn("缺符号", out)
        self.assertIn("别改算法", out)
        self.assertNotIn("编不到一起", out, "缺符号被讲成「与测试台合不来」")


class TestFix4PromptRecipes(unittest.TestCase):
    """H2：两条**正向配方**必须真的在出厂 system.md 里。

    它们不是修辞：四条 agent L1（`add_round_key` / `aes` / `sort_radix` /
    `fixed__small__2mm`）的自验失败逐字是 `ambiguous operator '/'`、
    `no matching function for call to '<top>'`、`undeclared identifier 'hls_sqrt'`、
    `ref_mmul` 未定义 —— 每一条都对应下面的一行。
    """

    def _text(self):
        with open(os.path.join(ROOT, "agent", "prompts", "system.md"),
                  encoding="utf-8") as fh:
            return fh.read()

    def test_the_measured_tb_failures_have_a_recipe(self):
        text = self._text()
        self.assertIn("no matching function", text, "ap_fixed/double 形参那条没有配方")
        self.assertIn("ambiguous operator", text, "ap_fixed 混算那条没有配方")
        self.assertIn("hls::sqrt", text, "数学函数那条没有配方")
        self.assertIn("written out", text, "「自己写出来才算存在」那条没有配方")

    # 负对照：system.md 是**直接读的**，不是模板 —— 带占位符就是漏替换。
    def test_the_shipped_system_prompt_has_no_template_placeholders(self):
        self.assertNotIn("{{", self._text())


class TestFix8A(unittest.TestCase):
    """改动 A：测试台里的 `#include "<名字>.cpp"` 是**结构上不可能对**的一行。

    病灶（RESULTS `agent-fix7-20261025` §1.1 逐字）：aes 的第 2/3/4 轮全是
    `agent_tb.cpp:9:10: fatal error: 'aes256_encrypt.cpp' file not found`，
    而三轮之间 kernel 的 sha16 一字未变（`b03929b39837cf34`）—— 构建目录里
    没有任何 `.cpp` 可供 include，kernel 与测试台本来就是同一次 csim 里
    各自编成 TU 再链接。
    """

    TB = ('#include <cstdio>\n'
          '#include "kernel.h"\n'
          '#include <stdint.h>\n'
          '\n'
          'static int ref(int x) { return x + 1; }\n'
          '\n'
          'int main(void) {\n'
          '    int got = f(1);\n'
          '    return got == ref(1) ? 0 : 1;\n'
          '}\n')

    def test_the_aes_line_is_removed_and_line_numbers_are_kept(self):
        # 逐字复刻 aes 那一行所在的位置（第 9 行）。
        tb = ("#include <cstdio>\n"
              "#include \"kernel.h\"\n"
              "\n"
              "\n"
              "\n"
              "\n"
              "\n"
              "\n"
              "#include \"aes256_encrypt.cpp\"\n"
              "int main(void) { return 0; }\n")
        new, removed = strip_cpp_includes(tb)
        self.assertEqual(removed, ["aes256_encrypt.cpp"])
        self.assertNotIn('#include "aes256_encrypt.cpp"', new)
        self.assertIn("[harness] removed", new)
        # 行数不变 ⇒ 下一轮编译器给的 `agent_tb.cpp:<行>:<列>` 仍指着同一处。
        self.assertEqual(len(tb.splitlines()), len(new.splitlines()),
                         "删行改变了行号：下一轮的错误行会指到别的位置")
        self.assertEqual(new.splitlines()[8].count("aes256_encrypt.cpp"), 1,
                         "第 9 行没有被就地改写")

    def test_angle_bracket_form_and_other_cpp_suffixes(self):
        tb = ('#include <foo.cpp>\n#include "bar.cxx"\n#include "baz.cc"\n'
              'int main(void) { return 0; }\n')
        new, removed = strip_cpp_includes(tb)
        self.assertEqual(removed, ["foo.cpp", "bar.cxx", "baz.cc"])
        self.assertNotIn("foo.cpp>", new)

    # 负对照 ①：没有 `.cpp` include 的测试台必须**逐字节不变** —— 这条改动对
    # 绝大多数题应当是 no-op，若不是，它就是在悄悄改写模型交了正确的测试台。
    def test_no_cpp_include_is_byte_identical(self):
        new, removed = strip_cpp_includes(self.TB)
        self.assertEqual(removed, [])
        self.assertEqual(new, self.TB)

    # 负对照 ②：头文件 / 系统头不许被碰。
    def test_header_and_system_includes_are_untouched(self):
        new, removed = strip_cpp_includes(self.TB)
        self.assertIn('#include "kernel.h"', new)
        self.assertIn("#include <stdint.h>", new)
        self.assertIn("#include <cstdio>", new)

    # 负对照 ③：注释里的同形文字不许被当成 include 删掉。
    def test_commented_out_include_is_untouched(self):
        tb = '// #include "old.cpp"\nint main(void) { return 0; }\n'
        new, removed = strip_cpp_includes(tb)
        self.assertEqual(removed, [])
        self.assertEqual(new, tb)

    # 负对照 ④：模型若把 `.h` 写成 `.hpp`，那是**真头文件**，不许删。
    def test_hpp_is_not_a_cpp(self):
        tb = '#include "kernel.hpp"\nint main(void) { return 0; }\n'
        new, removed = strip_cpp_includes(tb)
        self.assertEqual(removed, [])
        self.assertEqual(new, tb)

    @unittest.skipUnless(shutil.which("g++") is not None, "本机没有 g++")
    def test_csim_writes_the_stripped_testbench(self):
        """端到端：`csim()` 真正写进工作目录的那份 TB 是**删过**的。"""
        import agent.tools as T
        tmp = tempfile.mkdtemp(prefix="hls_fix8a_")
        old = os.environ.get("AGENT_TMP")
        os.environ["AGENT_TMP"] = tmp
        t = T.HlsToolchain.__new__(T.HlsToolchain)
        t.part, t.period_ns, t.reason = T.PART, T.PERIOD_NS, ""
        t.exe = "vitis-run-stub"
        real = T._run

        def fake(cmd, cwd, timeout_s):
            if str(cmd[0]) != "vitis-run-stub":
                return real(cmd, cwd, timeout_s)
            return 0, ""                     # 没有 csim.exe ⇒ 走分类链
        T._run = fake
        try:
            r = t.csim("int f(int x) { return x; }\n",
                       '#include "kernel.h"\n#include "ff.cpp"\n'
                       'int main(void) { return 0; }\n',
                       "f", keep=True)
        finally:
            T._run = real
            if old is None:
                os.environ.pop("AGENT_TMP", None)
            else:
                os.environ["AGENT_TMP"] = old
        try:
            self.assertEqual(r.get("tb_fix"), {"cpp_includes": ["ff.cpp"]})
            with open(os.path.join(r["work"], TB_SRC), encoding="utf-8") as fh:
                written = fh.read()
            self.assertNotIn('"ff.cpp"', written)
            self.assertEqual(len(written.splitlines()), 3, "写盘件行数变了")
            self.assertIn("harness 已从测试台里删掉", r.get("note") or "",
                          "删了 include 却没在反馈里说 —— 模型会以为那份文件真的在")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestFix8B(unittest.TestCase):
    """改动 B：**构建确实失败了**、却没有一条诊断指得到某一行 ⇒ 不是环境故障。

    病灶（RESULTS `agent-fix7-20261025` §1.2）：sort_radix r1 落进
    `env="fixture"` ⇒ `main.py` 停机，四轮预算只用了一轮；而同一份 kernel
    在官方臂上是 L2（环境是好的）。下面这段日志是归档 excerpt 的**逐字节切片**。
    """

    SRC = "kernel.cpp"
    #: 归档逐字（`agent/out/machsuite__sort_radix/trace.jsonl` 的 selfcheck.excerpt）。
    LOG = (
        "INFO: [HLS 200-1510] Running: open_project proj\n"
        "INFO: [HLS 200-10] Adding design file 'kernel.cpp' to the project\n"
        "INFO: [HLS 200-10] Adding test bench file 'agent_tb.cpp' to the project\n"
        "INFO: [HLS 200-1510] Running: csim_design -setup\n"
        "INFO: [HLS 200-2191] C-Simulation will use clang-16 as the compiler\n"
        "INFO: [HLS 200-2036] Building debug C Simulation binaries\n"
        "   Compiling ../../../../agent_tb.cpp in debug mode\n"
        "/tools/Xilinx/2026.1/Vitis/tps/lnx64/gcc-8.3.0/lib/gcc/x86_64-pc-linux-gnu/"
        "8.3.0/../../../../include/c++/8.3.0/bits/stl_relops.h:68:1: error: "
        "namespaces can only be defined in global or namespace scope\n"
        "ERROR: [SIM 211-100] CSim file generation failed: compilation error(s).\n")

    def test_sort_radix_log_stops_being_an_environment_failure(self):
        got = classify_no_exe(self.LOG, self.SRC)
        self.assertEqual(got.get("kind"), "build-unlocalized")
        self.assertIsNone(got.get("env"),
                          "环境是好的（同一份 kernel 在官方臂上拿到 L2），报 env 会停机")
        self.assertIsNone(got.get("level"))

    # 顺序是语义的一部分：诊断指着 kernel ⇒ 仍归 kernel-compile（那一支更具体）。
    def test_kernel_diagnostic_still_wins(self):
        out = self.LOG.replace(
            "INFO: [HLS 200-2036] Building debug C Simulation binaries\n",
            "INFO: [HLS 200-2036] Building debug C Simulation binaries\n"
            "../../../../kernel.cpp:3:5: error: unknown type name 'uint64_t'\n")
        got = classify_no_exe(out, self.SRC)
        self.assertEqual(got.get("kind"), "kernel-compile")

    # 诊断指着 TB ⇒ 仍归 testbench-compile（带文件:行:列，比这一支更可操作）。
    def test_testbench_diagnostic_still_wins(self):
        out = self.LOG.replace(
            "INFO: [HLS 200-2036] Building debug C Simulation binaries\n",
            "INFO: [HLS 200-2036] Building debug C Simulation binaries\n"
            "../../../../agent_tb.cpp:9:10: fatal error: 'x.h' file not found\n")
        got = classify_no_exe(out, self.SRC)
        self.assertEqual(got.get("kind"), "testbench-compile")

    # 授权故障优先于一切 —— 新支不许抢在它前面。
    def test_license_still_wins(self):
        out = self.LOG + ("ERROR: Vivado Design Suite cannot be launched because a valid "
                          "license\n       was not found.\n")
        got = classify_no_exe(out, self.SRC)
        self.assertEqual(got.get("env"), "license")

    def test_wording_does_not_tell_the_model_to_rewrite_the_kernel(self):
        out = _classify_base(None, {"level": None, "env": None,
                                    "kind": "build-unlocalized", "note": "", "log": ""})
        self.assertIn("测试台", out)
        self.assertIn("不要改 kernel", out)
        self.assertNotIn("自验没能给出关于设计的结论", out,
                         "新支被讲成了『没有结论』—— 那正是停机分支的说法")

    REPLY = TestSolveKeepsSomething.KERNEL + "\n" + TestSolveKeepsSomething.TB_LONG

    # 行为面：main.py 必须**继续**跑下一轮（fix8 的全部意义就在这一条）。
    def test_solve_continues_to_the_next_round(self):
        stub = _scripted([
            {"level": None, "env": None, "kind": "build-unlocalized", "note": "构建失败"},
            {"level": 3, "env": None, "kind": None, "note": "ok"},
        ])
        # 第 2 轮要能收工（否则它会一路跑到 MAX_ROUNDS，calls 计数就没有判据意义）。
        stub.csynth = lambda self, kernel, top, timeout_s=0.0, headers=None: (0, "")
        keeper = TestSolveKeepsSomething()
        with tempfile.TemporaryDirectory() as d:
            import agent.main as m
            for fname, text in (("prompt.txt", "Top-Level Function : `add128`\n"),
                                ("interface.txt", keeper.INTERFACE),
                                ("top.txt", "add128\n")):
                with open(os.path.join(d, fname), "w", encoding="utf-8") as fh:
                    fh.write(text)
            task = m.Task(d)
            top, _src = task.resolve_top()
            trace = m.Trace(os.path.join(d, "trace.jsonl"))
            real = m.HlsToolchain
            m.HlsToolchain = stub
            try:
                out = m.solve(_StubLLM([self.REPLY] * 4), trace, task, top)
            finally:
                m.HlsToolchain = real
                trace.close()
        self.assertEqual(stub.calls, 2,
                         "build-unlocalized 之后没有进下一轮 —— 又变成停机了")
        self.assertIn("void add128", out)

    # 负对照：真环境故障仍然**必须**停机（一次 EDA 都不多跑）。
    def test_real_environment_failure_still_stops(self):
        stub = _scripted([{"level": None, "env": "fixture",
                           "note": "csim.exe 未生成，原因不明"}])
        keeper = TestSolveKeepsSomething()
        with tempfile.TemporaryDirectory() as d:
            import agent.main as m
            for fname, text in (("prompt.txt", "Top-Level Function : `add128`\n"),
                                ("interface.txt", keeper.INTERFACE),
                                ("top.txt", "add128\n")):
                with open(os.path.join(d, fname), "w", encoding="utf-8") as fh:
                    fh.write(text)
            task = m.Task(d)
            top, _src = task.resolve_top()
            trace = m.Trace(os.path.join(d, "trace.jsonl"))
            real = m.HlsToolchain
            m.HlsToolchain = stub
            try:
                m.solve(_StubLLM([self.REPLY] * 4), trace, task, top)
            finally:
                m.HlsToolchain = real
                trace.close()
        self.assertEqual(stub.calls, 1, "环境故障之后还在跑 —— 又去改一份对的实现")


class TestFix8CD(unittest.TestCase):
    """改动 C/D：出厂 system.md 里必须有那两节，且旧的 pragma 提示被限定。

    出处：fix7 §1.3（doitgen 的 `C4` 与 `sum` 一次都没被引用）与 §1.4
    （gramschmidt 的 `i = k` 对参考解的 `i = 0`，baseline 臂同一模型拿 L4）。
    """

    def _text(self):
        with open(os.path.join(ROOT, "agent", "prompts", "system.md"),
                  encoding="utf-8") as fh:
            return fh.read()

    def test_interface_authority_section(self):
        text = self._text()
        self.assertIn("The interface is the specification", text)
        self.assertIn("Every parameter must be read or written", text)
        self.assertIn("the signature wins", text)

    def test_arithmetic_fidelity_section(self):
        text = self._text()
        self.assertIn("match one specific implementation", text)
        self.assertIn("Transcribe the given formula", text)
        self.assertIn("Do not drop terms", text)
        self.assertIn("textbook", text)

    def test_pragma_nudge_is_qualified(self):
        text = self._text()
        self.assertIn("never the arithmetic", text,
                      "pragma 提示没有被限定 —— 它就是 gramschmidt 改坏算式的入口")

    # 负对照：这两节不许出现**任何一道题**的专有名字（硬编码红线）。
    def test_no_task_specific_answer_leaks_in(self):
        text = self._text()
        for bad in ("C4", "doitgen", "gramschmidt", "nussinov", "2mm", "aes"):
            self.assertNotIn(bad, text, "system.md 里出现了题目专有的%s" % bad)



# ---------------------------------------------------------------- fix9（2026-10-25）
class TestFix9A(unittest.TestCase):
    """改动 A：**回复里有围栏行，就绝不能整段取用。**

    实测病灶（fix8 面板 p9 `hls_polybench__fixed__small__doitgen` 的**真实交付件**，
    22,939 B）：模型把整篇回复写成了

        **Block 1 — the kernel**
        ```cpp        ← 开
        ```cpp        ← 又开一个
        …代码…
        ```           ← 闭
        ```           ← 再闭

    `_FENCE`（要求闭合）把「开+开」配成空块、「闭+闭」配成空块 ⇒ raw=["",""]；
    `_unclosed_tail` 取最后一条围栏行之后 ⇒ 空 ⇒ None；于是落进「没有围栏 ⇒ 整段
    按代码取用」的退让 ⇒ 整篇 markdown（第一行 `**Block 1 — the kernel**`）成了
    solution.cpp ⇒ 官方 L1。

    ★ 下面这条夹具是**按真实交付件的行结构逐行重写的**（4 条围栏行、同样的先后），
      不是随手编的形状 —— 合成形状若配不出空块，测的就不是那个病灶。
    """

    DOUBLED = ("**Block 1 \u2014 the kernel**\n"
               "```cpp\n```cpp\n"
               "#include \"add128.h\"\n\n"
               "void add128(bits64 a0, bits64 a1, bits64 b0, bits64 b1,\n"
               "            bits64 *z0Ptr, bits64 *z1Ptr) {\n"
               "    bits64 z1 = a1 + b1;\n"
               "    *z1Ptr = z1;\n"
               "}\n```\n```\n")

    def test_the_whole_markdown_reply_is_never_the_kernel(self):
        k, tb, note = extract_blocks(self.DOUBLED, "add128")
        self.assertNotIn("```", k, "围栏行被写进了 kernel（= 整段原文当代码）")
        self.assertNotIn("Block 1", k, "散文标题被写进了 kernel")
        self.assertTrue(k.lstrip().startswith("#include"), "kernel 不以 #include 开头")
        self.assertIn("void add128(", k)
        self.assertEqual(tb, "")
        self.assertIn("围栏", note)

    # 负对照：围栏行在、但围栏之间**确实没有代码** ⇒ 如实报「没取到任何代码」，
    # 不许退回到「整段原文」。
    def test_prose_only_fence_still_yields_no_code(self):
        k, tb, note = extract_blocks("```\nI cannot help with that request.\n```\n",
                                     "add128")
        self.assertEqual(k, "")
        self.assertEqual(tb, "")
        self.assertIn("没取到任何代码", note)

    # 负对照：正常的、成对的围栏**照旧**走原路（这条改动对它必须是 no-op）。
    def test_a_normal_closed_fence_is_unchanged(self):
        text = ('```cpp\n#include "add128.h"\nvoid add128(int a0) { (void)a0; }\n```\n')
        k, tb, _note = extract_blocks(text, "add128")
        self.assertIn("void add128", k)
        self.assertNotIn("```", k)
        self.assertEqual(tb, "")


class TestFix9BC(unittest.TestCase):
    """改动 B：没有测试台的轮次也要做一次**零 EDA** 的宿主语法体检。
    改动 C：发过「只输出一个块 / 不要测试台」之后，要测试台时必须显式作废它。

    B 的病灶（fix8 面板 p12 `machsuite__aes_aes`，交付件 4,504 B）：
    r2–r4 三轮 `tb=0` ⇒ `kinds=none:3`，**一次编译都没跑**；而那份 kernel 本地
    `g++ -fsyntax-only -std=c++14 -I.` 直接报
    `error: 'aes_addRoundKey' was not declared in this scope`（rc=1）。
    C 的病灶是同一题的 r3/r4：两轮都在要测试台，两轮都只回 kernel，
    且 r3 与 r4 **逐字节相同** —— 它们头顶上还压着 r2 那句「不要测试台」。
    """

    INTERFACE = TestSolveKeepsSomething.INTERFACE
    TOP = TestSolveKeepsSomething.TOP
    KERNEL = TestSolveKeepsSomething.KERNEL
    _solve = TestFix3NoPinnedRounds._solve
    _rows = TestFix3NoPinnedRounds._rows

    def _failing_stub(self, rounds=4):
        stub = _scripted([{"level": 1, "env": None, "kind": "compile"}] * rounds)
        stub.syntax_status = "fail"
        stub.syntax_diags = [
            "kernel.cpp:9:5: error: 'aes_addRoundKey' was not declared in this scope"]
        return stub

    def test_kernel_only_round_that_does_not_compile_is_reported(self):
        import agent.main as m
        stub = self._failing_stub()
        self._solve([self.KERNEL] * m.MAX_ROUNDS, stub=stub)
        sc = self._rows("selfcheck")
        self.assertTrue(sc, "一轮 selfcheck 都没落 trace")
        self.assertEqual(sc[0].get("kind"), "kernel-compile",
                         "宿主说编不过，trace 里却没有类别（下一轮也就不会有原文）")
        self.assertEqual(sc[0].get("level"), 1)
        self.assertEqual(sc[0].get("kok"), -1)
        self.assertEqual(sc[0]["kernel_check"]["status"], "fail")
        self.assertEqual(stub.calls, 0, "没有测试台却起了 EDA")
        self.assertIn("was not declared", self.last_llm.seen[1][-1]["content"],
                      "编译器原文没有交到下一轮")

    # 负对照：宿主不给结论（skipped）⇒ 行为与 fix8 **逐字节相同**：
    # level=None、没有 kind、仍然只走「要测试台」那一支。
    def test_skipped_probe_keeps_the_old_behaviour(self):
        self._solve([self.KERNEL, self.KERNEL])
        sc = self._rows("selfcheck")
        self.assertIsNone(sc[0].get("kind"), "宿主没给结论却记了一个类别")
        self.assertIsNone(sc[0].get("level"))
        self.assertEqual(sc[0]["kernel_check"]["status"], "skipped")
        self.assertIn("没有测试台", sc[0].get("note") or "")

    # 负对照：体检自己抛异常 ⇒ 收敛成 skipped，**不许**毁掉整轮。
    def test_a_broken_probe_does_not_kill_the_round(self):
        class _Boom(_StubHls):
            def kernel_syntax(self, kernel, headers=None, timeout_s=0.0):
                raise RuntimeError("boom")
        self._solve([self.KERNEL, self.KERNEL], stub=_Boom)
        sc = self._rows("selfcheck")
        self.assertTrue(sc, "体检抛异常把整轮吞了")
        self.assertIsNone(sc[0].get("kind"))
        self.assertIn("抛异常", sc[0]["kernel_check"]["why"])

    # ── 改动 C ────────────────────────────────────────────────────────────
    TRUNC_BAD = ('```cpp\n#include "add128.h"\nvoid not_the_top(int x) {\n', "length")

    def test_the_stale_kernel_only_instruction_is_cancelled(self):
        import agent.main as m
        self._solve([self.TRUNC_BAD, self.KERNEL, self.KERNEL])
        seen = [msgs[-1]["content"] for msgs in self.last_llm.seen]
        self.assertIn("truncated-bad-kernel", seen[1],
                      "第 2 轮没收到「只输出一个块」那条（夹具没演到病灶）")
        self.assertIn("作废", seen[2],
                      "第 3 轮没有作废「只输出一个块 / 不要测试台」—— 两条指令顶着干")

    # 负对照：没发过那条要求时**一个字都不许多**（这条改动对常规路径必须 no-op）。
    def test_normal_rounds_do_not_mention_cancellation(self):
        self._solve([self.KERNEL, self.KERNEL])
        seen = [msgs[-1]["content"] for msgs in self.last_llm.seen]
        self.assertNotIn("作废", seen[1])
        self.assertIn("两个", seen[1])

class TestFix10P(unittest.TestCase):
    """改动 P：围栏配不成对时，**全部**像代码的段落都要交给下游挑选。

    病灶（fix9 面板 p8 `gramschmidt`、p12 `aes_aes` 同形）：模型连开两个围栏 ——
    `` ```cpp `` 紧接着又是一行 `` ```cpp `` —— `_FENCE` 非贪婪配对把「前一个开」与
    「后一个开」配成一对，块内容只有一行注释；真正的 kernel 与测试台落在后面。
    fix9 只留**最长**的一段 ⇒ 测试台留下、kernel 被丢；P 之后两段都在候选里，
    由 `named`/`with_main` 按结构挑（那一步本来就会挑，不需要更早地扔掉候选）。
    """

    TOP = "k10"

    #: 逐字复刻「连开两个围栏」的形状：第一对围栏里只有一行注释，
    #: kernel 在**第一个围栏之前**，测试台在**第二、第三个围栏之间**。
    REPLY = (
        '#include "k10.h"\n'
        'void k10(int *a, int n) { for (int i = 0; i < n; ++i) a[i] = a[i] + 1; }\n'
        '```cpp\n'
        '// kernel block 1\n'
        '```cpp\n'
        '#include <cstdio>\n'
        'int main() { int a[2] = {0, 0}; k10(a, 2); printf("%d %d\\n", a[0], a[1]); return 0; }\n'
        '```\n'
        '以上。\n')

    def test_both_segments_survive(self):
        k, tb, note = extract_blocks(self.REPLY, self.TOP)
        self.assertIn("void k10(", k, "kernel 段被丢了")
        self.assertNotIn("int main", k)
        self.assertIn("int main", tb, "测试台段被丢了")
        self.assertIn("全部代码段落", note, "说明里没有如实写取了几段")

    # 负对照：只留最长的那一段（fix9 的行为）会把 kernel 丢掉 —— 这条用例
    # 证明上面那条红得有意义，而不是「两块本来就能取到」。
    def test_longest_only_would_lose_the_kernel(self):
        import agent.llm as L
        best = L._longest_code_segment(self.REPLY, self.TOP)
        self.assertIn("int main", best)
        self.assertNotIn("void k10(", best)

    # 负对照：配不成对、且**一段都不像代码** ⇒ 如实报「没取到」，不许拿原文充数。
    def test_no_code_segment_is_reported_not_invented(self):
        k, tb, note = extract_blocks("```cpp\n// 只有注释\n```cpp\n说说思路\n```\n尾注",
                                     self.TOP)
        self.assertEqual((k, tb), ("", ""))
        self.assertIn("没取到任何代码", note)


class TestFix10R(unittest.TestCase):
    """改动 R：数组/指针的位运算错误，规则里要**数星号与括号**（`_DEREF_RULE`）。

    病灶（fix8 面板 p1 `add_round_key`，4 轮 0 升）：编译器说
    `invalid operands of types 'unsigned char (*)[4][4]' … to binary 'operator^'`，
    旧规则只说「按下标循环」，模型就写 `p[i][j] ^= k` —— 而 `p` 是**指向二维数组的
    指针**，得写 `(*p)[i][j]`。规则名不许变（既有用例与 trace 都按名字记账）。
    """

    def test_bitop_rule_counts_the_stars(self):
        rule, txt = _rule_for_error(
            "kernel.cpp:9:25: error: invalid operands of types "
            "'unsigned char (*)[4][4]' and 'unsigned char' to binary 'operator^'")
        self.assertEqual(rule, "array-bitop")
        self.assertIn("(*p)[i][j]", txt)

    def test_binary_rule_also_carries_the_deref_rule(self):
        rule, txt = _rule_for_error(
            "kernel.cpp:3:9: error: invalid operands of types 'uint8_t [16]' and "
            "'uint8_t [16]' to binary 'operator+'")
        self.assertEqual(rule, "array-binary")
        self.assertIn("(*p)[i][j]", txt)

    # 负对照：没有这条错误形状 ⇒ 一个字都不许多（R 对绝大多数轮次是 no-op）。
    def test_unrelated_notes_get_no_rule(self):
        self.assertEqual(_rule_for_error("error: unknown type name 'uint8_t'"),
                         ("", ""))


class TestFix10S(unittest.TestCase):
    """改动 S：**逐字节停滞**要在修复提示里说出来（修复轮不许原样重贴）。

    病灶（fix7 面板 p1，四轮 0 升）：`prev_sha` 的环内记录只用来说明历史，
    修复提示本身对「又交了一份一模一样的文件」没有任何反应。S 把这件事写进
    `_set_repair` 的前缀，并记 `stagnant` 进 trace（`add_log_bytes` 不含它）。
    ★ 三态：`both`（kernel 与测试台都没改）/ `kernel`（只有 kernel 没改）/ 无。
      测试台的指纹用 `_sha16(tb) or "-"`：空测试台与「没算过」不许混为一谈。
    """

    INTERFACE = TestSolveKeepsSomething.INTERFACE
    TOP = TestSolveKeepsSomething.TOP
    KERNEL = TestSolveKeepsSomething.KERNEL
    TB_LONG = TestSolveKeepsSomething.TB_LONG
    _solve = TestFix3NoPinnedRounds._solve
    _rows = TestFix3NoPinnedRounds._rows

    TB2 = TB_LONG.replace('printf("got %llx', 'printf("res %llx')
    KERNEL2 = KERNEL.replace("bits64 z1 = a1 + b1;", "bits64 z1 = a1 + b1;  // r2")

    def _seen(self):
        return [msgs[-1]["content"] for msgs in self.last_llm.seen]

    def test_identical_kernel_and_tb_is_flagged(self):
        self._solve([self.KERNEL + self.TB_LONG] * 3)
        seen = self._seen()
        self.assertIn("逐字节相同", seen[2], "第 3 轮没有被告知「又交了一份一样的」")
        st = [r.get("stagnant") for r in self._rows("repair-log")]
        self.assertIn("both", st)

    def test_identical_kernel_with_a_new_tb_is_flagged_as_kernel(self):
        self._solve([self.KERNEL + self.TB_LONG,
                     self.KERNEL + self.TB2,
                     self.KERNEL + self.TB2])
        seen = self._seen()
        self.assertIn("kernel 与上一轮逐字节相同", seen[2])
        self.assertNotIn("测试台都没改", seen[2])
        st = [r.get("stagnant") for r in self._rows("repair-log")]
        self.assertIn("kernel", st)

    # 负对照：两轮都不一样 ⇒ 不许出现停滞话术（假红会驱动模型去改对的东西）。
    def test_a_real_change_is_not_called_stagnation(self):
        self._solve([self.KERNEL + self.TB_LONG,
                     self.KERNEL2 + self.TB2,
                     self.KERNEL2 + self.TB2])
        seen = self._seen()
        self.assertNotIn("逐字节相同", seen[2])
        st = [r.get("stagnant") for r in self._rows("repair-log")]
        self.assertEqual(st[1], "", "没有停滞却记了一个停滞态")


class TestFix15RuntimeStreak(unittest.TestCase):
    """fix15（2026-10-28）：**同一类失败连着出现**时，要换的不是算法、是策略。

    病灶（`results/agent-adaptive-20261027/PREREG.md` ADDENDUM A.5，k=5 逐轮实测）：
    四轮里有三轮交出的 kernel 各不相同（sha16 每轮都变），测试台的失败文本却
    **逐字相同**（`FAIL: level[4]=3 expected 2`）—— 模型在同一处重写了三遍，因为
    每轮收到的都是同一句「算法或边界错了」。真正的病灶是**读了没写过的栈数组**
    （定长队列的查重循环扫到了栈上残留的旧字节），改算法层永远改不掉它。

    判据：`level == 2` **且**同一类别此前连续出现过 ⇒ 追加「先定位再改」规则，
    并在 `repair-log` 记 `rule2=runtime-streak`。首轮失败、其它类别、其它等级
    —— 一个字都不许多（假红会驱动模型去改对的东西）。
    """

    INTERFACE = TestSolveKeepsSomething.INTERFACE
    TOP = TestSolveKeepsSomething.TOP
    KERNEL = TestSolveKeepsSomething.KERNEL
    TB_LONG = TestSolveKeepsSomething.TB_LONG
    _solve = TestFix3NoPinnedRounds._solve
    _rows = TestFix3NoPinnedRounds._rows
    # ★ 必须包一层 `staticmethod`：直接取类上的静态方法得到的是**裸函数**，
    #   于是 `self._sc(...)` 会把 self 当第一个位置参数传进去（TypeError）。
    _sc = staticmethod(TestFix7GiveBackTheEvidence._sc)

    RUNTIME_NOTE = "测试台返回非零退出码 1 —— 功能不对"

    # ── 台账 → 连击数 ──────────────────────────────────────────────────
    def test_streak_counts_only_the_trailing_run(self):
        import agent.main as m
        at = [{"kind": "compile"}, {"kind": "runtime"}, {"kind": "runtime"}]
        self.assertEqual(m._same_kind_streak(at, "runtime"), 2)
        # 负对照：被别的类别打断的那一段不算连击。
        self.assertEqual(m._same_kind_streak(at, "compile"), 0)
        self.assertEqual(m._same_kind_streak([], "runtime"), 0)

    # ── 首轮 / 其它类别 / 其它等级：一个字都不许多 ──────────────────────
    def test_first_failure_is_untouched(self):
        sc = self._sc(note=self.RUNTIME_NOTE, log="FAIL: x")
        facts, text = _classify_detail(2, sc)          # 默认 streak=0
        self.assertNotIn("rule2", facts)
        self.assertEqual(text, _classify(2, sc), "首轮失败被加了话")

    def test_other_levels_never_get_the_runtime_rule(self):
        for lvl, kind in ((1, "kernel-compile"), (0, None),
                          (None, "testbench-compile")):
            sc = self._sc(level=lvl, kind=kind, note="x", log="")
            facts, text = _classify_detail(lvl, sc, streak=5)
            self.assertNotIn("rule2", facts, lvl)
            self.assertNotIn("同一个失败已经连续", text, lvl)

    # ── 连击时追加的是**定位方法**，不是题面知识 ────────────────────────
    def test_second_consecutive_runtime_failure_gets_the_rule(self):
        sc = self._sc(note=self.RUNTIME_NOTE, log="FAIL: x")
        facts, text = _classify_detail(2, sc, streak=1)
        self.assertEqual(facts.get("rule2"), "runtime-streak")
        self.assertIn("同一个失败已经连续 2 轮", text)
        self.assertIn("栈上残留的旧字节", text)
        self.assertIn("定位到第一个算错的元素", text)
        self.assertEqual(facts["rule2_bytes"], len(
            _rule_for_runtime_streak(1).encode("utf-8")))

    def test_the_rule_carries_no_task_identity(self):
        """反硬编码口径（V6）：规则里不许出现题名、题目录、金标值。"""
        text = _classify_detail(2, self._sc(), streak=3)[1]
        for bad in ("machsuite", "bfs", "queue", "level_counts", "check.data",
                    "N_NODES", "input.data"):
            self.assertNotIn(bad, text)

    # ── solve() 端到端：第 3 轮起，提示词与 trace 都要说到「连击」 ────────
    def test_the_second_and_later_repairs_say_it_out_loud(self):
        import agent.main as m
        reply = self.KERNEL + "\n" + self.TB_LONG
        stub = _scripted([{"level": 2, "env": None, "kind": None,
                           "note": self.RUNTIME_NOTE, "log": "FAIL: x"}]
                         * m.MAX_ROUNDS)
        self._solve([reply] * m.MAX_ROUNDS, stub=stub)
        seen = [msgs[-1]["content"] for msgs in self.last_llm.seen]
        self.assertEqual(len(seen), m.MAX_ROUNDS, "没走满轮次，前提不成立")
        # r2 的提示词带的是 r1 的修复文本：r1 之前没有历史 ⇒ 不许有连击话术。
        self.assertNotIn("同一个失败已经连续", seen[1])
        self.assertIn("同一个失败已经连续 2 轮", seen[2])
        r2 = [r.get("rule2") for r in self._rows("repair-log")]
        self.assertEqual(r2[0], "")
        self.assertEqual(r2[1:], ["runtime-streak"] * (m.MAX_ROUNDS - 2))


class TestFix16DeliveryAudit(unittest.TestCase):
    """fix16（2026-10-28）：**首轮就过 L4** 的交付，交出去之前再让它看自己一眼。

    病灶（PREREG ADDENDUM A.6，k=5 `machsuite__bfs_queue` 逐轮实测）：一轮就走到
    `selfcheck L3 → csynth rc=0 → accept-l4`；交付件里那条入队路径写了
    `queue[tail]`、推进了 `tail`，独独没写 `queue_size++`，主循环处理完起始节点
    就退出，而它自写的 4,392 B 测试台**照样报通过**。首轮通过 ⇒ 此后零失败反馈
    ⇒ 运行时再没看过这份代码一眼。

    判据：只审「首轮 → 自验过 → 综合过」的稿子，每题最多一次。交回原样是**合法
    且预期**的结果（`audit.same`，不重跑综合）；改坏了就退回第 1 轮那份已过 L4 的
    kernel —— 自审只能帮忙，不能把已验过的交付换掉。

    负对照（该绿的必须绿）：没到 L4 的轮、第 2 轮才到 L4 的轮、开关关掉 —— 一条
    `audit` 痕都不许多（假的红会驱动模型去改本来正确的代码）。
    """

    INTERFACE = TestSolveKeepsSomething.INTERFACE
    TOP = TestSolveKeepsSomething.TOP
    KERNEL = TestSolveKeepsSomething.KERNEL
    TB_LONG = TestSolveKeepsSomething.TB_LONG
    _solve = TestFix3NoPinnedRounds._solve
    _rows = TestFix3NoPinnedRounds._rows

    L4 = {"level": 3, "env": None, "kind": None, "note": "", "log": "ok"}
    L2 = {"level": 2, "env": None, "kind": None,
          "note": "FAIL: x", "log": "FAIL: x"}

    # ── 主证：首轮 L4 ⇒ 恰好一轮自审；原样交回 ⇒ 不重跑综合 ────────────────
    def test_a_first_round_l4_delivery_gets_one_audit_round(self):
        import agent.main as m
        reply = self.KERNEL + "\n" + self.TB_LONG
        stub = _scripted_l4([self.L4, self.L4])
        out = self._solve([reply, reply], stub=stub)
        self.assertEqual(self.last_llm.rounds, 2, "自审轮没发出去")
        self.assertEqual(stub.synth_calls, 1,
                         "交回逐字节相同的 kernel 后又跑了一遍综合 —— "
                         "第 1 轮的 rc=0 就是这份文件的证据")
        self.assertEqual([r["event"] for r in self._rows("audit")],
                         ["request", "inject", "same"])
        self.assertEqual([r.get("audit") for r in self._rows("prompt")],
                         [False, True])
        # 自审轮**不是**修复轮：不进 attempts 台账、不落 repair-log。
        self.assertEqual(self._rows("repair-log"), [])
        self.assertEqual([r.get("attempts") for r in self._rows("prompt")],
                         [0, 0])
        msgs = self.last_llm.seen[1]
        self.assertIn("delivery audit", msgs[0]["content"])
        self.assertEqual(msgs[-1]["content"], m.AUDIT_TEXT,
                         "自审正文与断言用的原文不一致")
        self.assertIn("byte-for-byte unchanged", msgs[-1]["content"])
        # 自我描述必须诚实：这一轮没有失败，不许沿用失败模板的措辞。
        self.assertNotIn("Your previous attempt failed", msgs[-1]["content"])
        self.assertEqual(self._rows("audit")[0].get("kernel_sha16"),
                         m._sha16(out), "request 记的指纹不是交出去的那份")

    # ── 回退：自审把代码改坏了 ⇒ 交第 1 轮那份（fix17：先给一次修复机会）────
    def test_an_audit_that_makes_it_worse_gives_back_the_l4_kernel(self):
        import agent.main as m
        other = self.KERNEL.replace("((z1 < a1) ? 1 : 0)",
                                    "((z1 >= a1) ? 0 : 1)")
        self.assertNotEqual(other, self.KERNEL, "负对照的前提不成立：替换没命中")
        # 每条回复都要有码：空回复会触发**同轮重试**（另一次 chat），
        # 那样 `rounds` 就数不出「循环跑了几轮」了（实测 4 轮 → 5 次 chat）。
        rest = m.MAX_ROUNDS - 2
        stub = _scripted_l4([self.L4, self.L2] + [self.L2] * rest)
        out = self._solve(
            [self.KERNEL + "\n" + self.TB_LONG,
             other + "\n" + self.TB_LONG]
            + [other + "\n" + self.TB_LONG] * rest, stub=stub)
        self.assertEqual(stub.synth_calls, 1, "改坏的稿子不该拿到一次综合")
        # ★ fix17：发现失败的那一刻**不收工** —— 记一行 `audit/regressed`，
        #   然后落进正常修复路（剩下的轮次照发）。旧行为是 `break`，
        #   在 k=6 上表现为「闸开了火，唯一后果是提前结束」。
        self.assertEqual([r.get("event") for r in self._rows("audit")],
                         ["request", "inject", "regressed"])
        self.assertEqual(self._rows("audit")[-1].get("stage"), "selfcheck")
        self.assertEqual(self.last_llm.rounds, m.MAX_ROUNDS,
                         "自审失败后没有继续修 —— 闸开了火却只负责收工")
        self.assertTrue(self._rows("repair-log"),
                        "自审失败之后没有修复轮：repair-log 是空的")
        # 交付出路与旧行为逐字节相同：`_better` 只让更强者顶替，L2 顶不掉 L4。
        self.assertIn("(z1 < a1) ? 1 : 0", out, "退回去的不是第 1 轮那份")
        self.assertNotIn("(z1 >= a1) ? 0 : 1", out)

    # ── 负对照：没到 L4，一个字都不许多 ──────────────────────────────────
    def test_no_audit_when_the_round_never_gets_to_l4(self):
        import agent.main as m
        reply = self.KERNEL + "\n" + self.TB_LONG
        stub = _scripted([self.L2] * m.MAX_ROUNDS)
        self._solve([reply] * m.MAX_ROUNDS, stub=stub)
        self.assertEqual(self._rows("audit"), [])
        self.assertFalse(any(r.get("audit") for r in self._rows("prompt")))

    # ── 负对照：第 2 轮才到 L4 ⇒ 模型已经收到过失败反馈，不在暴露面上 ────
    def test_no_audit_when_l4_is_reached_only_after_a_failure(self):
        import agent.main as m
        reply = self.KERNEL + "\n" + self.TB_LONG
        stub = _scripted_l4([self.L2, self.L4])
        self._solve([reply, reply], stub=stub)
        self.assertEqual(self.last_llm.rounds, 2, "第 2 轮没跑，前提不成立")
        self.assertEqual(self._rows("audit"), [])

    # ── 开关：关掉即回到改动前的形状（多一轮都不能发） ────────────────────
    def test_the_switch_off_keeps_the_old_shape(self):
        import agent.main as m
        reply = self.KERNEL + "\n" + self.TB_LONG
        old = m.AUDIT_MODE
        m.AUDIT_MODE = "off"
        try:
            stub = _scripted_l4([self.L4])
            out = self._solve([reply, reply], stub=stub)
        finally:
            m.AUDIT_MODE = old
        self.assertEqual(self.last_llm.rounds, 1, "开关关掉了还多发了一轮")
        self.assertEqual(self._rows("audit"), [])
        self.assertIn("void add128", out)

    # ── 反硬编码口径（V6）：清单里不许出现题名 / 题目录 / 金标值 ──────────
    def test_the_audit_text_carries_no_task_identity(self):
        import agent.main as m
        blob = (m.AUDIT_SYS + m.AUDIT_TEXT).lower()
        for bad in ("machsuite", "bfs", "queue", "n_nodes", "level_counts",
                    "check.data", "input.data", "starting_node", "stencil",
                    "polybench", "c2hlsc", "rosetta", "chstone"):
            self.assertNotIn(bad, blob)


class TestFix17AuditRepairPath(unittest.TestCase):
    """fix17（2026-10-28）：自审**发现**了问题，要接得上「修」，而不是收工。

    病灶（PREREG ADDENDUM A.7，k=6 `polybench__ludcmp` 逐轮实测）：fix16 的自审轮
    把同一份 kernel **逐字节原样**交回（`audit.same`），而那份 kernel 的消元把同一
    行算了两遍（第一趟从头消到尾、把 `A[i][k]` 也改了，第二趟又把改过的值当乘子）。
    官方测试台 40/40 个数值超容差。两处病因各自独立：

      ① **自审只让模型读代码**。读一遍看不出自己想错了；自写的测试台只打印
         `Test PASSED`，运行时手上没有任何独立判据。fix16 的第 5 条（「你的证据
         够强吗」）在 A.6.2 §4 实测**没有独立可观测效果** —— 让模型自问不会产出证据。
      ② **自审一失败就 `break`**。发现「自验过了其实错了」之后，最该做的恰恰是修；
         旧代码把这次发现直接变成收工，白白用掉了唯一一次自审。

    判据：① 自审轮失败 ⇒ 记 `audit/regressed` 后落进正常修复路，轮次照发；
    ② 交付**绝不因此变差** —— `_better` 只让更强者顶替，`best` 仍是那份已过 L4 的；
    ③ 自审文本的第一动作换成「用题面导出的关系式在**原始输入**上验算」。

    负对照：自审交回逐字节相同的 kernel（`audit.same`）、自审改好了（`accept-l4`）
    —— 两条都不许多出 `audit/regressed`。
    """

    INTERFACE = TestSolveKeepsSomething.INTERFACE
    TOP = TestSolveKeepsSomething.TOP
    KERNEL = TestSolveKeepsSomething.KERNEL
    TB_LONG = TestSolveKeepsSomething.TB_LONG
    _solve = TestFix3NoPinnedRounds._solve
    _rows = TestFix3NoPinnedRounds._rows

    L4 = {"level": 3, "env": None, "kind": None, "note": "", "log": "ok"}
    L2 = {"level": 2, "env": None, "kind": None,
          "note": "FAIL: x", "log": "FAIL: x"}

    def _other(self):
        other = self.KERNEL.replace("((z1 < a1) ? 1 : 0)",
                                    "((z1 >= a1) ? 0 : 1)")
        self.assertNotEqual(other, self.KERNEL, "负对照的前提不成立：替换没命中")
        return other

    # ── 自审失败之后发出去的那一轮，必须是**修复**轮而不是又一遍自审 ────────
    def test_the_failed_audit_is_followed_by_repair_not_by_a_second_audit(self):
        import agent.main as m
        stub = _scripted_l4([self.L4, self.L2])
        self._solve([self.KERNEL + "\n" + self.TB_LONG,
                     self._other() + "\n" + self.TB_LONG], stub=stub)
        self.assertEqual([r.get("event") for r in self._rows("audit")],
                         ["request", "inject", "regressed"],
                         "自审每题的额度是 1 次：失败之后不许再审一遍")
        self.assertEqual([r.get("audit") for r in self._rows("prompt")],
                         [False, True, False, False])
        r3 = self.last_llm.seen[2]
        self.assertNotIn(m.AUDIT_TEXT, r3[-1]["content"],
                         "修复轮又把自审正文发了一遍")
        self.assertIn("Your previous attempt failed", r3[-1]["content"],
                      "自审失败之后的正文不是修复模板")
        self.assertNotIn("delivery audit", r3[0]["content"],
                         "自审段还留在 system 里")

    # ── 正对照：自审真的修好了 ⇒ 交付新稿、并且**再综合一次**给它证据 ──────
    def test_an_audit_that_repairs_it_delivers_the_repaired_kernel(self):
        stub = _scripted_l4([self.L4, self.L4])
        other = self._other()
        out = self._solve([self.KERNEL + "\n" + self.TB_LONG,
                           other + "\n" + self.TB_LONG], stub=stub)
        self.assertEqual(self.last_llm.rounds, 2, "自审轮没发出去")
        self.assertEqual(stub.synth_calls, 2,
                         "改过的稿子必须重跑综合才能交付")
        self.assertIn("(z1 >= a1) ? 0 : 1", out, "交付的不是自审轮修好的那份")
        self.assertNotIn("regressed", [r.get("event") for r in self._rows("audit")],
                         "改好了却记了 regressed")

    # ── 额度：自审只有一次；修好之后不许再开一轮 ────────────────────────────
    def test_the_one_audit_budget_survives_the_repair_path(self):
        import agent.main as m
        stub = _scripted_l4([self.L4, self.L2, self.L4])
        self._solve([self.KERNEL + "\n" + self.TB_LONG,
                     self._other() + "\n" + self.TB_LONG,
                     self.KERNEL + "\n" + self.TB_LONG], stub=stub)
        self.assertEqual(self.last_llm.rounds, 3, "修好之后又多跑了一轮")
        self.assertEqual([r.get("event") for r in self._rows("audit")],
                         ["request", "inject", "regressed"],
                         "同一题开了第二次自审")
        self.assertNotIn(True, [r.get("audit") for r in self._rows("prompt")[2:]])

    # ── 文本形状：第一步必须是**在原始输入上验题面导出的关系式** ─────────────
    def test_the_audit_text_starts_from_a_property_check_on_original_inputs(self):
        import agent.main as m
        blob = m.AUDIT_TEXT
        self.assertIn("STEP A", blob)
        self.assertIn("STEP B", blob)
        for must in ("BEFORE the call",        # 就地修改过的输入必须先留副本
                     "worst violation as a number",  # 要数字，不要布尔
                     "never against the kernel's own",  # 不许拿自己的中间值当判据
                     "In-place update order",  # ludcmp 那一类的病因
                     "byte-for-byte unchanged"):  # 正确的稿子不许被扰动
            self.assertIn(must, blob)
        # 被换掉的那一条要**真的**不在了：A.6.2 §4 实测它没有独立效果。
        self.assertNotIn("Strength of your evidence", blob)
        # system 段要把两步**先讲一遍**，否则模型先读到 user 才明白这轮在干什么。
        self.assertIn("two steps", m.AUDIT_SYS)
        self.assertIn("original inputs", m.AUDIT_SYS)


class TestFix18KernelSynthGate(unittest.TestCase):
    """fix18（2026-10-28）：测试台编不过时，**kernel 单独的综合结论必须进环内**。

    病灶（PREREG ADDENDUM A.8，k=7 `rosetta__optical_flow__outer_product` 逐轮实测）：
    `csynth` 只有一个调用点，挂在 `lvl == 3` 那一支；模型自写的测试台编不过 ⇒
    `lvl` 恒 None ⇒ **四轮一次综合都没跑**（trace 里零 `csynth` 行）。交付的 kernel
    带两条自加的 `#pragma HLS INTERFACE axis`，把二维数组端口声明成 AXI4-Stream，
    官方判分 `HLS 214-244` 直接否掉 ⇒ `synth:false`，L3/0.8。
    而四轮手里一直有 `stub_probe: ok`（kernel 单独过过真工具链）。**综合不需要测试台。**

    判据：① 有工具链级「kernel 编得过」证据 ⇒ 只过 kernel 综合一次；
    ② rc>0 ⇒ 修复类别改判 `kernel-synth`，综合器原文进下一轮提示词；
    ③ rc=0 ⇒ 类别不变（错的仍是测试台），但正文要说「kernel 综合通过」；
    ④ 没有证据 ⇒ **一次综合都不跑**（白烧 EDA 的负对照）；
    ⑤ `called object type … is not a function` ⇒ `rule3`；别的测试台错 ⇒ 不追加。
    """

    INTERFACE = TestSolveKeepsSomething.INTERFACE
    TOP = TestSolveKeepsSomething.TOP
    KERNEL = TestSolveKeepsSomething.KERNEL
    TB_LONG = TestSolveKeepsSomething.TB_LONG
    _solve = TestFix3NoPinnedRounds._solve
    _rows = TestFix3NoPinnedRounds._rows

    #: k=7 的原文（逐字，两行都留着）：局部数组与顶层函数同名 ⇒ 名字遮蔽；
    #: 第二行的 `hls` 未声明是**另一种**测试台错，用来验规则不越界。
    SHADOW_NOTE = (
        "../../../../agent_tb.cpp:31:18: error: called object type "
        "'outer_t[436][1024]' is not a function or function pointer\n"
        "../../../../agent_tb.cpp:51:21: error: use of undeclared identifier 'hls'")
    #: 另一种测试台错：没有任何「当函数调用」的形状 —— 规则必须沉默。
    OTHER_NOTE = ("../../../../agent_tb.cpp:12:9: error: unknown type name "
                  "'ap_fixed'; did you mean 'ap_float'?")
    SYNTH_FAIL = (
        "ERROR: [HLS 214-244] in function 'toplevel': Failed to implement stream "
        "interface on variable 'toplevel'. Each array element of 'toplevel' must "
        "be a scalar.")
    L2 = {"level": 2, "env": None, "kind": None, "note": "FAIL: x", "log": "FAIL: x"}

    def _tb_fail(self, note=None, stub_probe=None, kernel_check=None):
        r = {"level": None, "env": None, "kind": "testbench-compile",
             "note": note or self.SHADOW_NOTE, "log": note or self.SHADOW_NOTE}
        r["kernel_check"] = kernel_check or {
            "status": "skipped", "why": "stub", "diags": [], "rc": 1,
            "elapsed_s": 0.0}
        if stub_probe is not None:
            r["stub_probe"] = stub_probe
        return r

    @staticmethod
    def _probe_ok():
        return {"status": "ok", "why": "", "diags": [], "rc": 0,
                "elapsed_s": 4.4, "timeout_s": 90.0}

    def _scripted_synth(self, results, rc, log="stub: synth"):
        base = _scripted(results)

        class _StubSynth(base):
            synth_calls = 0

            def csynth(self, kernel, top, timeout_s=0.0, headers=None):
                type(self).synth_calls += 1
                return rc, log

        _StubSynth.script = list(results)
        return _StubSynth

    # ── rc>0：综合器否掉 kernel ⇒ 改判类别、原文进提示词 ─────────────────────
    def test_a_kernel_that_fails_synth_reclassifies_the_repair(self):
        stub = self._scripted_synth(
            [self._tb_fail(stub_probe=self._probe_ok()), self.L2],
            rc=1, log=self.SYNTH_FAIL)
        self._solve([self.KERNEL + "\n" + self.TB_LONG,
                     self.KERNEL + "\n" + self.TB_LONG], stub=stub)
        cs = self._rows("csynth")
        self.assertEqual(len(cs), 1, "只过 kernel 的综合每轮最多一次")
        self.assertEqual(cs[0].get("when"), "kernel-only")
        self.assertEqual(cs[0].get("evidence"), "stub_probe",
                         "准入用的证据来源没记进 trace")
        self.assertEqual(cs[0].get("rc"), 1)
        logs = self._rows("repair-log")
        self.assertEqual(logs[0].get("kind"), "kernel-synth",
                         "综合器否掉了 kernel，修复类别却还写着测试台")
        self.assertEqual(logs[0].get("ksyn"), "fail")
        r2 = self.last_llm.seen[1][-1]["content"]
        self.assertIn("HLS 214-244", r2, "综合器原文没进下一轮提示词")
        self.assertIn("#pragma HLS INTERFACE", r2,
                      "缺「别给顶层端口加接口声明」那条通用规则")

    # ── rc=0：类别不变（错的仍是测试台），但要明说 kernel 已被证明没问题 ──────
    def test_synth_success_keeps_the_testbench_kind_and_says_so(self):
        stub = self._scripted_synth(
            [self._tb_fail(stub_probe=self._probe_ok()), self.L2],
            rc=0, log="stub: synth ok")
        self._solve([self.KERNEL + "\n" + self.TB_LONG,
                     self.KERNEL + "\n" + self.TB_LONG], stub=stub)
        self.assertEqual(stub.synth_calls, 1)
        logs = self._rows("repair-log")
        self.assertEqual(logs[0].get("kind"), "testbench-compile",
                         "kernel 综合过了，修复类别却被改成了别的")
        self.assertEqual(logs[0].get("ksyn"), "ok")
        r2 = self.last_llm.seen[1][-1]["content"]
        self.assertIn("综合通过", r2, "没有把「kernel 综合通过」这句话交出去")
        self.assertIn("只在测试台", r2)
        self.assertNotIn("kernel-synth", r2, "负对照：rc=0 不许出现改判类别")

    # ── 没有 kernel 级证据 ⇒ 一次综合都不跑（白烧 EDA 的负对照）──────────────
    def test_no_kernel_evidence_means_no_synth_at_all(self):
        for probe in (None, {"status": "skipped", "why": "缺头", "diags": [],
                             "rc": None, "elapsed_s": 0.0}):
            stub = self._scripted_synth(
                [self._tb_fail(stub_probe=probe), self.L2], rc=1,
                log=self.SYNTH_FAIL)
            self._solve([self.KERNEL + "\n" + self.TB_LONG,
                         self.KERNEL + "\n" + self.TB_LONG], stub=stub)
            self.assertEqual(stub.synth_calls, 0,
                             "没有「kernel 编得过」的证据却去烧综合（probe=%r）"
                             % (probe,))
            self.assertEqual(self._rows("csynth"), [])
            self.assertEqual(self._rows("repair-log")[0].get("kind"),
                             "testbench-compile")

    # ── 遮蔽诊断 → rule3；别的测试台错 → 沉默 ───────────────────────────────
    def test_the_shadow_diagnostic_gets_its_own_action(self):
        import agent.main as m
        sc = {"kind": "testbench-compile", "note": self.SHADOW_NOTE}
        facts, text = m._classify_detail(None, sc)
        self.assertEqual(facts.get("rule3"), "tb-shadow")
        self.assertGreater(facts.get("rule3_bytes", 0), 0)
        self.assertIn("同名", text)
        self.assertIn("改个名字", text)
        self.assertIn("kernel 一个字都不用改", text)
        # 负对照：没有这个形状的测试台错 —— 一个字都不许追加。
        facts2, text2 = m._classify_detail(
            None, {"kind": "testbench-compile", "note": self.OTHER_NOTE})
        self.assertNotIn("rule3", facts2)
        self.assertEqual(m._rule_for_tb_error(self.OTHER_NOTE), ("", ""))

    # ── 反硬编码：规则正文里没有题名 / 顶层函数名 / 题目录路径 ────────────────
    def test_the_new_rules_name_no_task_and_no_top_function(self):
        import agent.main as m
        # 模板本体（`_kernel_synth_repair` 只把**综合器原文**当证据贴进来 ——
        # 那一段是仪器的话，不是规则的话，所以拿空日志测模板）。
        blob = (m._KSYN_OK + m._kernel_synth_repair("")
                + m._rule_for_tb_error(self.SHADOW_NOTE)[1])
        for forbidden in ("rosetta", "optical_flow", "outer_product", "ludcmp",
                          "polybench", "task.json", "dataset/"):
            self.assertNotIn(forbidden, blob,
                             "规则正文里出现了题目相关字样：%s" % forbidden)


class TestFix10T(unittest.TestCase):
    """改动 T：测试台编不过时，用**桩测试台**把 kernel 单独过一遍真工具链。

    ★ 判据只有一条：诊断行**指着 kernel 源文件**才判 `fail`（并把这一轮改判
      `kernel-compile`，编译器原文交给模型）。超时、缺头、诊断不指任何一行、
      工具起不来、探针自己抛异常、以及桩测试台**编过了**（`ok`，只作观测）——
      全部 `skipped`，行为回到 fix9。
    """

    TB = "int main() { return 0; }\n"
    #: 宿主 g++ 一定 `skipped` 的 kernel（Vitis 专有头）—— 与面板 p1/p2 同形。
    VITIS_ONLY = '#include <ap_int.h>\nint f(ap_int<8> x) { return (int)x; }\n'
    TB_ERR = "agent_tb.cpp:9:10: error: 'foo' was not declared in this scope\n"

    def setUp(self):
        import agent.tools as T
        self.T = T
        self.tmp = tempfile.mkdtemp(prefix="hls_test_")
        self._old = os.environ.get("AGENT_TMP")
        os.environ["AGENT_TMP"] = self.tmp

    def tearDown(self):
        if self._old is None:
            os.environ.pop("AGENT_TMP", None)
        else:
            os.environ["AGENT_TMP"] = self._old
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _tool(self):
        t = self.T.HlsToolchain.__new__(self.T.HlsToolchain)
        t.part, t.period_ns, t.reason = self.T.PART, self.T.PERIOD_NS, ""
        t.exe = "vitis-run-stub"
        return t

    def _probe(self, ret):
        """把 `_run` 换成脚本；返回 (结果, 每次调用的 cwd)。"""
        t, real = self._tool(), self.T._run
        calls = []

        def fake(cmd, cwd, timeout_s):
            calls.append(cwd)
            if str(cmd[0]) != "vitis-run-stub":
                return real(cmd, cwd, timeout_s)
            return ret(cwd) if callable(ret) else ret

        self.T._run = fake
        try:
            return t._stub_kernel_probe("void f() { return; }\n", None, "f", 30.0), calls
        finally:
            self.T._run = real

    # ── 直接测探针 ────────────────────────────────────────────────────────
    def test_kernel_errors_make_it_fail(self):
        res, calls = self._probe(
            (1, "kernel.cpp:2:9: error: no match for 'operator[]'\n"))
        self.assertEqual(res["status"], "fail")
        self.assertIn("no match", res["diags"][0])
        self.assertEqual(len(calls), 1)
        self.assertTrue(os.path.basename(calls[0]).startswith("agent_stub_"),
                        "探针没在自己的工作目录里跑")

    def test_missing_header_is_not_a_verdict(self):
        res, _ = self._probe(
            (1, "kernel.cpp:1:10: fatal error: 'ap_int.h' file not found\n"))
        self.assertEqual(res["status"], "skipped")
        self.assertIn("缺头", res["why"])

    def test_errors_pointing_elsewhere_are_not_a_verdict(self):
        res, _ = self._probe((1, self.TB_ERR))
        self.assertEqual(res["status"], "skipped")
        self.assertIn("不指着 kernel", res["why"])

    def test_timeout_and_no_tool_are_not_verdicts(self):
        for rc, word in ((124, "超时"), (-1, "起不来")):
            res, _ = self._probe((rc, "kernel.cpp:1:1: error: boom\n"))
            self.assertEqual(res["status"], "skipped")
            self.assertIn(word, res["why"])

    def test_a_broken_probe_does_not_kill_the_round(self):
        def boom(cwd):
            raise RuntimeError("boom")
        res, _ = self._probe(boom)
        self.assertEqual(res["status"], "skipped")
        self.assertIn("探针异常", res["why"])

    def test_csim_exe_means_the_kernel_built(self):
        def made(cwd):
            p = os.path.join(cwd, self.T.CSIM_EXE)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("stub")
            return 0, ""
        res, _ = self._probe(made)
        self.assertEqual(res["status"], "ok")

    # ── 接线：只在 tb-compile / build-unlocalized 且 kernel_check=skipped 时出手 ──
    def _csim(self, stub_ret):
        """真正的 `csim()`；Vitis 第一次返回 TB 编译错，第二次（桩探针）按脚本。"""
        t, real = self._tool(), self.T._run
        calls = []

        def fake(cmd, cwd, timeout_s):
            if str(cmd[0]) != "vitis-run-stub":
                return real(cmd, cwd, timeout_s)
            calls.append(cwd)
            if os.path.basename(cwd).startswith("agent_stub_"):
                return stub_ret(cwd) if callable(stub_ret) else stub_ret
            return 1, self.TB_ERR

        self.T._run = fake
        try:
            return t.csim(self.VITIS_ONLY, self.TB, "f"), calls
        finally:
            self.T._run = real

    def test_failing_stub_flips_the_round_to_kernel_compile(self):
        r, calls = self._csim((1, "kernel.cpp:2:9: error: no match for 'operator[]'\n"))
        self.assertEqual(len(calls), 2, "测试台编不过时没有去问一次 kernel")
        self.assertEqual(r["kind"], "kernel-compile")
        self.assertEqual(r["level"], 1)
        self.assertEqual(r["stub_probe"]["status"], "fail")
        self.assertIn("kernel 自己编不过", r["note"])
        self.assertIn("no match", r["log"])

    def test_ok_stub_leaves_the_round_alone(self):
        def made(cwd):                       # 桩测试台编过了 ⇒ ok（只作观测）
            p = os.path.join(cwd, self.T.CSIM_EXE)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("stub")
            return 0, ""
        r, calls = self._csim(made)
        self.assertEqual(len(calls), 2)
        self.assertEqual(r["stub_probe"]["status"], "ok")
        self.assertEqual(r["kind"], "testbench-compile",
                         "ok 都被改判了 —— T 只能多给一条信息或什么也不给")

    def test_skipped_stub_leaves_the_round_alone(self):
        r, _ = self._csim((1, self.TB_ERR))
        self.assertEqual(r["stub_probe"]["status"], "skipped")
        self.assertEqual(r["kind"], "testbench-compile")

    # 负对照：kernel 在宿主上就编不过 ⇒ `csim()` 早已返回，探针根本不该出手。
    def test_no_probe_when_the_host_already_judged_the_kernel(self):
        t, real = self._tool(), self.T._run
        calls = []

        def fake(cmd, cwd, timeout_s):
            if str(cmd[0]) != "vitis-run-stub":
                return real(cmd, cwd, timeout_s)
            calls.append(cwd)
            return 1, self.TB_ERR

        self.T._run = fake
        try:
            r = t.csim("int f() { return 1 }\n", self.TB, "f")
        finally:
            self.T._run = real
        self.assertEqual(r["kernel_check"]["status"], "fail")
        self.assertNotIn("stub_probe", r)
        self.assertEqual(calls, [])


class TestStubFallback(unittest.TestCase):
    """fix13：交付兜底桩 —— 只在**编译证据为负**时动，且只从 interface 取材。

    病灶与判据见 results/agent-adaptive-20261027/PREREG.md A.3 §10。
    这一组全部是零 EDA、零模型的纯函数测试：桩长什么样、什么时候换、什么时候不换。
    """

    IFACE = ('// header: sort_radix.h\n\n#include <stdint.h>\n'
             '#define SIZE 2048\n'
             'void ss_sort(\n'
             '    int a[SIZE],\n'
             '    int b[SIZE]);\n')
    TOP = "ss_sort"

    class _Task:
        def __init__(self, interface):
            self.interface = interface

    class _Trace:
        def __init__(self):
            self.rows = []

        def write(self, **kw):
            self.rows.append(kw)

    class _Hls:
        """按 `status` 给结论的假工具链；`kernel_syntax` 是被测代码的**唯一**依据。"""

        def __init__(self, status="ok", diags=()):
            self.status, self.diags, self.calls = status, list(diags), []

        def kernel_syntax(self, kernel, headers=None):
            self.calls.append({"bytes": len(kernel), "headers": sorted(headers or {})})
            return {"status": self.status, "why": "" if self.status != "fail" else "fail",
                    "diags": self.diags, "rc": 1 if self.status == "fail" else 0,
                    "elapsed_s": 0.0}

    def _run(self, kok, best, status="ok", iface=None, diags=()):
        from agent.main import _stub_fallback
        trace, saved = self._Trace(), []
        hls = self._Hls(status, diags)
        out = _stub_fallback(best, kok, hls, trace,
                             self._Task(self.IFACE if iface is None else iface),
                             self.TOP, {"sort_radix.h": "#define SIZE 2048\n"},
                             saved.append)
        return out, trace.rows, saved, hls

    # ---- 抠声明 -------------------------------------------------------
    def test_extracts_multiline_decl(self):
        from agent.main import _top_decl
        decl = _top_decl(self.IFACE, self.TOP)
        self.assertTrue(decl.startswith("void ss_sort("), decl)
        self.assertTrue(decl.endswith(");"), decl)
        self.assertIn("int b[SIZE]", decl)

    def test_only_the_one_statement_before_it(self):
        """前面还有一条声明时，抠出来的**不能**把它们一起带上。"""
        from agent.main import _top_decl
        iface = "void other(int x);\nvoid ss_sort(int a[4]);\n"
        self.assertEqual(_top_decl(iface, self.TOP), "void ss_sort(int a[4]);")

    def test_comment_mention_is_not_a_decl(self):
        from agent.main import _top_decl
        self.assertEqual(_top_decl("// ss_sort(int a) 见上文\n", self.TOP), "")

    def test_missing_name_gives_empty_string(self):
        from agent.main import _top_decl
        self.assertEqual(_top_decl("void other(int x);\n", self.TOP), "")

    # ---- 桩的形状 -----------------------------------------------------
    def test_stub_is_an_empty_body_definition(self):
        from agent.main import _stub_source
        src = _stub_source(self.IFACE, self.TOP, {"sort_radix.h": "#define SIZE 2048\n"})
        self.assertIn('#include "sort_radix.h"', src)
        self.assertTrue(src.rstrip().endswith(") {\n}"), repr(src))
        self.assertIn("void ss_sort(", src)

    def test_static_and_inline_are_stripped(self):
        """`static` 会改链接属性（测试台在另一个 TU 里找符号）⇒ 必须剥掉。"""
        from agent.main import _stub_source
        src = _stub_source("static inline void ss_sort(int a[4]);\n", self.TOP, {})
        self.assertTrue(src.rstrip().endswith("void ss_sort(int a[4]) {\n}"), repr(src))

    def test_no_header_no_include(self):
        from agent.main import _stub_source
        src = _stub_source("void ss_sort(int a[4]);\n", self.TOP, {})
        self.assertNotIn("#include", src)

    # ---- 换不换 -------------------------------------------------------
    def test_negative_evidence_is_replaced(self):
        from agent.main import _sha16
        out, rows, saved, hls = self._run(-1, "int x = ;\n")
        self.assertIn("compile-only fallback", out)
        self.assertEqual(saved, [out])                    # 立刻落盘
        self.assertEqual(len(hls.calls), 1)               # 落盘前先验过
        row = rows[-1]
        self.assertEqual((row["tool"], row["kind"]), ("fallback", "stub"))
        self.assertIs(row["applied"], True)
        self.assertEqual(row["best_kok"], -1)
        self.assertEqual(row["stub_sha16"], _sha16(out))

    def test_empty_hand_is_replaced(self):
        from agent.main import BEST_KOK_EMPTY
        out, rows, saved, _ = self._run(BEST_KOK_EMPTY, "")
        self.assertIn("compile-only fallback", out)
        self.assertIs(rows[-1]["applied"], True)

    def test_positive_evidence_is_never_touched(self):
        """**负对照**：有编译证据的候选一个字节都不许动，trace 也不许落行。"""
        for kok in (0, 1):
            out, rows, saved, hls = self._run(kok, "void ss_sort(int a[4]) { }\n")
            self.assertEqual(out, "void ss_sort(int a[4]) { }\n")
            self.assertEqual(rows, [])
            self.assertEqual(saved, [])
            self.assertEqual(hls.calls, [])

    def test_failing_stub_does_not_displace_a_real_attempt(self):
        out, rows, saved, _ = self._run(-1, "int broken(\n", status="fail",
                                        diags=["kernel.cpp:1:1: error: boom"])
        self.assertEqual(out, "int broken(\n")
        self.assertEqual(saved, [])
        self.assertIs(rows[-1]["applied"], False)
        self.assertIn("编不过", rows[-1]["why"])

    def test_failing_stub_still_beats_an_empty_hand(self):
        """0 B 是实测的 L0；能解析的桩至少 L1 ⇒ 空手时即使桩编不过也要换。"""
        from agent.main import BEST_KOK_EMPTY
        out, rows, _, _ = self._run(BEST_KOK_EMPTY, "   ", status="fail")
        self.assertIn("compile-only fallback", out)
        self.assertIs(rows[-1]["applied"], True)

    def test_unusable_interface_keeps_behaviour_unchanged(self):
        out, rows, saved, hls = self._run(-1, "int x = ;\n", iface="void other(int);\n")
        self.assertEqual(out, "int x = ;\n")
        self.assertEqual(saved, [])
        self.assertEqual(hls.calls, [])                   # 没桩就不烧编译器
        self.assertIs(rows[-1]["applied"], False)


class TestFix19(unittest.TestCase):
    """fix19：桩要把头文件里**其余**只有声明、没有函数体的函数也定义上。

    病灶（PREREG A.9 §1）：官方测试台调 `AES_init_ctx`，它只在头里声明、题面的
    Sub-Components 列表里没有它 ⇒ 只定义顶层函数的桩链接缺符号 ⇒ 停在 L1。
    这一组全是零 EDA、零模型的纯函数测试。
    """

    IFACE = (
        '// header: aes_like.h\n'
        '#include <stdint.h>\n'
        'typedef uint8_t state_t[4][4];\n'
        'void init_ctx(struct ctx_t *ctx, const uint8_t *key);\n'
        'int  extra_len(const state_t *s);\n'
        'static inline int helper(int x);\n'
        'void top_fn(state_t *s);\n'
    )
    TOP = "top_fn"
    HDR = {"aes_like.h": "#include <stdint.h>\n"}

    class _Task:
        def __init__(self, interface):
            self.interface = interface

    class _Trace:
        def __init__(self):
            self.rows = []

        def write(self, **kw):
            self.rows.append(kw)

    class _Hls:
        def __init__(self, status="ok", diags=()):
            self.status, self.diags, self.calls = status, list(diags), []

        def kernel_syntax(self, kernel, headers=None):
            self.calls.append(len(kernel))
            return {"status": self.status, "why": "" if self.status != "fail" else "fail",
                    "diags": self.diags, "rc": 1 if self.status == "fail" else 0,
                    "elapsed_s": 0.0}

    def _run(self, kok, best, status="ok", iface=None):
        from agent.main import _stub_fallback
        trace, saved = self._Trace(), []
        hls = self._Hls(status)
        out = _stub_fallback(best, kok, hls, trace,
                             self._Task(self.IFACE if iface is None else iface),
                             self.TOP, self.HDR, saved.append)
        return out, trace.rows, saved, hls

    # ---- 声明识别 -----------------------------------------------------
    def test_other_decls_skips_typedef_static_and_main(self):
        from agent.main import _other_decls
        got = [line.split("(")[0].split()[-1]
               for _ret, line in _other_decls(self.IFACE, self.TOP)]
        self.assertEqual(got, ["init_ctx", "extra_len"])
        self.assertEqual(_other_decls("void top_fn(int);\nint main(int, char **);\n",
                                      self.TOP), [])

    def test_multiline_top_decl_leaves_no_fragments(self):
        """多行顶层声明的续行不得被认成别的声明。"""
        from agent.main import _other_decls
        iface = "void top_fn(\n    int a,\n    int b);\n"
        self.assertEqual(_other_decls(iface, self.TOP), [])

    def test_empty_def_rejects_malformed(self):
        from agent.main import _empty_def
        self.assertEqual(_empty_def("void", "void f(int);"), "void f(int) {\n}\n")
        self.assertEqual(_empty_def("void", "void f(int"), "")

    # ---- 桩的形状 -----------------------------------------------------
    def test_every_bodyless_decl_is_defined(self):
        from agent.main import _stub_source
        src = _stub_source(self.IFACE, self.TOP, self.HDR)
        self.assertIn('#include "aes_like.h"', src)
        self.assertIn("void top_fn(state_t *s) {\n}", src)
        self.assertIn("void init_ctx(struct ctx_t *ctx, const uint8_t *key) {\n}", src)
        # 非 void ⇒ 必须有返回语句，否则桩自己编不过
        self.assertIn("extra_len(const state_t *s) {\n    return {};\n}", src)
        # static inline 跳过；typedef 不得被定义
        self.assertNotIn("helper", src)
        self.assertNotIn("typedef uint8_t state_t[4][4] {", src)

    def test_top_is_not_duplicated(self):
        from agent.main import _stub_source
        src = _stub_source(self.IFACE, self.TOP, self.HDR)
        self.assertEqual(src.count("void top_fn(state_t *s)"), 1)

    def test_extras_off_reproduces_fix13_shape(self):
        from agent.main import _stub_source
        src = _stub_source(self.IFACE, self.TOP, self.HDR, extras=False)
        self.assertTrue(src.rstrip().endswith("void top_fn(state_t *s) {\n}"), repr(src))
        self.assertNotIn("init_ctx", src)
        # 没有可补的声明时，两级是**同一份字节**（老路径字节不变）
        iface = "void top_fn(int a[4]);\n"
        self.assertEqual(_stub_source(iface, self.TOP, self.HDR),
                         _stub_source(iface, self.TOP, self.HDR, extras=False))

    # ---- 两级探针 -----------------------------------------------------
    def test_ok_path_probes_full_stub_once(self):
        out, rows, saved, hls = self._run(-1, "int x = ;\n")
        self.assertIn("init_ctx", out)
        self.assertEqual(saved, [out])
        self.assertEqual(len(hls.calls), 1)
        self.assertEqual(rows[-1]["stub_mode"], "full")
        self.assertEqual(rows[-1]["extras"], 2)

    def test_failing_full_stub_falls_back_to_top_only(self):
        """全量桩编不过 ⇒ 退只顶层桩再探一次（最坏也只是白探一次）。"""
        from agent.main import _stub_source
        out, rows, saved, hls = self._run(-1, "int broken(\n", status="fail")
        self.assertEqual(out, "int broken(\n")           # 两级都编不过 ⇒ 不动
        self.assertEqual(saved, [])
        self.assertEqual(len(hls.calls), 2)
        top_only = len(_stub_source(self.IFACE, self.TOP, self.HDR, extras=False))
        self.assertEqual(hls.calls[1], top_only)
        self.assertLess(hls.calls[1], hls.calls[0])
        row = rows[-1]
        self.assertEqual(row["stub_mode"], "top-only")
        self.assertEqual(row["probe_full"], "fail")
        self.assertIs(row["applied"], False)

    def test_top_only_success_is_what_gets_saved(self):
        """全量桩编不过、只顶层桩编得过 ⇒ 交的必须是**只顶层**那份。"""
        from agent.main import _stub_source
        trace, saved = self._Trace(), []

        class _Hls2(TestFix19._Hls):
            def kernel_syntax(self, kernel, headers=None):
                self.calls.append(len(kernel))
                ok = len(self.calls) > 1               # 第一次 fail，第二次 ok
                return {"status": "ok" if ok else "fail", "why": "",
                        "diags": [], "rc": 0 if ok else 1, "elapsed_s": 0.0}

        hls = _Hls2()
        from agent.main import _stub_fallback
        out = _stub_fallback("int x = ;\n", -1, hls, trace, self._Task(self.IFACE),
                             self.TOP, self.HDR, saved.append)
        self.assertEqual(out, _stub_source(self.IFACE, self.TOP, self.HDR, extras=False))
        self.assertEqual(saved, [out])
        self.assertEqual(trace.rows[-1]["stub_mode"], "top-only")
        self.assertNotIn("init_ctx", out)


class TestFix20(unittest.TestCase):
    """fix20（`results/agent-adaptive-20261027/PREREG.md` ADDENDUM A.10 §3）。

    两个**通用**缺陷，与题名无关（k=11 `c2hlsc__des` 的实测触发）：

    A `_other_decls` 只认**行内**声明 ⇒ 头文件里折行写的声明一条都看不见
      ⇒ 兜底桩缺那个符号 ⇒ 官方测试台链接 `undefined reference` ⇒ 停在 L1。
    B 签名闸不过的候选被记成 `kok=0`（「无编译证据」），而 `_better` 以 kok 为
      **第一关键字** ⇒ 它锁死 `best`（后面每一轮 kok=-1 的都进不来），且让
      `_stub_fallback` 的 `best_kok not in (-1, -2)` 静默返回（零条 trace）。

    全是零 EDA、零模型的纯函数测试。
    """

    IFACE = (
        '// header: multi.h\n'
        '#include <stdint.h>\n'
        'typedef unsigned char block_t[8];\n'
        'void top_fn(block_t *in, block_t *out);\n'
        'void helper_setup(\n'
        '    const unsigned char key[],\n'
        '    block_t schedule,\n'
        '    uint32_t mode);\n'
        'int  inline_len(const block_t *s);\n'
    )
    TOP = "top_fn"

    @staticmethod
    def _names(interface, top):
        from agent.main import _other_decls
        return [line.split("(")[0].split()[-1]
                for _ret, line in _other_decls(interface, top)]

    # ---- 改动 A：跨行声明 ---------------------------------------------
    def test_multiline_decl_is_seen(self):
        self.assertEqual(self._names(self.IFACE, self.TOP),
                         ["helper_setup", "inline_len"])

    def test_single_line_path_is_unchanged(self):
        """负对照：没有跨行声明时，切分与 `splitlines()` 一一对应且都不标 joined。"""
        from agent.main import _decl_lines
        plain = "void top_fn(int a[4]);\nint f(void);\n"
        self.assertEqual(_decl_lines(plain),
                         [("void top_fn(int a[4]);", False), ("int f(void);", False)])

    def test_unterminated_decl_is_not_joined(self):
        """接不成（括号不配平 / 不以 `;` 收尾）就不接 —— 照原样交给逐行口径。"""
        from agent.main import _decl_lines
        self.assertEqual(_decl_lines("void helper(\n    int a,\n"),
                         [("void helper(", False), ("int a,", False)])

    def test_bracket_relaxation_is_joined_only(self):
        """单行带 `[]` 的仍跳过（老口径）；跨行拼出来的 `key[]` 形参要放行。"""
        self.assertEqual(self._names("void keeper(int a[4]);\nvoid top_fn(int);\n",
                                     self.TOP), [])
        self.assertIn("helper_setup", self._names(self.IFACE, self.TOP))

    def test_stub_defines_the_multiline_helper(self):
        from agent.main import _stub_source
        src = _stub_source(self.IFACE, self.TOP, {})
        flat = " ".join(src.split())
        self.assertIn("void helper_setup( const unsigned char key[], "
                      "block_t schedule, uint32_t mode) {", flat)
        self.assertEqual(src.count("helper_setup"), 1)

    # ---- 改动 B：签名闸的记账 -----------------------------------------
    def test_signature_failure_is_negative_evidence(self):
        """`kok=-1` 才让后面「签名合法但编不过」的同级候选有资格替换它。

        第一行是**旧病见证**：把记账改回 0，这一行就红。
        """
        from agent.main import _better
        self.assertFalse(_better(1, -1, -2, 0))     # 旧账：-1 > 0 不成立 ⇒ 换不掉
        self.assertTrue(_better(1, -1, -2, -1))     # 新账：同 kok 比等级，1 > -2
        # 无编译证据（0）也压得过签名闸不过的候选
        self.assertTrue(_better(0, 0, -2, -1))
        self.assertFalse(_better(-2, -1, 0, 0))

    def test_stub_fallback_now_fires_for_signature_failures(self):
        """B 的第二个后果：`best_kok=-1` ⇒ 兜底桩不再静默返回。"""
        from agent.main import _sha16, _stub_fallback

        class _Task:
            interface = self.IFACE

        class _Trace:
            rows = []

            def write(self, **kw):
                self.rows.append(kw)

        class _Hls:
            def kernel_syntax(self, kernel, headers=None):
                return {"status": "ok", "why": "", "diags": [], "rc": 0,
                        "elapsed_s": 0.0}

        trace, saved = _Trace(), []
        out = _stub_fallback("int x = ;\n", -1, _Hls(), trace, _Task(),
                             self.TOP, {}, saved.append)
        self.assertIn("compile-only fallback", out)
        self.assertIn("helper_setup", out)
        self.assertEqual(trace.rows[-1]["best_kok"], -1)
        self.assertIs(trace.rows[-1]["applied"], True)
        self.assertEqual(saved, [out])
        self.assertEqual(trace.rows[-1]["stub_sha16"], _sha16(out))


class TestFix14(unittest.TestCase):
    """fix14：`_FENCE` 已经配出块，**也不能**因此丢掉围栏之外的代码段。

    行结构逐字取自 `results/agent-adaptive-20261027/probe-r1-20261028/reply.txt`
    （自适应轮 run8b k=4 `machsuite__stencil_stencil3d` 第 1 轮的真实回复，6,260 B）：
    每个「块」= 开围栏 + 标题 + **再开一个围栏** + 代码 + 一个闭围栏。
    `_FENCE` 的非贪婪配对允许**带标签的行**去闭合前一个围栏 ⇒ kernel 整段落在围栏
    之外，而 testbench 被配成一个完整块 ⇒ `blocks` 非空 ⇒ fix9/fix10 那三条退让
    一条都走不到 ⇒ kernel 只剩测试台里 `main` 之前那点前缀（实测 246 B，0 次编译）。
    """

    TOP = "k14"
    REPLY = (
        "```cpp\n// Block 1: the kernel\n```cpp\n"
        "#include \"k14.h\"\n\n"
        "void k14(int *a, int n) {\n"
        "    for (int i = 0; i < n; ++i) a[i] = a[i] + 1;\n"
        "}\n"
        "```\n"
        "```cpp\n// Block 2: the testbench\n```cpp\n"
        "#include \"k14.h\"\n#include <cstdio>\n\n"
        "int main() {\n    int a[2] = {0, 0};\n    k14(a, 2);\n"
        "    printf(\"%d\\n\", a[0]);\n    return 0;\n}\n"
        "```\n"
    )

    def test_kernel_outside_the_fences_still_wins(self):
        k, tb, note = extract_blocks(self.REPLY, self.TOP)
        self.assertIn("void k14(", k, "围栏外的 kernel 段被丢了")
        self.assertNotIn("int main", k, "测试台被当成 kernel 交了出去")
        self.assertIn("int main", tb, "测试台块被丢了")
        self.assertIn("一并做候选", note, "说明里没有如实写补了几段")
        self.assertNotIn("```", k, "围栏行被写进了 kernel")

    # 负对照：正常的两块回复**不许**因为这条改动多出候选（fix14 必须对正常路径 no-op）。
    def test_normal_reply_gains_no_extra_candidate(self):
        text = ("```cpp\n#include \"k14.h\"\n"
                "void k14(int *a, int n) { (void)a; (void)n; }\n```\n\n"
                "```cpp\n#include \"k14.h\"\n"
                "int main() { int a[1] = {0}; k14(a, 1); return 0; }\n```\n")
        k, tb, note = extract_blocks(text, self.TOP)
        self.assertIn("void k14(", k)
        self.assertIn("int main", tb)
        self.assertNotIn("一并做候选", note, "正常回复也多了候选 ⇒ 不是 no-op")


class TestFix21(unittest.TestCase):
    """fix21（`results/agent-adaptive-20261027/PREREG.md` ADDENDUM A.11 §3 A–D）。

    两个**通用**缺陷（k=15 `chstone__dfmul` 的官方 csim 现场触发，与题名无关）：

    A 在环编译闸用 `g++ -fsyntax-only`，且**没有**官方那两条 `-Werror=` ⇒ 比官方
      csim 松。GCC 的 `-Wreturn-type` 在生成代码阶段才发出 ⇒ 光加旗标没用
      （`-fsyntax-only` + 旗标实测 rc=0，`-c` + 旗标 rc=1）。
    B 兜底桩的顶层体恒为 `{}` ⇒ 非 void 顶层在官方口径下是编译错误
      （126 题里 23 题的兜底件这样死在 L1）。

    全是零 EDA、零模型的纯函数 / 宿主编译器测试。
    """

    NEED_GXX = shutil.which("g++") is not None
    FALLS_OFF = "int f(int x) { if (x) return 1; }\n"
    UNINIT = "int f() { int x; return x; }\n"
    GOOD = "int f(int x) { return x + 1; }\n"

    def _probe(self, kernel, **kw):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "kernel.cpp"), "w", encoding="utf-8") as fh:
                fh.write(kernel)
            got = host_kernel_probe(d, "kernel.cpp", timeout_s=60.0, **kw)
            left = sorted(os.listdir(d))
        return got, left

    # ---- 改动 A：strict 口径 ------------------------------------------
    @unittest.skipUnless(NEED_GXX, "本机没有 g++")
    def test_missing_return_fails_under_strict(self):
        got, left = self._probe(self.FALLS_OFF, strict=True)
        self.assertEqual(got["status"], "fail", got)
        self.assertTrue(any("return-type" in d for d in got["diags"]),
                        "诊断里没有 return-type：%r" % (got["diags"],))
        self.assertEqual(left, ["kernel.cpp"], "临时 .o 没删掉：%r" % (left,))

    @unittest.skipUnless(NEED_GXX, "本机没有 g++")
    def test_uninitialized_use_fails_under_strict(self):
        got, _ = self._probe(self.UNINIT, strict=True)
        self.assertEqual(got["status"], "fail", got)
        self.assertTrue(any("uninitialized" in d for d in got["diags"]),
                        "诊断里没有 uninitialized：%r" % (got["diags"],))

    @unittest.skipUnless(NEED_GXX, "本机没有 g++")
    def test_correct_kernel_is_ok_under_strict(self):
        """负对照：两条旗标**不许**误杀一份正确的 kernel（假红最贵）。"""
        got, left = self._probe(self.GOOD, strict=True)
        self.assertEqual(got["status"], "ok", got)
        self.assertEqual(left, ["kernel.cpp"])

    @unittest.skipUnless(NEED_GXX, "本机没有 g++")
    def test_non_strict_keeps_the_old_command(self):
        """`strict=False`（兜底桩的两处探针用的就是这个）口径一个字节都不许变。"""
        got, _ = self._probe(self.FALLS_OFF, strict=False)
        self.assertEqual(got["status"], "ok", got)
        got, _ = self._probe(self.FALLS_OFF)          # 缺省也必须是 old
        self.assertEqual(got["status"], "ok", got)

    def test_kernel_syntax_defaults_to_strict(self):
        from unittest import mock

        import agent.tools as T
        t = T.HlsToolchain.__new__(T.HlsToolchain)    # 不跑 __init__（那会找 vitis-run）
        seen = []

        def fake(work, src, timeout_s=60.0, cxx=None, strict=False):
            seen.append(strict)
            return {"status": "ok", "why": "", "diags": [], "rc": 0, "elapsed_s": 0.0}

        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(T, "host_kernel_probe", fake):
            old = os.environ.get("AGENT_TMP")
            os.environ["AGENT_TMP"] = d
            try:
                t.kernel_syntax("int f() { return 0; }", headers={})
                t.kernel_syntax("int f() { return 0; }", headers={}, strict=False)
            finally:
                if old is None:
                    os.environ.pop("AGENT_TMP", None)
                else:
                    os.environ["AGENT_TMP"] = old
        self.assertEqual(seen, [True, False])

    def test_toolchain_without_strict_param_still_works(self):
        """假/旧工具链的 `kernel_syntax` 没有 `strict` 形参 ⇒ 按签名退回老调用。"""
        from agent.main import _host_syntax_probe

        class _Hls:
            def kernel_syntax(self, kernel, headers=None):
                return {"status": "fail", "why": "", "diags": ["x"], "rc": 1,
                        "elapsed_s": 0.0}

        got = _host_syntax_probe(_Hls(), "int f() { }", {})
        self.assertEqual(got["status"], "fail")

    # ---- 改动 B：非 void 顶层的桩体 -----------------------------------
    def test_stub_top_returns_a_value_for_non_void(self):
        from agent.main import _stub_source
        src = _stub_source("int top_fn(int a[4]);\n", "top_fn", {})
        self.assertTrue(
            src.endswith("int top_fn(int a[4]) {\n    return {};\n}\n"), repr(src))

    def test_stub_top_void_body_is_unchanged(self):
        """负对照：void 顶层一个字节都不许变（k=10/k=11 的复测字节靠这一条）。"""
        from agent.main import _stub_source
        src = _stub_source("void top_fn(int a[4]);\n", "top_fn", {})
        self.assertTrue(src.endswith("void top_fn(int a[4]) {\n}\n"), repr(src))

    def test_stub_fallback_probe_stays_non_strict(self):
        """兜底桩的判定口径不动：两处探针显式 `strict=False`（A.11 §5）。"""
        from agent.main import _stub_fallback

        class _Task:
            interface = "void top_fn(int a[4]);\nvoid helper(int);\n"

        class _Trace:
            rows = []

            def write(self, **kw):
                self.rows.append(kw)

        class _Hls:
            def __init__(self):
                self.kw = []

            def kernel_syntax(self, kernel, headers=None, strict=True):
                self.kw.append(strict)
                return {"status": "ok", "why": "", "diags": [], "rc": 0,
                        "elapsed_s": 0.0}

        hls, saved = _Hls(), []
        out = _stub_fallback("int x = ;\n", -1, hls, _Trace(), _Task(),
                             "top_fn", {}, saved.append)
        self.assertTrue(hls.kw, "兜底桩一次探针都没跑")
        self.assertEqual(set(hls.kw), {False})
        self.assertIn("compile-only fallback", out)


# ── fix22（A.14 §3 D）：辅助函数拿不到调用者的形参 ─────────────────────────
#    证据落点 results/agent-adaptive-20261027/PREREG.md ADDENDUM A.14：
#    k=19 `machsuite__nw_nw` 四轮 kernel-compile，编译器原文对 5 个名字报
#    'was not declared in this scope'（模型自己的注释写着 "via closure"）。

NWNW_DIR = os.environ.get(
    "HLS_TEST_NWNW",
    "B:/fpga2026-agent/dataset/hls-eval-tasks/machsuite__nw_nw")
NWNW_IFACE = _read(os.path.join(NWNW_DIR, "interface.txt"))


class TestFix22HelperParamScope(unittest.TestCase):
    """`param_names` 与「未声明的名字恰好是顶层形参」这条编译错规则。

    契约：`param_names()` 吃的是**形参表原文**（`declared_signature()` 的返回），
    不是整条声明 —— 所以 fixture 里不带 `void fname(` 前缀。

    规则只在 diag 里的名字与**顶层形参名**相交时开火；两套引号都认。
    全是零 EDA、零模型的纯函数测试。
    """

    #: (标签, 形参表原文, 期望名字表)。前两例是真数据（A.14 §1 的同一份接口 /
    #: 同一个 helper），其余是边界：数组后缀、函数指针、默认实参、无名形参。
    CASES = [
        ("nw_nw interface",
         r""" char SEQA[ALEN], char SEQB[BLEN], char alignedA[ALEN + BLEN],
          char alignedB[ALEN + BLEN], int M[(ALEN + 1) * (BLEN + 1)],
          char ptr[(ALEN + 1) * (BLEN + 1)]""",
         ["SEQA", "SEQB", "alignedA", "alignedB", "M", "ptr"]),
        ("probe helper trace()",
         r"""char alignedA[ALEN + BLEN], char alignedB[ALEN + BLEN],
              const char ptr[(ALEN + 1) * (BLEN + 1)],
              int ALEN_val, int BLEN_val""",
         ["alignedA", "alignedB", "ptr", "ALEN_val", "BLEN_val"]),
        ("plain scalars",
         r"""unsigned char state[4][4], unsigned char key[4][4]""",
         ["state", "key"]),
        ("unnamed fn-ptr array",
         r"""unsigned char (*)[4][4], int""",
         ["", ""]),
        ("unnamed params",
         r"""unsigned char, unsigned char (*)[4][4]""",
         ["", ""]),
        ("default arg + dim expr",
         r"""double A[ 40 + 0], int n = 4""",
         ["A", "n"]),
        ("named fn-ptr param",
         r"""void (*cb)(int), int n""",
         ["cb", "n"]),
        ("void only",
         r"""void""",
         [""]),
    ]

    def test_param_names_table(self):
        for label, src, want in self.CASES:
            with self.subTest(case=label):
                self.assertEqual(param_names(src), want)

    @unittest.skipUnless(NWNW_IFACE, "找不到 %s/interface.txt" % NWNW_DIR)
    def test_real_interface_names(self):
        """真 interface：6 个名字逐个对上（no name 就得是空串 —— 不许猜）。"""
        sig = declared_signature(NWNW_IFACE, "needwun")
        self.assertIsNotNone(sig)
        self.assertEqual(param_names(sig),
                         ["SEQA", "SEQB", "alignedA", "alignedB", "M", "ptr"])

    def test_named_params_match_norm_params_count(self):
        """与 `_norm_params` **同源**：切分出来的形参个数必须一一对上。

        这条钉子防的是「同一套切分被抄成两份、日后只改了一边」——
        `param_names` 是在 `_norm_params` 的步骤上只把最后一步换成「记下名字」。

        唯一**故意**不同的地方：`_norm_params` 把 `void` / 空项整条丢掉（类型序列
        里没有它们），`param_names` 保留成一个空串占位（位置要能对上调用方）。
        """
        for label, src, want in self.CASES:
            with self.subTest(case=label):
                n_names, n_norm = len(param_names(src)), len(_norm_params(src))
                if src.strip() == "void":          # 只有整条形参表就是 `void`
                    self.assertEqual((n_names, n_norm), (1, 0),
                                     "%s: void 的占位约定变了" % label)
                else:
                    self.assertEqual(n_names, n_norm,
                                     "%s: 条数漂开了" % label)

    # ---- 规则本体：firing + 两条负对照 --------------------------------
    NOTE = ("kernel.cpp:125:18: error: \u2018ptr\u2019 was not declared in this scope\n"
            "kernel.cpp:126:18: error: \u2018alignedA\u2019 was not declared in this scope")

    def test_rule_fires_on_intersection_with_bytes(self):
        sc = {"kind": "kernel-compile", "note": self.NOTE}
        facts, text = _classify_detail(1, sc, top_params=["ptr", "alignedA", "M"])
        self.assertEqual(facts.get("rule4"), "param-scope")
        self.assertGreater(facts.get("rule4_bytes", 0), 0)
        self.assertIn("`ptr/alignedA`", text)
        # 两个名字都点了名；`M` 没出现在 diag 里，不许被点名
        self.assertNotIn("`M`", text)

    def test_rule_fires_on_clang_form_and_ascii_quotes(self):
        sc = {"kind": "kernel-compile",
              "note": "use of undeclared identifier 'SEQA'"}
        facts, _ = _classify_detail(1, sc, top_params=["SEQA"])
        self.assertEqual(facts.get("rule4"), "param-scope")

    def test_rule_does_not_fire_without_intersection(self):
        """负对照 ①：名字不在顶层形参表里 ⇒ 一个字节都不加。"""
        sc = {"kind": "kernel-compile", "note": self.NOTE}
        facts, text = _classify_detail(1, sc, top_params=["other", ""])
        self.assertNotIn("rule4", facts)
        facts, text2 = _classify_detail(1, sc, top_params=[])
        self.assertNotIn("rule4", facts)
        facts, text3 = _classify_detail(1, sc)          # 缺省 None（旧行为）
        self.assertNotIn("rule4", facts)
        self.assertEqual(text, text2)
        self.assertEqual(text, text3, "缺省 top_params ⇒ 文本必须逐字节不变")

    def test_rule_does_not_fire_for_other_kinds(self):
        """负对照 ②：`kind != kernel-compile` ⇒ 恒不开火（别的诊断不走这条路）。"""
        for kind in ("compile", "testbench-compile", "runtime", "parse"):
            with self.subTest(kind=kind):
                sc = {"kind": kind, "note": self.NOTE}
                facts, _ = _classify_detail(1, sc, top_params=["ptr"])
                self.assertNotIn("rule4", facts)

    def test_helper_function_direct(self):
        """直接调 `_rule_for_param_scope`：空表 / 无名 / 噪声名字的边界。"""
        self.assertEqual(_rule_for_param_scope(self.NOTE, None), ("", ""))
        self.assertEqual(_rule_for_param_scope(self.NOTE, [""]), ("", ""))
        self.assertEqual(_rule_for_param_scope("", ["ptr"]), ("", ""))
        rule, text = _rule_for_param_scope(self.NOTE + "\n"
                                           "kernel.cpp:9:1: error: \u2018zzz\u2019 was "
                                           "not declared in this scope",
                                           ["ptr", "zzz"])
        self.assertEqual(rule, "param-scope")
        self.assertIn("`ptr/zzz`", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
