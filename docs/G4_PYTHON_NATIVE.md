# G4：无 YAML 的 Python 原生布局编辑（试点）

## 工作事实

基线：`a8db88a`（example + 适配器 + repair spec）；本报告的端到端流程改动与文档同批提交。本轮实现 **G4 试点**：一份**无 YAML** 的极简图，把排版位移以模块级 `LAYOUT_MM` 写在源码里，用 `ast` 唯一定位、只计划、显式授权后才写、另起进程重建实测、记 history、并按前向写入恢复。

**这是试点，不是"通用无 YAML 编辑已完成"。** 本轮只覆盖自带的 `examples/python_native/simple_figure.py` 这一类**显式声明布局绑定**的脚本；对任意 legacy 脚本只给候选提案与 `AuthoringRepairSpec`，**不做自动改写**。真实 NMR/FTIR 继续走既有 YAML adapter，本轮未改、未接。

修改文件：

- **新增** `examples/python_native/simple_figure.py`（119 行）：一条曲线 + 两个标签，模块级 `LAYOUT_MM = {gid: [dx, dy]}`，`build_scene(science, config, scope)` 经既有 `figpact.apply_display_shift` 施加位移；无 YAML、无随机/时间/文件 IO（导入本模块不写任何文件）。
- **新增** `figpact/python_native.py`（529 行）：`read_layout_binding` / `locate_layout_literal` / `plan_layout_edit` / `apply_planned_edit` / `edit_layout_and_verify` / `restore_layout_from_history`，以及 `LayoutBindingError`、`VERIFY_TOL_MM`。
- **新增** `figpact/authoring.py`（296 行）：`build_repair_spec(*, script, target_gid, session)`，字段对齐设计包 schema；**不执行用户脚本、零写入**；会话里没有的事实写 `unknown`。
- **新增** `tests/test_python_native_example.py`（3 项）、`tests/test_python_native.py`（14 项）、`tests/test_authoring.py`（9 项）、`tests/test_python_native_edit_flow.py`（4 项）。

未修改 `scene.py`、`geometry.py`、`science.py`、`intents.py`、`history.py`、`source_writes.py`、Inspector HTTP/UI、既有 YAML Agent API 或 `examples/` 下任何既有文件。

## 机制与不变量

### 绑定声明与定位

- `LAYOUT_MM` 是**模块级字典字面量**，值是 `[dx, dy]`（毫米）。名字不是配置项：改名等于没有声明（`LAYOUT_NAME`）。
- `read_layout_binding` 在隔离命名空间装载脚本（`spec_from_file_location` + 屏蔽 stdout，模块名唯一、用完即从 `sys.modules` 摘下），返回声明的**深拷贝**；没有声明返回 `{}`（"没声明"是事实，不是错误），导入期自己抛异常则不吞。
- 定位一律走 `ast`，且**只在模块级 `LAYOUT_MM` 字典里按字符串 key 精确匹配**——同一份源码里别处的同名字面量可能是科学数据，"用正则找一个数字就直接改"是该阶段明令禁止的。`locate_layout_literal` 只在命中恰好一次且字面量是纯数字 `[dx, dy]` 时返回 `{start, end, value, line}` 字符偏移，否则返回 `None`。

### 先计划、后授权

- `plan_layout_edit` 只做三件事：定位 → 生成"只替换命中的那个字面量、其余字节原样保留"的新源码 → 写 G3b journal/blob。**用户源码一个字节都不改。**
- 不确定一律停在提案，**即使已授权也零写入**：`AMBIGUOUS`（同一 key 出现多次、或字面量不是纯数字 `[dx, dy]`）与 `NEEDS_AUTHORING`（源码里没有这条绑定、脚本不存在、或源码不是 UTF-8 文本）都附 `candidates` 与 `confidence='low'`。
- 真正落盘要调用方拿 journal id 显式授权给 `apply_planned_edit(journal_id, authorized=...)`；`authorized` 不为真时直接 `UNAUTHORIZED`，且**授权检查发生在读取 journal 之前**，不碰任何文件与状态。写入走 G3b 的 `apply_source_change`，journal 状态即事实（成功 `COMMITTED`，写入期失败由 G3b 受控回滚）。
- `_format_pair` 用 `repr` 往返无损：只改数字，绝不顺手重排或截断精度。

