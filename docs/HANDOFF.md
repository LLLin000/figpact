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

## 真实 fig2 结果

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

B 不是“48mm 版”：它把 48mm 原图再次非等比缩放。FTIR 的 4.7pt 标签在 B 里实际只剩 `4.7 × 0.895265 = 4.21pt`；A 虽恢复到 1:1，4.7pt 仍低于 5pt 下限。**版面契约只回答缩放；字号合格与否仍须 figpact 自己的 QA/final-size 回执**，不能靠把版面缩小来“通过”。若要求 FTIR 在等宽缩放下达到 5pt，需要约 `48 × 5 / 4.7 = 51.06mm` 的占位，或把标签/图例提高到 5.0pt 后由 figpact 重排。

## Tavotto 刷新状态

- 只读 `python -m tavotto.engine.discover <fig2>` 只识别到 3 个脚本 / 4 个 stem，**没有** `08 NMR.py` 与 `plot_ftir.py`：它们通过 `fs.export(...)` 间接保存，Tavotto 静态扫描看不到，只能标为 `needs_probe`。需要一次 Tavotto 试运行探测或明确的 `tavotto_registry.json`；本桥不猜、不补注册表。
- 本宿主 MCP 的 `tavotto_refresh_project` 只授权了 `D:\L\AI\figpact`，真实项目根返回 `path_out_of_scope`。放开项目根需要把该目录加入 Tavotto MCP 的宿主 roots / `TAVOTTO_MCP_ROOTS` 后重启 MCP 宿主；本桥不绕过该授权，布局核验走只读 JSON。

## 边界

- 不修改 Tavotto 布局 JSON，不自动替换素材，不做双向编辑。
- `figpact_receipt.kind=asset-integrity` 只证明字节、页面与来源；不替代科学/Strict PASS，也不替代 Tavotto Preflight。
- 位图面板（照片、SEM 等）不在本桥的 PDF 契约内，仍由 Tavotto 负责。
