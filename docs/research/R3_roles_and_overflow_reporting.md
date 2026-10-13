# R3：角色化排版令牌 +「放不下要报，不自行缩」

外部调研（只读，未改仓库任何代码；写作日期 2026-10-14）。
议题：(1) 设计系统如何定义「轴标题 / 刻度 / 标注 / 图例」这类**语义角色**并集中改规格；(2) 溢出检测与报告的先例，各自是**报错让人取舍**还是**自动缩**；(3) 「不自动缩、报告需人工取舍」的工程实践与文案范本；(4) 对 figpact 的启示。

**阅读约定**
- `[事实]` = 有一手/可核来源，附 URL 与英文原话。
- `[推断]` = 我的推理，非文献直述。
- `[建议]` = 面向 figpact 的设计建议，不是文献结论。
- `[来源等级]` 标注：`一手`（规范 / 官方文档 / 源码）、`二手`（教程、论坛、扫描翻拍手册）、`搜索摘要`（本次只取到搜索引擎摘要，未逐字核读原页）。

---

## 0. 结论速览

1. **角色化 = 用「用途」命名尺度，令牌 = 把数值收敛到一处**。成熟做法（Material 3、Tailwind v4、DTCG、InDesign 段落样式）都同时具备两件东西：**稳定的角色名**（body/label/display…；段落样式名）与**可继承的默认值 + 显式覆盖记录**。命名与数值分开，覆盖必须留痕。[事实]
2. **溢出先例几乎不自动缩**。TeX 报 `Overfull \hbox`、InDesign 报「红加号 + Preflight 的 Overset text 错误 + 修复建议」、Figma 只做 clip/滚动且明确需要「内容大于框」才不报错——**报错让人取舍是主流**。真正「自动缩」的地方（SVG `textLength`、Android autosize、microtype 字体扩张、MDN 的 ResizeObserver 示例、CSSWG 正在孵化的 `text-fit`）**全部是显式 opt-in 且带上下限**。[事实]
3. **自动缩越界要付代价**：CSSWG 的 `text-fit: shrink` 到 2025-10 仍在争论 a11y（最小字号、用户对字号的最终控制权），并明确「未批准发布」。即：自动缩是一个**有争议的特性**，不是默认行为。[事实]
4. **诊断的结构在工业界已标准化**：`严重性 + 位置 + 消息 + 建议(带可机械应用程度)` 四件套，见 rustc-dev-guide、SARIF、LSP；预算式阻断见 webpack `performance.hints`。figpact 现有 `Diagnostic(rule_id, scope, object_ids, severity, measured, threshold, message)` 已经覆盖一半，缺的是**角色/令牌字段、预算来源、超出量、以及「可选取舍」列表**。[事实 + 建议]

---

## 1. 成熟设计系统的角色 / 令牌模型

### 1.1 角色（role）先行：用用途命名尺度

**Material Design 3** 的 typescale「organized into roles that describe their purpose」，命名形如 `--md-sys-typescale-<scale>-<size>-<property>`（如 `--md-sys-typescale-body-medium-size` / `-line-height` / `-weight` / `-font`），另有与尺度解耦的字族令牌 `--md-ref-typeface-brand|plain`。原文：

> "A typescale is a collection of font styles: `font-family`, `font-size`, `line-height`, and `font-weight`. They are organized into **roles** that describe their purpose."
> "Tokens follow the naming convention `--md-sys-typescale-<scale>-<size>-<property>`."
> "Tip: to change all font families across typescales, prefer setting `--md-ref-typeface-brand` and `--md-ref-typeface-plain`, which map to each typescale."
> — https://github.com/material-components/material-web/blob/main/docs/theming/typography.md `[一手]`

M3 的角色集是五类 × 三档（display/headline/title/body/label × large/medium/small = 15 baseline 样式；2025-05 起另有 15 个 emphasized 样式，合计 30）：

> "Material Design 3 (M3) Type Scale organizes typography into two synchronized sets: baseline and emphasized, each containing 15 styles (Display Large to Label Small), for a total of 30 styles."
> — https://m3.material.io/styles/typography/type-scale-tokens `[搜索摘要，页面为 JS 渲染，未逐字核读]`

**对 figpact 的关键点**：角色名是「用途」，不是「大小」。`body-medium` 改名不会因为字号从 14 变 16。而 figpact 现在把角色写进了参数名（`tick_font_pt` / `axis_font_pt` / `legend_font_pt` / `note_font_pt` / `label_font_pt` / `peak_font_pt`，见 `figpact/params.py`）——角色其实已经存在，只是**没有一张集中的角色表**。[事实（读源码）+ 推断]

### 1.2 令牌（token）：把数值收进一份可继承、可别名、可覆盖的清单

DTCG（W3C Design Tokens Community Group，2025-10-28 Final Community Group Report）定义了跨工具交换格式：

> "A (Design) Token is information associated with a human readable name, at minimum a name/value pair. For example: `color-text-primary: #000000;` `font-size-heading-level-1: 44px;` … The name may be associated with additional **Token Properties**. For example: Value, Type, Description."
> "A **Group** is a set of tokens belonging to a specific category."
> "A design token's value can be a reference to another token. The same value can have multiple names or *aliases*."
> "**Composite** (Design) Token: A design token whose value is made up of multiple, named child values… For example, a typography style might be made up of a font name, font size, line height, and color."
> — https://www.w3.org/community/reports/design-tokens/CG-FINAL-format-20251028/ §3.1–3.9 `[一手]`

以及结构规则（同一份报告 §6）：

> "An object with a **`$value`** property is a token. Thus, `$value` is a reserved word in our spec… The parent object's key is the token name."
> "Groups support root tokens using the reserved name `$root` as the token name."
> "Token paths are constructed by concatenating group names and token names with periods (`.`)."
> — 同上 `[一手]`

DTCG 还要求工具**报错而不是猜**：

> "*MUST* validate that token names do not conflict with reserved properties"（§ 实现者要求）
> — 同上 `[一手]`

`$type` 缺失时从父组继承、类型与语法不符即令牌无效：见同规范 §5（本次只经搜索摘要读到「`$type` … because it is explicitly set, inherited from a parent group, or is an alias」一句）`[搜索摘要]`。

### 1.3 承载机制：令牌如何「集中改规格」

三种承载方式，语义不同：

**(a) CSS 自定义属性**：可继承、级联，`var()` 在**使用处**替换；值是**大小写敏感**的裸 token 流，未替换前无法解释：

