# R1 — 期刊"最终尺寸"硬规范调研

调研目的：为 figpact 下一阶段 **Final-size Style**（把不同尺寸的代码图统一到最终拼版规格）提供可落地的外部硬约束。
调研日期：2026-10-14。方法：仅读取一手来源（期刊作者指南 / 出版社官方政策页 / 官方 PDF）。所有数字均给原文英文引用 + URL。标 `[推断]` 者为本文推断，非原文。

## 0. "最终尺寸"口径（重要前提）

各社口径并不一致，落设计时必须区分三种：

1. **printed / final print size / 最终印刷尺寸**——Nature、Science、Cell、Elsevier、ACS 均指"排版后印在纸上的尺寸"，字号、线宽、dpi 全部以这个尺寸为准。
2. **投稿时像素尺寸**——PLOS 用"300 dpi 下的像素宽高"表达，等价于最终尺寸；Wiley/RSC 直接用 mm/cm。
3. **投稿 vs 生产两阶段**——Cell、Wiley、Science 明确区分 initial submission（宽松）与 production/accepted（严格）。figpact 的目标是生产阶段规格。

> Nature: "This guide provides information on preparing production-quality figures and text files. The instructions apply only if your manuscript has been accepted in principle for publication..." —— https://www.nature.com/nature/for-authors/final-submission

---

## 1. 主流期刊的最终宽度规范（单栏/双栏/整页）

| 出版社/期刊 | 单栏 | 双栏/整页 | 其它 | 来源口径 |
|---|---|---|---|---|
| **Nature** | 89 mm | 183 mm | 1.5 栏 120–136 mm；整页深 247 mm；图最大高 170 mm | printed figure widths |
| **Science** | 9 cm (3.6 in, 21p3) | 18.3 cm (7.25 in, 43p4) | 介于之间不得 > 14.4 cm；页高 22.75 cm | final print size |
| **Science Advances** | 9 cm (3.55 in, 21p3) | 18.4 cm (7.25 in, 43p6) | 非满两栏 ≤ 14.4 cm；最大深 22.75 cm | final size |
| **Cell Press**（研究/综述） | 8.5 cm | 整页 17.4 cm | 1.5 栏 11.4 cm；最大 16.5×20 cm | final production |
| **Cell Press STAR Protocols** | 13.4 cm | 17.2 cm | — | final production |
| **Elsevier**（通用） | 90 mm (255 pt) | 190 mm (539 pt) | 最小 30 mm；1.5 栏 140 mm (397 pt) | finished/printed size |
| **Wiley**（通用） | ~80 mm (8 cm) | ~170–180 mm (17 cm) | 图尺寸须在 80–180 mm 之间 | final publication size |
| **ACS** | ≤ 240 pt (3.33 in) | 300–504 pt (4.167–7 in) | 最大深 660 pt (9.167 in，含图注) | final published format |
| **IEEE** | 88.9 mm (3.5 in, 21 picas) | 182 mm (7.16 in, 43 picas) | 最大 182×220 mm | — |
| **PLOS** | 最小宽 789 px@300dpi (6.68 cm)；正文栏对齐 ≤ 13.2 cm (5.2 in) | 最大 2250 px@300dpi (19.05 cm, 7.5 in) | 最大高 2625 px (22.23 cm) | 300 dpi 像素等价 |
| **RSC** | 8.3 cm | 17.1 cm | 最大长 23.3 cm，不超过单页 | — |

### 原文引用

**Nature**
> "For guidance, *Nature*'s standard figure sizes are 89 mm wide (single column) and 183 mm wide (double column). The full depth of a *Nature* page is 247 mm. Figures can also be a column-and-a-half where necessary (120–136 mm)."
> —— https://www.nature.com/nature/for-authors/final-submission

> "The widths of printed figures are: 89 mm (single column) / 183 mm (double column). The maximum height for a *Nature* figure is 170 mm, to allow space for the figure legend to fit underneath."
> —— https://research-figure-guide.nature.com/figures/building-and-exporting-figure-panels/

> "Tables can be set at one-column (8.9 cm) or two-column (18 cm) width." / "The maximum page dimension is 18 cm by 24 cm."（Extended Data）
> —— https://www.nature.com/nature/for-authors/final-submission

