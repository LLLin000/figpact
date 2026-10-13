# R6 — 多面板拼版时如何保证跨图规格一致

调研目的：为 figpact 下一阶段 **Final-size Style**（把不同尺寸的代码图统一到最终拼版规格）与 P1.5 / 拖动→保存闭环提供"拼版一致性"这一侧的外部硬约束与可抄/不可抄的工程做法。
调研日期：2026-10-14。方法：只读一手来源（期刊作者指南 / 出版社官方 PDF / 官方源码与文档）。所有数字与措辞给原文英文引用 + URL；标 `[推断]` 者为本文推断，非原文。
**与 R1 的分工**：R1 覆盖"单张图的最终宽度/字号/线宽/分辨率硬规范"。本文只覆盖 R1 没做的三块：**(1) 组合图专有的拼版规则**（同图内一致性、面板字母、缩放比例、矢量嵌入、单文件提交）、**(2) R 生态的跨面板统一机制**、**(3) 实操拼版里"缩放后字号不一致"的成因与避法**，最后给 figpact 的最小界面建议。宽度/字号的绝对值以 R1 为准，本文不重复。

## 场景锚定（全文算例都用它）

用户有 NMR 与 FTIR 两张代码图，源画布各 **48.0 mm** 宽，要进同一张论文 Figure，最终各到 **42.0 mm / 38.0 mm**。

- 两张图的缩放比不同：$k_{\text{NMR}} = 42/48 = 0.875$，$k_{\text{FTIR}} = 38/48 = 0.7917$。
- 横向总占位 $42 + 38 + 2\text{ mm 间隙} = 82$ mm，落在主流刊物单栏档内（Nature 89 mm / Cell 85 mm / Elsevier 90 mm / Science 90 mm，见 R1 §1）。
- **全程要盯的不是"两个面板一样宽"，而是"缩放比不同 → 同一 pt 字号在成品上变成两个 pt 值"**。§4 的算例给出具体偏差。

---

## 1. 期刊/出版社对"组合图"的官方要求

### 1.1 同一 Figure 内必须风格一致（字号/线宽/字体族）

- **Science**（AAAS 官方 *GUIDE TO PREPARING FIGURES* PDF，原文措辞最直白）：
  > "Font size variation within a figure can be confusing. Differences in size should be used for typographic hierarchy (**maximum of 3 sizes**)."
  > "Avoid wide variation in type size within a figure."
  > 自检清单："Is the figure color blind friendly? … **Are the font sizes consistent?**"
  > —— https://www.science.org/cms/asset/67f37ac8-4d02-4625-8a05-230568cb8323/author_prep_guide_2025.pdf
- **IEEE**：
  > "Use the same font type, font size, and label style across all graphics." / "Maintain consistent spacing across all graphics."
  > —— *Proceedings of the IEEE* 图形指南，https://proceedingsoftheieee.ieee.org/resources/guidelines-for-figures-and-tables/ （经 R1 核对）
- **Nature**：
  > "Lettering should be in a sans-serif typeface, preferably Helvetica or Arial, **the same font throughout all figures in the paper**."
  > —— https://www.nature.com/nature/for-authors/final-submission
  > "standard fonts used throughout the figure labels."
  > —— https://research-figure-guide.nature.com/figures/building-and-exporting-figure-panels/
- **Elsevier**：
  > "Elsevier's aim is to have a **uniform look for all artwork contained in a single article**." / "If a collection of artwork contains more than one halftone, again make sure that there is **consistency in size** between similar diagrams."
  > —— https://www.elsevier.com/about/policies-and-standards/author/artwork-and-media-instructions/artwork-sizing
- **JEEG**（把"一个字号"写成 MUST）：
  > "All labels (*e.g.*, axes' numbers and labels, bars' numbers and labels, map legends, *etc.*) **MUST be in the same eight-point font** with normal (regular) font weight (sans serif font such as Arial or Helvetica is preferred)." / "Lettering within single/multipanel figures … MUST be legible, not too large or too small in the same font with normal (regular) font weight (six-point sans serif fonts … are preferred)." / "The figure's style, font, size, and format **MUST be consistent with those in other figures**."
  > —— https://enengs.memberclicks.net/assets/docs/Publications/JEEG/JEEG%20guideline%20for%20display%20items_v03.pdf
- **Chicago Press**（书籍类，但把"一条线宽 + 一个字号"说成硬风格）：
  > "One consistent line weight is preferred, but use no more than two line weights." / "**Use one font point size throughout the figure.** If two sizes are used, they should vary from each other only slightly (e.g., 10 pt and 12 pt, not 10 pt and 18 pt)." / "Do not use all caps, as this decreases overall legibility."
  > —— https://chicagodistributioncenter.org/dam/jcr:a5ec70ab-ee46-449c-958d-cd9a28ac3a3a/artguide.pdf
- **npj 系列**（措辞最直接地表达了"整张图按同一比例缩"）：
  > "each panel of a multipart figure should be sized so that the whole figure can be **reduced by the same amount** and reproduced at the smallest size at which essential details are visible."
  > "Figure lettering should be in a clear, sans-serif typeface (for example, Helvetica); **the same typeface in the same font size should be used for all figures in a paper**."
  > "Figures divided into parts should be labeled with a **lower-case bold a, b**, and so on, in the **same type size as used elsewhere in the figure**."
  > "Figures are best prepared at the size you would expect them to appear in print. At this size, the **optimum font size is 8pt**."
  > —— https://www.nature.com/npjforests/for-authors-and-referees/submission-guidelines

**可落地判据**：同一 Figure 内 → 字体族唯一；字号档位 ≤ 3（Science 明示）；线宽档位唯一或 ≤ 2（Chicago）；面板字母大小写/字重统一。

### 1.2 面板字母（panel letters）的官方规则

