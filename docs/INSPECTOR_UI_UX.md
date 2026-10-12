# Figpact 检查器 UI/UX 规范与实测报告 (Apple Preview 启发版)

本文档记录了 figpact 检查器从早期工程测试界面重构为「Apple 预览 (Preview) 启发式对象检查器」的设计决策、官方规范引用、通俗中文文案演进对照、实测数据与边界限制。

---

## 1. 规范来源与官方文档依据 (Primary Sources & URLs)

本界面的视觉结构、操作层级与信息收折设计参考了 Apple 官方人机交互指南 (HIG) 与 macOS Preview 官方用户手册，并根据科学图件审查需求进行了必要的工程适配：

### 1.1 官方人机交互规范 (HIG)
1. **Toolbars (工具栏)**
   - **URL**: `https://developer.apple.com/design/human-interface-guidelines/toolbars`
   - **规范要点与支持项**：工具栏保持静雅克制 (Quiet & Unobtrusive)，仅放置与当前视图强相关的全局控制项；使用分段控件 (Segmented Controls) 呈现互斥选项（如显示清晰度选择）；按钮使用清晰的文字配合辅助说明；避免无关花哨装饰。
2. **Inspectors (检查器交互模式)**
   - **来源说明**: Apple HIG 当前架构中独立的 `/inspectors` 页面已归入 Sidebars、Toolbars 与 Panels 综合模式（原独立链接返回 404）；Preview 原生 Inspector 窗口以 Apple 官方支持手册为准：<https://support.apple.com/guide/preview/view-information-about-pdfs-and-images-prvw9c94f0a4/mac>。
   - **规范要点与支持项**：检查器作为上下文面板，聚焦展示当前所选对象的属性；严格区分常用属性与次要高级细节；将技术标识、哈希、底层协议等高级信息收纳在折叠区 (Disclosure/Details)，不干扰首屏阅读。
3. **Sidebars (侧边栏)**
   - **URL**: `https://developer.apple.com/design/human-interface-guidelines/sidebars`
   - **规范要点与支持项**：提供平级的大纲/对象列表导航，支持一键切换展开与收起；大纲列表项清晰展示对象可读名称与类型类别。

### 1.2 Apple Preview (预览) 官方手册
1. **Preview User Guide for Mac (macOS 预览用户手册)**
   - **URL**: `https://support.apple.com/guide/preview/welcome/mac`
2. **View information about PDFs and images (查看图件信息)**
   - **URL**: <https://support.apple.com/guide/preview/view-information-about-pdfs-and-images-prvw9c94f0a4/mac>
   - **实际支持项**：打开 Inspector 查看信息，按信息类别切换；其中图像信息包括尺寸与分辨率。首屏简明、更多技术信息收折，是本项目的适配，不声称是该手册逐项规定。
3. **View PDFs and images (查看、缩放与侧栏)**
   - **URL**: <https://support.apple.com/guide/preview/view-pdfs-and-images-prvw11470/mac>
   - **实际支持项**：工具栏放大/缩小、指定缩放比例、切换侧栏与放大镜。毫米标尺、指针锚定和本项目自适应计算不归为 Apple 原生功能。
4. **Writing (用户界面措辞)**
   - **URL**: <https://developer.apple.com/design/human-interface-guidelines/writing>
   - **实际支持项**：使用日常词汇、短句和明确的动作按钮；避免行话；提示用户下一步，而非堆砌内部状态。

### 1.3 科学图件工程适配说明
- **毫米物理标尺与指针锚定缩放**：macOS 官方 Preview.app 的常规图片查看器默认不带动态物理毫米标尺。本实现中的顶/左双向 mm 标尺与以鼠标指针为锚点的视口居中变换，是针对学术出版计量校验需求、借鉴专业 CAD/DTP 排版审校软件开发的工程实现，特此说明，不掠归为 Preview.app 原生自带特性。
- **Windows Web UI 原生适配**：完全剥离仿 macOS 风格的红黄绿窗口控制球 (Traffic Lights)；使用 Windows 原生字体栈（`Segoe UI`、`Microsoft YaHei`、`PingFang SC`）；严格遵守安全策略 (CSP: `default-src 'self'`)，不加载任何远程 CDN 字体或脚本。

---

