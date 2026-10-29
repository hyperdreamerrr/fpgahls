# 技能包

本目录是智能体的**领域知识**，也是官方提交清单（`SCORING.md` §5.1/§5.3）要求的
「技能包 + `README.md`」中的那一项。

```
skill/
├── README.md                      ← 本文件
├── hls-interface-contract/
│   ├── SKILL.md
│   └── EVIDENCE.md
├── hls-self-verification/
│   ├── SKILL.md
│   └── EVIDENCE.md
├── hls-testbench-callsite/
│   ├── SKILL.md
│   └── EVIDENCE.md
├── hls-testbench-compile-errors/
│   ├── SKILL.md
│   └── EVIDENCE.md
├── hls-testbench-function-mismatch/
│   ├── SKILL.md
│   └── EVIDENCE.md
├── hls-testbench-undeclared-identifiers/
│   ├── SKILL.md
│   └── EVIDENCE.md
├── hls-empty-round-recovery/
│   ├── SKILL.md
│   └── EVIDENCE.md
├── hls-truncated-response/
│   ├── SKILL.md
│   └── EVIDENCE.md
├── hls-self-test-passes-official-fails/
│   ├── SKILL.md
│   └── EVIDENCE.md
├── hls-runtime-algorithm-mismatch/
│   ├── SKILL.md
│   └── EVIDENCE.md
├── hls-runtime-functional-errors/
│   ├── SKILL.md
│   └── EVIDENCE.md
├── hls-testbench-integration/
│   ├── SKILL.md
│   └── EVIDENCE.md
├── hls-testbench-validation/
│   ├── SKILL.md
│   └── EVIDENCE.md
├── hls-testbench-compilation-errors/
│   ├── SKILL.md
│   └── EVIDENCE.md
└── hls-testbench-type-mismatch/
    ├── SKILL.md
    └── EVIDENCE.md
```

一条技能一个目录；目录名与文件名一律英文小写加连字符（官方 §5.1 的命名要求）。
`SKILL.md` 的**正文是英文**，与 AMD 官方技能包的写法一致；本 README 与仓库其余
文档为中文。

加载器只读各目录的 `SKILL.md`；同目录的 `EVIDENCE.md` 是该条的证据清单
（逐条引文与出处，人读件，不参与注入）。

---

## 1. 交付的十五条技能

