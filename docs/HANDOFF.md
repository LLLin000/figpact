# figpact ↔ Tavotto 交接（第一版）

Tavotto 在这里只提供**一张画布的版面事实**：哪个 PDF 放在哪个矩形里。figpact 不读 YAML、不接管 Tavotto 的布局编辑，也不做双向同步；它只把版面契约与图件身份对上，并核验「按原生物理尺寸 1:1 放置」是否真实成立。

## 契约

`figpact handoff scan` 直接读 `.tavotto` 布局（只读），为每个 PDF panel 生成 `figpact-tavotto-handoff/1`：

| 字段 | 来源 |
| --- | --- |
| `asset` / `asset_sha256` | 布局里的 `fileId` + 真实文件字节 |
| `target_width_mm` / `target_height_mm` | **PDF 自己的 `CropBox`**（原生物理尺寸） |
| `require_uniform_scale` / `require_scale` | 固定为等比、1.0 |
| `source_sha256` | 布局里的 `script`（存在时） |
| `page.media_mm` / `page.crop_mm` / `rotation` / `user_unit` | PDF 实测 |
| `font_roles` | 可选；不解析 YAML，扫描时留空 |

规则只有一句：**画布矩形必须等于 PDF 的原生页面**。这不是把配置值当结果——`scan` 和 `verify` 都从 PDF 重新量。

```bash
python -m pip install -e ".[handoff]"   # 仓库内开发；只额外装 pypdf
# 已安装 figpact 时：python -m pip install pypdf

figpact handoff scan --layout <fig2>/tavottofile/新版面-A.json \
  --base <fig2> --canvas "新版面 A（180 版心）" --out fig2.manifest.json

figpact handoff verify --manifest fig2.manifest.json --base <fig2> \
  --layout <fig2>/tavottofile/新版面-A.json --canvas "新版面 A（180 版心）"
```

`verify` 重新测量 PDF、重算每个 panel 的 `scale_x/scale_y`，并重验来源哈希；文件或脚本一变就 FAIL。它只读布局，绝不改 Tavotto 的 JSON。

面板身份要求**唯一匹配**：`asset` 的完整相对路径（反斜杠归一）与可选的 `layout_panel_id` 都必须对上；预期面板缺失、重复或歧义（同名 basename 在别的目录也算）直接 FAIL，不会因为其他面板仍匹配就 PASS。报告里带 `expected_panels` 与 `matched_panels` 计数。

## 反向拟合：Tavotto 占位 → figpact 候选

`figpact fit-layout` 读取 Tavotto 面板的 `w/h`，在**已有授权 Native 控制**里搜索字号/图例候选，并用现有引擎真实 preview 验证；不保存、不改源文件。

```bash
figpact fit-layout --script examples/ftir/plot_ftir.py \
  --config examples/ftir/ftir.yaml --scope annotated \
  --layout <fig2>/tavottofile/新版面-A.json --canvas "新版面 A（180 版心）" \
  --panel Fig2_FTIR_transmittance_stacked_annotated --min-font-pt 5
```

返回 `FEASIBLE`（含 `selected.edits` 与每个候选的 `new_qa`）、`ALREADY_OK` 或 `INFEASIBLE`。可行候选只提高低于下限的字号；字号已够时不做无意义改动。失败时给 `estimate_width_for_floor_mm`，但明确标注它只在允许等比放大整图时成立，1:1 契约下不能靠放大占位提高源字号。

真实 FTIR（repo 版，48mm）：`label_font_pt`/`legend_font_pt` 4.7→5.0 的候选 `RENDER_CHECKED`、`new_qa=[]`，可直接拿去 Inspector Native 复查并确认保存。NMR 在 5pt 下限下 `ALREADY_OK`。

前提：脚本必须暴露 figpact 既有 `build_figure_and_registry` 契约。项目里的旧版 `08 NMR.py`/`plot_ftir.py` 还没有这个入口，`fit-layout` 会拒绝；需要先迁移到 repo 版契约，或继续手工 Native。不要为旧脚本临时写旁路。



三张矢量图的 PDF 页面都是 **48.000 × 48.000 mm**。

`新版面 A`：

| 图 | 画布矩形 mm | scale_x | scale_y | 结论 |
| --- | --- | --- | --- | --- |
| NMR | 48.0 × 48.0 | 1.0 | 1.0 | PASS |
| FTIR | 48.0 × 48.0 | 1.0 | 1.0 | PASS |
| XRD | 48.0 × 48.0 | 1.0 | 1.0 | PASS |

