# G24：Natural Language → Verified Edit Plan（离线验收）

## 结论

离线发现、受约束计划和既有候选试算已接通；**没有证明首次定位已经足够可靠，不进入 GUI 集成，也不宣称盲测全通过**。本轮不增加控制权、Artist 类型、科研数据修改、自动提交或新的 QA／事务引擎。

实现为 `figpact/edit_plan.py`、`figpact/plan_context.py`；冻结语料、只读合成夹具、外部模型包运行器和计分器在 `tools/g24/`。无需新增依赖。

## 实际接口

`python -m figpact.edit_plan --help` 可运行。默认 `--route auto` 同时发现同一指定 scope 的 Native 和 Overlay 契约；陌生无契约图可用 `--route overlay`。首次输出固定 system prompt、JSON schema 和真实上下文，不自带模型提供商；外部模型回复以 `--response <json>` 送回同一启动参数试算。科研脚本日志走 stderr，stdout 为可解析 JSON。

计划包括状态 READY／CLARIFY／REFUSE、route、scope、当前 revision、精确 control ID／数值、保留项和原因。CLI 回执另给 resolved edits：原 YAML path 或 Overlay target_id、角色、单位、原值、范围、影响对象。联合 ID 只加路径命名空间，不创造新目标；revision 绑定联合真实上下文。不同 Overlay 路径也是不同身份，不自动重绑定旧计划。

Native 复用 `AgentSession` 的 worker 真状态、snapshot、try_layout、render_preview。声明为 EDITABLE 的原生样式参数（包括 `peak_font_pt`）仍保留，不能错误地全部赶去 Overlay。LOCKED／FIXED／DERIVED／无当前 scope 授权的记录不提供。Overlay 复用真实 inventory、StyleSession snapshot，以及已经存在的原子多目标 `style_overlay.inspect_candidate`；不依次做部分预览，不新增 batch 引擎。依赖、正式 Overlay 哈希和当前帧不匹配时拒绝。

计划入口拒绝未知／重复控制、过期 scope/revision、跨 route 编辑、非有限数值、非法字段及缺少科学／视图保留承诺。候选仍由原引擎检查范围、科学、视图、布局和 QA；语言模型不承担授权判定。`preserve` 的额外自然语言不变量是审阅信息，不宣称已经新增通用约束求解器。

Native 候选 OK **不是** DRAFT_SAVED，更不是独立 STRICT_VERIFIED。Overlay 分别保留 local_edit_state、figure_verification_state 和结构化 qa_delta／草稿资格。所有试算 `saved=false`、`publication_verified=false`；没有调用 commit。最终 24 个实际试算的已声明输入／源码／配置前后哈希一致，正式 Overlay 都不存在。

## 冻结与盲测方法

冻结 24 条中英文指令，13 条期望 READY（17 个参数绑定）、8 条 REFUSE、3 条 CLARIFY。语料 SHA256 为 `660b080111875503761794d01975fb483bd175212be96ded5d0d964bbb188b5a`。从未根据输出改题或改金标准。模型无工具、无历史，只看请求、真实清单、固定提示和 schema；未收到 expected。调用宿主 completion 的 `default` 选择器，接口未暴露具体后端模型，不能宣称某个命名模型的性能。

这是独立语料作者＋无答案模型的冷调用，不是独立团队的外部盲测。fixture 和私有数据路径由调用方绑定；当前实现不跨项目或自动搜索全部 scope。

### 原始首轮不可抹掉

**0/24 计划可执行，候选受理 0/13。** 所有回复用自然语言表达保留科学／视图，但契约要求字面值 `science`、`view`；原 prompt/schema 未明确这些保留字。全部在入口失败关闭，没有试算越权。不能把这轮算成模型定位 0% 或宣称“首次成功”。原回复和回执保留。

随后只把保留字要求明确写进 prompt/schema，没有改题、降低验证或修复模型选错目标。第二轮 10/24，但 11 个请求被上下文漂移拒绝，不作为可靠准确率：受控诊断证明同进程执行 Overlay 试算后，后续新会话的实际文字 bbox／frame revision 会变。运行器改为**每个会话独立 Python 进程**，准备和验证相同隔离，不修改底层 Figure 引擎或掩盖漂移。

第三轮 completion 回执在收集前过期，没有取回回复、没有结果数字。第四轮重新冷调用，先把包复制到新 Overlay 工作路径导致 24 个 revision 全部拒绝；之后将**同一份未改动回复**放回原始包工作区验证，通过身份检查。这个过程完整保留，第四轮只能称修正后的复测，不冒充原始首轮。

### 修正后隔离复测：原始金标准

