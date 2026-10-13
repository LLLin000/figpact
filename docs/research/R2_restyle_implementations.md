# R2 — 成熟项目怎么按"最终尺寸"统一规格（实现与机制）

调研目的：为 figpact 下一阶段 **Final-size Style** 提供可复用的机制与不可踩的坑。本文只做**外部一手来源 + 本地可复现实测**，不改仓库任何其它文件。

调研日期：2026-10-14
版本基线：matplotlib 文档 3.11.2（docbuild 2026-09-11）/ 本机实测 **matplotlib 3.10.8**（下文所有"实测"块均来自 3.10.8，Python 侧 API 在 3.11 未变，已核对 main 分支源码）；SciencePlots `master`（README 标注 v2.0.0 起需 `import scienceplots`）；ggplot2 v4.0.3（文档页 Source 链接版本）；seaborn 0.13.2 文档 + `master` 源码；cowplot vignette 2025-07-06；patchwork 1.3.0；LaTeX graphics bundle `grfguide` 2026-05-17。

约定：`[实测]` = 本机跑出来的数字；`[推断]` = 我的推论、非原文；其余均为原文英文引用 + URL。

---

## 1. matplotlib：rcParams / style sheets / savefig 尺寸语义

### 1.1 三层配置与优先级

> "There are three ways to customize Matplotlib, all of which effectively change `rcParams`: 1. Setting rcParams at runtime. 2. Using style sheets. 3. Changing your matplotlibrc file.
> Setting rcParams at runtime takes precedence over style sheets, style sheets take precedence over `matplotlibrc` files."
> —— https://matplotlib.org/stable/users/explain/customizing.html

- 运行时：`mpl.rcParams['lines.linewidth'] = 2`，或 `mpl.rc('lines', linewidth=4, linestyle='-.')`（group 形式）。
- 作用域：`mpl.rc_context({'lines.linewidth': 2, ...})` 可作上下文管理器或装饰器；退出时**恢复**（含上下文体内被改的 rcParams）。注意原文：`backend` 不会被 context manager 重置。
- 只读查询/批量筛选：`RcParams.find_all(pattern)`（用 `re.search`），返回值是拷贝，改动不回写。
- API 参考：https://matplotlib.org/stable/api/matplotlib_configuration_api.html

**对 figpact 的意义**：`rc_context` 是唯一"会话级/单图级隔离"的官方手段——restyle 必须落在 context 内，否则污染宿主工程（见 §5 不要照抄）。

### 1.2 style sheet（`.mplstyle`）机制

- 语法与 `matplotlibrc` 相同，但**只能设置与"样式"相关的 rcParams**：

> "in a style sheet you can only set rcParams that are related to the actual style of a plot. Other rcParams, like *backend*, will be ignored."
> —— https://matplotlib.org/stable/users/explain/customizing.html

被忽略的完整清单（`style.use` Notes）：`backend, backend_fallback, date.epoch, docstring.hardcopy, figure.max_open_warning, figure.raise_window, interactive, savefig.directory, timezone, tk.window_focus, toolbar, webagg.*`
—— https://matplotlib.org/stable/api/style_api.html
（**注意**：`figure.figsize`、`savefig.bbox`、`savefig.pad_inches` **不在**忽略清单里，所以可以被写进 style —— SciencePlots 正是这么干的，见 §2.1。）

- 加载：`plt.style.use('science')`、`plt.style.use(['dark_background','presentation'])`（**右侧覆盖左侧**）、`plt.style.use(path_or_url)`、`plt.style.context('science')`（临时）。
- 分发：把 `<pkg>/presentation.mplstyle` 放进可导入包，即可 `plt.style.use("mypackage.presentation")`；或放进 `mpl_configdir/stylelib`（`matplotlib.get_configdir()`）。同名时用户目录覆盖内置。
- 库内省：`style.available`（下划线开头视为私有，不列出）、`style.library`（只读 dict）、`style.reload_library()`、`style.use('default')` 回默认。
- 参考：https://matplotlib.org/stable/api/style_api.html

### 1.3 "角色 → 字号/线宽"在 matplotlib 里的既有表达

字体尺寸单位是 **points**（物理单位），相对字号是相对 `font.size` 的比例：

> "`'font.size'` | Default font size in points. Relative font sizes (`'large'`, `'x-small'`) are computed against this size."
> —— https://matplotlib.org/stable/users/explain/text/text_props.html

内置角色比例表（**这是 matplotlib 自带的唯一"role ladder"**）：

| Relative font size | Scaling of default font size |
|---|---|
| xx-small | 0.579 |
| x-small | 0.694 |
| small | 0.833 |
| medium | 1.000 |
| large | 1.200 |
| x-large | 1.440 |
| xx-large | 1.728 |

—— 同上 URL。