**Science**
> "1 column = 21p3 picas (9 cm, or 3.6 in.)  |  2 column = 43p4 picas (18.3 cm, or 7.25 in.)"
> —— *Guide to preparing figures* (Science), https://www.science.org/cms/asset/67f37ac8-4d02-4625-8a05-230568cb8323/author_prep_guide_2025.pdf

**Science Advances**
> "1 column = 21p3 (3.55 in or 9 cm)  2 column = 43p6 (7.25 in or 18.4 cm)" / "For figures between 1 and 2 columns, the width should not exceed 34p (5.67 in or 14.4 cm)"
> —— https://www.science.org/cms/asset/94238a69-3add-4d93-9e79-804c7ef9ec01/sciadv_guide_to_preparing_figures_2026.pdf

**Cell Press**
> "For all other Cell Press journals, including partner journals:
> • Two-column formats (such as research articles and reviews): 8.5 cm (1 column), 11.4 cm (1.5 columns), and 17.4 cm (full width of the page)
> • Three-column formats (such as previews and commentaries): 5.5 cm (1 column), 11.4 cm (2 columns), and 17.4 cm (full width of the page)"
> "We recommend that figures be a maximum of 6.5 x 8 in (16.5 x 20 cm) to allow for page margins and text."
> —— https://www.cell.com/information-for-authors/figure-guidelines （原页 HTTP 403；存档：https://web.archive.org/web/20250414002944/https://www.cell.com/information-for-authors/figure-guidelines ）

**Elsevier**
> Table "TARGET SIZE": Minimal size 30 mm / 85 pt; Single column 90 mm / 255 pt; 1.5 column 140 mm / 397 pt; Double column (full width) 190 mm / 539 pt
> —— https://www.elsevier.com/about/policies-and-standards/author/artwork-and-media-instructions/artwork-sizing

**Wiley**
> "Figures are created at a size between 80mm and 180mm in width and between 300dpi and 600dpi."
> —— https://authors.wiley.com/author-resources/Journal-Authors/Prepare/manuscript-preparation-guidelines.html/figure-preparation.html
> 补充（Wiley figure guide PDF）："width targets are 8 cm for a single column and 17 cm for full page width" —— https://onlinelibrary.wiley.com/pb-assets/assets/16000722/GUIDE%20TO%20Figures%5B1%5D-1606231997277.pdf

**ACS**
> "Graphics must fit a one- or two-column format. Single-column graphics can be sized up to 240 points wide (3.33 in.) and double-column graphics must be sized between 300 and 504 points (4.167 in. and 7 in.). The maximum depth for all graphics is 660 points (9.167 in.) including the caption (allow 12 pts for each line of caption text)."
> —— ACS *Author Guidelines*, Appendix 2: Preparing Graphics, e.g. https://researcher-resources.acs.org/publish/author_guidelines/pdf?coden=jacsat

**IEEE**
> "One column width: 3.5 inches, 88.9 millimeters, or 21 picas / Two columns width: 7.16 inches, 182 millimeters, or 43 picas"
> —— https://journals.ieeeauthorcenter.ieee.org/create-your-ieee-journal-article/create-graphics-for-your-article/resolution-and-size/

**PLOS**
> Dimensions table: "Minimum width 6.68 cm / 2.63 in / 789 px;  Maximum width 19.05 cm / 7.5 in / 2250 px;  Height maximum 22.23 cm / 8.75 in / 2625 px"（at 300 dpi）
> "To align your figure with the text column of the PDF version of the article, make it no wider than 5.2 inches (13.2 cm)."
> —— https://journals.plos.org/plosone/s/figures

**RSC**
> "Images should fit within either single column (8.3 cm) or double column (17.1 cm) width, and must be no longer than 23.3 cm."
> —— https://www.rsc.org/publishing/publish-with-us/publish-a-journal-article/chemical-science （存档：https://web.archive.org/web/20260121035434/https://www.rsc.org/publishing/publish-with-us/publish-a-journal-article/chemical-science ）

---

## 2. 最终尺寸下的字号 / 线宽 / 分辨率 / 矢量要求