| 刊物 | 大小写 | 字号/字重 | 位置 | 顺序 | 来源 |
|---|---|---|---|---|---|
| Nature | **小写** a, b, c | 8 pt bold, upright（不斜体） | 面板内左上 | 尽量按字母序；面板从左到右、从上到下 | https://www.nature.com/documents/nature-final-artwork.pdf · https://research-figure-guide.nature.com/figures/building-and-exporting-figure-panels/ |
| Science（2025 指南） | 大写 A, B, C | "Panel parts are **10-point Bold**" | 面板内左上 | left to right / top to bottom | https://www.science.org/cms/asset/67f37ac8-4d02-4625-8a05-230568cb8323/author_prep_guide_2025.pdf |
| Science Advances | 大写 A, B, C | 9 pt Myriad bold | 面板内左上 | 逻辑顺序；不用子面板标签 | https://www.science.org/cms/asset/94238a69-3add-4d93-9e79-804c7ef9ec01/sciadv_guide_to_preparing_figures_2026.pdf |
| Cell Press | 大写 A, B, C | R1 §2.1 | 面板内左上 | — | R1 §1/§2.1（cell.com 原页 403，用存档） |
| PALASS | 大写 A, B, C … AA, AB | 不编号 | — | — | https://palass.org/sites/default/files/2025-06/Figure_guidelines_2024_v5.pdf |
| npj 系列 | **小写粗体** a, b | 与图内其他文字**同字号** | 未指定 | — | https://www.nature.com/npjforests/for-authors-and-referees/submission-guidelines |
| JEEG | 小写 + 右括号（`a)`，括号前无空格），**粗体** | 8 pt | **面板/图像左上角；"can NOT be inside (within) a plot, image, map"** | left to right / top to bottom | https://enengs.memberclicks.net/assets/docs/Publications/JEEG/JEEG%20guideline%20for%20display%20items_v03.pdf |

Science 的原始措辞（同一段同时给了"避免子面板标签"）：
> "Use capital letters for part labels in multipart figures – A, B, C, etc. These should be 9 pt. and bold in the final figure. When possible, place part labels at the upper left-hand corner of each figure part; if a part is an image, set labels inside the perimeter so as not to waste space. … **Avoid subpart labels within a figure part**; instead, maintain the established sequence of part labels [e.g., use A, B, C, D, E instead of A, B, C(a), C(b), C(c)]. If use of subpart labels is unavoidable, use lowercase letters (a, b, c), not Roman numerals. Use numbers (1, 2, 3) only to represent a time sequence of images."

**注意"面板字母放哪"也有冲突**：FigureGuild 说"**Inside, at the top-left**"；JEEG 说"a panel label **can NOT be inside (within)** a plot, image, map, etc."（即放在图框外的左上角）；Nature/Science 说"place part labels at the upper left-hand corner of each figure part; **if a part is an image, set labels inside the perimeter**"（图像面板才放进框内）。三套说法互斥 —— figpact 只能把它当可配置元件，不能写死。
**面板字母的"大小写"**：Nature/npj 小写，Science/Cell/SciAdv/PALASS 大写。同上，配置化。

**图例（legend）**：
> JEEG: "If more than one panel of a multipanel figure holds similar items, instead of a legend for each panel, **one legend for all panels can be used**, but it should be in a place that is obvious it belongs to all panels, not one."
> —— https://enengs.memberclicks.net/assets/docs/Publications/JEEG/JEEG%20guideline%20for%20display%20items_v03.pdf
`[推断]` 这与 patchwork 的 `plot_layout(guides = 'collect')` 是同一个需求，且说明"图例共享"是排版动作而非科学内容。
**第三方汇总会互相矛盾**：FigureGuild 的博客写"Uppercase only (A, B, C — **never** a, b, c)"（https://figureguild.com/blog/figure-assembly-best-practices ），与 Nature 官方"8 pt bold … **a, b, c**"直接冲突。以官方页面为准。

### 1.3 缩放比例：官方是"只缩不放 + 按最终尺寸做"，不是给一个百分比上限

主流刊物没有统一的"不得缩放超过 X%"条款，但有等价的三条更硬的规则：

**(a) 只能缩、不能放（放大不可逆地毁质量）**
> "It is easy for IEEE to reduce the sizes of your graphics. But, in most cases, IEEE **cannot increase them** without negatively impacting quality."
> —— https://journals.ieeeauthorcenter.ieee.org/create-your-ieee-journal-article/create-graphics-for-your-article/resolution-and-size/
> Journal of Animal Science: "To preserve quality, figures are **never enlarged for printing, only reduced**." 同页还给硬数字："Ensure that all type within the figure and axis labels are readable at final publication size. A **minimum type size of 8 points (after reduction)** should be used." / "For line graphs, use a **minimum stroke weight of 1 point** for all lines."
> —— https://sitemaster.academic.oup.com/DocumentLibrary/ASAS/JAS/infora-guidelines-for-figures.pdf
> Wiley: "At least 80mm canvas size or 1800 pixels wide. **Smaller or larger images will be modified during composition**, which may reduce quality."
> —— https://authors.wiley.com/author-resources/Journal-Authors/Prepare/manuscript-preparation-guidelines.html/figure-preparation.html

**(b) 出版社保留再次缩放权 —— 你必须让"最小可能尺寸"仍然可读**
> "In the production process, figures **may be reduced to a smaller size** due to space limitations. Authors are encouraged to submit figures at the smallest appropriate size, ensuring all fonts are between 5pt and 7pt. Nature reserves the right to make the final decision on figure size."
> —— https://research-figure-guide.nature.com/figures/building-and-exporting-figure-panels/
> "Authors should check (using a reducing photocopier) that, at the smallest possible size, lettering remains readable and lines are sufficiently (but not too) heavy to print clearly."
> —— https://www.nature.com/nature/for-authors/final-submission
> "*Science* **might scale figures due to production constraints.**"
> —— https://www.science.org/cms/asset/67f37ac8-4d02-4625-8a05-230568cb8323/author_prep_guide_2025.pdf