可用的"角色 rcParams"（按任务粒度，均可在 style/rc_context 里覆盖）：`font.size`、`axes.labelsize`、`axes.titlesize`、`xtick.labelsize`、`ytick.labelsize`、`legend.fontsize`、`legend.title_fontsize`、`figure.titlesize`（字号）；`lines.linewidth`、`axes.linewidth`、`grid.linewidth`、`xtick.major.width`、`xtick.minor.width`、`ytick.*`、`patch.linewidth`、`lines.markersize`、`xtick.major.size`（尺寸）；`figure.figsize`、`figure.dpi`（画布）。完整清单见 https://matplotlib.org/stable/users/explain/configuration.html

**关键结构性事实**：`figure.figsize` 与所有 fontsize/linewidth 是**互相独立的两个常量**。改 `figsize` 不会改 pt 值——matplotlib **没有任何**"按最终尺寸重算字号"的机制。这就是 figpact Final-size Style 必须自己实现规则的根本原因（对照 §4 的 ggplot2/cowplot/seaborn 都提供了这个旋钮）。

### 1.4 savefig 的尺寸语义

`savefig` 签名（默认值来自 rcParams）：

```
savefig(fname, *, transparent=None, dpi='figure', format=None,
        metadata=None, bbox_inches=None, pad_inches=0.1,
        facecolor='auto', edgecolor='auto', backend=None, **kwargs)
```
—— https://matplotlib.org/stable/api/_as_gen/matplotlib.pyplot.savefig.html

- `dpi='figure'`：用 figure 的 dpi；`savefig.dpi` 默认就是 `'figure'`。
- `bbox_inches`：`"Bounding box in inches: only the given portion of the figure is saved. If 'tight', try to figure out the tight bbox of the figure."`
- `pad_inches`：`"Amount of padding in inches around the figure when bbox_inches is 'tight'. If 'layout' use the padding from the constrained or compressed layout engine; ignored if one of those engines is not in use."`（rcParam 默认 0.1）
- `bbox_extra_artists`：参与 tight bbox 计算的额外 artist 列表。
- **输出像素 = figsize(in) × dpi 仅当 `bbox_inches=None`**；一旦 `'tight'`，尺寸改由内容决定。
- `Figure.get_tightbbox(renderer=None, *, bbox_extra_artists=None)`：
  > "Return a (tight) bounding box of the figure *in inches*. Note that `.FigureBase` differs from all other artists, which return their `.Bbox` in pixels. Artists that have `artist.set_in_layout(False)` are not included in the bbox."
  > —— https://matplotlib.org/stable/api/_as_gen/matplotlib.figure.Figure.get_tightbbox.html
  → **单位不一致是这个 API 家族最经典的坑**：Figure 级是 inches，其它 artist 是 px。

实测（mpl 3.10.8，`figsize=(3.5,2.5)`, `dpi=100`, `layout="constrained"`, 单 axes + 7pt xlabel）：

```
get_tightbbox(renderer)  -> TransformedBbox(Bbox(x0=4.167, y0=4.167, x1=345.833, y1=245.833), Affine2D().scale(0.01))
   width = 3.41666 in, height = 2.41666 in          # 不含 pad
savefig(dpi=600)                        -> png (2100, 1500)   = 3.5x2.5 in @600
savefig(dpi=600, bbox_inches='tight')   -> png (2169, 1569)   # 3.6167 in = 3.4167 + 2*0.1
savefig(dpi=600, bbox_inches='tight', pad_inches=0) -> (2049, 1449)  # 3.415 in
```

**可落地公式（实测成立）**：`输出宽(in) = tightbbox_width(in) + 2 * pad_inches`。
**tight bbox 对 figsize 是斜率 1 的仿射函数**（装饰物是绝对尺寸），所以"一步收敛"即可：

```
figsize 3.0 -> tight width 2.9165 in
figsize 3.5 -> tight width 3.4167 in
figsize 4.0 -> tight width 3.9167 in
figsize 5.0 -> tight width 4.9167 in
```
→ 目标 3.5 in（含 pad 0.1）：先量 `W0`，令 `figwidth += (3.5 - 0.2) - W0`，再存：
`figsize 3.2 -> 3.38334`，`savefig(dpi=600, tight, pad_inches=0.1)` → **png 宽 2100 px = 3.5 in 整**（实测）。

### 1.5 布局引擎与顺序陷阱（官方原文）

> "In order for a legend or other artist to *not* steal space from the subplot layout, we can `leg.set_in_layout(False)`. … Note, however, that the legend's `get_in_layout` status will have to be toggled again to make the saved file work, and we must manually trigger a draw if we want *constrained layout* to adjust the size of the Axes before printing."
> —— https://matplotlib.org/stable/users/explain/axes/constrainedlayout_guide.html

同页示例的固定顺序：`leg.set_in_layout(False)` → `fig.canvas.draw()` → `leg.set_in_layout(True)` → `fig.set_layout_engine('none')` → `savefig(..., bbox_inches='tight', dpi=...)`。
另外：`tight_layout()` **会关掉** constrained layout（同页 Warning）。