> "The value of a custom property can be substituted into the value of another property with the `var()` function."
> "The values of custom properties, and the values of `var()` functions substituted into custom properties, are *case-sensitive*, and must be preserved in their original author-given casing."
> "…there is no general way to know how to interpret what's inside of them (until they're substituted into a known property with `var()`). Rather than have them *partially* resolve in some cases but not others, they're left completely unresolved; they're a bare stream of CSS tokens interspersed with var() functions."
> — https://drafts.csswg.org/css-variables-1/ `[一手]`

**(b) Tailwind v4 `@theme`**：明确区分「设计令牌（会生成 utility）」与「普通 CSS 变量（不会）」：

> "Theme variables are special CSS variables defined using the `@theme` directive that influence which utility classes exist in your project."
> "Theme variables aren't *just* CSS variables — they also instruct Tailwind to create new utility classes that you can use in your HTML."
> "Defining regular CSS variables with `:root` can still be useful … when you want to define a variable that isn't meant to be connected to a utility class."
> 命名空间表：`--text-*` → `text-xl` 之类的字号 utility；`--leading-*` → `leading-tight`；`--font-*` → 字族。
> — https://tailwindcss.com/docs/theme `[一手]`

字号令牌可自带关联属性（这就是「一个角色 = 一组复合数值」）：

> "You can also set default values for related properties per size, such as line-height, letter-spacing, and font-weight, e.g.: `@theme { --text-tiny: 0.625rem; --text-tiny--line-height: 1.5; --text-tiny--letter-spacing: 0.125rem; --text-tiny--font-weight: 500; }`"
> — https://tailwindcss.com/docs/font-size `[搜索摘要]`

**(c) 印刷侧：段落样式 / 对象样式**。InDesign 的样式体系就是「角色 → 一组属性 → 可由另一角色派生 → 覆盖留痕」：样式可 `Based on`（继承）与 `Next Style`（顺序），并有专门的 `Override text styles`（覆盖）与 `Break the link between text and its style`（切断继承链接）文档页；Auto-Size 可保存进对象样式以获得一致性。

> Adobe InDesign Help 目录中明确存在：`Create and edit text styles` / `Override text styles` / `Break the link between text and its style` / `Apply sequential text styles to multiple paragraphs` / `Break the link...`
> — https://helpx.adobe.com/indesign/desktop/add-and-manage-text/add-and-manage-text-frames/change-text-frame-properties.html（帮助站导航内容）`[一手，仅目录级]`
> "Auto Size can be saved in object styles for consistency across layouts."
> — https://creativepro.com/allow-your-frames-to-resize-with-your-text/ `[二手]`

### 1.4 三点共同结构（可提炼的规律）

| 规律 | Material 3 | Tailwind v4 | DTCG | InDesign 样式 |
|---|---|---|---|---|
| 角色名独立于数值 | display/body/label | `--text-*` 名可自定义 | 令牌名 + `$description` | 样式名 |
| 默认值成组继承 | `--md-ref-typeface-*` 映射到全部 typescale | `@theme` 覆盖命名空间默认 | group `$type`/`$extends` | Based on / 对象样式 |
| 覆盖必须显式 | 覆盖 CSS 变量 | 重定义 `@theme` 变量 | 别名 vs 新令牌 | Override 面板 / 断链 |

`[事实（逐项有 URL）+ 推断（这张对照表的形式是我归纳的）]`

### 1.5 不要照抄的地方

- **别把 web 的「档位」当断点搬进印刷图**。M3/Tailwind 的 15 档 scale 服务于视口变化；figpact 的目标是**最终拼版尺寸固定**的一张图，预算来自「最终毫米 / 磅」（见 §4.2），不是响应式断点。[建议]
- **别把 utility 名当角色名**。`--text-sm` 是尺度名，`body-medium` 才是用途名；figpact 的角色应写成 `axis.tick` / `axis.title` / `legend` / `annotation.peak` 这类**用途路径**。[建议]
- **别引入 DTCG 全规范**。figpact 只需要它三条规则：令牌＝有名有值有类型、组内可继承默认、别名≠新令牌。不需要 `$root`、`$extends`、schema 校验那一整套。[建议]
- **InDesign Auto-Size 的真实教训是「它会反过来制造溢出」**：社区里长期存在 Auto-Size 框架在被缩放 / 从 CC Libraries 置入后产生 overset 的缺陷报告（`https://indesign.uservoice.com/forums/601180-adobe-indesign-bugs/suggestions/47465690-auto-size-frames-create-overset-text-when-scaled-o` `[二手]`）。即：**自动适配机制本身需要被验收**，否则它只是把问题挪到下一层。[事实（该缺陷报告存在）+ 推断]

---

## 2. 溢出检测与报告的先例

### 2.1 TeX：报错让人取舍的原始范本

**哲学**（一手 FAQ，极其直白）：

> "If you're getting an undesired 'overfull box', what has happened is that TeX has given up: the parameters you gave it don't allow it to produce a result that *doesn't* overfill. In this circumstance, **Knuth decided the best thing to do was to produce a warning, and to allow the user to solve the problem**. (The alternative, silently to go beyond the envelope of 'good taste' defined for this run of TeX, would be distasteful to any discerning typographer.)"
> — https://texfaq.org/FAQ-overfull `[一手]`

**诊断形态**（含量值与位置）：

> "Overfull \hbox (<value>pt too wide) … at line(s) …"
> "**Overfull boxes** have too much content to fit the (box) dimensions allocated to contain it and TeX cannot 'squeeze it' into the space provided. The TeX engine reports the amount (`<value>`), in points, by which your content exceeds the available space"
> "these messages are not errors … They are *warnings* or, more correctly, 'diagnostic messages'"
> — https://www.overleaf.com/learn/how-to/Understanding_underfull_and_overfull_box_warnings `[一手（Overleaf 官方教学）]`

**死区（deadband）与阈值是独立可调参数**，且默认非零：

> "`\hfuzz` … is **the overrun allowed before overfull hboxes are reported**"（默认 `0.1pt`）
> "`\hbadness` … is the badness above which bad hboxes are reported"（默认 `1000`）
> "`\overfullrule` … is **the width of the rule appended to an overfull box**"
> Overfull 判定表：`overfull ⇔ glue shrink ∧ (\hbadness < 100 ∨ excess width > \hfuzz)`
> — https://www.tug.org/utilities/plain/cseq.html（David Bausum, *TeX Reference Manual* HTML 版，逐条对应 TeXbook 页号 272/274/302）`[一手]`