**(c) 传统的"先放大 1.5 倍、再缩回来"只为容错；上限是"缩到 50%"**
> "The size of the original should be **no more than twice the intended size on the final printed page** unless the thickness of the line is robust enough to survive **reduction beyond 50%**. Ideally, your original should be x l.5 larger than its final size on the book page. **Enlargement of your original is to be avoided** as any flaws/unsharpnesses become exaggerated." / "We aim for a cap height after reproduction of 2 mm (or 8pt type size). If, for example, the artwork is to be **reduced to 67%**, the cap height on the original should be 3 mm (or l2pt type size)." / "For MAC programmes do not use rule weights below 0.5 pt and for PC programmes never use the fine weight rule."
> —— https://www.chapmanhall.com/chaphall/illust.html
> "drawings must be reduced in size … **preview** reproduction size by printing out your figures **at 50%** or use a photocopier to reduce figures to 50%." / "The **minimum rule size** should be no smaller than 1 pt in the large original." / "The **maximum rule size** should be no larger than 2 pts in the large original."
> —— https://chicagodistributioncenter.org/dam/jcr:a5ec70ab-ee46-449c-958d-cd9a28ac3a3a/artguide.pdf

`[推断]` 把这些合成可编程的判据：
- $k > 1.0$（放大）→ 硬拒（IEEE/JAS/Wiley 三条都指向放大是错的方向）。
- $0.5 \le k \le 1.0$（缩小）→ 允许，但必须按"最终尺寸下"的字号线宽重新校验（Chicago 的 50% 缩印就是这条）。
- $k < 0.5$ → 拒绝或强警告，因为点阵/细线在缩 50% 以下会消失（Chicago 的 1 pt 最小规则就是为此设的）。
- $k = 1$ 是唯一无需第二次校验的取值 → **应作为默认目标**（见 §3、§4）。

### 1.4 矢量嵌入与"可编辑性"：拼版文件必须是矢量的、分层的、字体可编辑

- **Nature**（主图必须"可编辑 + 分层"）：
  > "For main figures we require **vector files with editable layers**. Nature's preferred formats are: .ai, .eps, .pdf (please choose to retain all editing capabilities)." / "We do **not** accept the following formats: .jpeg, .tiff, .png, Canvas, DeltaGraph, Tex, ChemDraw, SigmaPlot, Coreldraw." / "Please limit file sizes to 50 MB where possible and ensure that all components are **embedded (not linked)** in the file." / "Do not outline text" / "Embed fonts (True Type 2 or 42)" / ".svg (**if saving from Inkscape, please choose to save as plain svg and not Inkscape svg**)" / "Powerpoint (please save .ppt to .pdf first to avoid Mac/Windows corruption issues)."
  > —— https://research-figure-guide.nature.com/figures/building-and-exporting-figure-panels/
- **Nature Reviews**（明确说"拼版动作本身会让质量与可编辑性变差"，并要求**同时交整图和分面板**）：
  > "We have found that when figure panels are combined into the final layout **the editability and quality can deteriorate**. If we have the individual figure panels we can rebuild the figure using those files, using the whole figure as a reference."
  > "When arranging your figure panels into one file … use a **vector-based application such as Adobe Illustrator or Microsoft PowerPoint**, as these retain the resolution and editability of the source files." / "We do not recommend using Microsoft Word and Adobe Photoshop."
  > "All text, annotation and scale bars should be in **editable format** and laid over the bitmapped images."
  > —— https://www.nature.com/documents/natrev-figure-guidelines-v1.pdf
- **Science**（分层是显式要求，且禁止"PPT 另存成别的格式"这种洗白）：
  > "Lines, arrows, and text placed over images should be on a **separate editable layer**." / "TOP LAYER: text labels (vector) / MID LAYER: graphics, arrows, illustrations (vector) / BASE LAYER: Photos/scans (raster image: 300 ppi)"
  > "Do not rasterize, flatten, or outline line art."
  > —— https://www.science.org/cms/asset/67f37ac8-4d02-4625-8a05-230568cb8323/author_prep_guide_2025.pdf
  > Science Advances: "**The following formats are not allowed**: Figures embedded in Word files, PowerPoint files, and figures prepared in PowerPoint or Word that have been converted to other, acceptable formats such as .ps or .pdf."
  > —— https://www.science.org/cms/asset/94238a69-3add-4d93-9e79-804c7ef9ec01/sciadv_guide_to_preparing_figures_2026.pdf
- **Elsevier/JBC**：
  > "Text and line-work should always be submitted in **vector format**." / "**graph lines at least .25 point wide**" / "Please use the **same font for all figures** in your manuscript" / "If fonts have not been converted to outlines always choose to **embed fonts** when saving files."
  > —— https://www.elsevier.com/__data/promis_misc/JBCDigitalArtGuidelines.pdf
- **PGF/TikZ 手册 §7.4**（不是期刊，但把"为什么"讲得最清楚，且是排版工具作者的一手经验）：
  > "Perhaps the most common 'mistake' people do when creating graphics … is to have a mismatch between the way their graphics look and the way their text looks. … All these graphics will, most likely, use different line widths, different fonts, and have different sizes. In addition, authors often use options like `[height=5cm]` when including graphics to scale them to some 'nice size'. If the same approach were taken to writing the main text, every section would be written in a different font at a different size."
  > "To create consistency between graphics and text, stick to the following guidelines: • **Do not scale graphics.** This means that when generating graphics using an external program, **create them 'at the right size'**. • Use the same font(s) both in graphics and the body text. • Use the same line width in text and graphics."
  > —— https://tikz.dev/guidelines

**结论**：期刊层面拼版的"正确姿势"是 **矢量面板 + 各面板在自己的程序里按最终尺寸生成 → 拼版时只挪位置不改比例**。一旦拼版工具里出现非 1.0 的缩放，"风格一致"和"pt 绝对值"同时失效。

### 1.5 单文件 vs 分面板提交