## 2. 界面文案通俗化与去技术黑话对照表 (Old → New Rationale)

秉持「第一眼通俗中文」原则，消除「图元」、「帧摘要」、「渲染像素完全吻合」等过度工程化的黑话，区分显示控制与正式出图，将技术细节收纳至折叠卡片中。

### 2.1 核心术语与交互用语演进

| 界面元素 / 交互状态 | 旧文案 (Old) | 新文案 (New) | 改进理由与 UX 依据 |
| :--- | :--- | :--- | :--- |
| **基础术语 (全局)** | 图元 (Primitive) | **对象 (Object)** | 「图元」属于底层图形学渲染术语，对普通用户晦涩；「对象」是自然且直观的通用称谓。 |
| **引线说明 (重点)** | 科学锚点固定，引线可随关联标签重建，本界面不能编辑或独立拖端点。 | **移动标签时，引线会跟着调整；指向峰的位置不变。这里不能单独移动引线。** | 消除主被动混杂与学术词汇，用因果明晰的短句说明标签与引线的从属关系，直白告知引线不可单拖。且不再将锚点浮点数组堆在主面板上。 |
| **位置调整按钮** | 试算排版 / 运行试算 | **检查排版** | 符合 HIG Writing 动作导向原则（动词开头），消除「试算」这一内部工程算法行话。 |
| **接受调整按钮** | 接受 / Accept / 接受到会话 | **保留这次调整** | 彻底杜绝可能联想到「保存到文件」或「正式出图」的误导，配合提示文字限定在当前服务中。 |
| **服务时效提示** | 仅本次打开有效，未保存到文件 | **只保留在当前服务中，未保存到文件；停止服务后会丢失** | 准确区分浏览器窗口与后端服务的生命周期：同一后端服务存活期间，刷新或重新打开浏览器页面仍能取回已保留的内存操作；一旦停止或重启服务，未写盘的调整即丢失。既不夸大为永久保存，也不误导为关页即丢。 |
| **取消按钮** | 取消 / Cancel / 取消候选 | **取消** | 保持极简克制，符合日常直觉。 |
| **撤销按钮** | 撤销 / Undo / 撤销操作 | **撤销调整** | 直观清晰，无选定对象时依然常驻可用。 |
| **模式徽章 (可试调)** | READ_ONLY / 会话试算 | **可试调 / 不改原文件** | 直击用户最关心的两个问题：能不能调（能）、会不会弄坏磁盘源文件（不会）。 |
| **模式徽章 (只读图件)** | READ_ONLY / 只读快照 | **仅查看** | 简短直接，不带工程术语。 |
| **清晰度 120 DPI** | 120 DPI / 标准清晰度 | **流畅 (120 DPI)** | 提示：`流畅视图 (120 DPI)，仅改变显示`。消除「标准」的诱导性，明确仅为显示清晰度切换。 |
| **清晰度 240 DPI** | 240 DPI / 高清打印清晰度 | **清晰 (240 DPI)** | 提示：`清晰视图 (240 DPI)，仅改变显示`。不再使用「打印级」等误导性词汇。 |
| **清晰度 600 DPI** | (无) / 出版原图清晰度 | **精细 (600 DPI)** | 提示：`精细视图 (600 DPI)，仅改变显示`。准确描述最高显示渲染档位，高亮与当前图像 DPI 精确同步。 |
| **编号与调整权限** | 稳定标识（支持排版调整） | **固定编号 / 本次临时编号**，另列 **位置调整** | 编号稳定不等于授权编辑。分别说明“可以试调，检查通过后才能保留”“可以示范位置，不能保留修改”或“仅查看”，不混淆示范与真实重建。 |
| **引线类型误标** | 数据曲线 (Curve) | **引线 (Guide)** | 引线在底层 Matplotlib 中虽可能为 Line2D，但在用户界面必须明确标为「引线」，绝不误导为数据曲线。 |
| **科学文本 Mathtext** | `Ar–OCH$_3$` | **Ar–OCH₃** | 只转换有明确对应字符的数字上下标片段。普通名称的下划线、大小写、字母下标与单独的 `$` 原样保留，不做通用公式解析。原始字符串仍可在技术详情查看。 |
| **显示位置与尺寸** | `[20.45, 21.79, 22.14, 24.41]` | **水平 x: 20.450 mm, 垂直 y: 21.792 mm · 宽 1.688 mm × 高 2.413 mm** | 4 个浮点数坐标数组对人类不友好；拆解为 x/y 与宽高尺寸，统一保留 3 位小数。 |
| **次级技术数据** | 折叠卡片：高级技术细节与凭证 | **折叠卡片：详细技术参数** | 消除「凭证」黑话，与 Apple Preview「详细信息 (More Info)」规范对齐，GID/原始文本/哈希默认折叠。 |
| **系统底栏卡片** | 系统与校验凭证 | **系统与校验信息** | 消除「凭证」用词，显示输出范围、图像版本与渲染引擎。 |
| **候选操作提示** | 当前有正在调整的候选… | **当前有未完成的位置微调；请先保留或取消，再选择其他对象** | 消除底层「候选 (candidate)」概念，通俗直白告知用户必须完成或放弃当前微调。 |
| **排版校验中状态** | 正在进行真实排版试算与几何安全校验… | **正在重新绘图并检查新位置…** | 消除「试算」与机械堆砌，日常口语直观描述重绘与位置核对过程。 |
| **峰位锚点参数** | 科学峰位锚点 | **峰位锚定数据** | 折叠参数区去除「科学锚点」工程词汇，保持事实精确与安全只读。 |
| **安全质检项** | 质检项 | **安全检查** | 日常化词汇，准确传达几何重叠与越界安全检查的含义。 |
| **配置缺失提示** | 普通图件缺少可信重建支持，无法撤销 | **当前图件无对应配置，无法撤销** | 消除「可信重建」抽象术语，直指缺少 YAML 配置这一根本原因。 |
| **无名称对象** | `curve: fig2_nmr.main.curve…` | **曲线 3** 等中文类别与本帧序号 | 不把程序编号当人类名称；真实 ID 仍在技术详情，序号不冒充持久身份。 |