**可视标记默认关闭、draft 才开**（LaTeX2e 类文件源码）：

> `\DeclareOption{draft}{\setlength\overfullrule{5pt}}`
> `\DeclareOption{final}{\setlength\overfullrule{0pt}}`
> — https://www.tug.org/texlive/Contents/live/texmf-dist/tex/latex/base/article.cls `[一手]`

**「重排」与「缩字」是两条不同路径**：`\tolerance` / `\emergencystretch` 允许 TeX 更松/更紧地排，不去动字号；真正的**字体缩放是独立扩展**，且**有硬上限与显式开关**：

> "Font expansion will be applied in discrete steps. For example, if `step` is set to 4 (which it is by default), pdfTEX will try up to eleven different expansion levels of a font (from −20 to +20)."
> "`\usepackage[stretch=20,shrink=20]{microtype}`"（宏内默认值：`\def\MT@stretch@default{20}` `\def\MT@shrink@default{20}` `\def\MT@step@default{4}`）
> "**Don't use too large a value for expansion.** … Expanding the fonts by more than 2%, i. e., setting a stretch limit of more than 20, **should be justified by a typographically trained eye**."
> 运行期可关：`\microtypesetup{expansion=false}`
> — http://www.thamnos.de/stuff/latex/microtype.pdf `[一手]`

**归类：报错 + 可视标记；自动缩只作为有界、可关的经验性扩展。**

### 2.2 InDesign：溢出是「错误级别」的生产问题，且带修复建议

**实时指示器**（无框可放时）：

> "Each frame has an in port and an out port… a **red plus sign in an out port** icon indicates overset text with no frame left to hold it."
> "Any text that previously appeared in the frames becomes overset text (**no text is deleted**)."
> — https://helpx.adobe.com/indesign/desktop/add-and-manage-text/add-and-import-text/thread-text-frames.html `[一手]`

**Preflight 把它变成可枚举、可分级、带建议的诊断**：

> "live Preflight alerts you to problems such as missing fonts, modified links, **overset text**, and low-resolution images through a status indicator at the bottom of your document window."
> "the Preflight panel lists detected issues by category, such as Links, Text, or Color, and shows **details and fix suggestions** for each error… lets you jump directly to affected content using page numbers."
> — https://helpx.adobe.com/indesign/desktop/print/preflight/configure-and-use-the-preflight-panel.html `[一手]`

默认 Basic profile 即包含 overset text 检查（"The Basic profile … flags missing/modified links, overset text, and missing fonts"）`[二手：Adobe 用户手册扫描翻拍页 https://www.manualsdir.com/manuals/753855/adobe-indesign.html?page=714]`。

**「自动」的是框，不是字**：Auto-Size 只在显式开启时让**文本框**随内容伸缩，选项 Off / Height only / Width only / Height and Width / Height and Width (Keep proportions)，并可设最小高宽约束；**InDesign 没有任何把字号自动调小以塞进框的功能**。[事实（选项集）+ 推断（末句为对「未找到缩字功能」的表述）]

> "Object > Text Frame Options > Auto-size … Off / Height only / Width only / Height and Width / Height and Width (Keep proportions) … You can set constraints for minimum height and width"
> — https://www.manualsdir.com/manuals/753855/adobe-indesign.html?page=265（Adobe InDesign 用户手册翻拍）`[二手]`
> — 佐证：https://creativepro.com/allow-your-frames-to-resize-with-your-text/ `[二手]`

**归类：报错（错误级别 + 可定位 + 修复建议）；「自动」只作用于容器几何，且需 opt-in。**

### 2.3 Figma：默认静默处理，几乎不报告溢出

- 「框比内容小」时 Figma 的手段是 **clip / 滚动 / 换行/盖住**，不是缩小：`Clip content`「hide any content that extends beyond the bounds of a frame」；`No scrolling` 时「Content that extends beyond the bounds of the frame will not be viewable」。— https://help.figma.com/hc/en-us/articles/360039818734-Prototype-scroll-and-overflow-behavior `[一手]`
- **唯一显式告警是「你开了滚动但没有溢出」**：`"For scrolling to work on this frame, the content needs to be bigger than the frame"`（同上）`[一手]`
- Auto layout 的适配手段是**几何**（hug contents / fill container / fixed / min-max）与**换行**（wrap 把子项移到新行列），仍然不是缩字；且「Hug contents」会被子项 fill 行为取消：

> "If any child objects within an auto layout frame are set to **Fill container**, the parent frame will no longer hug contents and become **Fixed** for the axis."
> — https://help.figma.com/hc/en-us/articles/360040451373-Guide-to-auto-layout `[一手]`

- 文本溢出用**截断 + 省略号**这种「静默降级」表达，而不是报错：

> "Truncate text hides text that overflows the bounding box. An ellipsis `...` is added at the end of the text to indicate hidden overflow text."
> — https://help.figma.com/hc/en-us/articles/360039956634-Explore-text-properties `[一手（grep 命中原文行）]`

**归类：静默/降级为主，溢出本身不报错 → figpact 不应把 Figma 当行为范本，只把它当「不要这样做」的对照。**

### 2.4 CSS / 浏览器：三种截然不同的答案

**(a) `text-overflow` 是「信号」不是「修复」**：

> "The `text-overflow` property sets how hidden overflow content is **signaled to users**."
> "The `text-overflow` property doesn't force an overflow to occur. To make text overflow its container, you have to set other CSS properties: `overflow` and `white-space`."
> — https://developer.mozilla.org/en-US/docs/Web/CSS/text-overflow `[一手]`

**(b) 布局层面天然是「让框长大」**：flex/grid 项目的自动最小尺寸取 `min-content`，即内容不肯再窄时**容器被撑开**，而不是文字被缩小：

> "For flex items and grid items, the minimum width value is either the specified suggested size… otherwise, the `min-content` size is used."
> — https://developer.mozilla.org/en-US/docs/Web/CSS/min-width `[一手]`

**(c) 一旦进入 JS/新提案，就立刻出现「自动缩」及其代价**：

- MDN 的 `ResizeObserver` 官方示例就是自动缩字，且**必须自己加地板**（`Math.max(1.5, …)`），否则可以缩到不可读：
  > `h1Elem.style.fontSize = \`${Math.max(1.5, contentBoxSize.inlineSize / 200)}rem\`;`
  > — https://developer.mozilla.org/en-US/docs/Web/API/ResizeObserver `[一手]`
