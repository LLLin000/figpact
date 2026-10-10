# figpact 技能 —— 新图接入与既有场景操作（SKILL.md）

`figpact`（Figure + Pact）分别提供**图的测量**与**有授权的排版编辑**。
测量读取 Figure / Scene 的对象和关系，不要求 YAML；编辑把科研载荷、
YAML 排版参数与显式绑定连接起来，记录改动会影响谁。
这里是通用规则；具体图的参数表和科学限制放在自己的示例 Skill。

## 什么时候读哪一节

| 你要做的事 | 从哪开始 |
|---|---|
| 只测量已有 Figure，不提供 YAML | §0 |
| 接入一张新图（新脚本 + 新 YAML） | §1 |
| 改一张已经接好的图（人改 YAML，或让 agent 操作场景） | §2 |
| 用既有 JSON-RPC 会话跑五个操作（确切键名与命令） | §2.1 |
| 判断一个改动能不能做、该报什么 | §3 身份与路径 · §4 不变量 · §5 验证等级 · §6 不支持与歧义 |
| 看真实范例与 legacy 人工闭环 | §7 · §8 |

---

## 0. 只读测量先行

已有 Matplotlib Figure 直接用 Python 场景接口取毫米几何：

```python
from figpact import GidRegistry, scene, geometry

snapshot = scene.snapshot(fig, GidRegistry(), scope="measurement")   # 已有 Figure，无 YAML
panels = scene.inspect(snapshot, type="panel")["nodes"]
gap = geometry.measure_relation("gap", panels[:2], axis="x")
```

没有登记表时传空 `GidRegistry()`：未登记可见对象仍进入诊断，不要求创建 YAML、编辑契约
或 `prepare_config`。这些临时身份只对当前快照有效；能测量不等于有编辑权限。

测量不要求 YAML、不要求可编辑绑定、不要求 `prepare_config` 与草稿文件；统一入口的
「测量模式 / 编辑模式」**尚未实现**，现在只有上面的 Python 接口与既有 CLI/GUI。
下面的接入、Worker、试算、保存与 strict 规则都只适用于编辑，不是测量的前置条件。

## 1. 新图接入

**先分家，再接线。** 分家的判据是双向的：

- `load_science()` 里**没有任何排版数值**（尺寸、字号、净距、锚点）；
- 科研值可以作为受保护记录保留在既有 YAML，但必须只读并进入科学不变量；不能把它们当排版旋钮。

分完家，脚本必须暴露**五个钩子**（legacy 入口原样保留，见本节末）：

| 钩子 | 职责 | 完成判据 |
|---|---|---|
| `load_science()` | 读数据 + 受保护计算；**不建 Figure、不打印、不解析 argv** | 确定性：重复调用得到同一结果，同一会话可反复复用同一个 science 对象；**复用与缓存归会话/worker 所有**，钩子本身不需要再造一套缓存或懒加载副作用 |
| `build_scene(science, config, scope)` | 由**候选配置**确定性建图，返回 `(Figure, GidRegistry)` | 同一 `(science, config, scope)` 永远得到同一张图 |
| `layout_contract(scope)` | 声明该场景的精确路径 / 节点 / 分组 / 关系 / 产物名 | 每个可编辑参数 `objects` 非空，且每个 gid 都真实存在（不声明不存在的图元） |
| `science_manifest(science)` | 声明来源、处理、受保护锚点与标尺含义；只列**偏离默认策略**的图元 | 峰锚点与绘图用的是**同一个检测函数**，不是另抄一份数 |
| `science_inputs()` | 逐条列出**实际读取**的输入文件（精确路径，不 glob、不扫目录）；等价写法是模块级 `SCIENCE_INPUTS` | 声明的文件不存在就报错，不静默丢；产物不算输入 |