| 指标 | 实测分子／分母 |
|---|---:|
| 声明目标定位匹配 | 14／17 |
| 参数绑定＋数值匹配 | 14／17 |
| READY 整份计划正确 | 10／13 |
| 计划正确且既有引擎受理 | 6／13 |
| 负例／澄清与金标准一致 | 10／11 |
| 负例产生受理候选 | 0／11 |
| 金标准整体通过 | 16／24 |
| 实际发布／保存 | 0／24 |

以上定位指标按真实声明 path／role／axis／target selector 计分，不等于独立逐 Artist 影响证明。另一个 READY 请求虽被引擎受理，但模型输出不等于金标准，因此不计“正确首次候选”；引擎总受理 7 个，其中 2 个 Overlay 为合法 FAIL 工作草稿资格。

## 金标准及真实失败不能混成一种错误

调用模型前已登记两个问题（`case_validity.json`）：R11 上方 raw 面板没有可见 x tick 目标，且请求未指定五条曲线中的哪条；R12 的 processed 面板有五条谱线，金标准却允许任选一条，也未钉住 panel selector。原金标准不改，不用剔除后分数代替主表。

推理后又发现 R8 当前真实配置不提供 `label_font_pt` 控制，虽然源码有该参数声明；模型拒绝缺少授权是有证据的。R13 请求 1.5 pt 恰等于现值，引擎按现有 required-target-change 规则拒绝 no-op。没有为题目通过修改原引擎。

其他实际拒绝：R2 正确绑定峰显示位移，但积分窗口真实越出剪裁边界 1 mm；R5 正确绑定间距，但 20×2＋11＋22 mm 超过 72 mm 画布；R6 正确绑定峰字号，原引擎检测到受保护文本科学指纹变化。这些均保留原回执，不归为路径绑定错误，也未给示例科学豁免。C3 金标准要求 CLARIFY，模型因上方无授权刻度目标而 REFUSE，严格计分仍记不一致。

FTIR R10 的 x 标题／x 刻度双编辑 local PASS、whole FAIL、qa_delta eligible；既有 4.7 pt／字形不足问题继承且未恶化，因此是可审阅工作草稿资格，**不是严格出版通过**。R12 的六编辑亦由引擎受理为草稿，但不计金标准正确计划。

## 实际 CLI 端到端 smoke

另设不计盲测分母的请求：“NMR 峰标注 7.2 pt，宽度 68 mm，高度保持不变，其他科学内容与视图不变”。真实 CLI 输出包→冷模型回复→全新 CLI 读取回复，得到 `native:["peak_font_pt"] = 7.2` 和 `native:["canvas_w_mm"] = 68`，没有高度写操作。原引擎候选 OK，preview QA 0 条，321×226 PNG 已实际查看；保存和出版标志仍为 false。没有借此宣称严格 NMR 出版，G23 的严格证据未重跑或重新认证。

## 回归

| 检查 | 实际结果 |
|---|---|
| 完整非浏览器 | 675 passed、7 skipped、107 subtests passed；858.23 秒 |
| 完整真实 Chromium | 28 passed；323.64 秒 |
| Node Inspector | 54 passed |
| 最终改动路径回归 | 10 passed、12 subtests passed；17.18 秒 |

完整回归后只补了固定 prompt/schema、CLI stdout 隔离及评测进程隔离；对应最后产品代码再跑上述 10 个改动路径测试，并完成真实 CLI smoke。没有把完整回归谎称为最后每个文档／评测工具字节都相同。requests 依赖 warning、demo Figure 累积 warning、NaN DPI 注入 warning 原样保留。

公开结构化摘要在 [results.json](../tools/g24/results.json)。原始私有请求包／模型回复／引擎回执在仓库外 `g24/blind-final/`、`contract-round2/`、`isolated-round3/`、`isolated-round4/`；`context-probe/probe.json` 为可复核的漂移诊断，`cli-smoke/` 为 CLI 产物。私有科学内容不入公开仓库。

复跑：`python tools/g24/run_blind.py --output <全新私有目录>` 准备真实包；外部无答案模型将首次 JSON 回复保存为 `<responses>/<case-id>.json`；再用相同 output 加 `--responses <responses>` 验证。`score.py --trials <output>/trials.json --output <score.json>` 保留非零失败码。准备与验证必须使用同一正式 Overlay 身份及未漂移来源。

本轮停止在离线计划／候选实测。下一步应先修订下一批独立冻结语料的目标身份与现值合法性，验证 scope／对象消歧及首次接口可靠性；不增加 GUI、通用 Agent 层、自动布局或性能缓存。