- 同页还给出了这类反馈环固有的失败信号：`"ResizeObserver loop completed with undelivered notifications."`，并强调 "this only prevents user-agent lockup, not the infinite loop itself" —— **「观察→改尺寸→再触发观察」是回路，不是解算**。`[一手]`
- 容器查询単位（`cqw/cqi`）是「按容器改字号」的正统做法：
  > "`cqi`: 1% of a query container's inline size" + 示例 `font-size: max(1.5em, 1.23em + 2cqi);`
  > — https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_containment/Container_queries `[一手]`
- 断行层面的自动改进**不动字号**：`text-wrap: balance|pretty`（"Text is wrapped in a way that best balances the number of characters on each line"）。— https://developer.mozilla.org/en-US/docs/Web/CSS/text-wrap `[一手]`
- **没有标准的「是否被裁切」API**：`Element.checkVisibility()` 的当前选项只有 `contentVisibilityAuto` / `opacityProperty` / `visibilityProperty`（+ 两个历史别名），**不含 overflow/clip 检查**。— https://developer.mozilla.org/en-US/docs/Web/API/Element/checkVisibility `[一手]`
  [推断] 这也是为什么 web 上「溢出检测」普遍靠 `scrollWidth > clientWidth` 这类测量咒语，而没有权威判定；`ResizeObserver` 又恰好可见说明这类测量极易写成回路。

**归类：混合——布局层默认「让框长大」，样式层默认「显示省略号」，真正缩字要 JS/新提案，且都必须自己补地板。**

### 2.5 SVG `textLength`：自动缩的教科书案例（注意默认只动间距）

> "The `textLength` attribute… lets you specify the width of the space into which the text will draw. The user agent will ensure that the text does not extend farther than that distance, using the method or methods specified by the `lengthAdjust` attribute. **By default, only the spacing between characters is adjusted**, but the glyph size can also be adjusted if you change `lengthAdjust`."
> — https://developer.mozilla.org/en-US/docs/Web/SVG/Attribute/textLength `[一手]`

> `lengthAdjust` = `spacing | spacingAndGlyphs`（默认 `spacing`）；示例直接命名 "Shrunk using spacing only." / "Shrunk using spacing and glyphs."
> — https://developer.mozilla.org/en-US/docs/Web/SVG/Attribute/lengthAdjust `[一手]`

含义：**「缩字」在 SVG 里是一个显式开关的降级档，默认档只调字距。** `[事实+推断]`

### 2.6 移动端：自动缩，但强制带上下限

Android 自 API 26 起 `TextView` 可 autosize，且**必须**声明区间/步长/预设集合之一：

> "The default dimensions for uniform scaling are `minTextSize = 12sp`, `maxTextSize = 112sp`, and `granularity = 1px.`"
> "You can define a range of minimum and maximum text sizes and a dimension that specifies the size of each step."
> Preset sizes 方式：`app:autoSizePresetSizes="@array/autosize_text_sizes"`（数组中只能取既定档位）
> — https://developer.android.com/develop/ui/views/text-and-emoji/autosizing-textview `[一手]`

`[未核读一手来源的旁证]` iOS/UIKit 的 `adjustsFontSizeToFitWidth` + `minimumScaleFactor`、SwiftUI `minimumScaleFactor` 是同类「有界自动缩」设计，本次未取到 Apple 官方页面原文，仅作旁证列出，不作为论据。

### 2.7 正在标准化中的 `text-fit`：连标准组织都还在争

Google Blink 的 explainer（明确未发布）：

> "This proposal is an early design sketch by Blink Layout Team in Google… **It has not been approved to ship in Chrome.**"
> `text-fit: <fit-type> <fit-target>? <scale-limit>?`；`<fit-type> = none | grow | shrink`
> "`<scale-limit> = <percentage>` — The maximum scaling factor for `grow`, or **the minimum scaling factor for `shrink`**."
> "This feature should not affect the container's intrinsic size."
> — https://github.com/explainers-by-googlers/css-fit-text `[一手]`

CSSWG 讨论（2025）把反对意见写在提案旁边（issue #12887 正文与会议记录）：

> "If we want to fix the accessibility issue and introduce the default limit (https://github.com/w3c/csswg-drafts/issues/12886), having two properties with their separate limits won't work…"
> `<miriam> I worry about shrink option, if it is able to continue shrinking, would prefer if there was a baseline…`
> `<emilio> … to ask how would shrinking interact with stuff like minimum-font-size and other accessibility settings`
> "The more author control we offer here, the more likely user-hostile the feature becomes – even if we put in some wcag-based boundaries… **as a user, I want final control over font-sizing**."
> — https://github.com/w3c/csswg-drafts/issues/12887 `[一手]`
> 相关：`#2528`（Fit-to-width 原始议题）、`#12886`（a11y 限制）、`#12888`（可缩放 vs 静态对象）。`[一手（编号在正文中互引）]`
> 注意：MDN 目前**没有** `text-fit` 页面（本次访问 https://developer.mozilla.org/en-US/docs/Web/CSS/text-fit 返回 HTTP 404）；不要引用不存在的 MDN 条目。`[事实]`

配套的可访问性底线（WCAG 2.2）：文本必须能被放大到 200% 而不丢内容，裁切/截断属于失败模式：

> SC 1.4.4: "Except for captions and images of text, text can be resized without assistive technology up to 200 percent **without loss of content or functionality**."
> 失败技术 F69: "Failure of Success Criterion 1.4.4 when resizing visually rendered text up to 200 percent causes the text, image or controls to be **clipped, truncated or obscured**"
> — https://www.w3.org/WAI/WCAG22/Understanding/resize-text.html `[一手]`

### 2.8 汇总表：谁报错、谁自动缩

| 系统 | 溢出时默认行为 | 是否显式报错 | 若自动缩：有界吗 / 可关吗 |
|---|---|---|---|
| TeX / LaTeX | 照排，标记/警告 | **是**（`Overfull \hbox (…)`，可选黑条 `\overfullrule`） | 不缩字；microtype 扩张 ±2% 上限（stretch 20），可 `expansion=false` |
| InDesign | 保留 overset，红加号 | **是**（Preflight 错误 + fix suggestion） | 不缩字；Auto-Size 只动框、需 opt-in、可存对象样式 |
| Figma | clip / 截断省略号 / 换行 | 仅「开了滚动却没溢出」报错 | 不缩字 |
| CSS 布局 | 容器撑开（min-content 地板） | 否 | 不缩字 |
| CSS 样式 | 省略号「信号」 | 否 | 不缩字 |
| SVG | 按 `textLength` 适配 | 否 | **缩**：默认只调间距，缩字形需 `spacingAndGlyphs` |
| Android TextView | 自动缩放 | 否 | 缩，但 min/max/step/preset 必填 |
| CSSWG `text-fit` | 未发布 | 未定 | 缩，但 `<scale-limit>` 必配、a11y 争议未决 |
| WCAG 2.2 | —— | —— | 放大 200% 时裁切/截断 = 失败 |

