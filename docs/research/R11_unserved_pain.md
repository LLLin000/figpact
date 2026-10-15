# R11 — "真痛且未被解决"的证据

**任务**：按 `docs/G8DIFF_TASK.md` 路线 R11 执行，回答四问：(1) 期刊/编辑对图的退改或拒稿原因（官方作者指南/编辑说明/可引用的统计）；(2) 图不可复现的一手证据（图与数据脱节、"后期手动美化导致无法重跑"）；(3) 科研人员实际用什么工具、各自被公开记录的痛点；(4) 跨图一致性与整版规格目前是怎么被人手工核对的。

**调研日期**：2026-10-15。**方法**：只读外部一手来源（期刊作者指南原文 / 出版社官方 PDF / 同行评议期刊论文与编辑述评 / 工具官方文档 / 开源 issue 与仓库元数据）。全部 URL 与抓取日期在文内给出；数字尽量给**原文英文引用**。

**标记约定**：`[事实]`＝来源原文可核对（含原文英文引用）；`[实测]`＝本次在本机对公开数据的直接查询结果（GitHub API / issue 列表，给查询时间）；`[推断]`＝我的判断，非原文；`未找到`＝本轮检索未能确证，**不做推测填充**。

**与既有调研的分工**（避免重复）：R1 覆盖期刊宽度/字号/线宽/DPI 的**绝对值**；R2 覆盖按最终尺寸统一规格的**实现机制**；R6 覆盖拼版规则**原文**与 R 生态统一机制；R9 覆盖 mpltweak 对照。**本文只做"痛"这一侧**：退改/拒稿的真实机制与统计、不可复现的一手描述、工具痛点的公开记录、人工核对方式的真实描述。凡 R1/R6 已引的期刊硬规范，本文不重复引用，只在需要解释"痛从哪来"时点名。

---

## 0. 给父代理的结论（先读这段）

1. **"图导致退改/拒稿"是真实且被官方文档承认的流程，不是我们编的需求**：[事实] JCI 编辑述评披露，在 200 篇"即将接受"的稿件中，**27.5% 有图像问题、21% 有 blot 问题、28.5% 有统计问题**；其中 2 篇（1%）因图像问题**直接拒稿**（原文 "resulting in loss of confidence in the data and ultimately rejection of the manuscript"）。这是"图 → 拒稿"最硬的一手链条。URL 见 §1.1。
2. **跨图一致性是期刊明文的硬要求，但没有任何自动化工具在管它**：[事实] Science 作者指南把 "Are the font sizes consistent?" 写进投稿**自检清单**，并要求 "maximum of 3 sizes"；JEEG/EMBO/Plant Cell 等把"所有图必须同一字号/同一字体"写成 MUST。**但检查动作被明确定义为作者自查**（checklist 是给人勾的）。→ 这是"最后一段路靠人眼"的直接证据，见 §4。
3. **"宽度变了 → 有效字号/线宽跟着变"是所有工具的公开伤口**，而且被**厂商自己的 FAQ** 承认：[事实] OriginLab 官方 FAQ-441 用整节文档讲"合并/缩放后你**不再知道文字标签的真实字号**"（原文 "At this point, you no longer know what the size of your text labels is unless you hover on a selected label"），并给出 22 → 10.1 的实例，补救办法是手工 `Graph: Fix Scale Factors`。见 §3.4、§4.5。
4. **"事后在 Illustrator/Inkscape 手动美化 → 无法重跑"有一手自述**（生态学家 Maxwell Joseph：重做三次；Meghan Duffy：审稿意见要求改一次、全套重现花了"几天"，且最后仍有一步只能回 PowerPoint 收尾）。见 §2.2、§2.3。
5. **不利于我们的发现（必须写清）**：
   - **"无法复现"的核心痛点，主流解法是"别在外部工具改图"**，不是一个新工具。见 §2.4 的三条独立表述。
   - **单图内的期刊规格检查已经被占住**：`figure-gate` 对**已构建的 matplotlib figure** 做 21 项检查（含 Type 3 字体、字号在栏宽下的可读性、色盲安全）；`plotstyle` 提供 journal preset。见 §3.6、§4.6。
   - **整版拼装 + 模板复用**在 Illustrator 工作流里已被当作"标准做法"教（master template / master legend / figure inventory），也就是说**"整版一致性"在实践上已有解法，只是手工的**。见 §4.4。
   - **bioRxiv 一手研究**（Acuna/Brookes/Kording）在**跨篇/篇内图像复用**尺度上已有自动检测：760k 篇、2M 图的规模，并提供数字（9% 生物相关复用至少"可疑"、0.6% 文章" unanimously fraudulent"、复用发生位置 43% 跨篇 / 28% 篇内 / 29% 图内）。**但它的单位是"图像区域复用"，不是"版面几何规格"，也不是"改一处能否整版重跑"**——这是留给我们的缝（§5.2）。
6. 【推断】本轮最可能"占得住"的位置**不是**"检查合规"（已有工具、且阈值可抄），**而是**：把"**最终尺寸下的跨图角色统一（字号/线宽/面板字母）× 整版级 `k≡1` 度量 × 改一处可重跑 × 可消费回执**"做成一条**可验证的闭环**。理由：本轮检索中，前三项各自有人在单图或 GUI 层面做，**但没有任何来源把四者接成一条带证据回执的链**；同时期刊文档恰好把这一段留给人工 checklist（§4.7）。此结论为**【推断】**，R12 需独立验证。

---

## 1. 期刊/编辑对图的退改或拒稿原因（一问）

### 1.1 最硬的一条：JCI 的预发表图像筛查统计（含"因图拒稿"）

[事实] Williams CL, Casadevall A, Jackson S. *Figure errors, sloppy science, and fraud: keeping eyes on your data*. **J Clin Invest** 2019;129(5):1805–1807. https://doi.org/10.1172/JCI128380（正文页 https://www.jci.org/articles/view/128380，抓取 2026-10-15）。