---

## 2. 第三方风格库怎么表达期刊规格

### 2.1 SciencePlots（`garrettj403/SciencePlots`，DOI 10.5281/zenodo.4106649）

**行名（style 名）**：`science`（主样式）、`ieee`、`nature`（期刊）；`notebook`、`scatter`、`grid`、`pgf`、`sans`、`latex-sans`、`no-latex`；多语言 `cjk-sc-font / cjk-tc-font / cjk-jp-font / cjk-kr-font / russian-font / turkish-font`；色环 `bright / high-vis / high-contrast / light / muted / retro / vibrant / std-colors / discrete-rainbow-<1..23>`。组合用法：

> "In this case, the `ieee` style will override some of the parameters from the `science` style in order to configure the plot for IEEE papers (column width, fontsizes, etc.)."
> —— https://github.com/garrettj403/SciencePlots （README）

**贡献（可直接抄的机制）**：把"期刊物理栏宽"写进 style 的 `figure.figsize`，把字号/线宽按期刊规矩写死。源码（`master`, `src/scienceplots/styles/…`）：

`science.mplstyle`（节选，原文）：
```
axes.prop_cycle : cycler('color', ['0C5DA5', '00B945', 'FF9500', 'FF2C00', '845B97', '474747', '9e9e9e'])
figure.figsize : 3.5, 2.625
xtick.direction : in
xtick.major.size : 3
xtick.major.width : 0.5
axes.linewidth : 0.5
grid.linewidth : 0.5
lines.linewidth : 1.
legend.frameon : False
savefig.bbox : tight
savefig.pad_inches : 0.05
font.family : serif
mathtext.fontset : dejavuserif
text.usetex : True
```
`journals/ieee.mplstyle`（原文）：
```
axes.prop_cycle : (cycler('color', ['k','r','b','g']) + cycler('ls', ['-','--',':','-.']))
figure.figsize : 3.3, 2.5
figure.dpi : 600
font.size : 8
font.family : serif
font.serif : Times
```
`journals/nature.mplstyle`（原文，含注释）：
```
# In general, they advocate for all fonts to be panel labels to be sans serif
# and all font sizes in a figure to be 7 pt and panel labels to be 8 pt bold.
figure.figsize : 3.3, 2.5  # max width is 3.5 for single column
axes.labelsize: 7 / xtick.labelsize: 7 / ytick.labelsize: 7 / legend.fontsize: 7 / font.size: 7
font.family: sans-serif
axes.linewidth : 0.5 / grid.linewidth : 0.5 / lines.linewidth : 1.
lines.markersize: 3
# Always save as 'tight'
# savefig.bbox : tight
# savefig.pad_inches : 0.01  # Use virtually all space when we specify figure dimensions
```
（URL 模式：`https://raw.githubusercontent.com/garrettj403/SciencePlots/master/src/scienceplots/styles/<path>`）

**局限（不要照抄的部分）**：
1. **纯字符串常量，没有重算逻辑**。`science` 写死 3.5 in 配死字号；`ieee/nature` 写死 3.3 in 配死 7/8 pt。若用户图本身不是这个尺寸，style 只改字号不改尺寸（或反之）→ 相对字号失控。没有任何"已知最终宽度 → 反解字号"的路径。
2. **把 `savefig.bbox : tight` 写进基础样式**，直接破坏标称 `figure.figsize`（`science` 的 3.5 in 只在 pad 0.05 下≈成立）。`nature.mplstyle` 自己把它**注释掉**了，注释原文就是原因："Use virtually all space when we specify figure dimensions" —— 这是"规格与 tight 互斥"的一手证据。
3. **规格不完整**：`nature` 只设 5 个字号 rcParam，没有下限校验（Nature 官方要求 5–7 pt / 线宽 0.25–1 pt，见 §4.5），也没有 panel label 8pt bold 的强制。
4. **全局副作用**：`plt.style.use` 改的是全局 `rcParams`；且 v2.0.0 起必须 `import scienceplots` 才有副作用注册。
5. 依赖 LaTeX（`text.usetex: True`）与本地字体；CJK 需外部字体。
6. 期刊尺寸取自"常见栏宽"而非指南原文（`3.3` 与 Nature 的 89 mm=3.504 in、IEEE 的 3.5 in 都不完全一致）——`[推断]` 它留了排版余量。

### 2.2 seaborn `set_context` / `plotting_context`（matplotlib 生态里真正的"单旋钮缩放"）

> "The base context is 'notebook', and the other contexts are 'paper', 'talk', and 'poster', which are version of the notebook parameters scaled by different values. Font elements can also be scaled independently of (but relative to) the other values."
> —— https://seaborn.pydata.org/generated/seaborn.set_context.html

源码（`seaborn/rcmod.py`, master）给出机制，**每个角色一个基准值，然后整体乘一个缩放因子**：