### 2.1 字号（pt，均为"最终尺寸下"）

| 出版社 | 正文/轴标签 | 面板字母 (a/b/c 或 A/B/C) | 最小字号 | 硬性程度 |
|---|---|---|---|---|
| **Nature** | 5–7 pt（all other text，最大 7 / 最小 5） | 8 pt bold, upright, 小写 a,b,c（或大写 by 其它页表述） | 5 pt | 硬性 |
| **Science** | 6–9 pt（Labels are 6 to 9 points）；图内字号层级最多 3 档 | 10 pt bold（sciadv 为 9 pt bold 大写） | 6 pt | 硬性 |
| **Cell Press** | "about 6–8 pt at the desired print size" | 大写字母 | — | 推荐 |
| **Elsevier** | 7 pt 正常文本；下标/上标 ≥6 pt | — | 6 pt（sub/super）/ 7 pt（正文，"rule-of-thumb rather than a strict rule"） | 规则/惯例 |
| **ACS** | ≥4.5 pt（"no smaller than 4.5 points in the final published format"） | — | 4.5 pt | 硬性 |
| **IEEE** | ~9–10 pt（Proceedings of the IEEE，recommended） | — | — | 推荐 |
| **PLOS** | Arial/Times/Symbol，8–12 pt | — | 8 pt | 硬性 |
| **RSC** | 化学结构 atom labels/captions 7 pt（Arial/Helvetica） | — | — | — |

原文：
- Nature: "Separate panels in multi-part figures should each be labelled with 8 pt bold, upright (not italic) a, b, c. Maximum text size for all other text should be 7 pt; minimum text size should be 5 pt." —— final-submission；亦见 figure guide: "Maximum text size: 7pt / Minimum text size: 5pt"。
- Science: "Panel parts are 10-point Bold / Labels are 6 to 9 points – six, seven, eight, nine" —— author_prep_guide_2025.pdf。Science Advances: "the labels of each part of the figure (A, B, C, etc.) should be capitalized and must be in 9 pt. Myriad bold type"; "Axis labels or other type on the figure must be 8 pt. Myriad regular type... If needed, a minimum of 6 pt type can be used."
- Cell: "Text should be about 6–8 pt at the desired print size" —— figure-guidelines（存档）。
- Elsevier: "the lettering on the artwork should have a finished, printed size of 7 pt for normal text and no smaller than 6 pt for subscript and superscript characters." —— artwork-sizing。
- ACS: "Lettering should be no smaller than 4.5 points in the final published format." —— Appendix 2。
- IEEE: "Use the same font type, font size, and label style across all graphics. Recommended font size is approximately 9-10 points." —— https://proceedingsoftheieee.ieee.org/resources/guidelines-for-figures-and-tables/
- PLOS: "Use only Arial, Times, or Symbol font in 8-12 point." —— https://journals.plos.org/plosone/s/figures

**关键注意**：Nature（5 pt 下限）与 ACS（4.5 pt 下限）字号极小，说明"最终尺寸下"的判据是**印刷后实际 pt**，不是画布坐标系里的 pt。`[推断]` figpact 若以 mm 定义最终宽度，需按"画布宽/最终印刷宽"的缩放比折算字号。

### 2.2 线宽（pt，最终尺寸下）

| 出版社 | 规范 | 来源 |
|---|---|---|
| **Nature** | 0.25–1 pt at final size；<0.25 pt 可能印不出 | final-submission |
| **Science**（含 Sci. Adv.）| 最小 0.28 pt（~0.10 mm）at final print size | author_prep_guide_2025.pdf / sciadv guide |
| **Cell Press** | 0.5–1.5 pt | figure-guidelines |
| **Elsevier** | 一般 0.25 pt；绝对最小 0.1 pt；数据线 ~1 pt | artwork-faq |
| **ACS** | 不得细于 0.5 pt | Appendix 2 |
| **Wiley** | 未给全局最小（按 600 dpi 线稿） | — |
| **IEEE** | 未给 pt 最小值（Proceedings 建议"thick lines"以利色盲可读） | — |
| **PLOS** | 软件预设示例：线宽 0.2 mm（SigmaPlot 设置） | plos figures page |