---

## 3. 实测验证与证据记录 (Truthful Observed Evidence)

测试分为两组独立验证：
1. **6 节点基线夹具全交互验证 (Fixture Suite)**：验证微调、15 次 Alt+Up 聚集、试算、保留、取消回滚、空选撤销、窄屏响应等 31 项交互逻辑。
2. **真实 08 NMR 谱图选择与引线锁死验证 (Real NMR Suite)**：验证 600 DPI 真实化学位移谱图、Unicode 分子式美化与引线绝对防篡改规则。

### 3.1 真实运行环境
- **操作系统**：Windows 11 x64 (Build 26200)
- **Python 实际版本**：`Python 3.14.0` (`D:/programs/Python/python.exe`)
- **Node.js 实际版本**：`v24.11.1` (`C:/Program Files/nodejs/node.exe`)
- **图形后端**：Matplotlib RendererAgg
- **端到端浏览器**：Playwright Chromium 1208 (`chrome-win64`)

### 3.2 实测结果与日志证据

#### A. Node 核心算法与行为套件 (`tests/inspector/test_inspector.js`)
- **用例总数**：39 tests (0 suites)
- **通过数量**：39 pass, 0 fail
- **代理实测耗时**：`29.2483 ms`；最终主线整合运行 `105.7293 ms`。这是独立运行，不是百分位统计。
- **主要覆盖项**：几何命中（多段线距离、容差）、视口居中算式与锚点缩放不变性、防篡改哈希核对、15 次 Alt 聚集单个操作、空选独立撤销栈管理等。

