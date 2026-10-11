# figpact (figure + pact)

面向 Agent 的科研图几何测量、排版契约与严格出版验收引擎。

## 核心设计
1. **测量与编辑分层**：Figure / Scene 的测量不要求 YAML、可编辑绑定或 `prepare_config`；可写编辑与保存使用真实 YAML 参数契约，数据与绘图逻辑仍在 Python。编辑路径上脚本可提供纯归一化钩子 `prepare_config(config) -> dict`，只补齐缺省的布局字段（不读盘、不写盘、不碰科学量、幂等）：会话用它建立基线配置，但 revision 仍按**原始 YAML 字节**计算；`build_scene()` 对传入的配置走同一个钩子，因此会话与 legacy 装载器看到同一套默认值。
2. **纯显示位移**：不改数据坐标，不改数据本身，仅在布局完成后施加 Display Shift。
3. **图元身份（GID）与参数绑定**：每个排版图元具备稳定 ID 并声明关联参数。
4. **严格验收（QA）与阻断机制**：排版几何越界（裁剪、重叠、压线、顺序颠倒）作为阻断项。
5. **原子发布**：通过暂存目录渲染，验收合格后原子发布，防止半成品或破损图覆盖正式产物。

## CLI 命令与使用
```bash
# 查看支持的参数清单（按可见对象分组，含单位、范围与调参效果）
figpact list-params --script <py> [--config <yaml>]

# 校验 YAML 配置格式与取值范围
figpact validate <yaml> [--script <py>]

# 试算改动，不保存配置、不覆盖正式图
figpact try --script <py> --config <yaml> --set <parameter>=<value>

# 渲染图表（支持 --strict 严格模式阻断）
figpact render --script <py> [--config <yaml>] [--strict]

# 导出图表（等价于 render --strict）
figpact export --script <py> [--config <yaml>]

# 清点可见图元清单并统计未登记/未绑定项，支持参数扰动生效检查
figpact inventory --script <py> [--config <yaml>] [--check-effect]

# 检查特定 gid 图元的几何与绑定详情
figpact inspect <gid> --script <py> [--config <yaml>]

# 导出每张图、每个 scope 的全部参数清单为 JSON
figpact export-params --script <py> [--config <yaml>] [--json]

# 遍历可见图元所有可调属性，做五类参数覆盖审计
figpact audit-params --script <py> [--config <yaml>] [--output <md>]

# 本机持久会话（JSON-RPC）：snapshot / inspect / try_layout / render_preview / commit
figpact agent --script <py> --config <yaml> --scope <scope> [--output-dir <dir>]
```

`agent` 在 stdin/stdout 上跑 JSON-RPC：每行一个
`{"jsonrpc":"2.0","id":1,"method":"…","params":{…}}`，stdout 每行一个响应（`result`
或 `error{code,message}`），**只承载协议**。`try_layout` 的操作记录用判别键
`operation`：

```json
{"jsonrpc":"2.0","id":1,"method":"snapshot","params":{}}
{"jsonrpc":"2.0","id":2,"method":"try_layout","params":{"revision":"<上一条的 revision>","operations":[{"operation":"set_relation","relation_id":"annotated.clearance.hama","target_mm":2.5}]}}
{"jsonrpc":"2.0","id":3,"method":"render_preview","params":{"revision":"<上一条的 revision>"}}
{"jsonrpc":"2.0","id":4,"method":"commit","params":{"kind":"draft","revision":"<上一条的 revision>"}}
```

`kind:"draft"` 只写 YAML 草稿（`DRAFT_SAVED`，**未过**严格校验）；`kind:"publication"`
必须带 `confirm:true`，在独立沙箱跑全量 strict 后才事务性安装产物并保存 YAML。
`--config` 指向哪份 YAML 就写哪份：试算请把真配置拷到临时目录、产物落 `--output-dir`
沙箱，确认再用真实路径。实测几何读 `relations[].value_mm`（声明的 `target_mm` 是目标，
不是结果）。完整键名、状态字面量与错误码见 `SKILL.md` §2.1。