```python
base_context = {
  "axes.linewidth": 1.25, "grid.linewidth": 1, "lines.linewidth": 1.5,
  "lines.markersize": 6, "patch.linewidth": 1,
  "xtick.major.width": 1.25, "ytick.major.width": 1.25,
  "xtick.minor.width": 1, "ytick.minor.width": 1,
  "xtick.major.size": 6, "ytick.major.size": 6,
  "xtick.minor.size": 4, "ytick.minor.size": 4,
  "font.size": 12, "axes.labelsize": 12, "axes.titlesize": 12,
  "xtick.labelsize": 11, "ytick.labelsize": 11,
  "legend.fontsize": 11, "legend.title_fontsize": 12,
}
scaling = dict(paper=.8, notebook=1, talk=1.5, poster=2)[context]
context_dict = {k: v * scaling for k, v in base_context.items()}
# 然后 font_keys 再乘一个独立的 font_scale
```
—— https://raw.githubusercontent.com/mwaskom/seaborn/master/seaborn/rcmod.py

**值得复用**：role table + 一个 `scaling` 因子 + 可选的 font-only `font_scale`（两级）。**不要照抄**：它是全局改 `rcParams` + 只有固定 4 档，不满足 figpact 的 per-figure 隔离与任意最终宽度。

### 2.3 matplotlib 内置样式与分发面

内置：`ggplot`、`bmh`、`fivethirtyeight`、`grayscale`、`petroff6/8/10`、`seaborn-v0_8-*`、`tableau-colorblind10` 等（`plt.style.available`，https://matplotlib.org/stable/gallery/style_sheets/style_sheets_reference.html）。这些只改"观感"，不含任何物理尺寸规格——**"按最终尺寸"这件事整个 matplotlib 生态只有 SciencePlots 一个先例，且它只做到"把尺寸写死"**。

---

## 3. 测量：官方 API 与陷阱

### 3.1 API 与官方语义

| API | 返回单位 | 官方原文要点 |
|---|---|---|
| `Artist.get_window_extent(renderer=None)` | display（像素，**取决于 renderer 的 dpi**） | "Get the artist's bounding box in display space, ignoring clipping." |
| `Text.get_window_extent(renderer=None, dpi=None)` | display | "A renderer is needed to compute the bounding box. If the artist has already been drawn, the renderer is cached" |
| `Text.get_tightbbox(renderer=None)` | display，**考虑 clip** | "The enclosing bounding box (in figure pixel coordinates), or None if clipping results in no intersection." |
| `Figure.get_tightbbox(renderer, bbox_extra_artists=None)` | **inches** | 见 §1.4 |
| `RendererBase.get_text_width_height_descent(s, prop, ismath)` | display | "Get the width, height, and descent (offset from the bottom to the baseline), in display coords, of the string *s*" |
| `Figure.draw_without_rendering()` | — | "Draw the figure with no output. Useful to get the final size of artists that require a draw before their size is known (e.g. text)." |
| `TextPath(xy, s, size=None, prop=None, usetex=False)` | **points**（无 renderer） | "Note that it simply is a path, not an artist. You need to use the `.PathPatch` (or other artists) to draw this path onto the canvas." |
| `FT2Font.set_size(ptsize, dpi)` / `set_text(s, angle, flags)` / `get_width_height()` / `get_descent()` | **26.6 subpixel，÷64 得像素** | "To get width and height in pixels, divide these values by 64." |

URL：https://matplotlib.org/stable/api/_as_gen/matplotlib.artist.Artist.get_window_extent.html ；https://matplotlib.org/stable/api/text_api.html ；https://matplotlib.org/stable/api/figure_api.html ；https://matplotlib.org/stable/api/ft2font.html ；https://matplotlib.org/stable/api/textpath_api.html （该 URL 存在，HTTP 200；我抓取正文时拿到的是 `matplotlib.text` 参考页内容，故 `TextPath`/`TextToPath` 的权威描述以源码 docstring 为准：https://raw.githubusercontent.com/matplotlib/matplotlib/main/lib/matplotlib/textpath.py ）

### 3.2 官方明示的失效条件（核心引用）

> "**Warning**: The extent can change due to any changes in the transform stack, such as changing the Axes limits, the figure size, the canvas used (as is done when saving a figure), or the DPI. Relying on a once-retrieved window extent can lead to unexpected behavior in various cases such as interactive figures being resized or moved to a screen with different dpi, or figures that look fine on screen render incorrectly when saved to file. To get accurate results you may need to manually call `savefig` or `draw_without_rendering` to have Matplotlib compute the rendered size."
> —— https://matplotlib.org/stable/api/_as_gen/matplotlib.artist.Artist.get_window_extent.html