#### B. 6 节点夹具端到端全流程验证 (`verify_browser.py`)
- **检查总数**：31 checks
- **通过数量**：31 pass, 0 fail
- **控制台错误**：0 errors
- **实测耗时**：`9.09 s`
以下为 UI 代理在隔离工作树验证时的原始日志摘录。主线整合后进一步简化了状态提示、区分“仅示范”与“可验证”，并修正科学文本显示；最终主线复核见 [显示清晰度与最终验收记录](INSPECTOR_DISPLAY_QUALITY.md)。
- **实测日志摘录**：
  ```text
  [PASS] Initial Mode Badge badge: 可试调 / 不改原文件
  [PASS] Initial Integrity Status status: 图片已加载 · 尺寸核对一致
  [PASS] Default DPI Highlight 600 DPI highlighted active
  [PASS] Viewport Centering wrap: 1064x672.8125, vp: 979.5x653
  [PASS] Zoom In Button 979.5 -> 1224.375
  [PASS] View Reset Button 1224.375 -> 979.5
  [PASS] Sidebar Toggle Open Object list panel visible
  [PASS] Object List Count 共 6 个对象（总计 6 个）
  [PASS] Select Node A selected: intent.main.A
  [PASS] Detail Fields Plain Chinese fields formatted in clear Chinese
  [PASS] Collapsed Technical Details Present technical details tucked in details element
  [PASS] 15 AltUp Nudge Intent dy: 0.15, disp: 本次调整：ΔX 0 mm, ΔY 0.15 mm, badge: 示范中（未进行排版试算）
  [PASS] Evaluate Button Enabled btn-evaluate enabled for candidate
  [PASS] Evaluate Successful 状态：通过 · 验证：真实渲染几何检验通过; accept disabled=False
  [PASS] Accept A into Session 已保留本次调整（仅本次打开有效，未保存到文件）
  [PASS] Nudge B B dx=0.1
  [PASS] Cancel B Preserves A 已取消本次调整，已保留的历史不受影响
  [PASS] Deselected selected: ''
  [PASS] Undo Available Without Selection btn-undo enabled when no node selected
  [PASS] Undo B Completed 已撤销上一步调整，已恢复之前的状态; undo still available=True
  [PASS] Guide Notice Exact Phrase 移动标签时，引线会跟着调整；指向峰的位置不变。这里不能单独移动引线。
  [PASS] Guide Endpoint Editing Disabled inputs disabled for guide
  [PASS] Narrow Screen Responsive Layout stage y: 133.5, detail y: 650.296875
  [PASS] Plain Figure Badge 仅查看
  [PASS] Ephemeral Notice 该对象属于本次临时编号元素，仅在当前画面有效；不支持试调。
  [PASS] Plain Figure Eval/Accept Disabled eval disabled: True, accept disabled: True
  [PASS] No Console Errors found 0 errors: []
  ```

#### C. 真实 08 NMR 谱图加载验证 (`verify_nmr_real.py`)
- **被测图件**：`examples/nmr/08 NMR.py` + `nmr.yaml`，加载真实化学数据（600 DPI）
- **实测耗时**：`5.92 s`
- **实测日志**：
  ```text
  NMR Server running at http://127.0.0.1:13958
  DPI 600 active: True
  Label Name Displayed: 'Ar–OCH₃'
  Raw Text Displayed: 'Ar–OCH$_3$'
  Saved screenshot: I:\figpact-test-archive\Inspector-Apple-1e57ee4\screenshots\nmr_3p91_label.png
  Guide Annotation: '移动标签时，引线会跟着调整；指向峰的位置不变。这里不能单独移动引线。'
  Saved screenshot: I:\figpact-test-archive\Inspector-Apple-1e57ee4\screenshots\nmr_3p91_guide.png
  All Real NMR 08 NMR.py UI checks passed!
  ```
- **关键实测事实**：
  1. 真实 3.91 ppm 文本（`fig2_nmr.main.peak.vancho.3p91`）在主界面正确渲染为分子式 `Ar–OCH₃`；
  2. 原始 `Ar–OCH$_3$` 正确保留在折叠技术卡片内；
  3. 真实引线（`fig2_nmr.main.guide.vancho.3p91`）选中后呈现纯净的规定文案，未追加任何数组乱码，其坐标微调输入框被严格锁定。

#### D. 独立端到端复核实测 (Review Suite, `run_browser_verification.py`, 2026-10-12)
- **代码分支与基线**：`inspector-apple-review-aa2` (Baseline `aa2f604f9ae23825cacad05eed104dea4dd612c3`)
- **运行环境**：
  - 操作系统：Windows 11 x64 (Build 26200)
  - Python：`Python 3.14.0` (`D:/programs/Python/python.exe`)
  - Node.js：`v24.11.1` (`C:/Program Files/nodejs/node.exe`)
  - 隔离测试工作区：`I:/figpact-test-archive/Inspector-Apple-Review-aa2f604/`
  - 自动化端到端测试工具：Playwright Chromium 1208