- 筛查口径（原文）："Between July 1, 2018 and February 5, 2019, we screened **200 papers** that were on a clear path toward acceptance for publication."
- 三类问题的比例（原文）："**28.5% (57 of 200)** of the papers screened were flagged for issues with statistical tests, **21% (42 of 200)** of papers had some issue with the blots, and **27.5% (55 of 200)** of papers had issues with images."
- 图像问题的内部分级（原文）："**89.1% (49 of 55)** had what we consider to be minor transgressions, such as undisclosed reuse of representative images in more than one figure or **unaltered duplications of a panel that appeared to be inadvertent (i.e., a copy-and-paste error)**"；"**7.3% (4 of 55)** … moderate issues … multiple panels were reshown … or in which **a different crop of the same image was used to represent distinct treatment groups**"；"**3.6% (2 of 55)** … major issues … and **1% (2 of 200)** of the total papers screened"。
- **拒稿链条（原文）**："The authors of the papers in question were asked to provide explanations for the noted discrepancies, and in both cases, the Editorial Board members determined that the explanations provided were not sufficient, **resulting in loss of confidence in the data and ultimately rejection of the manuscript**."
- **"轻微错误也会变成正式更正"（原文）**："had they not been detected prior to publication, several would likely have required a formal correction."；"These issues almost certainly would have required post-publication correction."
- **"没人能自动全部检查"（原文，直指工具缺口）**："We have found that detection of data anomalies, especially image duplication and manipulation, requires a dedicated person with a keen eye and excellent pattern-recognition skills. We suspect that most scientists would be surprised to learn that **there is not automated software to screen all images in a manuscript for reuse, partial overlap, and rotation**."
- **"图是拼装错误的重灾区"（原文）**："One potential mechanism to reduce **figure assembly errors** is to have someone other than the primary author who generated the data put together the figures."；"as manuscripts increasingly become more complicated and involve more co-authors, the chance to introduce errors increases."
- **图注披露义务（原文）**："you must clearly indicate in the legend of the second instance that an image from a previous figure is being reshown for comparison purposes."

[推断] 这段对我们最有用的是**它的因果链**：不是"图丑被拒"，而是"**图的组装过程无法自证 → 编辑无法确认数据与呈现一致 → 失去信心 → 拒稿**"。这正是"可核对、可回执"要解决的问题，而不是"好看"要解决的问题。

### 1.2 期刊把"图有问题就要求补原始数据/改图"写进政策

[事实] JCI Author Information Center — *Scientific integrity*（https://www.jci.org/kiosks/authors，抓取 2026-10-15，页面标注 "Recent updates: Revised the Scientific integrity section. June 18, 2026."）。原文：

> "If we detect **any potential manipulation of images or figures prior to publication**, we will contact the authors and **may request primary data for verification purposes**."

[事实] 同页 *Generative artificial intelligence technologies*（原文）：

> "**Use of AI technology to generate or modify data images is strictly prohibited.**"
> "Generative AI technologies used for written or visual content must be explicitly described in a paragraph titled 'AI disclosures' … including writing of the manuscript and **preparation of figures, graphics, and other content**. The disclosure should specify **the task performed, the name and version of the AI tool, and the date or range of dates of use**."
> 示例："The graphical abstract was created in BioRender with **AI-assisted layout suggestions** (July 1, 2026)."

[事实] 同页 *Experimental design / Number of replicates*（原文）：

> "The exact number of samples (n) **for each figure panel** representing multiple experiments must be included in the figure or its legend."

[推断] 这是"**图的来源与过程必须可披露**"的官方制度化表述（任务名/工具名+版本/日期区间）。figpact 的 receipt（双状态 + 证据哈希 + 实测值）在语义上**正好落在这一栏**：把"我改了什么、依据什么版本、改完实测是多少"变成可粘贴进 AI disclosures / 数据可用性声明的结构化记录。注意【事实】：该政策明确**禁止**用 AI 生成或修改**数据图像**，允许的是"写作或视觉内容的 AI 辅助并披露"——所以我们的位置只能是**几何/版面层**，不能碰像素。这条边界必须写进我们的对外话术。

### 1.3 期刊官方文档承认"稿源到生产的路上会再缩放一次"

[事实] Science/AAAS *Guide to preparing figures* 2025（PDF，https://www.science.org/cms/asset/67f37ac8-4d02-4625-8a05-230568cb8323/author_prep_guide_2025.pdf，抓取 2026-10-15）第 2 页原文：

> "**FIGURE LAYOUT AND SCALING** — [Science] **might scale figures due to production constraints.**"
> "Avoid wide variation in type size within a figure."
> 投稿自检清单（原文）："Are the files editable? … Is the resolution 300 ppi? … **Are the font sizes consistent?** … Is the figure color blind friendly? … **Have figure sizes been considered?**"

同 PDF 第 1 页原文（硬下限，与 R1 口径一致，此处仅作"事后缩放会踩线"的语境）：

> "**Font size variation within a figure can be confusing.** Differences in size should be used for typographic hierarchy (**maximum of 3 sizes**)."
> "At final print size, **minimum line weight is 0.28 pt** (~0.10 mm)."

[事实] Cell Press *Figure guidelines*（https://www.cell.com/information-for-authors/figure-guidelines；该页本机直连返回 HTTP 403，本轮以检索快照为据，**标注为 403 降级来源**）确认生产阶段口径：字体 Arial、**final print size 下 6–8 pt**、彩色/灰度 ≥300 dpi、黑白 ≥500 dpi、线稿 ≥1000 dpi、单图尺寸上限 6.5×8 in。

[推断] "Science 可能因生产约束缩放你的图"＋"字号一致性由作者在 checklist 里自证"＝**把最终尺寸下的规格风险完全转移给作者**。这就是 §4 全部人工动作的来源。

### 1.4 拒稿原因的统计：图的位次要诚实说

[事实] 《Common Reasons for Rejecting Manuscripts at Medical Journals: A Survey of Editors and Peer Reviewers》（CSE，https://councilscienceeditors.org/wp-content/uploads/v23n2p039-044.pdf；检索快照）与后续多项拒稿原因内容分析（例：Academic Medicine 2018 内部编辑拒稿九主题 https://journals.lww.com/academicmedicine/fulltext/2018/03000/making_the_first_cut__an_analysis_of_academic.37.aspx；Indian J Psychol Med 898 份拒稿报告 https://pmc.ncbi.nlm.nih.gov/articles/PMC9022928/）**一致地把"研究设计/方法/重要性"排在最前**。

[事实] 影像类期刊编辑/审稿人问卷（The Impact of Figures and Schematics on Reviewer Ratings and Manuscript Acceptance, https://doi.org/10.1177/09760016251324320）显示图**重要**（91.7% 认为图重要；85.7% 偏好原始图像），但**"图的数量多"并不加分**（25.6% 认为更多图无益）。

**不利结论（必须写）**：[推断+事实] 就"拒稿"这个最刺激的指标而言，**图不是第一位原因**；把 R11 的叙事建立在"你因为图被拒了"上是**夸大**且站不住。**站得住的说法**是两条：(a) 图会**触发退改/要求补原始数据/生产阶段返工**，且**在极少数重大情形直接导致拒稿**（§1.1，1%/2 of 200）；(b) 图是**稿件的可核查性**（数据↔呈现一致性）的入口，编辑的筛查工具**不充分且明确依赖人工**（§1.1 最后一条原文）。我们对外描述应止步于此，不越界。