### 重建实测用独立进程探针

- `edit_layout_and_verify` 的顺序是：改前先量一次基线 → 授权落地 → **另起子进程**按 `FigureSession` 的真实接缝重建一次 → 比对。
- 探针是新解释器 + `PYTHONPATH` + `Agg`，避免模块缓存把"重建"变成"看旧世界"；它把画出来的毫米几何、图元身份（gid 集合）与**科研载荷指纹**（`load_science()` 输出的 SHA256）原样报回，**探针自己不判对错**，判定留在调用方。
- 三条不变量同时成立才算 `OK`：磁盘字节必须等于 after blob；目标 gid 的实测位移必须在 `VERIFY_TOL_MM = 0.01 mm` 内；其余测量键、gid 集合与科研载荷指纹必须一动不动。任一条不成立就返回 `MISMATCH` / `PROBE_FAILED` / `APPLY_FAILED` 并列出 `problems`，**绝不报成功**。
- 通过后把这次写入记成 `source_change` 检查点（`file_changes[]` 含 `path` / `before_sha256` / `after_sha256` / `is_binary` / `before_blob` / `after_blob` / `diff`）。

### 恢复是新的前向写入

- `restore_layout_from_history` 把检查点里的 **before** 内容作为目标、当前磁盘作为 before，走 G3b 的 `restore_project` 生成**新的 journal**；旧 journal 与旧检查点字节未被改写。
- 恢复本身也落地，所以恢复同样追加一个新的 `source_change` 检查点，否则 history 描述的"磁盘现状"会与真实磁盘对不上。
- **签名偏差（如实记录）**：该函数需要 `script` / `config` / `scope`，因为 `HistoryStore` 以工作区身份（脚本 + 配置 + scope）索引，单凭 `commit_id` 定位不到检查点。这不是设计意图，是当前存储接口的约束。

### 提案侧（`authoring.py`）

- `build_repair_spec` 只读源码字节与 `ast`，输出 `schema_version` / `repair_spec_id` / `intent_id` / `target_gid` / `base_source_sha256` / `goal` / `allowed_paths` / `forbidden_science_changes=true` / `fixed_gids` / `allowed_follow_gids` / `source_candidates` / `requires_explicit_approval=true` / `max_candidate_builds`。
- `session` 按鸭子类型取用（`contract` / `science_manifest` / `intent_id` / `desired_delta_mm` / `owned_closure()` / `state()`）；**会话没声明就写 `unknown`**，绝不用环境猜测补上。
- 它**只出提案**：不执行用户脚本、不建 Figure、不写任何文件。

### 本轮发现并修正的两处缺陷

1. `build_repair_spec` 的 `allowed_paths` 曾输出模块名而非 `.py` 文件路径，已改为带后缀的同目录相对路径。
2. 适配器测试夹具曾用文本模式写入，导致 Windows CRLF 与期望字节不符；实现本身是逐字节保真的，已把夹具改为逐字节写入。这是夹具问题，不是实现缺陷。

## 风险与权限

- **未接 UI / Hub**：本轮只有 Python API，没有浏览器/对话框授权流程。"授权"在 API 层就是一个显式布尔，不代表已有面向用户的授权链路。
- **不修 legacy 脚本**：`NEEDS_AUTHORING` 只给提案与 `AuthoringRepairSpec`，对任意旧脚本**不做自动改写**；无绑定就是无绑定，不猜常量。
- **只写被点名的目标脚本**：写入的是 G3b 的 journal/blob（落在 `state_home`）与被显式授权的那个 `.py`；不改科学数据、不碰 git、不加依赖、不改 `examples/` 下既有文件。
- **歧义即拒绝**：同一 key 多次出现、重复定义、非纯数字字面量一律 `AMBIGUOUS` + `confidence='low'`，**已授权也零写入**。宁可拒绝，不碰可能是科学数据的字面量。
- **`VERIFY_TOL_MM = 0.01 mm` 是验收容差**，不是宣称物理测量精度。探针复用的是既有 `apply_display_shift` 与量测接缝，本轮不新增绘图引擎。
- 本轮**未**做崩溃/强杀注入，**未**验证跨 scope 的源码编辑，**未**在多写者并发下验收（沿用 G3b 的单写者假设）。
- 未在真实 NMR/FTIR 上跑，也未接 UI/Hub/Agent 路径；不能据此声称这些风险已经解决。