- **实测数据与事实**：
  1. **Node 核心算法与纯逻辑套件** (`tests/inspector/test_inspector.js`)：
     - **39 tests (0 suites)**, 全部通过 (**39 pass, 0 fail**), 耗时 **93.8 ms**。
  2. **原生真实 08 NMR 独立服务实测** (`--script "08 NMR.py"` + `--config "nmr.yaml"`，600 DPI)：
     - 初始状态：徽章 `可试调 / 不改原文件`，状态 `图片已加载 · 尺寸核对一致`。
     - 选中 3.91 ppm 标签 (`fig2_nmr.main.peak.vancho.3p91`)：显示名称渲染为分子式 `Ar–OCH₃`，原始文字 `Ar–OCH$_3$` 正确保留在折叠详情中。
     - 15 次 Alt+Up 键盘微调：ΔY 准确达到 0.15 mm（微调输入框数值与位移文案精确联动）。
     - 点击「检查排版」(`#btn-evaluate`)：后端返回状态 `OK`、验证等级 `RENDER_CHECKED`；实测位移 `[0.0, 0.1500000000000039] mm`；峰位引线科学误差 `0.0 mm`（数据峰位端点绝对锁定）；状态面板显示 `状态：通过 · 验证：已重新绘图，位置检查通过`。
     - 点击「保留这次调整」(`#btn-accept`)：成功更新内存帧；时效提示精准显示 `只保留在当前服务中，未保存到文件；停止服务后会丢失`。
     - 选中 3.91 ppm 引线 (`fig2_nmr.main.guide.vancho.3p91`)：严格显示提示文案 `移动标签时，引线会跟着调整；指向峰的位置不变。这里不能单独移动引线。`，输入框与微调按钮被完全锁定禁用；技术折叠卡片清晰标明 `峰位锚定数据`。
  3. **无 YAML 普通图件独立服务实测** (`--example plain`，600 DPI)：
     - 初始状态：徽章显示 `仅查看`。
     - 选中对象：提示 `不会修改原图。可移动对象的轮廓来示范位置，但不能保留到图中。`
     - 15 次 Alt+Up 微调示范：状态徽章准确显示 `位置示范，尚未验证`。
     - 权限保护：`#btn-evaluate` 禁用（提示 `这个对象可以示范位置，但无法重新绘图验证`），`#btn-accept` 禁用（提示 `该图件无配置文件，不能保留修改`）。


#### E. 主线最终验收：易读反馈、能力提示与现有清晰度
- **做了什么**：从 `aa2f604` 开始，UI 独立任务使用 `google-antigravity/gemini-3.8-flash:auto`，在 I 盘隔离工作区调研 Apple Preview 与 Apple HIG。沿用已经完成的苹果式布局，收口按钮、说明与空状态；没有重新开发几何或编辑内核。
- **文案边界**：主线进一步把“无配置文件所以不能保留”改成“这张图只能查看和示范，不能保留修改”。是否能编辑取决于接入能力，不等同于是否有 YAML。清晰度不可切换时说明“暂不支持重新绘制”，不错误归因于缺少配置。
- **安全结果易读化**：主界面分别显示“科学内容、排版安全、目标位置、其他对象”的检查结果；原始记录仍在折叠的技术参数中。未知结果显示“未确认”，没有明细时明确说明，不宣称全部通过。
- **修改有效期**：已保留操作只在当前 Python 服务中生效，没有保存到文件。关闭浏览器页面不等同于停止服务；停止服务会丢失这些操作。本次没有实现 G3 History。
- **实际测试模型**：原生测试子代理明确使用 `opencode-go/step-5-preview-free`，没有程序化批量启动或替换模型。
  - 最终 JS 的 Node 套件：**39 通过、0 失败、0 跳过，143.2494 ms**；实际墙钟 0.33 s。
  - 本轮现有 `tests/test_intents.py`：**23 通过、0 失败、0 跳过，11.19 s**；实际墙钟 17.42 s。已有 Requests 依赖版本警告保留，没有屏蔽。
  - 没有重新运行全量 Python 套件。`aa2f604` 的 **312 通过、7 跳过、73 subtests 通过**属于历史基线，不冒充本轮结果。
