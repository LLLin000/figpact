# Figpact 检查器 UI/UX 规范与实测报告 (Apple Preview 启发版)

本文档记录了 figpact 检查器从早期工程测试界面重构为「Apple 预览 (Preview) 启发式对象检查器」的设计决策、官方规范引用、通俗中文文案演进对照、实测数据与边界限制。

---

## 1. 规范来源与官方文档依据 (Primary Sources & URLs)

本界面的视觉结构、操作层级与信息收折设计参考了 Apple 官方人机交互指南 (HIG) 与 macOS Preview 官方用户手册，并根据科学图件审查需求进行了必要的工程适配：

### 1.1 官方人机交互规范 (HIG)
1. **Toolbars (工具栏)**
   - **URL**: `https://developer.apple.com/design/human-interface-guidelines/toolbars`
   - **规范要点与支持项**：工具栏保持静雅克制 (Quiet & Unobtrusive)，仅放置与当前视图强相关的全局控制项；使用分段控件 (Segmented Controls) 呈现互斥选项（如显示清晰度选择）；按钮使用清晰的文字配合辅助说明；避免无关花哨装饰。
2. **Inspectors (检查器)**
   - **URL**: `https://developer.apple.com/design/human-interface-guidelines/inspectors`
   - **规范要点与支持项**：检查器作为上下文面板，聚焦展示当前所选对象的详细属性；严格区分主要常用属性与次要高级细节；将技术标识、哈希、底层协议等高级信息收纳在折叠区 (Disclosure/Details)，不干扰首屏阅读。
3. **Sidebars (侧边栏)**
   - **URL**: `https://developer.apple.com/design/human-interface-guidelines/sidebars`
   - **规范要点与支持项**：提供平级的大纲/对象列表导航，支持一键切换展开与收起；大纲列表项清晰展示对象可读名称与类型类别。

### 1.2 Apple Preview (预览) 官方手册
1. **Preview User Guide for Mac (macOS 预览用户手册)**
   - **URL**: `https://support.apple.com/guide/preview/welcome/mac`
2. **Inspect an image or PDF in Preview (检查图像或 PDF)**
   - **URL**: `https://support.apple.com/guide/preview/inspect-an-image-or-pdf-prvw1043/mac`
   - **规范要点与支持项**：检查器清晰分离「通用基础信息 (General Info)」与「详细元数据 (More Info/EXIF)」；展示图件页面物理尺寸、分辨率 (DPI) 与颜色通道。