---

## 2. 图不可复现的一手证据（二问）

### 2.1 图的"区域复用"在规模上被量化（且作者自己承认只能"人工三方裁决"）

[事实] Acuna DE, Brookes PS, Kording KP. *Bioscience-scale automated detection of figure element reuse*. bioRxiv 269415v3（https://www.biorxiv.org/content/10.1101/269415v3.full，抓取 2026-10-15）。原文摘要：

> "We present an analysis of figure element reuse on a large dataset comprising **760 thousand open access articles and 2 million figures**. … we estimate that **9% of the biological reuses would be unanimously perceived as at least suspicious**. We further estimate that **0.6% of all articles would be unanimously perceived as fraudulent**, with inappropriate reuses occurring **43% across articles, 28% within article, and 29% within a figure**."

[事实] 同行评议版本为 Bik EM, Fang FC, Kullas AL, Davis RJ, Casadevall A. *Analysis and Correction of Inappropriate Image Duplication: the Molecular and Cellular Biology Experience*. Mol Cell Biol 2018;38(20):e00309-18（https://pubmed.ncbi.nlm.nih.gov/30037982/）：**960 篇 MCB 论文（2009–2016）中 59 篇（6.1%）含不当重复图像**。

[事实] Bik EM, Casadevall A, Fang FC. *The Prevalence of Inappropriate Image Duplication in Biomedical Research Publications*. mBio 2016;7(3):e00809-16（https://pmc.ncbi.nlm.nih.gov/articles/PMC4941872/）。原文摘要与结果：

> "The images from a total of **20,621 papers** published in 40 scientific journals from 1995 to 2014 were visually screened. Overall, **3.8% of published papers contained problematic figures**, with at least half exhibiting features suggestive of deliberate manipulation."
> "Among the 782 problematic papers … **230 (29.4%) contained simple duplications** and **356 (45.5%) contained duplicated images with repositioning**, while the remaining **196 (25.1%) contained duplicated figures with alteration**."
> "**Beautification.** Part of the background of a blot or gel where no band of interest is expected may show signs of patching, perhaps to remove a smudge or stain. This is **not considered to represent best practice** according to contemporary guidelines for data presentation."
> 期刊间差异（原文）："ranged from the *Journal of Cell Biology* (**0.3%**) to the *International Journal of Oncology* (**12.4%**)"；"This coincides with … the widespread availability and usage of digital image modification software"；"the increasing tendency for images to be **directly prepared by authors instead of by professional photographers** working in consultation with authors has removed a potential mechanism of quality control."

[事实] 撤回文语境下的同类量化：*Characterizing Problematic Images in Retracted Scientific Articles*（https://ecommons.luc.edu/cgi/viewcontent.cgi?article=1421&context=cs_facpubs）报告：凝胶/blot 是最常见被指图像类型（1074 篇；**51.68%**）；**图像重复是撤回的首要原因（1827 例；87.92%）**；跨文复用为主要场景（1241 例；59.72%）。

[事实] Nature 新闻口径（2016）：约 **4% 生物医学论文含不当重复图像（≈1/25）**，期刊间从 >12%（Int. J. Oncology）到 <1% 不等。https://www.nature.com/articles/nature.2016.19802

**这些数字的边界（必须同时说）**：[推断] 上述全部研究**只处理"图像像素层面"的复用/篡改**（blot、显微镜、FACS、照片）。它们**完全不触及**本文关心的另一类问题：**矢量图（曲线/柱/坐标轴）在"数据 → 代码 → 人工美化 → 最终尺寸"之间的脱节**。也就是说，"图不可复现"被学术界量化的部分**只覆盖了图像复用这一支**，而我们关心的"几何/规格脱节"这一支**尚未见到公开的量化统计**（见 §5.3 `未找到`）。

### 2.2 一手自述 A：在 Inkscape 里做"最终版"，结果重做了三次

[事实] Maxwell B. Joseph（生态学/统计学者），*Why I think twice before editing plots in Powerpoint, Illustrator, Inkscape, etc.*（2015-02-26；https://mbjoseph.github.io/posts/2018-12-27-why-i-think-twice-before-editing-plots-in-powerpoint-illustrator-inkscape-etc/，抓取 2026-10-15）。原文：

> "When figures are edited outside of R, they can be **much more difficult to reproduce**."
> "I had to learn this the hard way. … initially I created a rough version in R, **edited it in Inkscape (~30 minutes invested)**, and ended up with a 'final' version for submission. Turns out that **I had to remake the figure three times** throughout the revision process (for the better)."
> 归因（原文，直接点名投资回报）："The payoff from this time investment will be a function of **how much manipulation is done outside R**, how hard it is to get the desired result in R, and **how many times a figure will be re-made**."
> "point-and-click programs are inherently slow because I'm manually manipulating elements, usually with a mouse, and **my mouse isn't getting any faster**."

同一帖的语境来源（[事实]，2015-02-25，https://dynamicecology.wordpress.com/2015/02/25/how-do-you-make-figures/）：作者 Meghan Duffy 的读者调查引出共识式自述——"I mostly make figures in R but then **pull them into Powerpoint to make multi-panel figures, add panel labels (a), (b), etc., fiddle with the axis labels**"；"for journals that expect you to do a lot of the typesetting yourself (e.g., Plos One), **I've had trouble conforming to their formatting requirements using this approach**"。

### 2.3 一手自述 B：审稿要求改一次 → 全套图重做"几天"；最后一步仍只能手改

[事实] Meghan Duffy（Georgia Tech 生态学教授），*The biggest benefit of my switch to R? Reproducibility*（2015-02-18；https://dynamicecology.wordpress.com/2015/02/18/the-biggest-benefit-of-my-switch-to-r-reproducibility/，抓取 2026-10-15）。原文：

> "I would then paste the figure and command file I had used to make it into Powerpoint, and then would **get the figure to publication-quality in Powerpoint**. (For example, **the tick marks … never show up as straight once the figure has been exported, so I would manually draw a new tick mark over the old one**…) That sort of thing was clearly really tedious."
> "One paper of mine has a ton of figures in the supplement. … but that change meant that I had to **remake all of them. It took days.**"
> 迁移到 R 之后仍有残留手工步骤（原文）："For the manuscript I'm working on now, I still **exported figures to Powerpoint to arrange them into panels**. I know that, in theory, I can do this in R … but I couldn't figure out how to get it to arrange them in a way that didn't include **a lot more white space between the panels** than I wanted."；更新："I decided to add two new panels to the figure, and **spent all day Monday working on it**. I got to the point where I could get them arranged nicely in R, but **never did figure out why two of the y-axis labels weren't centering properly. So, that last step still happened in powerpoint. Sigh.**"
> 读者补充（原文，同一评论区）："You will feel the pain when you find some error in your raw data or your code **if you modify figures using Illustrator**."