---

## 3. 「不自动缩、报告需人工取舍」的工程实践与文案范本

### 3.1 四件套：严重性 / 位置 / 消息 / 建议 —— rustc 的成文规则

**结构**（rustc-dev-guide 的诊断示例）：

> "The main parts of a diagnostic error are the following: **Level** (`error`, `warning`, etc.)… **Code** (for example, for "mismatched types", it is `E0308`)… **Message**… **Diagnostic window**: The path, line number and column of the beginning of the primary span. The users' affected code and its surroundings. Primary and secondary spans… **Sub-diagnostics**."
> — https://rustc-dev-guide.rust-lang.org/diagnostics.html `[一手]`

**严重性语义**（同一页）：

> "`error`: … a problem that makes it unable to compile the program…"
> "`warning`: … something odd about a program. **Care should be taken when adding warnings to avoid warning fatigue**, and avoid false-positives…"
> "`help`: … to give additional information to the user about how to solve their problem… **The error or warning portion should *not* suggest how to fix the problem, only the "help" sub-diagnostic should.**"
> "`note`: … more context and identify additional circumstances and parts of the code that caused the warning or error."（并明确 `help` vs `note` 的分工）
> — 同上 `[一手]`

**建议必须标注「能不能机械应用」**——这是「人工取舍」的机器可读表达：

> "Not all suggestions should be applied mechanically; they have a degree of confidence in the suggested code, from high (`Applicability::MachineApplicable`) to low (`Applicability::MaybeIncorrect`). **Be conservative when choosing the level.**"
> 取值：`MachineApplicable`（可机械应用）/ `HasPlaceholders`（含占位符）/ `MaybeIncorrect`（可能不对）/ `Unspecified`
> — 同上 `[一手]`

**文案与格式细则**（同页 Style Guide，可直接当 lint 规则）：
> "Error messages should be succinct." … "Errors should document the span of code where they occur." … "**Try not to emit multiple error messages for the same error.** This may require detecting duplicates." … "When emitting a message with span, try to reduce the span to the smallest amount possible that still signifies the issue." … "`Error`, `Warning`, `Note`, and `Help` messages start with a lowercase letter and do not end with punctuation." … "Suggestions should not be a question. In particular, language like 'did you mean' should be avoided." `[一手]`

### 3.2 机器可读的标准化：SARIF 与 LSP

**SARIF 2.1.0（OASIS）**：一条结果 = 规则 id + 严重性 + 位置 + 可选修复 + 自定义属性：

> "A result object **MAY** contain a property named `level` whose value is one of a fixed set of strings that specify the severity level of the result. If present, the `level` property **SHALL** have one of the following values… `"warning"`, `"error"`, `"note"`, `"none"`（含义逐条给出）"
> "A result object **MAY** contain a property named `fixes` whose value is an array of zero or more unique fix objects"
> "3.49.14 `defaultConfiguration`: … A reportingDescriptor object MAY contain a property named defaultConfiguration whose value is a reportingConfiguration object（同一规则可有默认级别，可在 invocation 层被 `configurationOverride` 覆盖）"
> — https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html（§3.27.9/3.27.10/3.27.30/3.49.14/3.51）`[一手]`

**LSP**：`Diagnostic` 与 `CodeAction` 就是「诊断 + 取舍方案」的工业标准形状（取自官方 metaModel，等价于规范正文）：

```jsonc
// Diagnostic
{ "range": Range, "severity"?: DiagnosticSeverity, "code"?: integer|string,
  "source": string, "message": string, "relatedInformation"?: [...] }
// DiagnosticSeverity: Error = 1, Warning = 2, Information = 3, Hint = 4
// CodeAction: { "title", "kind"?, "diagnostics"?, "isPreferred"?: boolean, ... }
```
> "The diagnostic's severity. Can be omitted. If omitted it is up to the client to interpret diagnostics as error, warning, info or hint."
> "Whether code action supports the `isPreferred` property."（`isPreferredSupport`，@since 3.15.0）
> — https://raw.githubusercontent.com/microsoft/language-server-protocol/gh-pages/_specifications/lsp/3.17/metaModel/metaModel.json（`Diagnostic` / `DiagnosticSeverity` / `CodeAction.isPreferred` / `CodeActionContext.diagnostics`）`[一手]`

**要点**：`isPreferred` 表达「多个候选里默认推荐哪个」，但**是否应用仍由客户端/人决定**；`Diagnostic.code` 与 `source` 让同一规则可被稳定识别与豁免。[事实 + 推断]

### 3.3 预算式阻断：默认警告、可升级为错误

**webpack**：

> "`performance.hints`: `'error' | 'warning' | 'stats' | false` — Turns hints on/off. **In addition, tells webpack to throw either an error or a warning when hints are found.**"
> 默认值按 mode：`production` → `'warning'`；`development` / `none` → `false`
> "`performance.maxAssetSize`: `number = 250000`"；"`performance.maxEntrypointSize`: `number = 250000`"
> — https://webpack.js.org/configuration/performance/ `[一手]`

**Vite**：只有阈值 + 警告，不改默认行为：

> "`build.chunkSizeWarningLimit` — Type: `number` — Default: `500`"
> — https://raw.githubusercontent.com/vitejs/vite/main/docs/config/build-options.md（= https://vite.dev/config/build-options）`[一手（源码内文档）]`

`[推断]` 两者共同点：**预算不达标默认不阻断、但可配置为阻断（`hints: 'error'`）**；把「警告→错误」的升级交给项目策略，而不是工具替项目决定。

### 3.4 文案范本（可当模板）

**模板（推荐，事实来自 §3.1/§3.2 的结构）**
```
<规则 id / 严重性>        TEXT_OVERFLOW_ROLE  [blocking]
位置                      scope=main; role=axis.tick; gid=axes.main.ticklabels; 矩形 …
测得 vs 预算              measured 42.30 mm > budget 38.00 mm（excess 4.30 mm；deadband 0.05 mm）
消息（陈述事实，不指摘）   刻度标签宽度超出该角色预算；未自动缩小字号
可选取舍（不自动选）       A) 改数字格式（applicability: machine-applicable 需作者确认）
                        B) 缩短面板标签文本（applicability: needs-author-choice）
                        C) 重排 panel label 区（applicability: needs-author-choice）
                        D) 允许该角色有界缩放到 5.2 pt（applicability: maybe-incorrect；不得低于 5.0 pt 地板）
```