> npj: "Each complete figure must be supplied as a separate file upload. **Multi-part/panel figures must be prepared and arranged as a single image file** (including all sub-parts; a, b, c, etc.). **Please do not upload each panel individually.**" —— https://www.nature.com/npjforests/for-authors-and-referees/submission-guidelines
> JEEG: "A multipanel figure **MUST be displayed and submitted as one file** (e.g., each panel cannot be displayed or submitted as an individual file)." + "The figure's **style, font, size, and format MUST be consistent with those in other figures**." —— https://enengs.memberclicks.net/assets/docs/Publications/JEEG/JEEG%20guideline%20for%20display%20items_v03.pdf
> Science Advances: "Each complete figure (whether single or multiple panels) must be submitted as one separate file." —— https://www.science.org/cms/asset/94238a69-3add-4d93-9e79-804c7ef9ec01/sciadv_guide_to_preparing_figures_2026.pdf
> Nature Reviews 例外地要**两份**：整图 + 每个面板单文件。—— https://www.nature.com/documents/natrev-figure-guidelines-v1.pdf

`[推断]` 对 figpact 的含义：**"成品渲染"必须能给出一张合并的、单文件、矢量的 Figure**，同时（为了满足 Nature Reviews 这类要求）保留"逐面板单文件"的能力。这两个产物必须来自**同一组最终尺寸参数**，不能各算一遍。

### 1.6 面板间距

- Science："Panels should be set close to each other, and common axis labels should not be repeated." —— https://www.science.org/cms/asset/94238a69-3add-4d93-9e79-804c7ef9ec01/sciadv_guide_to_preparing_figures_2026.pdf （同一句亦见 2006 年主刊存档页 http://li.mit.edu/Archive/Activities/PubFormat/Science/Figures,pdf.pdf ）
- Nature：Panel 排列"neat and space-efficient, minimizing white space"。—— https://research-figure-guide.nature.com/figures/building-and-exporting-figure-panels/
- Cell（经 R1 核对）："Limit vertical space between parts of an illustration to only what is necessary for visual clarity"。
- `[未找到权威来源]`：主流出版社**没有**给"面板间距 = X mm"的硬数字。第三方（FigureGuild）给的"2–4 mm"是行业惯例而非官方值，**不要当规范引用**。

---

## 2. R 生态：patchwork / cowplot / egg 的跨面板主题统一

### 2.1 patchwork —— `&` / `*` 是唯一的"全局主题"机关

官方 vignette（一手，thomasp85/patchwork 源码仓库）：

> "Tags uses the theming of the plot they are applied to, so make sure they match up, or **modify the theming of all plots using `&`**."
> "For a coherent look, **don't mix widely different looks**. Setting the background colour of a single plot to a different shade is an effective way to highlight it, but e.g. **different fonts or line widths will just look like a mess**."
> "This operator will add to the theme of **all subplots as well as to the theme of the patchwork itself**."（`&` 的语义）
> —— https://github.com/thomasp85/patchwork/blob/main/vignettes/guides/annotation.Rmd

官方文档里字号一致的规范写法（多处一致）：
```r
(p1 + p2) + plot_annotation(tag_levels = 'a') &
  theme(plot.tag = element_text(size = 8), text = element_text(size = 7))
```
另一处把两个主题机关的分工讲清楚了：
> "If you need to address **only the theme of the patchwork itself** (e.g. for making the patchwork title larger than the plot titles), it can be done with the `theme` argument in `plot_annotation()`."
> —— 同上

`&` vs `*` vs `+` 的差别（assembly vignette，同一仓库）：
> "`&` will add the element to **all subplots** in the patchwork, and `*` will add the element to all the subplots **in the current nesting level**."
> "Be aware that mixing operators will put you under the control of the **operator precedence rule** (e.g. `/` will be evaluated before `+`). Because of this it is always a good idea to put sub-assemblies within braces."
> —— https://github.com/thomasp85/patchwork/blob/main/vignettes/guides/assembly.Rmd

一个已知的踩坑（维护者亲自回答，说明"以为改了全局其实没改"很常见）：
> Issue #372：用户对 `plot.tag` 的 font size / face 只对最后一个面板生效；维护者澄清**要用 `&` 而不是 `+`**。
> —— https://github.com/thomasp85/patchwork/issues/372

**尺寸方面 patchwork 的真相**（layout vignette）：
> "When grid sizes are given as a **numeric**, it will define the **relative** sizing of the panels."
> "It is also possible to supply a **unit vector** instead:"
> ```r
> p1 + p2 + p3 + p4 + plot_layout(widths = c(2, 1), heights = unit(c(5, 1), c('cm', 'null')))
> ```
> "In the last example the first row will always occupy 5cm, while the second will expand to fill the remaining area."
> "It is important to remember that sizing **only affects the plotting region (panel area)**. If a plot has, e.g. very wide y-axis text it will **not** be penalized and get a smaller overall plotting region."
> —— https://github.com/thomasp85/patchwork/blob/main/vignettes/guides/layout.Rmd

`[推断]` 关键含义：`plot_layout(widths=)` 的数值是**相对**比例；要落到绝对 mm，必须 (a) 用 grid unit（`unit(42, "mm")`），**并且** (b) 把输出设备的物理宽度设成"各面板 mm 之和 + 间隙"，否则 unit 之外的轴标签/图例会被"算进面板"再被拉扯。patchwork 本身没有"整张图的物理宽度"概念 —— 那属于设备（`ggsave(width=)`）。

### 2.2 cowplot —— `align` 对齐的是坐标轴，`rel_widths` 仍是相对值

> "By default, the plots are **not aligned**, but in many cases they can be aligned via the `align` option."（`align = "h"` / `"v"`）
> "The **relative** widths and heights of rows and columns can be adjusted with the `rel_widths` and `rel_heights` arguments."
> "**alignment of plots is only supported for ggplot2 plots**."
> "Alignment can be a bit tricky in this case. However, it can usually be achieved through an explicit call to `align_plots()`. The trick is to first align the top-row plot and the first bottom-row plot vertically along the left axis, using the `align_plots()` function."
> —— https://wilkelab.org/cowplot/articles/plot_grid.html