| 技能 | 何时触发 | 它挡住的失败 | 证据来源 |
|---|---|---|---|
| `hls-interface-contract` | kernel 单独能编译，但拿不到 `csim.exe`；日志里是签名/重复定义/未定义符号一类 | **L1 明明能修却停在 L1**：签名被改、kernel 里带了 `main`、头文件里的 helper 只声明不定义 | 4 题配对归因（`gnnbuilder` 382 B / `gemm_ncubed` 442 B / `2mm` 213 B 三题的产物**纯声明无定义**，官方判 L1）+ 签名闸两侧的假红/假绿实测 |
| `hls-self-verification` | kernel 链接通过但自写测试台报错值不对；或**正要写**测试台 | **L2→L3 那 0.6 系数差**：官方测试台不交给选手，`csynth` 又只看「能不能综合」，两头都证明不了算得对 | 判分阶梯本身（L2 0.2 → L3 0.8，**六倍**）+ 测试台写坏时的假绿形态（比没有测试台更糟） |
| `hls-testbench-callsite` | 测试台编译报 `no matching function for call to`：第一个报错行指向 `agent_tb.cpp`，kernel 源文件里没有报错行 | 改错对象白烧轮次：这是**调用点与声明不匹配**，该修调用点一侧（或补声明/包含），去改 kernel 签名/实现是改错地方 | 3 题 4 条引文（含 1 条反证：该题各轮产物同 sha16 的卡死派生事实） |
| `hls-testbench-compile-errors` | 测试台编译报 `call to 'abs' is ambiguous` / `no member named 'sort' in namespace 'std'` | 名字解析问题被误当 kernel 问题：缺 `std::` 限定或标准库包含，都在测试台侧 | 3 题 3 条引文 |
| `hls-testbench-function-mismatch` | 测试台编译报 `comparison between pointer and integer` / `use of undeclared label` | 测试台表达式类型不匹配、或跳转到不存在的标号：处方全在测试台内，改 kernel 无效 | 1 题 1 条引文 |
| `hls-testbench-undeclared-identifiers` | 测试台编译报 `use of undeclared identifier`（如 `'alpha'`、`'rand_r'`） | 同上一族：测试台引用的名字没声明/没包含，先补声明或包含，别动 kernel | 3 题 3 条引文 |
| `hls-empty-round-recovery` | 上一轮被 token 帽截断 / 内容里没有代码块 / 只给内核块 / 模型调用失败，且还有剩余轮次 | 空轮之后的**二次失败**：重来设计、把剩余轮次在同一形态上再烧一遍 | 4 题 5 条引文（四类空轮修复文本逐字命中） |
| `hls-truncated-response` | 响应被 token 帽截断、留下的测试台代码不完整 | 截断之后的**二次失败**：把不完整的产物当完整设计继续往下改 | 3 题 3 条引文（九批次云端语料；与 `hls-empty-round-recovery` 的截断签名**串联**） |
| `hls-self-test-passes-official-fails` | 自写测试台编译并通过，官方验证仍不过 | 把「自验通过」当成「官方也会过」：两者判据不同，差距要单独定位 | 3 题 3 条引文（九批次云端语料） |
| `hls-runtime-algorithm-mismatch` | 测试台编译通过、运行以 SIGFPE（-8）退出：结果与规格不符 | 把运行期算错当编译问题改：该查算法与实现的偏差，不是接口 | 1 题 1 条引文（九批次云端语料） |
| `hls-runtime-functional-errors` | 退出码 1：能跑但结果不对 | 同族：先定位实现与规格的功能性偏差，再动结构（含 `hls-testbench-length-and-correctness` 合并项） | 2 题 2 条引文（九批次云端语料） |
| `hls-testbench-integration` | 源码单独能编译，但与测试台**链接**失败（参数不匹配/缺符号/重复 `main`） | 把链接期问题当 kernel 问题改（含 `hls-linking-testbench` 合并项） | 3 题 3 条引文（九批次云端语料） |
| `hls-testbench-validation` | 测试台编译通过但返回非 0（-6/-11），功能校验不过 | 只改 kernel、不管测试台侧的边界与期望值假设 | 2 题 2 条引文（九批次云端语料） |
| `hls-testbench-compilation-errors` | 编译错全部落在测试台文件（`agent_tb.cpp`）一侧（未声明标识符/初始化器一类） | 改错对象：内核没问题，要动的是测试台的声明与包含 | 2 题 2 条引文（九批次云端语料） |
| `hls-testbench-type-mismatch` | 测试台编译报 `ap_fixed` 歧义转换、缺函数定义一类 | 同族：把类型/包含问题误当 kernel 逻辑问题 | 2 题 2 条引文（九批次云端语料） |

十五条都不是泛泛的经验谈：每一条都写出了**已证伪的做法**（例如「日志说
`undefined reference` 时不要改算术」），因为一次综合轮次就是墙钟，墙钟就是分数。
前两条（`hls-interface-contract`、`hls-self-verification`）迁移自本包早期手写件；
其余十三条由离线挖掘管线从归档失败样本产出（五条来自逐轮探针与本地跑归档，
八条来自九批次云端评测语料，2026-10-14 入包）。后八条的**开关对照读数已在
rev3 run 产出**（整包 Δ+0.0200、判词 neutral；其中 5 条 fires=0 判
not_exercised，**没有任何一条声称正增益**），2026-10-19 随 FREEZE-v3 全部冻结
—— 来路见 §6。

## 2. `Log signatures` 这一行是加载器的接口

`agent/skills.py` 不是让模型去读技能描述再挑，而是**拿工具输出做字面子串匹配**——
散文式的 Trigger（"User asks whether loops are flattenable"）永远不出现在综合日志里。
所以约定：

- `- **Log signatures:**` 这一行里**用反引号括起来**的字符串，会被逐个取出，
  与日志文本做**不区分大小写的字面子串**匹配；命中才把该技能注入这一轮的上下文。
- **没有这一行的技能照常加载**，只是永远不会因某条错误自动触发（官方技能包就是这样，
  原样拷进来能用）。
- 匹配是**故意笨**的：模型路由更灵活，但要多花一个来回，而错路由在墙钟预算下很贵。

## 3. 选择与注入的边界

- 每轮最多注入 **2 条**（`select(..., limit=2)`）。技能正文动辄几千 token，
  全量注入会把被解释的那段错误日志挤出上下文——这是要避免的失败形态。
- 单条技能渲染上限 12000 字符，超了**按 `## ` 节边界整节丢弃**并在文末写明丢了哪几节；
  不从中间截断（技能最后两节通常是输出格式与行为约束，正是防跑偏的那部分）。
- **第 1 轮不注入**：选择器只在拿到过工具日志之后才被调用（`last_log` 为空时不选），
  所以任何技能最早在第 2 轮出手。

## 4. 与官方（AMD）技能包的关系