**负面范本（明确不要写）**——直接违反 rustc Style Guide：
- `刻度字号太大了吧？要不要我帮你改小一点？`（疑问句 + “did you mean” 式措辞）`[一手反面]`
- `This figure has issues.`（无位置、无量值、无建议）`[一手反面]`
- 同一缺陷按每个刻度各报一条（违反 "Try not to emit multiple error messages for the same error"）`[一手反面]`
- 报告里写「已自动把字号从 6.0 pt 调到 5.2 pt 以保证通过」——静默改字 + 把 token 与渲染值混为一谈（§2.7 的 a11y 争议点正是这个）`[推断]`

### 3.5 不要照抄的地方

- **编译器的 `file:line:col` 不适合图**：图的位置是**毫米矩形 + 对象 id + 角色**。rustc 的 span 概念要换成「边界 id + 测得矩形」。[建议]
- **`warning` 放行会累积警告疲劳**（rustc 明确提醒 "warning fatigue"）：图的验收语义应让**溢出是 blocking**、只让「余量」类诊断留 warning。[事实+建议]
- **不要自动应用 SARIF 式的 `fixes`**：SARIF fix 是「对 artifact 的替换」，而图里的取舍常涉及改文本/改布局/改规格三类不同成本的动作；应保留候选并标 applicability，由作者选（对应 LSP `isPreferred` 而非直接 apply）。[建议]

---

## 4. 给 figpact 的启示

### 4.1 建一张「角色 → 令牌 → 承载参数」表（把隐式角色显式化）

现状（读源码，事实）：`figpact/params.py` 已经把这几类字号暴露为 YAML 参数：`tick_font_pt`（刻度数字）、`legend_font_pt`（图例）、`axis_font_pt`（轴标题）、`note_font_pt`（截顶标记 / 小注说明）、`label_font_pt`（官能团标注）、`peak_font_pt`（峰标注）；测量侧 `scene.py` 给每个节点带 `font_size_pt`，`inventory.py` 也能取 `get_fontsize()`。**角色事实上存在，但没有一张表说「谁属于哪个角色、该角色的预算是多少、来自哪条规格」。**

`[建议]` 落地形态（借 M3 的命名 + DTCG 的组继承，但保持最小）：

| 角色（用途路径） | 令牌 | 现承载参数 | 预算来源 |
|---|---|---|---|
| `axis.title` | `--fp-text-axis-title-size` | `axis_font_pt` | 期刊最终尺寸最小/最大字号 + 面板标签区 |
| `axis.tick` | `--fp-text-axis-tick-size` | `tick_font_pt` | 同上 |
| `legend` | `--fp-text-legend-size` | `legend_font_pt` | 同上 |
| `annotation.peak` | `--fp-text-annotation-size` | `peak_font_pt` | 同上 |
| `annotation.note` / `annotation.break` | 同上（组内默认继承） | `note_font_pt` | 同上 |
| `panel.label` | `--fp-text-panel-label-size` | 目前常硬编码在绘图层 | 期刊规定（见 4.2） |

三条硬约束（对应 §1）：**角色名不随 scope/输出格式变**；**数值集中一处、可组内继承默认**；**role → 物理对象必须唯一解析**（多个同样合法的候选就拒绝，与现有「跨 scope 绑定…存在多个同样合法映射时拒绝」同一原则）。

### 4.2 Final-size 预算来自「最终拼版规格」，不是「当前画布」

- 期刊把预算写死在**最终尺寸**上：Nature "Separate panels in multi-part figures should each be labelled with **8 pt bold**, upright (not italic) a, b, c. **Maximum text size for all other text should be 7 pt; minimum text size should be 5 pt.**"；线宽 "**between 0.25 and 1 pt at the final size**（lines thinner than 0.25 pt may vanish in print）"；单栏 89 mm / 双栏 183 mm；并明确 "Nature will often reduce figures to the smallest size possible… **reserves the right to make the final decision**"，要求作者用缩印机自检 "at the smallest possible size, lettering remains readable"。— https://www.nature.com/nature/for-authors/final-submission `[一手]`
- figpact 现有实现里已经有**同一个 5 pt 地板**：`qa.py` 的 `check_glyph_floor(min_pt=5.0, shrink=0.7)`（上下标按下标收缩率折算后不得跌破地板）与 `audit_pdf(path, min_pt=5.0)`（从导出 PDF 的字形真实尺寸终审）。`[事实（读源码）]`

`[建议]` 把「5.0 pt」从一个默认参数值，升级为**角色表里的显式预算字段 + 来源引用**（"Nature 2026 final submission: minimum text size 5 pt"），这样报告能说清「预算是谁定的」。

### 4.3 报告对象应包含哪些字段（在现有 `Diagnostic` 上扩展）

现状（读源码，事实）：`figpact/qa.py` 的 `Diagnostic(rule_id, scope, object_ids, severity, measured, threshold, message)`，`severity ∈ {blocking, warning, unknown}`，并且 **`diagnostic_key = (rule_id, scope, sorted(object_ids))`——数值刻意不进身份**；无法识别的问题进 `UNCLASSIFIED` 并保留完整原文，不允许被豁免。溢出量测现有写法：`overflow = max(0.0, frame.x0-bb.x0, frame.y0-bb.y0, bb.x1-frame.x1, bb.y1-frame.y1) * mm_per_px`，且仅当 `overflow > 0.05` 才报（0.05 mm 死区）。

`[建议]` 溢出报告的字段（★ = 相对现状新增）：