**新图优先显式传参。** 新脚本用 `build_scene(science, config, scope)` 收三个显式参数，
只从传入的配置确定性建图，不依赖模块全局。legacy 脚本把 YAML 装进模块全局也可以，但
**只留一条初始化路径**（例如 `_apply_config(cfg)`）：不要出现「另一处也把 YAML 读进另一套
全局」的分支——两份约定一定会漂。新 builder **不要求**经过 legacy 的 `_apply_config`；
全局初始化是 legacy 的兼容手段，不是新图的门槛。legacy 侧构建路径也只留一份：
`build_figure_and_registry(scope)` 与 `build_scene(science, config, scope)` 共用同一个
`_build(...)`，差别只在配置来源（基线 vs 候选）与科学对象（自取 vs 传入）。

### 可选纯归一化钩子：`prepare_config(config) -> dict`

原始 YAML 缺的布局字段要补齐（某作用域/对象没写就当 0 之类），否则「会话把原始 YAML
交给 `build_scene`」与「legacy 装载器读 YAML」会得到两套默认值——一份 YAML 两种行为。
补法只有一个：一个**纯函数**钩子。

- 输入输出都是映射：调用方给**独立拷贝**（不会回写 YAML），你返回归一化后的新映射；
  返回不是映射就是脚本错误。
- 只做布局参数的**纯归一化**：缺省补全、旧字段升级、键名/单位规范化、范围校验。
- **不读文件、不写文件、不建 Figure、不碰科学量与绘图**；幂等——归一化两次结果相同。
- 三种调用方共用同一个函数，拿到同一套默认值：会话装载基线时对 `deepcopy(原始 YAML)`
  调一次并按结果建基线；`build_scene()` 收到 `config` 时也先过它（外部直接调用脚本同样
  得到归一化结果）；legacy 的 `load_config_*()` 读盘后也调它。
- **复用 legacy 已有的归一化实现**，不写第二套。例如 `load_config_ftir` / `load_config_nmr`
  里补 `shifts_mm` 缺省的那段就是归一化：把它提出来让两处共用。
- **归一化不是改动**：YAML 的 revision / 指纹仍按**原始文件字节**计算；钩子只补配置语义。

legacy 接缝保持原样：`SCOPES`、`FIGURE_ID`、`CONFIG_PATH`、脚本自身的 `SCHEMA` 与模块级
配置装载器（名字随脚本，例如 `load_config_ftir` / `load_config_nmr`，夹具用
`load_config(path)`——**不要假定全库只有一个单参数 `load_config()`**）、
`build_figure_and_registry(scope)`，以及脚本自身的
`--config / --inventory / --strict / --probe / --inspect / --list-params / --check-effect`。
`prepare_config` 是新增的**可选**钩子，缺了不影响 legacy 行为。
作为模块被导入时**不解析调用方 argv、不打印、不落盘**（argparse 只在 `__main__` 里跑），
否则持久 worker 的协议参数会被当场拒掉。

## 2. 既有场景：五个核心操作

| 操作 | 做什么 | 完成判据 |
|---|---|---|
| `snapshot()` | 量出当前场景：mm 物理坐标、canvas 左下原点、节点/关系/参数索引 | 量不出来的对象报 `UNMEASURED`，**绝不填 0 或估计值** |
| `inspect()` | 按 gid / 名字 / 类型 / 作用域查节点、邻居、关系、参数 | 每个参数都带精确路径数组 |
| `try_layout()` | 一批已声明的改动（`set_parameter` / `set_relation`）→ 候选配置 | 原子：失败不改状态；候选**永远**由「基线配置 + 已声明目标」推导，不是累加变换 |
| `render_preview()` | 出候选 PNG | 同一 revision 缓存；只预览，不发布 |
| `commit()` | 保存 YAML 草稿，或独立全量 strict 发布 | 严查 revision；科学或 QA 检查失败不安装正式图件 |

`check_effects()` 是辅助诊断：真实扰动 YAML 并重建，区别 `NO_EFFECT`、
`EFFECT_MISMATCH` 与科学违规；不属于只读测量的必需步骤。