`新版面 B（48mm 手调）`：

| 图 | 画布矩形 mm | scale_x | scale_y | 结论 |
| --- | --- | --- | --- | --- |
| NMR | 52.6375 × 49.9685 | 1.096614 | 1.041010 | FAIL 非等比 |
| FTIR | 49.2505 × 42.9727 | 1.026053 | 0.895265 | FAIL 非等比 |
| XRD | 53.3879 × 45.0655 | 1.112247 | 0.938865 | FAIL 非等比 |

B 不是“48mm 版”：它把 48mm 原图再次非等比缩放。FTIR 的 4.7pt 标签在 B 里实际只剩 `4.7 × 0.895265 = 4.21pt`；A 虽恢复到 1:1，4.7pt 仍低于 5pt 下限。**版面契约只回答缩放；字号合格与否仍须 figpact 自己的 QA/final-size 回执**，不能靠把版面缩小来“通过”。

在 1:1 契约下，单纯把占位放大到 51.06mm **不会**把源字号从 4.7 变成 5.0；只有允许整图放大 1.064 倍时才成立，而那是 scale≠1。要满足 5pt，必须由 figpact 把标签/图例改成 5.0pt 并重排；48mm 内能否容纳要实测，不能靠版面缩放替代。

## Fig2 真实联动结果

- 授权：用显式 `TAVOTTO_MCP_ROOTS`（figpact + fig2 项目根）启动官方 MCP server，`tavotto_health` 返回 `source=explicit_env`，`tavotto_refresh_project` 成功，不再 `path_out_of_scope`。OMP 当前已启动的 MCP 进程仍持旧 roots，需要重载/重启宿主；配置文件已包含项目根。
- 发现：refresh 首次写入项目根 `tavotto_registry.json`，补上 `fig2/08 核磁/08 NMR.py → Fig2_NMR_pure_stacked`、`fig2/09 FTIR/plot_ftir.py → 3 个 stem`、`fig2/10 XRD/plot_xrd.py → 2 个 stem`。这解决了 `fs.export(...)` 静态扫描不到的问题；第二次 refresh 显示“脚本注册表无变化”。
- Probe：真实 `tavotto_open_figure` 打开三张图，均为 48.0×48.0 mm：
  - NMR：35 个可编辑元素，2 errors / 3 warns。
  - FTIR：30 个可编辑元素，2 errors / 4 warns。
  - XRD：35 个可编辑元素，2 errors / 3 warns。
- 默认规范 `lab-publication-v1` 对单图要求 80/150mm 页面和 8pt 绝对下限，因此三张 48mm 面板全部报 `page-width` + `font-below-absolute-floor`。这是“单图规范”和“48mm 面板”的冲突，不应靠缩图解决。
- 以显式面板覆盖（48mm 单双栏 + 5pt 下限）重跑：NMR 与 XRD 为 **0 errors**（仅有字体替换等警告）；FTIR 仍有 **1 error：4.70pt < 5pt**，另有图例压数据警告。
- 导出：NMR、XRD 已由 `tavotto_export` 真实导出到 `tools/v01/tavotto-export/`，页面均为 48.0×48.0 mm，proof 报告已核验 integrity/size/carrier/fonts_embedded；FTIR 被 `preflight_blocked` 拒绝，未用 `explicit_confirm` 绕过。
- 整版 180×254.4mm 的最终 PDF 仍只能在 Tavotto 桌面完成（MCP 工具导出“单图”，不导出画布组合）。布局 A 的 1:1 放置已由本桥核验；桌面整版导出尚未自动化。

## Tavotto 刷新状态

- 静态 `discover` 只看到 3 个脚本 / 4 个 stem，缺 `08 NMR.py`、`plot_ftir.py`；但授权 refresh 后已由注册表补全上述 stem，后续 open 不再需要猜。
- 本机 OMP 进程的旧 roots 仍是 `D:\L\AI\figpact`；显式 env 的独立 MCP 连接已验证可用。要让它成为宿主默认，需重载/重启 MCP 宿主；本桥不绕过该授权，布局核验走只读 JSON。

## 边界

- 不修改 Tavotto 布局 JSON，不自动替换素材，不做双向编辑。
- `figpact_receipt.kind=asset-integrity` 只证明字节、页面与来源；不替代科学/Strict PASS，也不替代 Tavotto Preflight。
- 位图面板（照片、SEM 等）不在本桥的 PDF 契约内，仍由 Tavotto 负责。
