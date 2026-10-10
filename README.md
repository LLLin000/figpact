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

# 渲染图表（支持 --strict 严格模式阻断）
figpact render --script <py> [--config <yaml>] [--strict]

# 导出图表（等价于 render --strict）
figpact export --script <py> [--config <yaml>]

# 清点可见图元清单并统计未登记/未绑定项，支持参数扰动生效检查
figpact inventory --script <py> [--config <yaml>] [--check-effect]

# 检查特定 gid 图元的几何与绑定详情
figpact inspect <gid> --script <py> [--config <yaml>]
```

## 数据文件说明
`examples/*/` 数据目录下的 PDF 与 PNG 文件（例如 `examples/ftir/2084_1788253487778_26083154776/26083154776/*.pdf` 为科学指南针测试机构导出的对照报告，`examples/nmr/核磁原始数据/*/pdata/1/thumb.png` 为 Bruker TopSpin 仪器采集生成的原始缩略图）均为仪器原始产物与输入数据，不是 render 导出的渲染产物。render 产生的所有构建产物均通过 `.gitignore` 排除，不进入版本跟踪。