> "There's one catch with calculating text bounding boxes: Querying the text bounding boxes (`Text.get_window_extent`) needs a renderer … This renderer is only available after the figure has been drawn (`Figure.draw`). A solution to this is putting the adjustment logic in a draw callback."
> —— https://matplotlib.org/stable/gallery/subplots_axes_and_figures/auto_subplots_adjust.html

### 3.3 实测陷阱（mpl 3.10.8，可直接复现）

**T1 — draw 之前测量不报错，但返回退化 bbox（假数据）**
```
pre-draw extent: Bbox(x0=142.625, y0=-10.0, x1=216.125, y1=0.0)   # height = 0
after draw_without_rendering: Bbox(x0=154.111, y0=4.167, x1=227.611, y1=14.167)   # height = 10.0
```
→ 必须 `draw_without_rendering()` / `canvas.draw()` 之后再量。（`[推断]` pre-draw 只是锚点占位；官方 docstring 说 renderer 缺失时会 `raise RuntimeError … call 'figure.draw_without_rendering()' first`，实测 3.10.8 走了缓存的退化路径而不是抛错——**不要依赖异常来发现它**。）

**T2 — 单位跟"当前缓存的 renderer"走：`savefig(dpi=600)` 会改变后续测量的单位**
```
A  before savefig          : x0=154.111  w=73.5
B  after savefig(dpi=600)  : x0=-29.212  w=440.25     # 变成 600dpi 像素
C  after that, dpi=100 kw  : x0=-29.212  w=440.25     # 传 dpi kw 也救不回来
D  after savefig(dpi=100)  : x0=154.111  w=73.5       # 换回 100dpi renderer 才复原
px->in: A/100 = 0.7350 in ； B/600 = 0.7338 in        # 物理尺寸一致，差 0.2% 来自 hinting
```
→ **测量与保存必须显式配对**；英寸换算要用"当前 renderer 的 dpi"。

**T3 — `dpi=` 关键字只缩放锚点、不缩放尺寸 → 混单位 bbox**
```
[axeslabel, fresh fig @dpi100]
  get_window_extent()        -> x0=91.799  w=198.125
  get_window_extent(dpi=600) -> x0=1046.104 w=198.125     # 位置 ×6，宽度没变!
```
源码依据（3.10.8 与 main 一致）：
```python
with cbook._setattr_cm(fig, dpi=dpi):
    bbox, _, _ = self._get_layout(self._renderer)   # 尺寸来自 renderer(图 dpi)
    x, y = self.get_unitless_position()
    x, y = self.get_transform().transform((x, y))   # 位置来自 fig.dpi 变换
```
且 `_get_text_metrics_with_cache_impl` 明确写着 `# dpi is unused, but participates in cache invalidation (via the renderer).`
→ **figpact 禁用 `Text.get_window_extent(dpi=...)`**；要别的 dpi 就在那个 dpi 下重新 draw/save 之后再量。

**T4 — tight 与 pad 的算术**：`输出 = get_tightbbox(renderer) + 2*pad_inches`（实测 3.41666 + 0.2 = 3.61666 in × 600 = 2169 px ✓）。

**T5 — constrained layout 的"谁先跑"**：`set_in_layout(False)` 的 artist 不进 tight bbox；要它进，得 `canvas.draw()` 之后再 `set_in_layout(True)` 并把 layout engine 关掉（§1.5 官方示例）。**任何"先量尺寸再保存"的流水线都必须把 draw/layout 顺序写死**。

**T6 — hinting 让像素值有 ~1% 抖动**：同一串字，图 dpi 下量得 73.5 px，600 dpi 下量得 440.25 px（÷6 = 73.375 px）。→ `[推断]` 用 extent 做 **≥2px 或 ≥0.5%容差**的判定，别做 1px 断言。

### 3.4 TextPath：不要 renderer 的"几何真值"

实测（`TextPath((0,0), "Frequency (Hz)", size=7)`）：`width=51.497 pt, height=6.767 pt`；
size 3.5 → 25.748 / 3.384；size 14 → 102.994 / 13.534（**严格线性**，`[实测]`）。

机制（`lib/matplotlib/textpath.py`）：`TextToPath.FONT_SCALE = 100.`、`DPI = 72`；glyph 路径先按 100 pt 生成，再按 `size/100` 缩放：

```python
tr = Affine2D().scale(self._size / text_to_path.FONT_SCALE).translate(*self._xy)
```
—— https://raw.githubusercontent.com/matplotlib/matplotlib/main/lib/matplotlib/textpath.py

用途与边界：
- **适合**：无 renderer 的预测（"这段文字在 7 pt 下有多宽 → 会不会越出 axes → 要不要换行/缩写"），以及需要 path 做裁剪/贴边的场景。
- **不适合当排版真值**：`get_extents()` 是**墨迹包围盒**（不是行盒）；不做换行、不做对齐、不做 linespacing；rotation 要自己套变换；`\n` 不会被当换行处理；连字符/kerning 与 Agg 的实际渲染仍可能差一点点。`[推断]` 与 `get_window_extent` 的差主要来自 ink vs line box（实测 6.767 pt vs 10 px/100dpi=7.2 pt 的行盒）。