原文：
- Nature: "Line weights and strokes should be set between 0.25 and 1 pt at the final size (lines thinner than 0.25 pt may vanish in print)."
- Science: "At final print size, minimum line weight is 0.28 pt (~0.10 mm)"
- Cell: "Line weights or stroke widths should be in the 0.5–1.5 pt range"
- Elsevier: "Any line work should use a recommended line width of 0.25 pt (absolute minimum line width is 0.1 pt)... For prominent lines (e.g., plot lines on graphs), the weight should be approximately 1 pt." —— https://www.elsevier.com/about/policies-and-standards/author/artwork-and-media-instructions/artwork-faq
- ACS: "Lines should be no thinner than 0.5 point."

**设计含义**：0.25 pt 是主流下限（Elsevier/Nature），ACS 最严（0.5 pt）。`[推断]` figpact 若统一到"最保险"的公共下限，取 **0.5 pt**（覆盖 ACS/Cell）；若面向 Nature/Elsevier 可放宽到 0.25 pt，但 0.25 pt 在 ACS 会被判不合格。

### 2.3 分辨率与矢量优先

| 出版社 | 线稿 | 灰度/组合 | 彩色/照片 | 矢量 |
|---|---|---|---|---|
| **Nature** | 矢量必需（line art 不许栅格化） | — | ≥300 dpi（推荐/导出 ≥450 dpi） | 强要求：.ai/.eps/.pdf，禁 .jpeg/.tiff/.png |
| **Science** | ≥1200 dpi（黑白线稿） | 组合 ≥300 dpi | 300–500 dpi | 首选 vector（.ai/.pdf/.eps）；禁止 Word/PPT 转换图 |
| **Science Adv.** | ≥1200 dpi | ≥300 dpi | ≥300 dpi | 首选矢量；>600 dpi 会被降采样到 600 |
| **Cell Press** | ≥1000 dpi | 黑白 ≥500 dpi | ≥300 dpi | 建议矢量组装；TIFF/PDF 首选 |
| **Elsevier** | 1000 dpi | 组合 500 dpi | 300 dpi | 建议 EPS/TIFF |
| **Wiley** | 600 dpi | 组合 300 dpi（按图类型） | 300 dpi | PDF 首选 |
| **ACS** | 1200 dpi | 600 dpi（灰度） | 300 dpi | 数字图必须数字提交，production 不改图 |
| **IEEE** | >600 dpi | — | >300 dpi | 矢量（PS/EPS/PDF）优先 |
| **PLOS** | 300–600 dpi（统一） | — | — | EPS 偏好；TIFF 可 |
| **RSC** | 600 dpi 起（TIFF） | — | — | EPS/PDF 可但最终转 TIFF |

原文：
- Science: "the resolution of black and white line art (graphs or illustrations) must be at least 1200 dpi. Raster-based grayscale or color images... at least 300 dpi." ; "Upsampling artwork (artificially increasing file size or resolution) will not improve quality and causes production problems."
- Nature: "All photographic images must be supplied at a minimum of 300 dpi at the maximum size they can be used. Artificially increasing an image's resolution in an artwork program will not improve its quality." ; "Please do not rasterize line art or text in submitted figures and wherever possible supply editable, unflattened vector artwork."
- IEEE: "IEEE standards for non-vector graphics for color and grayscale images are >300dpi. IEEE standards for black and white line art are >600dpi." ; "IEEE recommends that you avoid sizing graphics to less than one column wide, as extreme enlargements may distort your images and result in poor reproduction."
- PLOS: "Submit figures at the desired dimensions with a resolution no greater than 300-600 dpi." ; "The quality of a low-resolution figure cannot be improved by simply increasing the resolution in graphics software."
- Cell: "for color or grayscale figures, at least 300 dpi; for black and white figures, at least 500 dpi; for line-art figures, at least 1,000 dpi at the desired print size"

---

## 3. 权威表述：为什么必须按最终尺寸生成/缩放