> "the cowplot package now provides a set of complementary themes … I now believe that there isn't one single theme that works for all figures, and therefore I recommend that **you always explicitly set a theme for every plot you make**."
> —— https://cran.r-project.org/web/packages/cowplot/vignettes/introduction.html

**cowplot 不解决的**：`align` 只对齐轴/面板边缘；它不声明任何 mm 尺寸，也不改字号。`plot_grid(labels=, label_size=)` 只管标签本身。

### 2.3 egg —— 唯一直说"不要缩放，否则字体会被拉变形"的包

一手（CRAN vignette，作者 Baptiste Auguié）：

> "In some cases, having ggplot2 expand the plot panel to best fit the available space isn't ideal: for instance, we may want to produce multiple plots to appear on different slides … Another use-case is to **embed multiple separate graphics in a drawing/page layout software**. In this situation the plot alignement will be made manually, but **the plots should not be rescaled (otherwise the fonts would be distorted)**. For such situations, the easiest solution is to **set fixed dimensions to the gtable** produced by ggplot2."
> "The function `set_panel_size` helps **set the panel size (width, height) to absolute measurements in the form of grid units**."
> "Note that the total size is now fixed, therefore when exporting the plot on a device it can be useful to **query the size and set the width and height accordingly, to avoid clipping or white margins**."
> —— https://cran.r-project.org/web/packages/egg/vignettes/Overview.html

对齐策略（不是靠"两个图都设成一样宽"猜出来的）：
> "decompose each plot into a 3x3 layout, where the central cell corresponds to the core panels, surrounded by axes, legends, etc. • set the core width and height to a fixed dimension • align the individual 3x3 gtables using `rbind`/`cbind`"
> —— 同上；也见 https://cran.r-project.org/web/packages/egg/vignettes/Ecosystem.html

API：
```r
set_panel_size(p = NULL, g = ggplot2::ggplotGrob(p), file = NULL,
               margin = unit(1, "mm"), width = unit(4, "cm"), height = unit(4, "cm"))
```
—— https://search.r-project.org/CRAN/refmans/egg/html/set_panel_size.html

### 2.4 生态层面的共同结论（给 figpact 的关键输入）

| 工具 | 能统一主题？ | 能声明面板绝对尺寸？ | 能保证成品 pt == 设计 pt？ |
|---|---|---|---|
| patchwork | ✅ `&` + `plot_annotation(theme=)` | ⚠️ 只有 grid unit（`unit(42,"mm")`）；数值是相对比例 | ❌ 设备宽度决定一切 |
| cowplot | ⚠️ 靠"每张图显式设 theme" | ❌ `rel_widths` 是相对值 | ❌ |
| egg `set_panel_size` | ➖ 不管主题 | ✅ grid unit 绝对尺寸 | ✅ **前提是不再缩放** |

**三条可直接落设计的结论：**
1. **"统一主题"和"统一物理尺寸"是两件事**，主流 R 生态把它们拆成两个包（patchwork/cowplot 管前者，egg 管后者）。figpact 要一并管，但必须在内部保持这个分离：**字号/线宽是排版契约的"档位"，宽度是"尺寸"**。
2. **所有 R 方案的失效点都在"最后一步缩放"**。egg 作者一句话点破："the plots should not be rescaled (otherwise the fonts would be distorted)"。
3. **绝对尺寸必须表达为 grid unit / mm，不能表达为比例**。任何"两个面板都 = 1 份宽"的写法在不同数据密度下会得到不同 mm。

---

## 3. 实操拼版（Illustrator / Inkscape / PPT）如何避免"缩放后面板字号不一致"

### 3.1 权威共识：**先在源头按最终尺寸做，不要事后缩**

- **PGF/TikZ 手册**："**Do not scale graphics.** … create them 'at the right size'." —— https://tikz.dev/guidelines
- **egg 作者**："the plots should not be rescaled (otherwise the fonts would be distorted)" —— https://cran.r-project.org/web/packages/egg/vignettes/Overview.html
- **Chicago Press**："The relationship between font size, rule weight, and final printed size should be considered **when creating drawings**." + "reduce your printouts 50% to make sure your type is clear" —— https://chicagodistributioncenter.org/dam/jcr:a5ec70ab-ee46-449c-958d-cd9a28ac3a3a/artguide.pdf
- **PALASS**："View your figures at their final intended size and check that all text is clearly legible." + "Do not scale up low resolution files to meet size or dpi requirements. Use an earlier, higher resolution version." —— https://palass.org/sites/default/files/2025-06/Figure_guidelines_2024_v5.pdf
- **Cell Press**："Use a vector graphics program (such as Adobe Illustrator or Inkscape) to assemble the figures and **verify that at final print size**, each displayed image is at least 300 pixels per inch." —— cell.com figure guidelines（原页 403，经 R1 核对 + 存档 https://web.archive.org/web/20250414002944/https://www.cell.com/information-for-authors/figure-guidelines ）
- **scholarviz**（二手，但把公式写清楚了）："**Design at 100% scale**: Never design at 2× or 0.5× scale with intention to resize. Fonts, line weights, and details must be evaluated at final print size." —— https://scholarviz.com/blog/journal-target-size-dpi-font-decision-tree
- **GLE**（二手）："Set figure width to a publication target … from the start; **avoid designing at a convenient canvas and scaling later**." + "Fonts must be defined in the final output size (**points refer to the printed size, not the canvas**). Don't rely on later scaling to fix font size." —— https://gle-graphics.org/blog/multi-panel-figure-layout/

### 3.2 缩放工具的**行为差异**是第二个坑（同一个"缩小 79%"，三个软件三套后果）