## 本地调参预览
在仓库根目录运行 `python -X utf8 tools/gui/server.py --port 8731`，打开
`http://127.0.0.1:8731`。选择 FTIR 或 NMR，调整控件，点击“所见即所得 (Try)”
查看新预览、毫米位移与 QA 差异。服务仅监听本机，同端口本机来源可访问，
外站 Origin 请求在执行绘图前返回 403。

Scope 切换会重新预览所选版本，未保存值跨 scope 保留；对照图保留上下两格，
位移只作用于参数指定的那一格。请求中的无效 scope 会被拒绝。参数目录的
`path` 是实际 YAML 路径段，含点号的完整 GID 是一个键，不能按点号拆开。

GUI 候选预览由 `figpact.preview.preview(script=..., config=..., scope=..., patch=...)`
一次构图返回 PNG、几何和当前 scope 的 QA，不生成 PDF/SVG/TIFF。基线按配置、
源码和数据文件状态缓存；画布不使用 tight 裁切。界面中的“当前 scope 通过”
不是完整 strict 发布验收，正式出图仍使用原 strict 流程。

预览不修改配置或正式图；即使 QA 不通过，仍可查看候选结果。
“保存草稿”只保存合法的排版参数，保留注释和未改字段；布局有阻断或无法构图时
也可以保存，但界面明确标记不可发布。科学字段、只读标尺和未知参数不能保存。
“保存并发布”先在沙箱运行所有必需输出的原始 strict，再一起更新 YAML 和图件；
strict 失败时两者均不修改，后续文件替换失败会回滚已经替换的文件。

保存检查浏览器所持配置 SHA-256；旧版本返回 HTTP 409，不覆盖磁盘的新修改。
“撤销保存”恢复本会话中该图最近一次保存；若该次已发布，也恢复原图件。
撤销前同样检查新修改，服务重启后不保留撤销记录。定点保存使用已有 PyYAML，
不重写整份配置；含 YAML 引用（alias）的文件会被拒绝，以免改动共享的科学字段。

inventory 返回测量时的 `figure_dpi` 与 `figure_size_mm`；CLI 与 GUI 的 bbox 位移
按该 renderer 的 DPI 换算，不能使用 PNG/TIFF 导出的 DPI。

相邻距离使用物理毫米：FTIR `clearance_mm.<scope>.<上方曲线id>` 是包络净距，
NMR `pitch_mm.main.<上方样品id>` 是基线间距——两者都是**声明的目标值**，不是测得的事实。
GUI 支持整组同值、逐对距离和 `group_y_mm.<scope>` 整组位置；它同时显示**实测**距离、
距画布边界及坐标框的剩余空间。改一对不会改变其他相邻距离，也不会缩小信号；
放不下时报告实测超限 mm。`shifts_mm` 是**额外声明**的逐对象显示抬升，在距离调整之后叠加、
只作用于被点名的对象，实测值会把它算进去：因此声明的毫米数与实测毫米数一般不相等，
报告以实测为准，不把声明值当测量结果，也不声称它「落在声明的容差内」。

旧 schema 1 YAML 用原脚本 `--config <旧.yaml> --migrate-config <新.yaml>` 显式迁移；
新文件保留旧图的实测标尺和原点，`layout_reference` 只读，不是调图旋钮。
迁移不覆盖旧配置、不发布；不能直接把旧数据单位间距当成毫米值。

QA 差异和人工豁免按 `(rule_id, scope, object_ids)` 区分，测量数字不参与已识别
诊断的身份；未知诊断保留完整原文，不能人工豁免。旧文本签名记录不再用于放行，
需要重新审核后记录规则、对象和理由。

## 可公开复现的排版基线

`tests/fixtures/native_ftir.py`、`native_nmr.py`、`native_panels.py` 和
`native_mixed.py` 使用固定种子的合成数据，无需仪器原始文件；另有无效绑定、
科学载荷暗改与真实碰撞的负例。各夹具支持 `--strict --probe <沙箱目录>`，
独立检查所有声明版本并导出 PNG、PDF、SVG、TIFF。