**Nature（最有代表性，明确点名"会被缩小"）**
> "In the production process, figures may be reduced to a smaller size due to space limitations. Authors are encouraged to submit figures at the smallest appropriate size, ensuring all fonts are between 5pt and 7pt. Nature reserves the right to make the final decision on figure size."
> —— https://research-figure-guide.nature.com/figures/building-and-exporting-figure-panels/

> "*Nature* will often reduce figures to the smallest size possible for reasons of space. Authors are encouraged to indicate the smallest possible size they think appropriate for their figures, but *Nature* reserves the right to make the final decision."
> "Authors should check (using a reducing photocopier) that, at the smallest possible size, lettering remains readable and lines are sufficiently (but not too) heavy to print clearly."
> —— https://www.nature.com/nature/for-authors/final-submission

**Elsevier（直说缩小后不可读）**
> "As a general rule, the lettering on the artwork should have a finished, printed size of 7 pt for normal text and no smaller than 6 pt for subscript and superscript characters. **Smaller lettering will yield text that is hardly legible.**"
> —— https://www.elsevier.com/about/policies-and-standards/author/artwork-and-media-instructions/artwork-sizing

**Science（会被 production 缩放 + 按比例缩放会毁像素）**
> "Science might scale figures due to production constraints."
> "Photographic images should have a resolution of 300 to 500 dots per inch (dpi) at final print size"
> —— https://www.science.org/cms/asset/67f37ac8-4d02-4625-8a05-230568cb8323/author_prep_guide_2025.pdf

**Wiley（缩小/放大都由出版社做，会掉质量）**
> "At least 80mm canvas size or 1800 pixels wide. Smaller or larger images will be modified during composition, which may reduce quality"
> —— https://authors.wiley.com/author-resources/Journal-Authors/Prepare/manuscript-preparation-guidelines.html/figure-preparation.html

**IEEE（只能缩，不能放大）**
> "It is easy for IEEE to reduce the sizes of your graphics. But, in most cases, IEEE cannot increase them without negatively impacting quality."
> —— https://journals.ieeeauthorcenter.ieee.org/create-your-ieee-journal-article/create-graphics-for-your-article/resolution-and-size/

**PLOS（低分辨率无法靠软件补救）**
> "The quality of a low-resolution figure cannot be improved by simply increasing the resolution in graphics software. To improve its resolution, re-create the figure from the beginning." / "Resolution below 300 results in blurred, jagged or pixelated published figures."
> —— https://journals.plos.org/plosone/s/figures

**Cell（明确要求按 final print size 校验）**
> "Use a vector graphics program (such as Adobe Illustrator or Inkscape) to assemble the figures and verify that at final print size, each displayed image is at least 300 pixels per inch."
> —— https://www.cell.com/information-for-authors/figure-guidelines（存档）

**小结（为什么统一到最终尺寸）**：出版社排版时会**单方面缩放**图片适配栏宽/页面，且**只会缩小、不会放大**；只要不是按最终尺寸设定，缩放比例一变，'最终印刷 pt 字号'与'dpi'就随之改变，导致文字不可读或线条消失。因此硬约束全部以"最终印刷尺寸"表述。

---

## 4. 同一 Figure 内多面板一致性要求

- **Elsevier**："Elsevier's aim is to have a uniform look for all artwork contained in a single article." / "If a collection of artwork contains more than one halftone, again make sure that there is consistency in size between similar diagrams." —— artwork-sizing
- **Nature**："Lettering should be in a sans-serif typeface, preferably Helvetica or Arial, **the same font throughout all figures in the paper**." —— final-submission；figure guide 图注示例："standard fonts used throughout the figure labels."
- **Science**："Avoid wide variation in type size within a figure." + "Font size variation within a figure can be confusing. Differences in size should be used for typographic hierarchy (**maximum of 3 sizes**)." + 自检清单："Are the font sizes consistent?" —— author_prep_guide_2025.pdf / sciadv guide ("Avoid wide variation in type size within a figure.")
- **IEEE**："Use the same font type, font size, and label style across all graphics." + "Maintain consistent spacing across all graphics." —— Proceedings guidelines
- **Cell Press**："Different panels should be labeled with capital letters"；"Limit vertical space between parts of an illustration to only what is necessary for visual clarity"；"Always embed fonts, and use only Arial fonts" —— figure-guidelines（存档）
- **Nature（面板布局）**："Figures should be laid out in a neat and space-efficient manner, minimizing white space and with panels in an alphabetical order wherever possible." —— building-and-exporting-figure-panels
- **Science（面板标签顺序/位置）**："labels... follow a logical order (left to right or top to bottom)"；"place part labels at the upper left-hand corner of each figure part" —— sciadv guide