### 2.4 不利发现：社区给出的主流"解法"不是新工具，而是"别出代码"

[事实] 上述同一篇的读者共识与原帖主张本身，都把结论指向**减少外部手动编辑**：Joseph 的 TLDR 原文即 "**scripting plots is more reproducible and efficient long term**"；Duffy 的评论区原文 "**do that after your paper has been accepted**"（指把 Illustrator 式微调推到录用后再做）。

[事实] 独立的同类主张（R-bloggers 转载，https://www.r-bloggers.com/2015/02/why-i-think-twice-before-editing-plots-in-powerpoint-illustrator-inkscape-etc/）与 bioCS 博客的动机陈述（*Creating composite figures with ggplot2 for reproducible research*，"aiming to **avoid manual post-processing in Illustrator or OmniGraffle**"，https://biocs-blog.blogspot.com/2015/03/creating-composite-figures-with-ggplot.html，该页正文抓取失败，仅有检索摘要，**标注为降级证据**）。

**不利结论（必须写）**：[推断] 也就是说，**"手动美化破坏可复现性"这个痛点，社区已有一条自洽的意识形态答案（"全都用代码"）**；我们的位置**不能**是"劝人别用 Illustrator"，只能是"**当你不得不在代码之外做版面决定时，让这个决定可测量、可写回、可重跑、带证据**"。这正是 R12 要验证的"整版"缝隙。

### 2.5 工具生态侧的一手缺口：跨图一致性的算法在 R 生态里被反复修而修不好

[事实] covplot/patchwork 官方 vignette 自己承认对齐能力有边界。cowplot *Aligning plots*（2025-07-06，https://wilkelab.org/cowplot/articles/aligning_plots.html，抓取 2026-10-15）原文：

> "There are several packages that can be used to align plots. The most widely used ones beside cowplot are egg and patchwork. **All these packages use slightly different approaches to plot alignment, and the respective approaches have different strengths and weaknesses. If you cannot achieve your desired result with one of these packages try another one.**"
> "**This method of alignment only works if all plots have exactly the same elements.** Therefore, it fails, for example, if we try to align a plot that is faceted with one that is not." （随后给出 warning 原文）
> "Graphs cannot be horizontally aligned unless the axis parameter is set. **Placing graphs unaligned.**"

[实测] `thomasp85/patchwork` 仓库元数据（GitHub API，2026-10-15）：stars **2616**、open issues **82**、最近 push **2025-08-25**、创建 **2017-11-28**。以 `is:issue label:bug` 检索得 13 条，标题包含 "**Nested graph and tag alignment**"、"**Design is not consistent when swapping figures that have fixed aspect ratio**"、"**plot_layout `axis_titles = "collect"` has unusual behaviour for non-square assemblies**"、"**Extraneous positioning dataframe emitted when combining grobs in Rmarkdown notebooks**"；以 `alignment` 检索得 **33** 条，含 "**axis alignment** (#419)"、"**Collect axes: tick mis-alignment** (#436)"、"**Heights in plot_layout breaks x-axis alignment** (#437)"、"**Plots misalignment with facets and `theme_void()`** (#441)"、"**[Feature Request] Align panels without aligning axis titles** (#348)"、"**Change the y-axis alignment of two faceted plots** (#312)"。

[事实] patchwork 维护者文档说明对齐的直接后果（*Controlling Layouts*，https://patchwork.data-imaginist.com/articles/guides/layout.html）：sizing 只作用于"plotting region"，**轴文本会额外占用空间而不改变面板区域**——这本就是"拼版后字号/白边与单图不再一致"的根源。

[实测] SciencePlots（提供 `journal` 风格预设，2026-10-15 查）stars **9291**、open issues **19**；adjustText（标签避让）stars **1665**、open issues **46**。adjustText 高互动 issue 全部是**避让本身的鲁棒性**："The return in 2d: Why do labels move that are not overlapping?"（27 条评论）、"Arrow markers strike through text"（20）、"avoid crossing of the connector lines"（17）、"Arrows disappear when using cartopy transformation"（11）。

[推断] 结论：**"跨图/跨面板一致性"在代码生态里是一个"有库、但库自己声明做不到全覆盖、且 issue 长期堆着"的状态**。它既不是"没人做"（不利），也不是"已解决"（有利）。真正没被占住的是**"最终成品尺寸下的统一度量 + 谁改了哪一处的可追溯"**（§5）。

### 2.6 `未找到`（不做推测填充）

- **未找到** 任何一手来源，直接量化"论文图与其源数据/代码不一致"的发生率（§2.1 的 3.8%/4% 均为**图像像素复用**，不是数据↔图不一致）。**在 PRISMM-Bench 之前未见系统统计**；PRISMM-Bench（见下）是唯一近期的量化，但它只覆盖 ICLR 投稿。
- **未找到** "编辑因字体/线宽/DPI 不符**直接拒稿**"的官方统计或一手编辑说明。已找到的都是"要求补件/返工/要求原始数据"（§1.2）与"投稿格式影响审稿人印象"的一般性表述。
- **未找到** 任何期刊把"每张图的最终有效字号/线宽"作为**投稿系统自动校验项**（即：闸门在编辑部，不在作者端，且是人工）。这条是**否证型**发现，对我们有利，但只是"未找到"，不等于"不存在"。

[事实] PRISMM-Bench（arXiv 2510.16505，https://arxiv.org/html/2510.16505v3；基于 ICLR 2024–2025 真实评审意见收集 **384 条不一致，来自 353 篇投稿**）：其中**图内不一致 23.7%**、**图↔正文不一致 21.9%**，为最高两类。来源为检索摘要与 arXiv HTML，**分类口径以原文为准，本轮未逐条复核**。可用作"'图的内部/跨模态不一致'已被认定为真实且占比最高的一类问题"的旁证——但注意它**仍是数据/内容层不一致，不是版面几何规格**。

---

## 3. 科研人员实际用什么、各自被公开记录的痛点（三问）

### 3.1 工具的分布（一手调查）

[事实] BioRender 委托 BioInformatics 的 **2023 State of Science Communication Report**（n=162 北美/欧洲生命科学界受访者；PDF https://www.rrze.fau.de/files/2023/06/2023-Science-Communication-Report-BioRender.pdf，抓取 2026-10-15）。原文：