```powershell
python -X utf8 tests/fixtures/native_panels.py --strict --probe "$env:TEMP/figpact-panels"
python -X utf8 tests/benchmarks/bench_vnext.py --lanes cold_preview warm_preview warm_qa --repeat 7 --json "$env:TEMP/figpact-baseline.json"
```

计时分开记录冷启动、重建出图、已构图 PNG 编码与 QA；PNG 编码时间不代表完整
预览或 Agent 任务耗时。科学检查保护实际绘制的数组、峰位、归属、原图像素、
裁剪范围、长宽比和比例尺含义，正式图与配置不被试算修改。

毫米位移可核对实际 renderer 的坐标；字体包围盒仍受 DPI 和栅格化影响，
不能宣称任意精度。移动图像时保护的是原图数组及科学窗口，不承诺不同画布下
重采样后的屏幕像素逐字节相同。

## 查询场景与物理几何

```python
from figpact import scene
from tests.fixtures import native_panels as plot

scope = "main"
fig, registry = plot.build_scene(plot.load_science(), plot.load_config(), scope)
snapshot = scene.snapshot(fig, registry, scope=scope, revision="baseline",
                          contract=plot.layout_contract(scope))
panels = scene.inspect(snapshot, type="panel")
```

快照给出稳定 ID、实际父节点、毫米边界、锚点、关系与精确 YAML 路径段；
`inspect` 可按 ID、名称、语义类型或 scope 查询邻居、关系和可控参数。
同一个已登记面板只有一个身份，未登记可见对象仍列入风险诊断。

六类测量为对齐、带符号包络间距、形状净距、容纳、等尺寸与均匀分布。
原点统一为画布左下角。曲线采用实际显示线段，不把整条曲线的矩形包络当轮廓；
文字包络、中心线与可见笔迹模型分别注明方法和局限。
快照记录 DPI、renderer、字体环境及 revision；允差是要求，不是测量精度。
96/300/600 DPI 实测四面板间距均为 6.000 mm、编号上内距均为 2.000 mm；
没有进行物理标定，因此不确定度保持未知。

编辑快路径同时检查移动的面板、图片和文字是否越出明确边界，不把裁剪后的可见范围
当作原对象已容纳。边界内的基线越界量为 0，不能把剩余边距当成既有越界来放行。
真实四面板 CLI 实测：新增 4.000 mm 越界被拒且候选状态不变；合法目标间距实测
5.000 mm，原图内容和尺寸不变。20 次热几何试算 P95 为 36.2 ms；
该候选未缓存预览为 0.176 秒，缓存命中单独计时，不冒充重绘或正式验收。

### 只测量，不提供 YAML

已有 Matplotlib Figure 可以直接测量，不必先建立排版配置或编辑契约：

```python
from figpact import GidRegistry, scene, geometry

snapshot = scene.snapshot(fig, GidRegistry(), scope="measurement")
panels = scene.inspect(snapshot, type="panel")["nodes"]
gap = geometry.measure_relation("gap", panels[:2], axis="x")
```

这里只读取图和空间关系，不调用编辑或保存。没有登记的可见对象仍报告风险；
临时对象身份只用于当前快照，不承诺跨版本稳定，也不虚构 `controlled_by`。
原有登记信息可直接传入测量，但能测量不等于获准修改。

当前无 YAML 的入口是上述 Python 接口；统一入口按只读“测量模式”和有真实绑定的
“编辑模式”区分，**尚未实现**——现在只有上述 Python 接口，以及下面的既有 CLI 与 GUI
（两者都在编辑路径上）。编辑模式继续检查参数范围、revision、科学载荷，
正式发布继续独立 strict；不为只读测量要求伪造 YAML、可编辑绑定或科学处理钩子。


## 数据文件说明
`examples/*/` 数据目录下的 PDF 与 PNG 文件（例如 `examples/ftir/2084_1788253487778_26083154776/26083154776/*.pdf` 为科学指南针测试机构导出的对照报告，`examples/nmr/核磁原始数据/*/pdata/1/thumb.png` 为 Bruker TopSpin 仪器采集生成的原始缩略图）均为仪器原始产物与输入数据，不是 render 导出的渲染产物。render 产生的所有构建产物均通过 `.gitignore` 排除，不进入版本跟踪。