**可落地判据**：同一 Figure 内 (a) 字体族唯一；(b) 字号层级 ≤3 档（Science）；(c) 线宽档位唯一或极少数；(d) 面板字母统一大小写与字重（Nature 小写 8pt bold / Science 大写 9–10pt bold / Cell 大写——各家不一致，需按目标刊选一种）。

---

## 5. 不要照抄的地方 / 给 figpact 的设计要点

1. **别把"单栏宽"当成唯一目标**。同一刊常有多档：Nature 89/120–136/183 mm；Cell 8.5/11.4/17.4 cm；Elsevier 30/90/140/190 mm。figpact 应支持"一刊多档"而非一刊一值。
2. **pt 与 mm 的关系必须换算，不是硬编码**。所有字号/线宽都是"最终印刷 pt"；figpact 若以画布像素/mm 工作，缩放比 = 最终印刷宽 / 画布宽，"画布 pt"≠"印刷 pt"。`[推断]`
3. **下限取交集会很保守**：字号下限主流 5–8 pt（Nature 5 / Science 6 / PLOS 8 / ACS 4.5），线宽下限 0.25–0.5 pt（ACS 最严 0.5）。用单一全局值会过保守或过宽松，应按目标刊配置。
4. **分辨率不是越高越好**：Science 会把 >600 dpi 降采样到 600；Nature/PLOS 上限 450–600 dpi；Elsevier 分 300/500/1000。线稿（line art）要求远高于照片（1000–1200 dpi vs 300 dpi），不能用一个值。
5. **矢量优先是硬要求**：Nature 直接禁 .jpeg/.tiff/.png 作为主图；Science 禁 Word/PPT 转出图；Cell 要 TIFF/PDF；PLOS 要 TIFF/EPS。figpact 若导出 PDF/SVG/EPS 矢量，天然满足大多数；但 PLOS 例外地要求 EPS/TIFF 而"不接受 LaTeX 生成的矢量 EPS"。
6. **不要照抄"最大/最小字号来自同一来源"**：Nature 的 5–7 pt 与 Science 的 6–9 pt、PLOS 8–12 pt 是不同刊各自口径，混用会自相矛盾。
7. **面板字母大小写不统一**：Nature 用小写 a,b,c；Science/Cell 用大写 A,B,C。figpact 的"面板字母"元件应可切换。
8. **Cell 原页现行 403**：引用其规范建议用存档 URL 或注明"原页不可直接访问"。当前有效宽度似为 8.5/11.4/17.4 cm（与第三方汇总之"85/174 mm"矛盾——以官方存档页为准）。

---

## 6. 未找到权威来源 / 存疑项

- **Wiley 全局最小线宽/字号**：官方 figure-preparation 页未给 pt 级最小线宽与最小字号，只给图宽 80–180 mm 与 300/600 dpi。`[推断]` Wiley 各刊在 journal-specific guidelines 里另定，需逐刊查。
- **IEEE journal 的官方最小字号**：IEEE Author Center "Resolution and Size" 页未给字号；"~9–10 pt"来自 *Proceedings of the IEEE* 专属页，不能当作所有 IEEE 期刊的硬规范。
- **Nature 面板字母大小写**：final-submission 页写小写 "a, b, c"，但 Extended Data 段与 figure guide 亦有 "a, b" 表述；未见官方明确禁止大写，需以正文页 final-submission 为准。
- **RSC 字号/线宽最小值**：官方页只给"clearly legible"、结构式 atom labels 7 pt、600 dpi；无正文最小 pt 与最小线宽。`[未找到权威来源]`
- **Science 主刊"legible after reduction"原文**：science.org 该页对抓取返回 HTTP 403，未能取得逐字原文；已用 Science 官方 2025 figure guide PDF（同社）替代，措辞不同原文见 §3。