- **Illustrator**：默认"**strokes and effects do not scale**"。要跟随缩放必须在 Edit ▸ Preferences ▸ General 打开 **Scale Strokes & Effects**，或在 Transform 面板/Scale 命令里单次勾选。
  > "Strokes and effects do not scale by default. To scale them, enable Scale Strokes & Effects in: Windows: Edit > Preferences > General"
  > —— Adobe Illustrator CC 参考手册（缩放章节），https://www.manualsdir.com/manuals/753912/adobe-illustrator-cc-2015.html?page=272
  `[推断]` 于是同一个画板上会出现三类对象三种命运：图形几何缩了、描边没缩（视觉变粗）、文本要么缩了要么没缩（取决于是否连同文本框一起选中并勾选）。**"看起来字号变了"往往不是字号变了，而是线宽没跟着缩**。
- **Inkscape**：由偏好 `/options/transform/stroke`（默认 **true**，即"stroke width is scaled when objects are scaled"）驱动；UI 上就是 Select 工具栏那个 "Scale stroke width" 按钮。
  > 提交信息原文："Preference: /options/transform/stroke (default true) controls whether stroke width scales with object scaling." / UI 反馈："Now stroke width is scaled when objects are scaled."
  > —— https://gitlab.com/inkscape/inkscape/-/commit/4d743dc9f4979c818ff75d69465975893bd55fa9
  > 变换章节（Visual vs Geometric bounding box 的差别）：http://tavmjong.free.fr/INKSCAPE/MANUAL/html/Transforms.html
  `[推断]` Inkscape 的默认值与 Illustrator 相反，所以"同一套操作在 AI 里对、在 Inkscape 里错"是常态；跨软件照抄流程必然翻车。
- **PowerPoint**：没有"描边是否随缩放"的开关，缩放是纯视觉的，导出时按目标设备栅格化；且**主流刊物直接禁 PPT 来源的图**：
  > Science Advances："The following formats are not allowed: Figures embedded in Word files, PowerPoint files, and figures prepared in PowerPoint or Word that have been converted to other, acceptable formats such as .ps or .pdf."
  > —— https://www.science.org/cms/asset/94238a69-3add-4d93-9e79-804c7ef9ec01/sciadv_guide_to_preparing_figures_2026.pdf
  > Nature 只是"接受 .ppt 但必须先另存为 .pdf"：".ppt to .pdf first to avoid Mac/Windows corruption issues" —— https://research-figure-guide.nature.com/figures/building-and-exporting-figure-panels/
  `[推断]` PPT 只能当"人工拼版的可视化草稿"，不能当"保证规格一致的生产工具"。
- **期刊自己的口头指令仍是"不要靠缩放"**：Nature Reviews 让作者**同时**交整图与逐面板原文件，正是因为"combination 之后 editability/quality 会退化"。—— https://www.nature.com/documents/natrev-figure-guidelines-v1.pdf

### 3.3 字号换算公式（唯一能"算出来"的部分）

设计尺寸 → 最终尺寸的换算，1:1 成立：
$$ \text{final\_pt} = \text{design\_pt} \times \frac{\text{final\_width}}{\text{design\_width}} $$
> "Font Scaling | Final size = Design size × (Target width ÷ Design width) | 10pt × (3.5" ÷ 7") = 5pt"
> —— https://scholarviz.com/blog/journal-target-size-dpi-font-decision-tree

**本场景代入（NMR 48→42，FTIR 48→38，两图源字号假设都是 7 pt）**：

| 面板 | 源宽 | 目标宽 | $k$ | 源字号 | 成品字号 | 源线宽 | 成品线宽 |
|---|---|---|---|---|---|---|---|
| NMR | 48.0 mm | 42.0 mm | 0.8750 | 7.0 pt | **6.125 pt** | 0.75 pt | 0.656 pt |
| FTIR | 48.0 mm | 38.0 mm | 0.7917 | 7.0 pt | **5.542 pt** | 0.75 pt | 0.594 pt |
| 差 | — | — | — | 0 | **Δ = 0.583 pt（相对 8.3%）** | 0 | Δ = 0.062 pt |

两个后果：
1. **同图内字号不一致**，且是"肉眼可辨"的 8% 级差异 —— 恰好命中 Science 的自检项 "Are the font sizes consistent?" 与 "Avoid wide variation in type size within a figure"。（Science 允许最多 3 档层级，所以严格说不是硬违规；但**这两个字号并不承载层级含义**，属于"不一致"而非"层级"，是典型的拼版事故。）
2. **下限判定会漂**：若源字号是 6 pt（NMR 6.0 → 5.25 pt 尚可；FTIR 6.0 → 4.75 pt）就跌破 Nature 的 5 pt 下限，也远低于 PLOS 的 8 pt。同一批输入，仅因为 $k$ 不同，一个合格一个不合格。**这就是"必须按最终尺寸生成、不能事后缩"的真正理由。**

### 3.4 拼版里的检查手段（都是"人眼 + 尺"，没有自动化）

- Chicago："printing out your figures **at 50%**" + "**use a photocopier to reduce** your printouts by 50% to ensure that the type will be easily readable" —— https://chicagodistributioncenter.org/dam/jcr:a5ec70ab-ee46-449c-958d-cd9a28ac3a3a/artguide.pdf
- Nature："check (**using a reducing photocopier**) that, at the smallest possible size, lettering remains readable" —— https://www.nature.com/nature/for-authors/final-submission
- PALASS："**Use a ruler** to check the actual size of your figure on screen and assess visually whether all text is clearly legible." —— https://palass.org/sites/default/files/2025-06/Figure_guidelines_2024_v5.pdf
- JAS："One simple test to determine whether a figure will be clear at one of the three widths used by JAS is to **reduce the figure on a photocopy machine to the appropriate width** and ask someone unfamiliar with the figure to evaluate it for readability." —— https://sitemaster.academic.oup.com/DocumentLibrary/ASAS/JAS/infora-guidelines-for-figures.pdf

`[推断]` 这四处恰好说明：**业界这套检查至今是人工的、定性的、不可复现的**。这是一块真空 —— figpact 的差异化价值就在于把 §3.3 的那张表变成可测量、可阻断的判据。

---

## 4. 给 figpact 的启示：最小界面 / 命令

### 4.0 根因（一句话）