> "**68% of respondents typically take 30-120 minutes to create a single illustration.** The amount of time it takes to create visuals is the most commonly experienced challenge in creating scientific illustrations, with **90% of respondents facing this issue**."
> "**89% (industry) / 90% (academia)** — illustration takes too much time；**73% / 76%** — illustration software is too difficult to use；**71% / 74%** — illustration creation is too complicated"
> "only **23%** of respondents indicate working with a creative department or contractor for visuals"；"**76%** of scientists who have outsourced illustrations indicate a range from **$50 to $500 per illustration**."
> 满意度/质量气泡图中，被点名的工具有：**BioRender、Adobe Illustrator、Adobe Photoshop、GraphPad Prism、Microsoft PowerPoint/Google Slides**（BioRender 在两项上最高）。

[事实] ACS Materials Au 社论（2025）列出的实际工具集（原文）："**software like Origin, MATLAB, PowerPoint, Python, and Adobe Illustrator to advanced platforms like Blender, SketchUp, and BioRender**"。见 §3.2。

**该调查的可用性边界（必须写）**：[推断] 这是**厂商委托**的调查，n=162，采样限定北美/欧洲生命科学，且"满意度/质量"分项由委托方主导呈现。适合用来说明"**时间是最普遍的痛点（90%）**"与"**外包不可行（77% 不外购；外购单价 $50–500）**"，**不适合**用来比较工具优劣。

### 3.2 ACS 编辑述评：工具不是瓶颈，习惯与时间才是（对我们不利的一手陈述）

[事实] Rayaroth A, Fiedler C, Ibáñez M. *Let Us FIGURE It Out: Why Do Scientists Still Make "Bad" Figures?* **ACS Mater. Au** 2025;5:438–440. https://doi.org/10.1021/acsmaterialsau.5c00037（正文 PDF 镜像 https://research-explorer.ista.ac.at/download/19731/19753/2025_ACSMaterialsAu_Rayaroth.pdf，抓取 2026-10-15）。原文：

> "**The problem is not a lack of technology**; it is a combination of poor design habits, rushed deadlines, and a tendency to treat figures as mere 'data dumps' rather than as essential storytelling tools."
> "**Most scientists … receive little to no formal training** in effectively communicating their findings visually. … the ability to present data visually is often left to informal learning through trial and error, lab traditions, or simply **imitating previous publications**."
> "**Researchers are often pressured to publish**, juggling experiments, data analysis, manuscript writing, and revisions. This multitasking can result in figures not receiving the attention they deserve."
> "While reviewers do evaluate figures, **much of the responsibility for their clarity and effectiveness lies with the authors** … certain visual issues may pass through the review process despite the best efforts of reviewers. To address this, journals **could** implement dedicated figure reviewers or graphical editors … AI-based or human-led screening tools **could** also help flag issues such as **low-resolution or misleading visuals before peer review**."

**不利结论（必须写，且是最强的一条）**：[推断] 这是一篇 2025 年 ACS 编辑述评，作者在**明确提出**"期刊应该做图编辑/图前筛查工具"这个方向。也就是说：**"投稿前的图质量筛查"这个位置正在被公开讨论并可能被期刊自己占住**。若我们把它当作主打卖点，风险是"当期刊开始做这件事时，我们的价值就变成替期刊重复劳动"。→ **建议把定位从"替你检查合规"移到"替你把版面决定变成可测量、可写回、可重跑、带证据的过程记录"**：后者即使期刊做了筛查也仍然需要（因为期刊只看最终产物，不看你是"改一处整版重跑"出来的还是一次性手搓的）。

### 3.3 Origin：图层缩放后"字号不再可知"（厂商自认）

见 §3.4（独立成节，因为这是本轮最直接、最可引用的一条"工具痛点"原始文本）。

### 3.4 OriginLab 官方 FAQ-441（逐条引用）

[事实] OriginLab, *1.88 FAQ-441 How do I export graphs with exact size and resolution as specified by publishers?*（Last Update 2019-01-08；http://docs.originlab.com/quick-help/set-expgraph-size-resolution/，抓取 2026-10-15）。原文要点：

> "**First, find out exactly what the publisher wants.** … Check font and font size requirements, as many journals have specific requirements for text inside of figures. Check lines weights of axes, annotations, etc. as **some journals specify minimum line weights**."（＝**规则查找本身是人工步骤**）
> "When you change the size of a graph layer … you can proportionally change the size of axis titles, tick labels, legend and text objects. … **At this point, you no longer know what the size of your text labels is unless you hover on a selected label.**"
> "During the operation, text objects were scaled proportionally. You can see that the X axis title of the original graph to left indicates an actual font size of **22**, while the same axis title in the merged graph to the right shows that the actual font size is now **10.1** after merging and rescaling."
> "**Line weights are also affected by scaling.** This is something that you'll also need to pay attention to as some journals specify minimum line weights."
> "The way to deal with both font size and line weight discrepancies is to activate your graph, then choose **Graph: Fix Scale Factors** and choose a factor of 1 … This will **reset font size and line weights** so that they are correctly indicated…"（＝**手动修复动作**）
> 后续步骤同为人工作业序列："**Specify Page Size** → **Adjust Font Size** → **Fit Layers to Page** → **Export with 100% Page Size**"。

[推断] 这段是"**跨图/整版一致性靠人工核对**"最干净的证据：工具不仅不阻止"合并后有效字号漂移"，还**把测量能力也一起丢掉了**（"你不再知道字号是多少"），把恢复动作交给一个需要用户主动选择的菜单项。**注意**：OriginLab 是商业软件里最成熟的科研绘图环境之一；这说明该痛点**不是"工具太弱"造成的，而是"尺寸语义在拼装时丢失"这一结构问题**。这与 figpact 的 `k`（缩放比）与"最终尺寸审计"是同一个数学模型。

### 3.5 GraphPad Prism / Origin 的第三方批评（**降级来源，须标注**）

[事实/降级] 以下为**第三方评测与聚合页**，非厂商或同行评议来源，仅作方向性参考，**不可作为硬证据**：
- *GraphPad Prism Review*（scientistinprogress.com/blog/graphpad-prism-review/，检索快照）：批评"no scripting or batch processing"、"analyses aren't easily documented or shareable as scripts"、"cannot run in the cloud, share scripts, or automate Prism workflows"。
- Capterra Prism vs OriginPro 对比页（https://www.capterra.com/compare/119786-185129/GraphPad-Prism-vs-OriginPro）：Origin 被批评"tedious layering/figure editing"、"lack of macOS support"；Prism 被批评"clunky figure item manipulation"、"limited customization"、价格高。
- [事实] 反证（厂商侧，可核）：GraphPad Prism 11 User Guide — *The PRISM file format*（https://www.graphpad.com/guides/prism/latest/user-guide/prism_file_format.htm，检索快照）说明其已转向开放的 ZIP 式 `.prism` 格式，数据/分析参数/结果以 CSV/JSON 存放，明确以 **FAIR/可复现** 为诉求。→ **"商业点选工具完全不可复现"是一个过期的刻板印象，我们不能用它当卖点。**