3. **Zoom in or out on an image (缩放图像)**
   - **URL**: `https://support.apple.com/guide/preview/zoom-in-or-out-on-an-image-prvw1040/mac`
   - **规范要点与支持项**：提供缩小 (-)、放大 (+) 与适应窗口 (Zoom to Fit) 的三态基础操作。

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
| **位置微调按钮** | 应用位移 / 设置位移 | **预览这个位置** | 在点击「试算排版」之前，该微调仅仅是前端视口上的临时预览，用「预览这个位置」避免用户误以为已经生效。 |
| **接受调整按钮** | 接受 / Accept / 接受到会话 | **保留这次调整** | 彻底杜绝可能联想到「保存到文件」或「正式出图」的误导，配合提示文字限定在当前打开的会话中。 |
| **会话时效提示** | (无或长句) | **仅本次打开有效，未保存到文件** | 醒目、直接地告知调整的作用边界，源文件受保护。 |
| **取消按钮** | 取消 / Cancel / 取消候选 | **取消** | 保持极简克制，符合日常直觉。 |
| **撤销按钮** | 撤销 / Undo / 撤销操作 | **撤销调整** | 直观清晰，无选定对象时依然常驻可用。 |
| **模式徽章 (可试调)** | READ_ONLY / 会话试算 | **可试调 / 不改原文件** | 直击用户最关心的两个问题：能不能调（能）、会不会弄坏磁盘源文件（不会）。 |
| **模式徽章 (只读图件)** | READ_ONLY / 只读快照 | **仅查看** | 简短直接，不带工程术语。 |
| **清晰度 120 DPI** | 120 DPI / 标准清晰度 | **流畅 (120 DPI)** | 提示：`流畅视图 (120 DPI)，仅改变显示`。消除「标准」的诱导性，明确仅为显示清晰度切换。 |
| **清晰度 240 DPI** | 240 DPI / 高清打印清晰度 | **清晰 (240 DPI)** | 提示：`清晰视图 (240 DPI)，仅改变显示`。不再使用「打印级」等误导性词汇。 |
| **清晰度 600 DPI** | (无) / 出版原图清晰度 | **精细 (600 DPI)** | 提示：`精细视图 (600 DPI)，仅改变显示`。准确描述最高显示渲染档位，高亮与当前图像 DPI 精确同步。 |
| **编号属性展示** | 稳定标识（支持排版调整） | **固定编号** 或 **本次临时编号** | 修正错误：稳定 ID 仅代表对象有持久命名，**并不等于**授权编辑。微调权限另外以独立字段「支持本次微调」展示。 |
| **引线类型误标** | 数据曲线 (Curve) | **引线 (Guide)** | 引线在底层 Matplotlib 中虽可能为 Line2D，但在用户界面必须明确标为「引线」，绝不误导为数据曲线。 |
| **科学文本 Mathtext** | `Ar–OCH$_3$` | **Ar–OCH₃** | 通过 Unicode 自动美化常见上下标分子式，原始 `Ar–OCH$_3$` 收纳进次级技术详情。 |
| **显示位置与尺寸** | `[20.45, 21.79, 22.14, 24.41]` | **水平 x: 20.450 mm, 垂直 y: 21.792 mm · 宽 1.688 mm × 高 2.413 mm** | 4 个浮点数坐标数组对人类不友好；拆解为 x/y 与宽高尺寸，统一保留 3 位小数。 |
| **次级技术数据** | (全部平铺在首屏) | **折叠卡片：高级技术细节与凭证** | GID、ID、原始字符串、锚点 JSON、源码版本哈希全部默认收起在 `<details>` 中，按需展开。 |
| **初始状态提示** | 正在校验帧完整性… | **图片已加载 · 尺寸核对一致** | 自然通顺，消除过于机械的「帧摘要/像素吻合」等表述。 |

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
- **实测耗时**：`29.2483 ms`
- **主要覆盖项**：几何命中（多段线距离、容差）、视口居中算式与锚点缩放不变性、防篡改哈希核对、15 次 Alt 聚集单个操作、空选独立撤销栈管理等。

#### B. 6 节点夹具端到端全流程验证 (`verify_browser.py`)
- **检查总数**：31 checks
- **通过数量**：31 pass, 0 fail
- **控制台错误**：0 errors
- **实测耗时**：`9.09 s`
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

---

## 4. 产物与截图归档清单

所有实测生成的截图与数据凭证存放在：
`I:/figpact-test-archive/Inspector-Apple-1e57ee4/screenshots/`
- `initial.png`：6 节点夹具会话的初始干净视口（600 DPI，居中放置）。
- `label_candidate.png`：微调示范状态（蓝色虚线幽灵外框与联动引线端点）。
- `guide.png`：夹具引线被选中时的防篡改说明与禁用输入状态。
- `plain.png`：无 YAML 普通 Matplotlib 图件（仅查看模式，临时编号，试算禁用）。
- `nmr_3p91_label.png`：真实 08 NMR 谱图选中 3.91 ppm 标签时的易读检查器面板。
- `nmr_3p91_guide.png`：真实 08 NMR 谱图选中 3.91 ppm 引线时的严格保护文案面板。
- `browser_verification.json`：`verify_browser.py` 的结构化校验记录。

---

## 5. 架构边界与不变性 (Architectural Limits)

1. **绝对禁止前端写入磁盘**：
   - 检查器虽然提供「保留这次调整」操作，但其本质是向后端发送 `accept` 决策，更新当前进程内的内存帧，**绝不具备**写入 `.py`、`.yaml` 或重新输出出版级文件的路由与能力。
2. **Agg 光栅与 SVG 矢量的度量差异**：
   - 测试表明 Matplotlib RendererAgg 与纯 SVG 文本包围盒存在最大 0.238 mm 的字形度量误差。检查器坚持以 Agg 光栅图为底图，SVG 仅做无害高亮覆盖，不宣称实现了纯矢量 SVG 排版引擎。
3. **引线不可独立移动**：
   - 引线的科学起点锚定在分子光谱的物理峰位上，其位置由科学数据清单保护，不开放端点自由拖拽，只允许跟随关联标签的重排而联动调整。