格式与 AMD 官方 Vitis HLS 智能体技能一致（frontmatter 只有 `name` 与 `description`，
其余信息在正文的 `## Skill Metadata` 列表里），**因此官方技能可以原样拷进本目录直接用**，
加载器对两者通用（`agent/skills.py` 的文件头就是按这条写的）。官方仓库：
https://github.com/amd/skills

官方技能已覆盖可综合性、pragma 作用域、dataflow 规范形式、burst 推断、循环展平、
stencil 与行缓冲等方向（带 ★ 的那批）；本包**不重复**这些。本包最早的两条（§1 前两行），
按官方那份方向表的口径：**顶层接口契约**官方技能未覆盖（示范目录里有一份
`hls-top-interface-contract` 作为写法示范——本包这条是同题目的**自有版本**，依据是本仓库
自己的 4 题配对归因，不是它的拷贝）；**自我验证**官方明说未覆盖，且点明它 "是本赛道
最缺的一环"、正是 L2→L3 那 0.6 系数差的所在。

**本轮提交带上述十五条**（官方技能尚未 vendor 进来）；官方技能的 vendor 与更宽
错误族的覆盖，都是可以继续补的方向，不是已经做完的事。

## 5. 已知边界

- **本目录不含判定后端**。技能是给模型的材料；真正的编译/仿真/综合在 `agent/` 里，
  由 `agent/tools.py` 调 EDA 工具执行。技能包跑不动任何东西。
- 技能不会自己验证自己被遵守——**它靠的是智能体在环里的反馈**：命中错误签名 ⇒ 注入
  对应技能 ⇒ 下一轮产物变了没有，这件事**记在 `trace.jsonl` 里**（`tool=skills`
  记 `loaded` 与 `event=inject` 的 `selected`），可事后核对。

## 6. 这些条目的来路（离线管线）

§1 后十三条不是手写的：
那是开发期的**离线管线**从已归档的失败样本里挖出来、逐条过闸后渲染进本目录的。

```
kb_mine.py（确定性聚类，不调模型）→ kb_draft.py（本地起草，引文由脚本回填）
  → kb_validate.py（十一道闸）→ kb_render.py（幂等渲染）→ 本目录的 SKILL.md
```

- **挖掘**只读归档的判词、逐轮证据与 `trace.jsonl`，一个字节不写回。进候选的簇
  有跑前定死的门槛（频次 ≥3 且跨 ≥2 题），不达标的留在 `rejected.jsonl` 里备查。
  语料有两个来源：逐轮内核轨迹探针 10 题（前五条），以及九批次云端评测的失败归档
  180 题-run / 375 轮（后八条，2026-10-14 入包）；两批都**只读**，一个字节不写回。
- **起草**由本地模型出草稿，但引文不许模型复述：模型只给 `quote_ref`，原句由
  脚本从证据件里回填——「编造引文」这条失败路径在结构上不存在。
- **闸**逐条查：渲染幂等、能被生产 `select()` 在自己那条证据日志上选中、正文
  预算、引文逐字与 `artifact_sha256` 对上、验证面板与证据题不相交、散文里无
  题名/路径（反硬编码）、签名不过泛（语料命中率 ≤0.60）等。每条闸都配了一个
  **必须把它打红**的种子错（`tools/test_kb_pipeline.py`，挂在 `verify_all.sh` 上）。
- **渲染是单向的**：`SKILL.md` 与 `EVIDENCE.md` 都由 `kb/hls/kb.jsonl` 生成；
  改条目要改 JSONL 再重渲，不直接编辑这两个文件。
- `EVIDENCE.md` 是给人读的证据清单：该条每条引文都带题 / run / 轮、原始字节
  区间与整文件 sha256，可按图索骥回原始日志逐字核对。
- 管线本体（`kb/` 数据仓与 `tools/` 下的管线脚本）**不进包**——包里只有渲染
  产物，即本目录。
- **开关对照（OFF/ON 两臂）读数**按官方报告模板 §5.3 的口径记入本包
  `REPORT.md`：run#3（本包六条时的整包对照）总注入 0 次 ⇒ 全部 not_exercised；
  run#4（第七条入包后）总注入 17 次、全部来自 `hls-empty-round-recovery`，整包
  判词 neutral（见 §5.3）。2026-10-14 入包的后八条已在 rev3 run 上跑过一轮
  对照（整包 Δ+0.0200、neutral；`hls-truncated-response` fires=18，另两条各
  fires=1，其余 5 条 fires=0 ⇒ not_exercised），2026-10-19 随 FREEZE-v3 全部
  冻结；**没有任何一条声称正增益**。本目录仍是「有证据的技能」——「已证有效」
  需要更大的样本，尚未达成。