### 3.6 已被占住的检查位（对我们不利）

[事实] `figure-gate`（MIT，PyPI/conda-forge，作者页面 https://narenp12.github.io/figure-gate/，检索快照）：对**已构建的 matplotlib figure** 做 **21 项检查（13 potential failures + 8 advisory）**，包含**字号在栏宽下的可读性**、**Type 3 字体（IEEE PDFXpress 拒稿风险）**、文本裁切、色盲不友好的色相对、colormap 亮度序、alt text；提供 `report/audit/audit_json`（**结构化输出**）、阈值走 `figure-gate.toml`；自述"**Does not draw or restyle figures; only verifies**"。

[实测] `narenp12/figure-gate` 仓库元数据（GitHub API，2026-10-15）：stars **1**、open issues **2**、创建 **2026-07-22**、最近 push **2026-10-14**。

[事实] `plotstyle`（https://plotstyle.readthedocs.io/en/stable/，检索快照）"enforces journal-specific figure standards for Matplotlib … consistent font sizes, figure dimensions, line weights, DPI, color accessibility, and export formats across all figures"；[实测] `rahulkaushal04/plotstyle` stars **1**、open issues **2**。

[事实] `PubPlotLib`（https://github.com/pier-astro/PubPlotLib）提供单栏/双栏预置与 `width_fraction` 用于"把多张已保存的图拼起来"时**按比例缩放**，并**明确警告**：不要画到画布外，否则"**breaking font sizing**"。

[推断] 这些工具的共同边界是：**都在单图/单次渲染之内做检查，都没有"整版级实测 + 变更可追溯 + 可消费回执"这一层**；而且 stars 都极低（1），说明**"检查"这个功能点没有需求引力**（与 §3.2 的"问题不在工具"互相印证）。这对我们是坏消息也是指路：**再加一个 checker 不会有人注意**。

### 3.7 代码路线被广泛使用的科学可视技能（非工具，但是真实的"做事方式"证据）

[事实] 多个公开的 agent/skill 仓库把"最终尺寸下的规格纪律"写成可执行清单，例：`assets/figstyle.py` 单一 style 模块保证跨面板一致、`CONTENT_WIDTH_PT` 定义可用栏宽、**"avoid bbox_inches='tight' 以保住预期尺寸与字号下限"**、**"flag any text under 7.5pt"**、`check_figure.py` 的 gate 集（裁切/可读性/alpha 叠加/线宽/双轴/contour/colormap/字体嵌入/alt text）。来源：https://github.com/narenp12/figure-gate/blob/main/skill/SKILL.md ；https://github.com/foryourhealth111-pixel/Vibe-Skills/blob/main/bundled/skills/scientific-visualization/SKILL.md （均经检索快照）。**降级说明**：这些是个人/社区技能文件，非权威规范，仅作为"从业者确实在做这些手动动作"的旁证。

---

## 4. 跨图一致性与整版规格，目前是怎么被人手工核对的（四问）

### 4.1 期刊把"一致性"写成作者的**纸面自检清单**

[事实] Science 2025 指南的自检清单（原文，见 §1.3）逐项为勾选框：files editable / 300 ppi / **font sizes consistent** / linked images embedded / color blind friendly / **figure sizes been considered** / permissions。**这是给人勾的，不是给系统跑的。**

[事实] JEEG（把一致性写成 MUST 的期刊之一，R6 已引原文，此处不重复 URL）："The figure's style, font, size, and format **MUST be consistent with those in other figures**."

[推断] 也就是说：**期刊把"跨图一致"定义为作者的交付责任，并只提供一份人工 checklist。** 这正是"人工按尺子对齐字号"的**制度性成因**。

### 4.2 官方指南给出的具体人工动作序列

[事实] OriginLab FAQ-441（§3.4）给出的五步是显式的人工序列（Fix Scale Factors → 设 page size → 调字号 → Fit Layers to Page → 100% page size 导出）；其中第一步的存在本身就说明"合并之后必须人工把被缩放的字号/线宽找回来"。

[事实] 排版实践指南（如 *Preparing figures for publications and presentations*，UCSB 课程材料 http://mrlweb.mrl.ucsb.edu/~seshadri/Seshadri-Figures.pdf，检索快照）给出的操作建议是**"the same font size across all text (tick labels, axis labels, legends)"**、**"design the original figure near its final displayed size"**、**"resize decisions should be validated at full size first"**——全部是人工判断动作。

[事实] *Tips for Scientific Figures*（UCSC IBSC，https://ibsc.ucsc.edu/tips-for-scientific-figures/，检索快照）："Always confirm each target journal's figure specs (width, height, color format RGB/CMYK, resolution, usually …)"——**逐刊对照，人工执行**。

### 4.3 真实"对照 / 核对"的失败模式（有原文）

[事实] TeX.SE #145745 *How to keep ggplot font size constant when varying figure width*（2013-11-19，票 14；https://tex.stackexchange.com/questions/145745/how-to-keep-ggplot-font-size-constant-when-varying-figure-width，抓取 2026-10-15）。提问者原文：

> "I set the font size for all ggplots globally with `theme_set(theme_bw() + theme(text=element_text(family='Palatino', size=20)))` but I want to set the figure width with the knitr option `out.width=` … **The problem is this results in different effective font size to be typeset by LaTeX. The solution of course would be to manually set the font size differently for each chunk.**"

[事实] 同帖唯一回答（Johan Larsson）给出的"聪明办法"是**把 `\textwidth` 的 pt 值硬编码进 R，然后对每张图手算 `fig.width = 比例 × \textwidth` 并同时手设 `fig.height`**（原答案代码 `textwidth <- 4.7917`）。

[推断] 这是"**手工按尺子对齐字号**"的教科书级实例：问题的本质是 `k ≡ 1`（最终宽度 == 绘制宽度）不成立，而**唯一的现成解法是人手工维护一张比例表**。

### 4.4 实践侧的标准做法：主模板 + 主图例 + 图表清单（人工资产）

[事实] *Thesis figure consistency guide*（https://www.graffiy.com/blog/thesis-figure-consistency-across-chapters-guide，检索快照）给出的方法是**纯人工资产管理**：建立单一视觉语言（一个字体、一种面板字母、一种图注结构）、建**master template**、**"Align old figures to the template: place originals beside the template to identify what needs changing"**、复用一个 **master legend**、建 **figure inventory spreadsheet**（图号/标题/源文件/导出文件/状态/权利）、"**When making global style changes (e.g., axis font size), update all affected figures in one pass rather than piecemeal**"、并"regularly export small previews to audit font, spacing, and color consistency at a glance"。