### 3.5 FT2Font：最底层、也最不稳

- `FT2Font.set_size(ptsize, dpi)`："Set the size of the text. ptsize: The size of the text in points. dpi: The DPI used for rendering the text."
- `FT2Font.set_text(string, angle=0.0, flags=LoadFlags.FORCE_AUTOHINT)` → 返回 x,y 位置数组，单位 **26.6 subpixels**；`get_width_height()` / `get_descent()` 同单位，**÷64 得像素**；`get_bitmap_offset()` 处理"墨迹挂到原点左/下"。
- kerning：`get_kerning(left, right, mode)`，mode ∈ `DEFAULT`（scaled & grid-fitted）/`UNFITTED`（scaled, not fitted）/`UNSCALED`（原字体单位）；3.10 起参数类型改为枚举。
- 官方警告：`FT2Font(..., _fallback_list=..., _warn_if_used=...)` —— "This API is both private and provisional: do not use it directly."
- 参考：https://matplotlib.org/stable/api/ft2font.html
- `[推断]` 正确入口是 `matplotlib.font_manager.get_font(path)`（有缓存）而不是自己 new；`TextToPath.get_text_width_height_descent` 是 matplotlib 内部量文字宽高的函数，先 `set_size(100, 72)` 再用 `fontsize/100` 缩放（源码见 §3.4 链接），不要复制这套常量。

---

## 4. 其它生态对照

### 4.1 ggplot2：`theme` 的角色树 + base_size 比例

> "Complete themes … `theme_grey(base_size = 11, base_family = "", header_family = NULL, base_line_size = base_size/22, base_rect_size = base_size/22, …)`"；"base_size: base font size, given in pts."；"base_line_size: base size for line elements"
> —— https://ggplot2.tidyverse.org/reference/ggtheme.html

主题是可继承的元素树（`text` / `line` / `rect` / `title` / `axis.text.*` / `legend.*` / `strip.*` …）：

> "axis.title.\*.\* inherits from axis.title.\* which inherits from axis.title, which in turn inherits from text"
> —— https://ggplot2.tidyverse.org/reference/theme.html

**这是"角色 → 尺寸"最成熟的设计**：一个 `base_size` 旋钮 + 从它按**固定比例**派生线宽/矩形边距；角色的**继承树**保证默认一致（只改父节点即可全局一致）。`theme_set()`/`theme_update()` 设全局活动主题，`theme()` 只改单图。

### 4.2 `ggsave(units="mm")` 的语义

> `ggsave(filename, plot, device, path, scale = 1, width = NA, height = NA, units = c("in","cm","mm","px"), dpi = 300, limitsize = TRUE, ...)`
> "units: One of the following units in which the width and height arguments are expressed: 'in', 'cm', 'mm' or 'px'." / "limitsize: When TRUE (the default), ggsave() will not save images larger than 50x50 inches, to prevent the common error of specifying dimensions in pixels."
> —— https://ggplot2.tidyverse.org/reference/ggsave.html

**`scale` 只乘物理尺寸，不乘字号**（源码 `R/save.R`）：
```r
dim <- to_inches(dim) * scale
```
—— https://raw.githubusercontent.com/tidyverse/ggplot2/main/R/save.R
`[推断]` 这正是"用 `units="mm"` 直接给最终物理宽 + 字号用 pt 独立指定"的语义：**尺寸与字号解耦，与 matplotlib 相同**；ggplot2 的补足在于 `base_size` 提供了"再缩放字号"的入口。

### 4.3 patchwork / cowplot：跨面板主题统一

patchwork：
> "The easiest is to simply use `&` with a theme element. This operator will add to the theme of **all subplots as well as to the theme of the patchwork itself**."
> "For a coherent look, don't mix widely different looks. … different fonts or line widths will just look like a mess."
> —— https://patchwork.data-imaginist.com/articles/guides/annotation.html

运算符语义（`R/arithmetic.R`）：`*` 只作用于当前嵌套层级的全部子图；`&` **递归**到嵌套 patch；拼版自身（标题/边距/背景）只能通过 `plot_annotation(theme = theme(...))` 单独设定。`plot_layout(guides="collect")` 时图例定位须在拼版层设。
—— https://github.com/thomasp85/patchwork/blob/main/R/arithmetic.R

cowplot（**比例表的另一种实现**）：
```
theme_cowplot(font_size = 14, font_family = "", line_size = 0.5,
              rel_small = 12/14, rel_tiny = 11/14, rel_large = 16/14)
```
参数说明：`rel_small: Relative size of small text (e.g., axis tick labels)`；`rel_tiny`（caption）、`rel_large`（title）。另外 v1.0 起 cowplot **不再自动设主题**，作者建议"always explicitly set a theme for every plot"。
—— https://wilkelab.org/cowplot/reference/theme_cowplot.html ； https://cran.r-project.org/web/packages/cowplot/vignettes/introduction.html