**pt 是绝对单位，画布是相对单位。** matplotlib 官方 API 表把这件事写清楚了：`size or fontsize` 的取值是 "size in points"；`font.size` 是 "Default font size in points"；相对字号（`'large'`、`'x-small'`）是"computed against this size"（即相对 **font.size**，不是相对画布）。
> `size or fontsize` → "size in points | relative size, e.g., 'small', 'x-large'"
> `'font.size'` → "Default font size in points. Relative font sizes ('large', 'x-small') are computed against this size."
> —— https://matplotlib.org/stable/users/explain/text/text_props.html
`[推断]` 结合 `savefig` 的 `bbox_inches` / `pad_inches` 语义（画布尺寸由 tight bbox 决定，字号本身不变），可得：**改 figsize 不改 pt，改 pt 不改 figsize；只有缩放成品文件才会同时改两者之比。**
所以：只要**在源头把画布设成最终 mm 并渲染**，$k = 1$，所有面板的 pt 天然一致；只要**先渲染再缩放**，每个面板各得到一个 $k_i$，一致性只能靠事后补偿。figpact 应把前者做成默认路径。

**两个必须记住的陷阱：**

1. **`bbox_inches='tight'` 会破坏"画布 mm = 成品 mm"的等式。**
   > "Bounding box in inches: only the given portion of the figure is saved. If 'tight', try to figure out the tight bbox of the figure." / `pad_inches` 默认 0.1 英寸
   > —— https://matplotlib.org/stable/api/_as_gen/matplotlib.pyplot.savefig.html
   `[推断]` 声明 `final_width_mm = 42.0` 而实际 tight bbox 是 44.7 mm 时，$k$ 已经不是 1，后面任何人缩到 42 mm 都会把 7 pt 变成 6.58 pt。**figpact 必须实测 tight bbox 并把它当作"实际成品宽"，而不是相信声明值** —— 这与 figpact 既有原则"声明的是目标，实测的是事实"完全同构。
2. **矢量的 pt 不会"跟着文件走"**：矢量 PDF/SVG 里的字号是绝对 pt，页面物理尺寸 = figsize。**缩放文件 = 缩放 pt**。所以"输出 PDF 就安全了"是错的；安全性来自 $k=1$，不来自格式。

### 4.1 最小 YAML 契约（只加三个字段）

figpact 已经在 ftir 侧有 `canvas_w_mm` / `canvas_h_mm`（"画布物理尺寸；字号**不**跟着缩放"，见 `examples/ftir/SKILL.md`）—— 同一语义应提升为**跨图统一契约**，而不是每图各写一个名字：

```yaml
# 建议新增：不引入新概念，只是把已有 canvas_w_mm 提到 figure 级 + 共享字号档
figure:
  final_width_mm: 82.0          # 拼版成品总宽（可省略；省略则 = Σ面板 + Σ间隙）
  gap_mm: 2.0
typography:                     # 全图唯一的排版档位（档位 = 契约，不是尺寸）
  text_pt: 7.0                  # 轴标签/刻度/图例统一字号（最终印刷 pt）
  panel_label_pt: 8.0           # 面板字母，独立档位（Nature 8 / SciAdv 9）
  line_pt: 0.5                  # 数据线宽下限
scopes:
  nmr:
    final_width_mm: 42.0        # 每作用域的成品宽（现在的 canvas_w_mm）
  ftir:
    final_width_mm: 38.0
```

**为什么只要三个字段**：`final_width_mm` 决定 $k$；`typography.*_pt` 决定绝对 pt；其余（栏宽档、上/下限、面板字母大小写）都应该是**profile 常量**或 CLI 参数，不进 YAML —— 否则每张图都要抄一遍期刊规范（R1 §5.1 已警告"一刊多档"）。

### 4.2 最小命令 / API（全部挂在既有面上，不新增引擎）

| 已有面 | 最小增量 | 说明 |
|---|---|---|
| `snapshot()` | result 新增 `typography` | `{per_scope: {declared_mm, measured_mm, k, text_pt, panel_label_pt, line_pt_min}, consistency: {...}}`。数据源已经存在：`scene.py` 已抓 `font_size_pt`，`inventory.py` 已抓 `fontsize`/`linewidth`。 |
| `figpact list-params` | 不新增命令名，`final_width_mm` 作为 LAYOUT 类型参数出现 | 与 `canvas_w_mm` 同类，`operation: "rebuild"` |
| `figpact render --strict` | 新增阻断项（见 4.3） | 复用既有阻断机制，不加新流程 |
| 新增只读命令 `figpact typography` | 打印 §3.3 那张表（declared / measured / k / effective pt / verdict） | 复用 `inventory` 的遍历，`--json` 同 `export-params` |

`try_layout` 侧：`set_parameter` 的 `path` 里出现 `final_width_mm` 时，天然落到既有 `rebuild` 语义，返回 `RENDER_CHECKED`（因为必须重建才知道 tight bbox）。**不允许**用 `GEOMETRY_CHECKED` 声称字号一致 —— 几何检查看不见 pt（沿用 SKILL.md §5"不要拿几何检查冒充渲染检查"）。

### 4.3 可验证的阻断判据（这是"可验"的全部）

沿用 figpact 的 `OK / UNMEASURED / 实测为准` 风格，每条都必须是**实测毫米/pt + 明确的比较基准**：

