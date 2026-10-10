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

试算使用临时发布目录，不修改正式输出；即使 QA 不通过，仍可查看候选预览。
界面目前不自动保存配置或导出正式图：点击“复制 Patch”，将对应改动合并到
该图 YAML，再运行 `python -m figpact render --script <py> --config <yaml> --strict`。
不要把完整 YAML 替换成仅包含改动的 Patch。QA 阻断时不发布正式图。

inventory 返回测量时的 `figure_dpi` 与 `figure_size_mm`；CLI 与 GUI 的 bbox 位移
按该 renderer 的 DPI 换算，不能使用 PNG/TIFF 导出的 DPI。

QA 差异和人工豁免按 `(rule_id, scope, object_ids)` 区分，测量数字不参与已识别
诊断的身份；未知诊断保留完整原文，不能人工豁免。旧文本签名记录不再用于放行，
需要重新审核后记录规则、对象和理由。

## 数据文件说明
`examples/*/` 数据目录下的 PDF 与 PNG 文件（例如 `examples/ftir/2084_1788253487778_26083154776/26083154776/*.pdf` 为科学指南针测试机构导出的对照报告，`examples/nmr/核磁原始数据/*/pdata/1/thumb.png` 为 Bruker TopSpin 仪器采集生成的原始缩略图）均为仪器原始产物与输入数据，不是 render 导出的渲染产物。render 产生的所有构建产物均通过 `.gitignore` 排除，不进入版本跟踪。
