# figpact (figure + pact)

科研出版图的参数契约与质量保障引擎。

## 核心设计
1. **参数契约**：排版参数在 YAML 集中管理，数据与绘图逻辑在 Python 脚本。
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
```

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
NMR `pitch_mm.main.<上方样品id>` 是基线距离。GUI 支持整组同值、逐对距离和
`group_y_mm.<scope>` 整组位置；显示实际距离、距画布边界及坐标框的剩余空间。
改一对不会改变其他相邻距离，也不会缩小信号；放不下时报告超限 mm。
独立 `shifts_mm` 在距离调整之后叠加，实测值会反映这一步微调。

旧 schema 1 YAML 用原脚本 `--config <旧.yaml> --migrate-config <新.yaml>` 显式迁移；
新文件保留旧图的实测标尺和原点，`layout_reference` 只读，不是调图旋钮。
迁移不覆盖旧配置、不发布；不能直接把旧数据单位间距当成毫米值。

QA 差异和人工豁免按 `(rule_id, scope, object_ids)` 区分，测量数字不参与已识别
诊断的身份；未知诊断保留完整原文，不能人工豁免。旧文本签名记录不再用于放行，
需要重新审核后记录规则、对象和理由。

## 数据文件说明
`examples/*/` 数据目录下的 PDF 与 PNG 文件（例如 `examples/ftir/2084_1788253487778_26083154776/26083154776/*.pdf` 为科学指南针测试机构导出的对照报告，`examples/nmr/核磁原始数据/*/pdata/1/thumb.png` 为 Bruker TopSpin 仪器采集生成的原始缩略图）均为仪器原始产物与输入数据，不是 render 导出的渲染产物。render 产生的所有构建产物均通过 `.gitignore` 排除，不进入版本跟踪。