规则：

- **只有 `translate` 是纯固定框刚体位移**（显式声明、毫米、完整受影响集合）；其余改动一律 rebuild/render。
- **声明的是目标，实测的是事实。** 参数值（净距 / 间距 / 位移）是你**声明**的目标；
  `snapshot()` 与关系测量给出的是重建后的**实际**几何。逐对象显示位移是叠加在距离调整
  **之后**的额外抬升，实测值会把它算进去：所以声明毫米数与实测毫米数一般不相等——报告以
  实测为准，不拿声明值当测量结果，也不说实测「落在声明的容差内」。放不下时报**实测**超限毫米数。
- **一个 scene 可以有多格。** 作用域是布局与校验的归属范围，不是文件名：例如 FTIR 对照版
  上下两格同在一张图里（`examples/ftir/SKILL.md`），是两个独立作用域共享一个产物；操作
  `compare_raw` 的路径**不会**动 `compare_processed` 的图元。
- **产物名 ≠ 作用域名。** 每个作用域声明自己的产物文件；发布时并集去重，正式产物按**精确
  声明路径**排除，不按扩展名一刀切。
- 人改 YAML 的 legacy 闭环仍然是：`figpact try`（只在内存合并、写沙箱）→ 审阅对象位移毫米数与
  可行区间 → 写 YAML → `figpact render --strict`（有未豁免阻断项则退出码非零且不覆盖正式产物）。

## 2.1 本机 JSON-RPC 会话：命令、信封与五个操作的精确形状

常驻会话是**一张图、一个作用域、一个进程**；stdin 每行一个 JSON 请求，stdout 每行一个
JSON 响应，**stdout 只承载协议**（不要往里打日志；诊断在结果字段里：`diagnostics[]` / `checks[]` / `qa`）。

```bash
python -m figpact agent --script examples/ftir/plot_ftir.py \
    --config examples/ftir/ftir.yaml --scope annotated [--output-dir <发布目录>]
```

请求 `{"jsonrpc":"2.0","id":1,"method":"<method>","params":{…}}`；成功回
`{"jsonrpc":"2.0","id":1,"result":{…}}`，失败回 `{"id":1,"error":{"code":<int>,"message":…}}`。
`id` 缺省（通知）不回；一行也可以是请求数组，按项回复。`params.detail` 只接受 `summary`
（默认，长几何采样折叠成 `{"elided":true,"hint":…}`）或 `full`（原样）。

| method | `params`（精确键名） | `result` 关键字段 |
|---|---|---|
| `snapshot` | `{}` | `revision` `scope` `unit` `measurement` `nodes[]` `relations[]` `parameter_index[]` `containment` `diagnostics[]` |
| `inspect` | `{"ids":[…], "name":…, "type":…, "scope":…}` | `count` `nodes[]` `neighbors` `relations[]` `parameters[]` `diagnostics[]` |
| `try_layout` | `{"operations":[<op>…], "revision":"<rev>"}` | `status` `message` `verification` `changes[]` `affected_objects[]` `relations[]` `checks[]` `diagnostics[]` `science_unchanged` `revision` |
| `render_preview` | `{"revision":"<rev>"}` | `png`（base64）`cached` `qa` `relations[]` `space[]` `science` `inventory` |
| `commit` | `{"kind":"draft"\|"publication", "revision":"<rev>", "confirm":<bool>, "output_dir":"<dir>"}` | `status:"committed"` `kind` `verification` `changed_paths[]` `files`/`artifacts[]` |

辅助：`status`（当前 revision / `has_candidate` / 契约摘要）、`close`（结束会话）。

`try_layout` 的每条操作记录用判别键 **`operation`**（不是 `op` / `kind` / `type`）：

```json
{"operation":"set_parameter","path":["clearance_mm","annotated","hama"],"value":2.5}
{"operation":"set_relation","relation_id":"annotated.clearance.hama","target_mm":2.5}
{"operation":"reset"}
```