### 4.4 LaTeX `graphicx`：缩放 = 连字号一起缩放

`\includegraphics` 的 key（`grfguide` §4.4 原文）：
> "**width** Required width. **The graphic is scaled to this width.** The special value ! can be used to (re)set the width to the natural width."
> "**scale** Scale factor."
> "**keepaspectratio** … specifying both 'width' and 'height' (or 'totalheight') does not distort the figure but scales such that neither of the specified dimensions is exceeded."
> "The next few keys specify any scaling or rotation to be applied to the image."
> "The keys are read left-to-right, so `[angle=90, height=1in]` means rotate by 90 degrees, and then scale to a height of 1in. `[height=1in, angle=90]` would result in a final width of 1in."
> —— graphics bundle (D. P. Carlisle, 2026-05-17), https://ctan.org/pkg/graphicx （`grfguide.pdf` §4.3–4.4）

`\scalebox` 原文："Again this is basically like `\mbox` but **scales the text**."（§4.3.1）——即"缩放一个 box，box 内的文字一起被缩放"。

`[推断]` 机制结论：`\includegraphics[width=W]{fig.pdf}` 是对**整个 box**做仿射缩放，因此 **最终 pt = 名义 pt × 缩放因子**，而缩放因子取决于 PDF 里的自然尺寸。例：matplotlib 以 3.5 in（=88.9 mm）宽的 PDF、7 pt 字，被 `[width=89mm]` 收缩到 3.504 in 时因子 1.0011 → 7.008 pt；但若作者按"屏幕上好看"做的 6 in 宽图被压到 89 mm，因子 0.583 → 7 pt 变 **4.08 pt**，直接违反期刊下限。**LaTeX 不会替你保字号，它只会等比缩放**。

期刊把这件事写成了硬约束（与 R1 的尺寸表互补）：
> "Authors should check (using a reducing photocopier) that, at the smallest possible size, lettering remains readable … **Line weights and strokes should be set between 0.25 and 1 pt at the final size** (lines thinner than 0.25 pt may vanish in print)."
> "Separate panels in multi-part figures should each be labelled with 8 pt bold, upright (not italic) a, b, c. **Maximum text size for all other text should be 7 pt; minimum text size should be 5 pt.**"
> "For guidance, *Nature*'s standard figure sizes are 89 mm wide (single column) and 183 mm wide (double column)."
> —— https://www.nature.com/nature/for-authors/final-submission

> "Most charts, graphs, and tables are sized to be one column width or two columns width: One column width: 3.5 inches, 88.9 millimeters, or 21 picas / Two columns width: 7.16 inches, 182 millimeters, or 43 picas … It is easy for IEEE to reduce the sizes of your graphics. But, in most cases, IEEE cannot increase them without negatively impacting quality."
> —— https://journals.ieeeauthorcenter.ieee.org/create-your-ieee-journal-article/create-graphics-for-your-article/resolution-and-size/

注意 "at the final size" 这个措辞——**规范的口径是最终印刷尺寸，不是源代码里的 figsize**，这正是 R2 要服务的目标。

---

## 5. figpact 该怎么用

### 5.1 直接复用（给理由）

| 复用 | 出处 | 为什么 |
|---|---|---|
| **role table + 单一 scale 因子**（每个角色一个基准值，整体乘 scale；字体可再乘一个独立 font_scale） | seaborn `base_context × scaling` | 唯一在 matplotlib 生态里被验证过的"整体缩放"设计；天然满足"不同尺寸代码图统一到同一最终规格" |
| **从 base 派生线宽/边距的固定比例** | ggplot2 `base_line_size = base_size/22`、`base_rect_size = base_size/22` | 线宽不是独立旋钮，随字号联动才不会出现"7pt 字配 1pt 线"的失配 |
| **角色相对比例表** | cowplot `rel_small=12/14, rel_tiny=11/14, rel_large=16/14`；matplotlib `small/x-large` 0.833/1.2/1.44 | 直接可用作 figpact 的默认 role→ratio 表，且是"行业既成习惯"，用户不会觉得意外 |
| **样式只写"可复现的 rcParams 覆盖"**（dict / `.mplstyle` 文本），用 `rc_context` 或 `style.context` 包裹落地 | matplotlib `style.use` / `rc_context` | 可直接进 diff、可回滚、可审计；`rc_context` 保证不污染宿主 |
| **journal profile = 物理规格 + 角色清单**（尺寸 + 字号区间 + 线宽区间），而不是只写尺寸 | SciencePlots 的 `ieee/nature` + Nature/IEEE 指南 | SciencePlots 只对了尺寸这一半；把"5–7 pt / 0.25–1 pt @final"这类**可校验区间**一起入 profile，restyle 才有验收标准 |
| **figsize 反解 = tight + pad 一步收敛**（§1.4 实测） | 官方 API 组合 | 想要"输出恰好 N in"时，这是纯公式、无需迭代搜索 |
| **测量协议：draw → 量（inch 层断言）→ save → 再量像素做终检** | Artist.get_window_extent Warning 原文 | 官方明确说 extent 会随 canvas/dpi/figsize 变；把顺序和断言层写死才可复现 |