## 真实验收

以下数字均为父代理亲自跑出的实测结果。

```bash
pytest tests/test_python_native_example.py tests/test_python_native.py tests/test_authoring.py -q
pytest tests/test_python_native_edit_flow.py tests/test_python_native.py tests/test_python_native_example.py tests/test_authoring.py tests/test_source_writes.py tests/test_history_file_changes.py tests/test_history.py -q
```

| 本轮运行 | 通过 | 失败 | 跳过 | 实际耗时 |
|---|---:|---:|---:|---:|
| 底座（example + adapter + repair spec） | 26 | 0 | 0 | 未单独记录 |
| 端到端流程 + G3b/G3 底座 | 65 | 0 | 0 | pytest 38.88 s |

65 = 新增 4（`test_python_native_edit_flow.py`）+ 14（`test_python_native.py`）+ 3（`test_python_native_example.py`）+ 9（`test_authoring.py`）+ 既有 7（`test_source_writes.py`）+ 5（`test_history_file_changes.py`）+ 23（`test_history.py`）。本轮**未跑全量**，也未运行前端 Node 测试、lint 或格式化。

### 扰动证明（真实重建，不是断言模拟）

把 `LAYOUT_MM` 里目标 gid 的字面量改成 `[0, 0.2]` 后**真实重建**，`tests/test_python_native_example.py` 实测：

- 只有目标 GID 的几何发生位移，实测位移与请求值在 **0.01 mm** 内一致；
- 其余测量键不变、GID 集合不变、科学指纹不变；
- 样例本身无 YAML、无环境输入（`test_example_has_no_yaml_and_no_ambient_inputs`）。

### 计划 → 授权 → 重建 → history → 恢复

`tests/test_python_native_edit_flow.py` 4 项按真实磁盘行为覆盖：

- **未授权**：`status='PLANNED'`、`written=False`，**用户源码字节与目录树不变**（只落 G3b journal/blob 到 `state_home`）。
- **授权写入**：落盘后磁盘字节 == after blob，并把这条写入记成 `source_change` 检查点；`file_changes[]` 里的 `path` / before/after SHA256 / blob 与磁盘实际字节一致。
- **前向恢复**：`restore_layout_from_history` 把文件恢复为历史 before 内容，产生**新 journal**；旧 journal 与旧检查点字节未被改写，恢复本身也追加一个新的 `source_change` 检查点。
- **歧义拒绝**：绑定出现歧义时**即使已授权也零写入**（`AMBIGUOUS` + `candidates` + `confidence='low'`）。

### 提案侧

`tests/test_authoring.py` 9 项覆盖：legacy 脚本的关键字段对齐 schema；已声明绑定判为 `confirmed` 候选；非字面量绑定只给 `candidate`；**信息缺失留 `unknown`**（不猜）。`build_repair_spec` 全程零写入、不执行用户脚本。

## 边界与未完成项

- **无 YAML 的 Python 原生编辑试点：已验证**（上表 65 项端到端 + 底座 26 项）。**通用无 YAML 编辑能力：未验收。**
- 只覆盖**显式声明 `LAYOUT_MM`** 的脚本；对任意 legacy 脚本只给候选提案与 `RepairSpec`，**不做自动改写**。
- **未接 UI / Hub**：授权只是 API 层的显式布尔，没有浏览器或对话框授权流程。
- 未在真实 NMR/FTIR 上运行（它们继续走 YAML adapter）；未验证跨 scope 的源码编辑。
- `restore_layout_from_history` 需额外传 `script` / `config` / `scope`（`HistoryStore` 的工作区索引所限），本轮如实记录，未改存储接口去消除它。
- 未做崩溃/强杀注入下的恢复验收；未做多写者并发控制（沿用 G3b 单写者假设）。
- **G6（冻结场景三臂配对 benchmark + profiler）未开始。**
- 后续若要把这条链路接给用户，应另行验收：授权来源与 UI 链路、legacy 脚本的作者级改写路径、以及跨 scope/真实图件上的源码往返；不能只因本轮单测通过就称"无 YAML 编辑"这条用户链路已完成。