- `path` 是**数组**，逐段是 YAML 真实 key（gid 里的点号不是路径分隔符）；`set_relation` 只认
  契约里声明过的关系 id（`id` 是别名，规范写法 `relation_id`）。
- 候选**永远**是「基线配置 + 当前累积目标」，不是累加变换；一批里任一条非法整批不生效、状态不变。
- 带 `revision` 就必须等于会话当前 revision，否则 `STALE_REVISION`。

**声明 ≠ 实测。** 操作里的 `value` / `target_mm` 是**声明的目标**；实际几何读
`snapshot` / `render_preview` 的 `relations[].value_mm`（并看 `status` `precision` `calibrated`
`uncertainty_mm`）。`shifts_mm` 这类逐对象显示位移叠加在净距调整**之后**，实测会把它算进去，
所以声明毫米数与实测毫米数一般不相等——报告以实测为准，也不说它「落在声明容差内」。

**找 id / 参数不用读绘图源码。** 一次 `snapshot` 就够：`relations[].id` 是关系 id，
`relations[].controlled_by` 是它映射到的精确路径，`parameter_index[] = {path, objects}` 是
路径↔对象索引，`nodes[].controlled_by` 是反向映射；要 `min` / `max` / `operation` /
`mutability`（含只读的 `FIXED_STYLE` / `DERIVED`）用 `figpact list-params --script <py> --config <yaml>`
或 `figpact export-params --script <py> --config <yaml> --json`。id 各图不同，**先查再写**，
不要照抄另一张图的字面量。

**二维标签位移**使用 `value:[dx_mm,dy_mm]`，只接受基线本来就是两个有限数字、且
契约声明 `operation:"rebuild"` 的精确路径。两个分量分别检查范围；必须真实重建、
测量并检查科学指纹和 QA，返回 `RENDER_CHECKED`，不能走刚性平移预测。
标量参数不接收数组，关系的 `target_mm` 仍是标量。

失败返回非 `OK` 的 `status`（会话状态不变）：`LOCKED`（科学量）、`UNCLASSIFIED`（缺可变性
或 `operation` 声明，失败关闭）、`OUT_OF_RANGE`、`UNSUPPORTED_PATH`、`NOT_IN_SCOPE`、
`AMBIGUOUS`、`UNKNOWN_RELATION`、`UNSUPPORTED_RELATION`、`GEOMETRY_REJECTED`（实测碰撞/越界，
`message` 是**实测**毫米数）、`NO_EFFECT`、`EFFECT_MISMATCH`、`QA_BLOCKED`。**被拒就是没做到**：
不要把声明的目标值当结果报出来（净距要 1.5 mm 被拒，就不能说「已到 1.5 mm」）。成功时
`verification` 是 `GEOMETRY_CHECKED` 或 `RENDER_CHECKED`，两者不可互相冒充（§5）。

**`commit` 的两种 kind 信任等级不同，别混：**

- `kind:"draft"`：把候选写回 `--config` 指向的 YAML（原子替换，保留注释与未改字段），
  `verification:"DRAFT_SAVED"`——**没有**严格校验，草稿还不等于「可发布」。
- `kind:"publication"`：必须显式 `confirm:true`（否则 `INVALID_PARAMS` 直接拒）；在**独立沙箱**
  跑全量 strict、比对科学指纹与基线，再把**该图全部声明产物**（各作用域并集去重）**事务性**
  装入 `output_dir`（缺省=脚本目录）并保存 YAML；任一步失败则产物与 YAML 都不动
  （错误码 -32005 `COMMIT_REJECTED`）。它是**独立**于草稿的第二次真实校验，不靠草稿的正确性。
- 提交前提：本会话有过**成功**的 `try_layout`（否则 -32004 `NO_CANDIDATE`），且 revision 是
  **当前** revision；候选生成后磁盘 YAML / 脚本 / 输入文件被改动同样拒（-32003）。