[事实] BioRender 的产品化对照物（官方帮助页，https://help.biorender.com/hc/en-gb/articles/35863177222941-Presenting-your-graphs，检索快照）：**Style Match** 功能在同一视图里"copying a source graph's style and pasting it onto targets"，并可勾选要套用的属性（graph styling / statistics markings / **size/dimensions** / axis range/scale）——其营销点正是"**reducing tediously manual adjustments in Illustrator**"。

**不利结论（必须写）**：[推断] 也就是说，**"整版一致性"在被手工解决的同时，正在被 GUI 工具产品化**（BioRender Style Match 是"样式复制"语义；Illustrator 侧有 Graphic Styles 可复用）。我们**不能**把卖点定在"能统一多图样式"——那是既有人工惯例、又有 GUI 功能的红海。

### 4.5 Illustrator 侧的真实坑（一手社区记录）

[事实] Adobe Community — *Excel charts imported into illustrator*（https://community.adobe.com/questions-652/excel-charts-imported-into-illustrator-767356，检索快照）：文本在 PDF 里变成组（非 Type 对象）、字体/文本在工作流中变形；讨论中给出的规避办法包括**改 Illustrator 的水平字符缩放回 100%**、**经 InDesign 中转**、**换字体**、**保留 EMF/WMF** 等，全部是人工试错。

[推断] 这类"**跨软件交接把可编辑文本/尺寸语义弄丢**"的坑，与 R6 已记录的"缩放后字号不一致"是同一族问题，**且没有任何自动化手段**——因为丢失发生在格式转换里、发生在别人的工具里。

### 4.6 手工核对的替代品：已被占住的"自动检查"（复述 §3.6，不重复）

`figure-gate`（21 gates、Type 3、字号可读性、色盲、alt text、`figure-gate.toml` 阈值、`audit_json` 结构化）与 `plotstyle`（journal preset：字号/尺寸/线宽/DPI/色可达性/导出格式）覆盖的是**单图在单次渲染中的静态合规**。**它们不处理**：整版（多图拼装后）的实测规格、改一处后的整版重跑、跨图角色的差异报告、外部可消费的证据。

### 4.7 本轮四问的合成结论

| 问题 | 现有解法的形态 | 证据位置 |
|---|---|---|
| 跨图字号/线宽一致 | **纸质 checklist + 人眼 + 手工 template/inventory** | §1.3、§4.1、§4.4 |
| 缩放后有效字号/线宽 | **人工"Fix Scale Factors"或手算比例表** | §3.4、§4.2、§4.3 |
| 期刊规格合规 | **单图静态 checker（figure-gate / plotstyle）** | §3.6 |
| 图与源的一致性 | **期刊人工筛查 + 少数分事件自动化（仅图像复用）** | §1.1、§2.1 |
| 改一处 → 整版重跑 | **未见自动化；社区答案是"别出代码"** | §2.2–§2.4 |

【推断】四问合起来指向一个**具体且未占住**的缺口：**"最终尺寸下的整版度量 + 变更→重跑→复验→回执"这一条链**。它之所以没被占住，很可能不是因为难，而是因为它**跨越了"图"与"版"的边界**——工具要么只管画图（matplotlib/R），要么只管排版（Illustrator/LaTeX），期刊只管成品，而**"数据→代码→版面决定→最终 mm 成品"这一段中间损失**没有责任主体。这与 CONTEXT.md 里 "Scope 不是 panel，也不是文件名" 的定义是同一件事。

---

## 5. 我们能占住什么 / 不能占住什么（含否证）

### 5.1 不能占住（本轮证据直接否证）

1. **"图启动审稿人能救你"**：证据不支持（§1.4）；**不要让市场话术越过"退改/返工/补原始数据"去说"拒稿"**。
2. **"统一多图样式"**：人工惯例（§4.4 master template）＋ GUI 产品（BioRender Style Match）＋ 代码侧（SciencePlots/patchwork）三重覆盖。
3. **"整版合规检查"**：figure-gate/plotstyle 已有；且 ACS 社论已公开呼吁期刊自己做（§3.2）。**加入这一列不会获得注意力，只会被拿去和已有 checker 比 gate 数量。**
4. **"图像完整性/复用检测"**：bioRxiv+mBio+MCB 已有规模化自动方法（§2.1），且与我们"不碰科学像素"的边界冲突。
5. **"劝导用户别用 Illustrator"**：社区已有自洽答案（§2.4）。

### 5.2 可能占住（**推断**，需 R12 独立验证）

把四件事接成**一条可验证的链**：**(a) 整版（plate）级的最终尺寸度量**（各面板 `k`、最终有效字号/线宽分布、面板字母与边距的实测值）→ **(b) 跨图角色统一**（不是复制样式，而是"同一角色在多张图里实测值是否落在同一容差内"）→ **(c) 改一处 → 整版重跑**（写回来源、漂移检查、写后复验）→ **(d) 结构化回执**（可粘贴进披露/审稿回复的证据块）。

覆盖证据（每条都可核）：`k` 与最终尺寸语义来自期刊口径（§1.3 Science 会缩放、Cell 生产尺寸）＋ Origin 的 22→10.1 现象（§3.4）＋ TeX.SE 手算比例表（§4.3）；"角色统一"来自期刊 MUST（§4.1）＋ checklist（§1.3）；"重跑"来自一手自述（§2.2/§2.3）；"回执"来自 JCI 的披露政策（§1.2）。

### 5.3 本轮明确"未找到"的（禁止在对外材料中宣称）

- **未找到** "数据↔图不一致"发生率的公开量化（§2.6）。
- **未找到** 编辑因**版面规格**（字号/线宽/DPI）**直接拒稿**的官方统计。
- **未找到** 任何期刊对**上传图做自动规格校验**的证据（闸门为人工）。
- **未找到** "整版级（多图拼装后）规格校验 + 变更重跑 + 回执"的现成实现。**注意**：这是"未找到"，不是"不存在"；R12 需用更宽的检索与代码层核对来收紧。

---

## 6. 来源清单（全部在文中给过 URL；此处仅作核对方便）