### 5.2 不要照抄（给理由）

| 不要 | 出处 | 理由 |
|---|---|---|
| 把 `savefig.bbox: tight` 写进规格样式 | SciencePlots `science.mplstyle`（`nature.mplstyle` 已注释掉） | tight 让输出尺寸由内容决定，标称最终尺寸立刻失效；规格与 tight 二选一，figpact 应显式选 `bbox_inches=None + pad=0 + 明确 figsize`，或"tight+pad 反解" |
| SciencePlots 式**纯常量** journal style | `ieee/nature.mplstyle` 写死 3.3 in + 7/8 pt | 输入图尺寸千差万别，常量没法重算、没法做下限校验；须改成"profile + 由最终宽度求解" |
| 全局改 `rcParams` | seaborn `set_context`、SciencePlots `plt.style.use` | figpact 在用户工程内运行，必须 per-figure/per-session 隔离（`rc_context`），否则改一次污染全部 |
| 用 `Text.get_window_extent(dpi=...)` | §3.3 T3 | 只缩放锚点不缩放尺寸 → 混单位 bbox（有源码依据） |
| 把 extent 当像素真值做 1px 断言 | §3.3 T2/T6 | 单位随 renderer 漂移；hinting 有 ~1% 抖动 |
| 拿 `TextPath` 当排版真值 | §3.4 | ink bbox、无换行/无对齐/无 linespacing；只适合做预测与路径 |
| 用 LaTeX 缩放来"统一字号" | `grfguide` §4.3–4.4 | 它改的是物理尺寸，会反向破坏最终字号；字号必须在**导出前**按最终尺寸定死 |
| 依赖 `matplotlib.textpath` / `TextToPath` / `FT2Font` 内部常量（`FONT_SCALE=100`, `DPI=72`, `fiv` 私有参数） | ft2font 官方 "private and provisional" 警告 | 未承诺稳定；figpact 只应调 `get_window_extent` / `get_tightbbox` / `get_text_width_height_descent` 这几条公开路径 |

### 5.3 推荐操作流程（可执行）

1. **输入**：源图（任意 figsize）+ 目标 profile（`final_width_in`, `min_font_pt`, `max_font_pt`, `line_pt_range`, 面板标号字号）。
2. **建立基线**：`with mpl.rc_context(): fig.draw_without_rendering()`；记录 `fig.get_size_inches()`、`fig.dpi`、`renderer.dpi`。
3. **求解尺寸**：若要求"输出恰为目标宽"→ 量 `W0 = fig.get_tightbbox(renderer).width`（inch），令 `figwidth += (W_target - 2*pad) - W0`（斜率 1，实测一步收敛）。
4. **求解字号**：`scale = W_target / W_ref`（`W_ref` = 该图"设计基准宽"或 profile 里的 journal 基准），角色 pt = `base_role_pt × scale`，线宽按 `base_line_size = font_base / 22` 同源派生；越界（<min 或 >max）→ 报告冲突而不是硬改。
5. **落地**：把结果写成一个 dict/mplstyle 文本，经 `rc_context` 应用并重绘（不写全局 `rcParams`）。
6. **验收**：保存后重新量像素（`A/fig_dpi` 与 `B/save_dpi` 两种换算都要一致到 ~0.5%），并把 `renderer`、`dpi`、`font` 与来源一并记录（PLAN §5 已要求报告来源/renderer/DPI/font）。

---

## 附：本文实测脚本要点（可复现）

```python
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
fig = plt.figure(figsize=(3.5, 2.5), dpi=100, layout="constrained")
ax = fig.add_subplot(); ax.plot([0,1],[0,1]); ax.set_xlabel("Frequency (Hz)", fontsize=7)
fig.draw_without_rendering()                    # 必须先 draw（T1）
t = ax.xaxis.get_label()
print(t.get_window_extent())                    # display px @ 当前 renderer dpi（T2）
print(fig.get_tightbbox(fig.canvas.get_renderer()).width)   # inches（T4）
fig.savefig("out.png", dpi=600, bbox_inches="tight", pad_inches=0.1)
```

版本提示：本文数值在 **matplotlib 3.10.8** 实测；官方引用页为 **3.11.2**。3.10→3.11 之间 `Text.get_window_extent`、`_get_text_metrics_with_cache_impl` 的实现在 main 分支与 3.10.8 一致（已核对源码），但 `ft2font` 的枚举类型与部分参数在 3.10 有变更（`get_kerning(mode)`、`load_char(flags)`），实现时按安装版本二次核对。