- **真实 NMR 浏览器操作**：主线独立服务完成 17 项交互检查，包括 A 接受后取消 B、撤销已接受 B 都保留 A 的实际图像。3.91 ppm 标签目标上移 **0.15 mm**，实际 **0.1500000000000039 mm**，引线指向峰的端点变化 **0 mm**，验证等级为 `RENDER_CHECKED`。点击检查到可保留 **2.2555542 s（单次）**，不是 P95 或完整 Agent 任务耗时。
- **最后的反馈检查**：最终文案改动后，再次实际重新绘图验证 3.91 ppm 标签；四项检查仍为真实 `PASS`，主界面显示中文结果，技术参数保留原始记录且默认折叠。候选已取消，不给用户留测试调整。这些毫米值是同一渲染环境的结果，不代表物理精度校准。
- **普通无 YAML Figure**：实际选中对象并用 15 次 Alt+Up 示范上移 0.15 mm；原底图引用不变，检查与保留按钮禁用，说明与权限一致。没有实现无 YAML 编辑或源码写回。
- **当前显示实测**：新服务 NMR 为 **600 DPI、1133 × 1133 px**；普通图为 **600 DPI、1889 × 1181 px**。在本次浏览器窗口中没有放大到超出底图像素。读取用户原有 Chrome 页面超时，无法确认原页面是否有旧缓存或更大缩放；没有替换或清空其现有会话。
- **低 DPI 与 SVG**：120/240 DPI 保留供大图降低像素缓冲、编码与传输负担；本轮未重跑既有性能比较。已有实际 SVG 导出可行性与 Agg/SVG 字框差异记录见 `INSPECTOR_DISPLAY_QUALITY.md`。仍未启用 SVG 底图，未混用两种 renderer 的几何，也未开发 G3、Python 写回或新保存权限。
- **完整证据位置**：`I:/figpact-test-archive/Inspector-Apple-Review-aa2f604/final-regression/` 为真实测试 stdout/stderr；`parent-final/` 为主线浏览器结果与截图，包含 `nmr-proof.json`、`plain-proof.json`、`human-feedback.json`、`human-feedback.png`；`parent-preview/` 为实际 DPI 与显示比例记录。
---

## 4. 产物与截图归档清单

### 4.1 历史实测存档
归档路径：`I:/figpact-test-archive/Inspector-Apple-1e57ee4/screenshots/`
- `initial.png`、`label_candidate.png`、`guide.png`、`plain.png`、`nmr_3p91_label.png`、`nmr_3p91_guide.png`、`browser_verification.json`。

### 4.2 本轮独立审查实测存档 (Branch `inspector-apple-review-aa2`)
归档路径：`I:/figpact-test-archive/Inspector-Apple-Review-aa2f604/screenshots/`
- `nmr_3p91_candidate.png`：原生 NMR 3.91 ppm 标签 0.15 mm 微调候选与幽灵引线联动视口。
- `nmr_3p91_accepted.png`：通过排版检查并成功保留调整后的状态与服务时效提示。
- `nmr_3p91_guide.png`：3.91 ppm 引线选中时的峰位锚定数据折叠与防篡改输入禁用保护。
- `plain_readonly_ghost.png`：无 YAML 普通图件的 0.15 mm 纯轮廓示范、重绘禁用与未配置说明。
- `browser_proof.json`：存放于 `I:/figpact-test-archive/Inspector-Apple-Review-aa2f604/browser_proof.json` 的自动化端到端实测结构化证据记录。

## 5. 架构边界与不变性 (Architectural Limits)

1. **绝对禁止前端写入磁盘**：
   - 检查器虽然提供「保留这次调整」操作，但其本质是向后端发送 `accept` 决策，更新当前进程内的内存帧，**绝不具备**写入 `.py`、`.yaml` 或重新输出出版级文件的路由与能力。
2. **Agg 光栅与 SVG 矢量的度量差异**：
   - 同一真实 Figure 的导出试验中，Agg 与 SVG renderer 测得的对象 bbox 最大差为 0.238 mm；这不是科学峰位变动，也不是完整精度校准。检查器仍以配帧 Agg PNG 为底图，SVG 只作为现有高亮覆盖；尚未实现 SVG 底图显示。
3. **引线不可独立移动**：
   - 引线的科学起点锚定在分子光谱的物理峰位上，其位置由科学数据清单保护，不开放端点自由拖拽，只允许跟随关联标签的重排而联动调整。