- **draft 之后会重新基线**：草稿写回 YAML，下一次调用按新文件重读基线、**清空候选目标**、
  revision 随之改变。**同一会话不需要重启**：重新 `snapshot` 拿新 revision，再
  `try_layout` → `render_preview` → `commit`；直接 `commit` 会因为没有候选而 -32004。
  `publication` 成功同样会推进磁盘 revision（届时照同一流程取新 revision）。

常用错误码：-32700 解析 · -32600 请求非法 · -32601 未知方法 · -32602 `params` 非法
（含 publication 缺 `confirm`）· -32603 内部错误 · -32001 会话不可用 · -32002 会话已关闭 ·
-32003 `STALE_REVISION` · -32004 `NO_CANDIDATE` · -32005 `COMMIT_REJECTED` · -32006 worker 错误。

**试算用沙箱副本，确认才动真件。** `--config` 指向哪份 YAML，draft / publication 就写哪份；
`--output-dir` 指向哪，产物就装到哪。探索阶段把真 YAML **拷一份到临时目录**当 `--config`、
产物落沙箱目录（真件零改动）；人或 CI 复核后，再用**真实配置路径**开新会话、带 `confirm:true`
做正式发布——发布写的是**你传进去的那份原始配置**，不要对着真配置反复试。

## 3. 稳定身份与精确参数路径

- **gid 是外部引用认的完整身份**（YAML、Skill、GUI、诊断等），不是旋钮；改身份须迁移引用。
- 身份在作用域内唯一并跨重建稳定；可以含点号，不能把完整身份按点号拆成参数路径。
  同一个对象只有一套身份构造规则，派生身份也遵循明确规则。
- **panel（Axes）也有作用域限定的 gid**（`<fig>.<scope>.panel`）：`panel.0` 这类位置编号在
  「一张图里两个作用域」时必然撞名，节点归属、视口声明和诊断都会指错轴。
- **参数路径是数组**，逐段是 YAML 的真实 key：`["clearance_mm", "main", "zno"]`、
  `["peak_label_shifts_mm", "main", "peak.vancho.3p91"]`。gid 里的点**永不**当路径分隔符用。
- 声明的关系用 `controlled_by` 指回这些精确路径；`move` 是**实际会动**的那批 gid。
- **可见的文字与线都要有身份**：轴标题、分图标题、图例里每一行样品名、每条谱线、每条基线、
  每条引线。可见却没有 gid 的文字只能被按位置编号，科学指纹和豁免键都会跟着漂。
- 声明节点/类型/角色时按 **artist 身份**判定（轴标签的 `.axes` 是 `None`、`loc="left"` 的标题
  挂在 `_left_title` 上），不要靠切 gid 字符串猜。

## 4. 不变量声明

- **科研指纹**：原始/处理数组、归属与标注文字、图像像素、受保护的显示窗口与标尺含义。
- 节点策略只有两类，**缺声明 = `UNCLASSIFIED`，失败关闭**：
  - `LOCKED_SCIENCE`（默认）：进指纹。谱线、峰/归属文字、轴文字、图例文字都属这类；
  - `LAYOUT`：纯布局几何，不进指纹。**只有点名的装饰线**能走这条：
    `science_manifest.nodes[gid] = {"science_policy": "LAYOUT", "type": "guide"}`——
    典型是峰标注引线与基线虚线，它们的位置是排版，不是数据。
- **`LAYOUT` 不能拿来豁免科研内容**：原始谱线/散点、图像像素、集合段（误差棒等）
  **永远**进指纹，给它们写 `LAYOUT` 不会生效，只会掩盖一次真实的科学改动；
  引线/基线这类装饰线必须**显式点名**并写明 `type: "guide"`。锚定的峰位与标尺含义
  仍在 `science_manifest` 里单独声明，不受豁免影响。
- 纯显示位移（`apply_display_shift`）叠加的是 transform，不改数据坐标，所以
  「改净距 / 整组平移 / 单条位移」不产生科学差异；改数据、改显示窗口、改标尺才会。