**期刊/编辑一手**
- JCI 编辑述评（200 篇筛查、因图拒稿、无自动化工具）：https://doi.org/10.1172/JCI128380 ；https://www.jci.org/articles/view/128380
- JCI Author Information Center（Scientific integrity / AI disclosures / 每个 figure panel 需给 n）：https://www.jci.org/kiosks/authors
- Science/AAAS *Guide to preparing figures* 2025（可能因生产约束缩放；checklist 含 font sizes consistent）：https://www.science.org/cms/asset/67f37ac8-4d02-4625-8a05-230568cb8323/author_prep_guide_2025.pdf
- Cell Press Figure guidelines（final print size 6–8 pt、各档 dpi、6.5×8 in）：https://www.cell.com/information-for-authors/figure-guidelines （本机 403，降级）
- EMBO Press Figure Guidelines（同字号、label 1.5–2.0 mm、字体嵌入）：https://onlinelibrary.wiley.com/pb-assets/assets/14602075/EMBOPress_Figure_Guidelines.pdf （检索快照）
- The Plant Cell Detailed Figure Guidelines（8 pt 首 6 pt 下限、面板字母 10–12 pt bold）：https://tpc.msubmit.net/html/TPC_Detailed_Figure_Guidelines.pdf （检索快照）
- ACS Mater. Au 社论（问题不在技术；呼吁期刊做图前筛查）：https://doi.org/10.1021/acsmaterialsau.5c00037 ；PDF 镜像 https://research-explorer.ista.ac.at/download/19731/19753/2025_ACSMaterialsAu_Rayaroth.pdf
- 拒稿原因统计（图非首位）：https://councilscienceeditors.org/wp-content/uploads/v23n2p039-044.pdf ；https://journals.lww.com/academicmedicine/fulltext/2018/03000/making_the_first_cut__an_analysis_of_academic.37.aspx ；https://pmc.ncbi.nlm.nih.gov/articles/PMC9022928/ ；影像期刊编辑问卷 https://doi.org/10.1177/09760016251324320

**图不可复现 / 图像完整性**
- Acuna/Brookes/Kording（760k 篇、2M 图；9% / 0.6% / 43-28-29%）：https://www.biorxiv.org/content/10.1101/269415v3.full
- mBio 2016（20,621 篇、3.8%、三类分类、beautification 不算最佳实践）：https://pmc.ncbi.nlm.nih.gov/articles/PMC4941872/
- MCB 2018（960 篇、6.1%）：https://pubmed.ncbi.nlm.nih.gov/30037982/
- Nature 新闻（≈4%、1/25）：https://www.nature.com/articles/nature.2016.19802
- 撤回文图像特征（gel blot 51.68%、重复 87.92%）：https://ecommons.luc.edu/cgi/viewcontent.cgi?article=1421&context=cs_facpubs
- PRISMM-Bench（ICLR 384 条不一致；图内 23.7%、图↔正文 21.9%）：https://arxiv.org/html/2510.16505v3

**一手自述 / 人工作业**
- Maxwell Joseph（Inkscape 30 分钟 → 重做三次）：https://mbjoseph.github.io/posts/2018-12-27-why-i-think-twice-before-editing-plots-in-powerpoint-illustrator-inkscape-etc/
- Meghan Duffy（重做全套"几天"；最后一步仍回 PowerPoint；tick 手绘）：https://dynamicecology.wordpress.com/2015/02/18/the-biggest-benefit-of-my-switch-to-r-reproducibility/
- Dynamic Ecology 读者做法调查（R→PowerPoint 拼版为常态；PLOS 格式难符合）：https://dynamicecology.wordpress.com/2015/02/25/how-do-you-make-figures/
- TeX.SE 145745（手算 `\textwidth` 比例表）：https://tex.stackexchange.com/questions/145745/how-to-keep-ggplot-font-size-constant-when-varying-figure-width
- OriginLab FAQ-441（字号 22→10.1、"你不再知道字号"、Fix Scale Factors）：http://docs.originlab.com/quick-help/set-expgraph-size-resolution/
- Adobe Community（Excel→Illustrator→PDF 文本语义丢失）：https://community.adobe.com/questions-652/excel-charts-imported-into-illustrator-767356
- Thesis figure consistency guide（master template / figure inventory）：https://www.graffiy.com/blog/thesis-figure-consistency-across-chapters-guide
- BioRender Style Match（样式批量套用，营销点为省去 Illustrator 手工调整）：https://help.biorender.com/hc/en-gb/articles/35863177222941-Presenting-your-graphs
- BioRender 2023 State of Science Communication Report（n=162；90% 时间痛点；30–120 min/图）：https://www.rrze.fau.de/files/2023/06/2023-Science-Communication-Report-BioRender.pdf

**工具/生态（含不利发现）**
- figure-gate（21 gates、Type 3、字号可读性、audit_json、阈值 toml）：https://narenp12.github.io/figure-gate/ ；https://github.com/narenp12/figure-gate/blob/main/skill/SKILL.md
- plotstyle（journal preset 全线）：https://plotstyle.readthedocs.io/en/stable/
- PubPlotLib（`k≡1` 与 font sizing 断裂的官方警告）：https://github.com/pier-astro/PubPlotLib
- cowplot *Aligning plots*（对齐方法互不通用、元素不同即失效）：https://wilkelab.org/cowplot/articles/aligning_plots.html
- patchwork *Controlling Layouts*（sizing 只作用于 panel 区域）：https://patchwork.data-imaginist.com/articles/guides/layout.html
- patchwork issue #419 / #436 / #437 / #441 / #348 / #312（对齐长期未解）：https://github.com/thomasp85/patchwork/issues
- adjustText issue（标签避让鲁棒性长期未解）：https://github.com/Phlya/adjustText/issues
- 工具使用方式与规格纪律的社区技能文件（降级）：https://github.com/foryourhealth111-pixel/Vibe-Skills/blob/main/bundled/skills/scientific-visualization/SKILL.md
- GraphPad Prism 11 文件格式（FAIR 化，反驳"点选工具不可复现"）：https://www.graphpad.com/guides/prism/latest/user-guide/prism_file_format.htm （检索快照）
- 第三方评测（降级，仅方向参考）：https://scientistinprogress.com/blog/graphpad-prism-review/ ；https://www.capterra.com/compare/119786-185129/GraphPad-Prism-vs-OriginPro

**本轮直接查询（[实测]）**
- GitHub REST API 仓库元数据与 issue 检索，2026-10-15（无法在本环境复现为文件的查询结果已在上文逐条给数）：`shdbl/mpltweak` stars 1 / issues 0 / pushed 2026-10-15；`garrettj403/SciencePlots` stars 9291 / issues 19；`MNoichl/pylabeladjust` stars 10 / issues 0 / pushed 2024-04-26；`rahulkaushal04/plotstyle` stars 1 / issues 2；`thomasp85/patchwork` stars 2616 / issues 82 / pushed 2025-08-25；`narenp12/figure-gate` stars 1 / issues 2 / created 2026-07-22；`adjustText/adjustText`（`Phlya/adjustText`）stars 1665 / issues 46。