| 字段 | 含义 | 依据 |
|---|---|---|
| `rule_id` ★（如 `TEXT_OVERFLOW_BOUNDARY` / `TEXT_OVERFLOW_ROLE_BUDGET`） | 稳定规则标识，可豁免、可回归对比 | rustc 错误码 / SARIF `ruleId` | 
| `severity`（`blocking`/`warning`） | 溢出=blocking，余量=warning | rustc 的 warning fatigue；figpact 现有两档 |
| `scope` / `object_ids` | 位置（对象而非行列） | LSP `range` 的位置语义 + figpact 现有身份 |
| `role` ★ / `token` ★ / `token_source` ★ | 哪个语义角色、声明值多少、来自哪个参数路径 | M3/DTCG 的角色-令牌模型 |
| `boundary` ★（id + 定义式） | 与谁比：画布 / 坐标框 / panel label 区 / 兄弟对象 | CONTEXT.md 的 Boundary 语义 |
| `measured`（mm 或 pt，含单位） | 实测 | TeX 报"too wide"的确切量 |
| `budget` ★ 与 `budget_source` ★ | 预算值与来源（期刊规格 / 角色表） | webpack/Vite 的 maxAssetSize / chunkSizeWarningLimit |
| `excess = measured − budget` ★ | 超出量（可为负=余量） | CONTEXT.md 的 Overflow / Boundary Margin 定义 |
| `deadband` ★ | 死区（本次用 0.05 mm；TeX 默认 `\hfuzz=0.1pt`） | TeX `\hfuzz` / `\hbadness` |
| `declared` vs `rendered` ★（若发生任何缩放） | 声明字号 ≠ 渲染字号时必须双列 | SVG `textLength` 默认只调间距；WCAG 1.4.4 |
| `resolutions[]`（每项 `{id, description, applicability, cost}`）★ | 可选取舍，**不自动选** | rustc `Applicability` / SARIF `fixes` / LSP `CodeAction.isPreferred` |
| `preferred` ★（可选） | 多个候选中的推荐项（仍由人确认） | LSP `isPreferred` |

`[建议]` `applicability` 取值直接借 rustc 四级：`machine-applicable`（如把刻度数字改成科学计数法）/ `needs-author-choice`（改文本、重排）/ `maybe-incorrect`（有界缩字）/ `unavailable`（必须改最终规格）。

### 4.4 「不自行缩」的可测规则（可作为验收项）

`[建议]`，每条都能写成断言：

- **R1 只有显式 opt-in 才允许改字号。** 依据：InDesign Auto-Size 是 `Object > Text Frame Options > Auto-size` 的显式设置；microtype 的 `expansion` 是可关的包选项（`\microtypesetup{expansion=false}`）；Android autosize 必须显式声明 `autoSizeTextType`。`[一手]`
- **R2 允许有界缩放时必须同时给下限与记录。** 依据：SVG 的 `scale-limit` 类比（`<fit-type>` 与 `<scale-limit>` 成对出现）、Android min/max/step、microtype "more than 2% should be justified by a typographically trained eye"、MDN ResizeObserver 示例的 `Math.max` 地板。figpact 已有 5.0 pt 地板可直接复用。`[一手 + 建议]`
- **R3 溢出是 blocking，余量不是。** 与 CONTEXT.md 已定义的一致：`Overflow`（越过边界，零则未越界）vs `Boundary Margin`（剩余空间）——"A margin is not existing overflow"。`[事实（仓库既有语言）+ 建议]`
- **R4 报告必须给出取舍候选，但不得替作者选。** 依据：rustc "The error or warning portion should *not* suggest how to fix the problem"（建议只放 `help`）+ `Applicability` 的保守标注策略；LSP `isPreferredSupport` 是能力协商，不是自动应用。`[一手 + 建议]`
- **R5 死区与预算是两个字段。** TeX 把 `\hfuzz`（报告门限）与 `\hbadness`（质量门限）分开；figpact 现在把 0.05 mm 混在比较表达式里，应显式化为 `deadband`。`[一手 + 建议]`
- **R6 一旦报告里出现「自动缩」，必须同时给出 `declared` 与 `rendered` 两个值，且缩到地板以下要单独 blocking。** 依据：WCAG 1.4.4 的 F69（放大时被裁/截断即失败）、CSSWG 的 a11y 争议主线。`[一手 + 建议]`
- **R7 同一缺陷只报一条，位置取最小充分范围。** 依据：rustc "Try not to emit multiple error messages for the same error"、"reduce the span to the smallest amount possible"。`[一手]`（figpact 现有 `diagnostic_key` 已按 `(rule_id, scope, object_ids)` 去重，方向一致。）

### 4.5 报告文案（中英各一，可直接抄）

中文：
```
[TEXT_OVERFLOW_ROLE · blocking] scope=main role=axis.tick token=tick_font_pt=6.0pt
对象 axes.main.ticklabels 实测宽度 42.30 mm，预算 38.00 mm（来源：panel label 区宽度），超出 4.30 mm（死区 0.05 mm）。
未自动缩小字号（declared 6.0 pt = rendered 6.0 pt）。
可选取舍：
  A) 刻度数字改科学计数法 → machine-applicable（需确认）
  B) 缩短 panel label 文本 → needs-author-choice
  C) 重排 panel label 区（改最终版式） → needs-author-choice
  D) 允许该角色有界缩放至 5.20 pt → maybe-incorrect（不得低于 5.00 pt 地板）
```
英文（按 rustc 风格：陈述句、不加句号、可以更短）：
```
error: axis.tick text exceeds its width budget by 4.30 mm (42.30 mm measured, 38.00 mm budget)
  --> scope=main, gid=axes.main.ticklabels
  = note: font size unchanged (declared 6.0 pt, rendered 6.0 pt)
  = help: 4 options available (scientific notation, shorten label, re-layout, bounded shrink to 5.20 pt)
```
（末行 `help` 只给「有选项」，具体清单进结构化字段——遵循 "only the 'help' sub-diagnostic [suggests]" 的原则）`[建议]`

### 4.6 反模式清单（看到就该拒）

1. **静默缩字**：字号在渲染时被改，报告里只出现渲染值或只出现声明值（违背 §2.7 的 declared/rendered 区分与 WCAG F69 的失败定义）。
2. **把余量当溢出**：把「还剩 1.2 mm」报成溢出（CONTEXT.md 已明令 "A margin is not existing overflow"）。
3. **自动把警告降级**：为了过 QA 把 blocking 调成 warning（等同 webpack 把 `hints:'error'` 改成 `false` 来「修好」超预算）。
4. **只报「有问题」不给可选项**：违反 rustc 的 `help`/`note` 分工。
5. **同一缺陷逐对象刷屏**：违反 "Try not to emit multiple error messages for the same error"。
6. **在无处可放时偷偷改文本**（如把长标签截断成省略号）——Figma 的 `Truncate text` 就是这么做的，**这是「静默数据降级」的教科书案例**，figpact 的科学文本不应如此。

---

## 5. 本报告未核实的与已知缺口