| 判据 | 计算 | 触发 |
|---|---|---|
| `CANVAS_WIDTH_MISMATCH` | `measured_mm`（实际 tight bbox）vs `declared final_width_mm` | \|Δ\| > 0.05 mm（即 $k$ 被 tight bbox 偷走） |
| `FONT_SIZE_INCONSISTENT` | 各 scope 的 `text_pt` 实测集合 `max - min` | > 0.25 pt（§3.3 的 0.583 pt 会被抓；声明层级的情况走白名单） |
| `FONT_BELOW_MIN` / `FONT_ABOVE_MAX` | 每个 text artist 的实测 pt vs profile 的 [min,max] | Nature [5,7] / SciAdv [6,8] |
| `LINE_BELOW_MIN` | 实测线宽 pt | 默认 0.28 pt（Science）；ACS profile 提到 0.5 pt |
| `SCALE_OUT_OF_BAND` | $k = $ measured_final_mm / 源 canvas mm | $k > 1.0$（放大，IEEE/JAS/Wiley 三条一致反对）或 $k < 0.5$ |
| `PANEL_LABEL_INCONSISTENT` | 各面板字母的 (case, pt, weight, 相对位置) 是否同档 | 任一不同 → 阻断（Nature 小写8pt bold / Science 大写10pt） |
| `UNMEASURED` | 任何 text/line artist 拿不到 `font_size_pt` / `linewidth` | 与既有策略一致：不填 0、不估计 |

**注意**：这些判据必须报"实测 pt"而不是"声明 pt" —— 与 SKILL.md 中"声明 ≠ 实测"的同一条规则保持同一套语言。

### 4.4 最小可用设计（三句话）

1. **默认路径 = 按最终尺寸生成**：每 scope 的 `final_width_mm` 直接进 `figsize`，`typography.text_pt` 全图共享一份 → $k \equiv 1$，一致性**由构造保证**，QA 只做复核（防 tight bbox 与漏改）。
2. **不做"拼版图层"**：不引入"把已渲染的面板图贴到画布再缩放"的机制。期刊（PGF/egg/Nature Reviews）一致指出这条路必然导致字体失真与可编辑性下降。
3. **一致性是可测量的数，不是感觉**：`figpact typography` 输出 §3.3 那张表；`render --strict` 把它变成阻断项。

### 4.5 明确"不要照抄"的清单

1. **不要硬编码面板字母大小写/字号**（Nature 小写 8 pt vs Science 大写 10 pt vs SciAdv 大写 9 pt）→ 必须 profile 化。
2. **不要把第三方博客的"2–4 mm 间距""uppercase only"当规范**（FigureGuild 的 uppercase 与 Nature 官方直接冲突；间距主流刊物未给数字）。
3. **不要引入"缩放比不得低于 X%"的全局限值**：官方没有这条；正确的是"$k \neq 1$ 时必须重新校验 pt/线宽，且拒绝 $k>1$"。`[推断]`
4. **不要用"两个面板等宽"来表达一致**：本场景 42+38 就是不等宽，且这是正常的（Nature："some panels may require more space than others"）。要一致的是**字号/线宽档位**，不是宽度。
5. **不要把 `--dpi` 或矢量格式当成字号问题的解**：字号在 API 层就是 pt（见 §4.0 的官方措辞），与 dpi/figsize 无关；矢量文件一样会被缩放。
6. **不要在 PPT 里做生产拼版**：Science Advances 直接禁 PPT 来源图。
7. **不要承诺"整批原子发布"级别的强一致承诺**（SKILL.md 已声明当前无事务日志）；typography QA 只对**本次渲染**负责。

### 4.6 与 P1.5 / 拖动→保存闭环的接缝

- `final_width_mm` 是 **rebuild** 参数，不是 translate 参数。拖动（纯显示位移）**不得**声称"字号已统一" —— 纯显示位移不动字号，这正好是 SKILL.md 里 `apply_display_shift` 的既有语义。`[推断]`
- 保存闭环里，`commit(kind="publication")` 的 strict 校验应包含 4.3 的全部判据；`commit(kind="draft")` 只需 YAML 合法（沿用既有信任等级，不升级）。

---

## 5. 未找到权威来源 / 存疑项

- **"面板间距 = 2–4 mm"**：主流出版社未给数字。FigureGuild 的 2–4 mm、Nature ~2 mm、Cell up to 4 mm 均属第三方转述；`[未找到权威来源]`（官方只给"set close / minimize white space"）。
- **"缩放比例不得超过 X%"的统一条款**：不存在。等价约束是"只缩不放 + 按最终尺寸做 + 缩小后必须仍满足字号/线宽下限"（§1.3）。第三方 bibliographic 类渠道（Amazon/图书指南）给的"50%"仅适用于书籍线稿的**预览检查**（Chicago），不是**硬上限**。
- **Cell Press figure guidelines 官方页**：直连 403；本文 Cell 相关引用沿用 R1 的存档链接（https://web.archive.org/web/20250414002944/https://www.cell.com/information-for-authors/figure-guidelines ）。`[推断]` 其现行数值以存档页为准。
- **Science 主刊"legible after reduction"逐字原文**：science.org 对抓取返回 403（本次实测 `instructions-preparing-initial-manuscript`、`instructions-preparing-revised-manuscript` 均 403）。已用同社官方 PDF（作者准备指南 2025 / SciAdv 2026）替代，措辞见 §1.1/§1.4。2006 年存档版另有："Line widths should be legible upon reduction (**minimum of 0.5 pt at the final reduced size**)"、"Use capital letters for part labels … These should be **9 pt and bold** in the final figure" —— http://li.mit.edu/Archive/Activities/PubFormat/Science/Figures,pdf.pdf （**注意：同一刊 2006 说 0.5 pt/9 pt，2025 说 0.28 pt/10 pt——不要跨版本混用**。）
- **Illustrator 官方 helpx 页面对 Scale Strokes & Effects 的现行措辞**：本次抓到的 helpx 页主要是导航骨架，未取到该选项正文；引用改用 Adobe Illustrator CC 参考手册缩放章节（https://www.manualsdir.com/manuals/753912/adobe-illustrator-cc-2015.html?page=272 ）。`[推断]` 行为描述"strokes and effects do not scale by default"多来源一致，可信。
- **Inkscape 官方用户手册**：tavmjong.free.fr 的版本对应旧版 Inkscape；现行行为以 GitLab 提交（`/options/transform/stroke` 默认 true）为准。
- **R 生态是否存在"绝对 mm 面板 + 绝对 pt 字号"一站式方案**：未找到。egg 只解决第一半（绝对面板尺寸），且其文档明确把"不缩放"当作作者义务。