- **定性 y 轴的冻结视口**：`science_manifest(science)['layout_viewports']` 声明
  `{axes_gid: {axis: "y", origin: <只读 ylim 原点>, units_per_mm: <只读 数据单位/mm>}}`，
  两个值都来自只读的 `layout_reference`。于是**画布变高只加余量**（span 变大）、信号的
  物理标尺与原点不动；x 窗口不在这条豁免里，它锁死在这张图回答的问题上。
  只给**定性轴**（a.u.）声明；定量轴不得靠这条豁免放宽。

## 5. 验证等级

- 返回里写明等级：`GEOMETRY_CHECKED`（几何、关系、包含、受影响集合实测，无 PNG）
  或 `RENDER_CHECKED`（真重建 + 全量 QA）。**不要拿几何检查冒充渲染检查。**
- 关系测量的 `status`：`OK` / `UNSUPPORTED` / `UNMEASURED`；`precision`：`exact`（数学几何）
  或 `envelope`（渲染盒）。`uncertainty_mm: null` 表示**未标定**，不是容差。
- 容差要么给出**实测标定过**的容差，要么暴露不确定性；`.001 mm` 是格式，不是精度。
- 门：strict 只对**新增**阻断项报警（存量问题走人签的豁免基线，`reason` 非空）；阻断项**不许**
  记进豁免。`--strict` 通过 ≠ 可以投稿——出版下限（字形、贴边）是排版取舍，看审计行。
- **绝对毫米数一律量导出件**（PDF/PNG）；不同 matplotlib 版本文字度量会差几毫米。

## 6. 不支持与歧义

| 情形 | 正确反应 |
|---|---|
| 路径没有可编辑映射 | `UNSUPPORTED`（明确状态，不是静默无操作） |
| 一个要求能落到多个参数 | `AMBIGUOUS` + 候选项列表；**不替用户挑一个** |
| 缺 mutability / 策略声明 | `UNCLASSIFIED`，失败关闭 |
| 空间放不下 | 报实测超限毫米数（`NO_FEASIBLE_SLOT`）；**不**缩字号、不裁数据、不缩小信号 |
| 图例要纵向自由移动 | 拒绝：该图没有这个自由度的可编辑绑定，报 `UNSUPPORTED` 并说明排版模型缺哪一维旋钮；各图口径见 `examples/*/SKILL.md` |
| 要求改科研量（归一化标尺、参考基准/定标、峰位、显示窗口） | 拒绝：这是「这张图回答什么问题」，不是排版 |

## 7. 禁止

- **不直接改 Artist 让 YAML「看起来生效」**（`set_position` / `set_fontsize` / `set_linewidth` /
  手改 transform / 手写 `_figpact_*`）。YAML 与 gid 之间必须有真实的构建路径，否则就是假绑定。
- 不把显示位移写回数据坐标，不为过 QA 缩字号、裁数据或加豁免。
- 不拿一个作用域的路径去动另一个作用域的图元，不把同一个 gid 用在两个 Axes 上。
- 不为通过检查而改科学量、删可见图元或让未注册的可见对象隐形——**报出来**。

## 8. 参考实现

- `examples/ftir/plot_ftir.py` + `examples/ftir/SKILL.md`：四作用域、两格共享产物、包络净距、归属标签分层。
- `examples/nmr/08 NMR.py` + `examples/nmr/SKILL.md`：单作用域、峰标注有界确定性避让、引线与基线声明为 `LAYOUT`。
- `tests/fixtures/native_*.py`（原生夹具，随引擎实现版本更新）：曲线、峰文字+引线、四图像面板、曲线+图像混合、
  以及**反例**（故意未使用的参数、错绑定），都是可直接跑的真实 native 脚本。
- `CONTEXT.md`：领域词汇表（scene / scope / envelope / gap / clearance / candidate 的确切含义）。