- `m3.material.io`（type scale / applying type 页）是 JS 渲染，本次只取到搜索摘要；「五角色 × 三档 = 15 样式 + 15 emphasized」以摘要为准。替代一手来源是 `material-web` 仓库文档（已核读）与 Android/Compose 参考页（搜索摘要）。
- InDesign 的 Auto-Size 选项集：现行 helpx 页面未包含该小节（已 grep 确认），引用的是 Adobe 用户手册的扫描翻拍页与第三方教程，标为 `[二手]`。
- iOS `minimumScaleFactor` / `adjustsFontSizeToFitWidth`：未取到 Apple 官方原文，本报告只作旁证列出。
- `text-fit` 的 CSSWG 三次议题（#12886/#12887/#12888）中，只有 #12887 的正文/会议记录被核读；另外两条以互引存在为依据。
- DTCG `$type/$value` 的正文章节（§4/§5）只核读到 §6 的结构规则与 §3 术语；`$type` 继承细节来自搜索摘要。
- 未找到权威来源的：任何**「自动缩字」在图出版流水线中被标准化为默认行为**的证据。反过来，所有一手来源（TeX/InDesign/Figma/SVG/Android/CSSWG/WCAG）都支持「显式、有界、可关、且要报告」。

## 6. 来源清单

| 主题 | URL | 等级 |
|---|---|---|
| TeX 溢出哲学 | https://texfaq.org/FAQ-overfull | 一手 |
| TeX 参数定义（hfuzz/hbadness/overfullrule/overfull 判定表） | https://www.tug.org/utilities/plain/cseq.html | 一手 |
| LaTeX2e `\overfullrule` (draft/final) | https://www.tug.org/texlive/Contents/live/texmf-dist/tex/latex/base/article.cls | 一手 |
| Overleaf 溢出警告教学 | https://www.overleaf.com/learn/how-to/Understanding_underfull_and_overfull_box_warnings | 一手 |
| microtype（字体扩张上界 2% / 默认 stretch=20 / 可关） | http://www.thamnos.de/stuff/latex/microtype.pdf | 一手 |
| InDesign overset 指示器 | https://helpx.adobe.com/indesign/desktop/add-and-manage-text/add-and-import-text/thread-text-frames.html | 一手 |
| InDesign Preflight（overset 属错误 + 修复建议） | https://helpx.adobe.com/indesign/desktop/print/preflight/configure-and-use-the-preflight-panel.html | 一手 |
| InDesign Auto-Size 选项 | https://www.manualsdir.com/manuals/753855/adobe-indesign.html?page=265 ；https://creativepro.com/allow-your-frames-to-resize-with-your-text/ | 二手 |
| Figma Auto layout（hug/fill/fixed/min-max） | https://help.figma.com/hc/en-us/articles/360040451373-Guide-to-auto-layout | 一手 |
| Figma clip / 滚动报错 | https://help.figma.com/hc/en-us/articles/360039818734-Prototype-scroll-and-overflow-behavior | 一手 |
| Figma Truncate text | https://help.figma.com/hc/en-us/articles/360039956634-Explore-text-properties | 一手 |
| CSS `text-overflow`（信号非修复） | https://developer.mozilla.org/en-US/docs/Web/CSS/text-overflow | 一手 |
| CSS flex/grid 自动最小尺寸 | https://developer.mozilla.org/en-US/docs/Web/CSS/min-width | 一手 |
| ResizeObserver（含自动缩示例 + loop 错误） | https://developer.mozilla.org/en-US/docs/Web/API/ResizeObserver | 一手 |
| Resize Observer 规范摘要 | https://www.w3.org/TR/resize-observer/ | 一手（仅 abstract） |
| 无标准裁切检测 API（checkVisibility 选项） | https://developer.mozilla.org/en-US/docs/Web/API/Element/checkVisibility | 一手 |
| 容器查询单位 `cqi/cqw` | https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_containment/Container_queries | 一手 |
| CSS 自定义属性（var()/大小写/裸 token） | https://drafts.csswg.org/css-variables-1/ | 一手 |
| SVG `textLength` | https://developer.mozilla.org/en-US/docs/Web/SVG/Attribute/textLength | 一手 |
| SVG `lengthAdjust` | https://developer.mozilla.org/en-US/docs/Web/SVG/Attribute/lengthAdjust | 一手 |
| Android autosize（min/max/step/preset） | https://developer.android.com/develop/ui/views/text-and-emoji/autosizing-textview | 一手 |
| CSSWG `text-fit` explainer | https://github.com/explainers-by-googlers/css-fit-text | 一手 |
| CSSWG 讨论 #12887 | https://github.com/w3c/csswg-drafts/issues/12887 | 一手 |
| WCAG 2.2 SC 1.4.4 + F69 | https://www.w3.org/WAI/WCAG22/Understanding/resize-text.html | 一手 |
| rustc 诊断结构 / levels / 建议 Applicability | https://rustc-dev-guide.rust-lang.org/diagnostics.html | 一手 |
| SARIF 2.1.0（level / fixes / defaultConfiguration） | https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html | 一手 |
| LSP Diagnostic / DiagnosticSeverity / CodeAction.isPreferred | https://raw.githubusercontent.com/microsoft/language-server-protocol/gh-pages/_specifications/lsp/3.17/metaModel/metaModel.json | 一手 |
| webpack performance hints / maxAssetSize | https://webpack.js.org/configuration/performance/ | 一手 |
| Vite `chunkSizeWarningLimit`（默认 500） | https://raw.githubusercontent.com/vitejs/vite/main/docs/config/build-options.md | 一手 |
| Material 3 typescale 角色与令牌 | https://github.com/material-components/material-web/blob/main/docs/theming/typography.md | 一手 |
| Material 3 30 样式说明 | https://m3.material.io/styles/typography/type-scale-tokens | 搜索摘要 |
| Tailwind v4 theme variables | https://tailwindcss.com/docs/theme | 一手 |
| DTCG 令牌格式（令牌/组/别名/复合） | https://www.w3.org/community/reports/design-tokens/CG-FINAL-format-20251028/ | 一手 |
| Nature 最终投稿图规范（5–7 pt / 8 pt bold / 0.25–1 pt 线宽） | https://www.nature.com/nature/for-authors/final-submission | 一手 |
| figpact 现有诊断/角色/地板（仓库内） | `figpact/qa.py`（`Diagnostic`、`check_glyph_floor(min_pt=5.0)`、`check_out_of_frame` 0.05 mm）、`figpact/params.py`（`*_font_pt`）、`CONTEXT.md`（Overflow / Boundary Margin） | 仓库源码 |
