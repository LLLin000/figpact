# Inspector 清晰度与 SVG 调研

基线 `1e57ee435850dda3055a87f574028c6a56f0a44d`；Windows、Python 3.14、Matplotlib 3.10.8。本记录只讨论 G1/G2 的显示，不扩展编辑权限、源码写回或正式出版。

## 结论

对当前 48 × 48 mm FTIR/NMR，120 DPI 预览省下的时间不足以抵消明显模糊。本机 Inspector 入口改为默认 **600 DPI**，保留 120/240 的选择。600 是这两套脚本现有 PNG/TIFF 出版值，不是从任意用户 Figure 猜出的“原图分辨率”。Python SDK 不指定显示 DPI 时仍尊重原 Figure；普通外部 Figure 不为清晰度被偷偷改动。

SVG 能从已经构建的 Figure 生成，即使用户脚本没写 SVG 导出；无需修改科学绘图脚本。但本次不把 SVG 接进现有 PNG 帧协议：实际 SVG 文字几何和 Agg 不相同，旧测量坐标不能直接复用。更清晰的 PNG 先解决当前阅读问题。

## 实测 DPI 代价

使用真实科学输入和原生 `FigureSession.build_candidate()`，预热后固定随机顺序，每个 DPI **N=3**，记录中位数。每次新建 Figure，使用同一科学载荷与样式，再执行 `capture_figure()`：实际 Agg draw、Scene、PNG、摘要配帧。不是完整 G2 试算、浏览器往返、冷启动或 Agent 总耗时；N=3 不报告可靠 P95。

| 图 / DPI | 配帧秒数 | PNG 字节 | 像素尺寸 | RGBA 缓冲字节 | 整帧 JSON 字节 |
|---|---:|---:|---|---:|---:|
| NMR / 120 | 0.666 | 16,571 | 226 × 226 | 204,304 | 4,053,347 |
| NMR / 240 | 0.673 | 39,299 | 453 × 453 | 820,836 | 4,083,726 |
| NMR / 360 | 0.686 | 61,399 | 680 × 680 | 1,849,600 | 4,112,915 |
| NMR / 600 | 0.705 | 110,883 | 1133 × 1133 | 5,134,756 | 4,178,652 |
| FTIR / 120 | 0.483 | 16,070 | 226 × 226 | 204,304 | 2,984,416 |
| FTIR / 240 | 0.513 | 39,155 | 453 × 453 | 820,836 | 3,015,204 |
| FTIR / 360 | 0.508 | 59,993 | 680 × 680 | 1,849,600 | 2,994,381 |
| FTIR / 600 | 0.506 | 109,576 | 1133 × 1133 | 5,134,756 | 3,014,497 |

RGBA 是按实际宽 × 高 × 4 算出的**单个像素缓冲大小**，不是测得的 Python/浏览器总内存；进程峰值和浏览器 GPU 内存尚未测量。120→600 像素缓冲约 25 倍，但仍约 5.1 MB。NMR PNG 多约 94 KB，整帧 JSON 只多约 125 KB；主要帧体积来自曲线几何，不是低清 PNG。因此降低 DPI 确实减少绘制、PNG 编码/传输、图片解码和纹理负担，不能说完全没用，但对这两张小图不值得作为默认。大型显微图、多面板和密集散点应另测，不能推广此代价。

另记录原生 build 中位数：NMR 各 DPI 约 0.077–0.080 s，FTIR 约 0.114–0.121 s。默认清晰度不会提高 science 加载频率，不在每次方向键按下时重建图。

## 为什么不能直接用正式 PNG 或直接把底图替换为 SVG

1. 现有 `figure_style.apply()` 设置的是 Figure DPI **120**，`figure_style.export()` 的 PNG/TIFF 默认是 **600**。两者不同；当前 Inspector 并没有把现成 600 DPI PNG 压低，而是从 120 DPI Figure 直接取得新帧。
2. Inspector 显示同一次绘制中的图像和对象位置。正式产物可能经过 `bbox_inches='tight'`、另一个配置或 revision；拿它覆盖当前图片会改变裁剪原点或对象位置，却保留旧命中结果。
3. 当前前端外层已是 SVG（毫米 viewBox、标尺、高亮、ghost），底图是 `<image>` 内的 PNG。这不等于整幅科研图已经矢量化。
4. 切换 DPI 必须重新绘制、测量和生成 revision；不得只把 image 的 href 换成高清图。已有待处理/已接受操作时仍拒绝质量切换，防止旧证明跨 renderer 复用。

## SVG 原型事实

研究脚本实际对同一个新建 Figure 调用 `fig.savefig(BytesIO(), format='svg', bbox_inches=None)`，设置 `svg.fonttype='path'` 和去掉时间元数据，产物只放在 I 盘。导出前后科学载荷相同、151 个原 examples 文件 SHA-256 不变；无用户 Python、YAML 或正式产物被写入。

| 图 | SVG 字节 | SVG 导出秒数（N=1，仅已构建 Figure 导出） | Agg600 / SVG 注册文字 bbox 最大角点差 mm |
|---|---:|---:|---:|
| NMR | 63,365 | 0.056 | 0.2320 |
| FTIR 标注版 | 68,709 | 0.029 | 0.2381 |

SVG 使用真实 `RendererSVG` 的 72 pt/in 坐标，毫米按 25.4/72 换算；对实际注册文字调用该 renderer 的 `get_window_extent()` 并与配帧 Agg600 比较。NMR **3.91 ppm 标签差 0.1369 mm**。这是 renderer 几何差异，不是峰位改变；也不是已经标定的肉眼轮廓误差。曲线文字混合时 SVG 更小、更适合放大，但只统计导出时间不能声称完整 SVG Inspector 会更快。

## 若后续接 SVG，最小正确路径

- 输入仍是已构建的真实 Matplotlib Figure；没有 YAML 不影响导出。脚本若不返回 Figure，需要先得到可信 Figure 入口，而不是让服务器任意执行用户上传脚本。只有 PNG 无法恢复真实曲线、文本身份或矢量细节，不能“转存 SVG”就冒充矢量化。
- 使用实际 SVG renderer 取得图像和同 renderer 几何；固定整个画布，不使用 tight 裁剪，统一 SVG viewBox 的 pt 与毫米、上下原点、clip 和 transform。不能让 savefig 产出的 SVG 搭配 Agg bbox。需验证字形、数学文字、旋转、虚线、clip、collection、图像、FigureImage 与目标引线。
- 文字先转 path，避免缺字体/浏览器字体度量造成漂移；照片、栅格化 Artist 仍是嵌入图片，SVG 不能凭空增加科学像素细节。密集路径可能增加 DOM/绘制负担，需实测，保留经验证的 PNG 路径。
- 在现有配帧协议上做明确的格式/revision 变更和负例验证；同时提供 PNG 回退。优先作为隔离 SVG 图片显示，不把任意 SVG 当可信 HTML 内联：脚本、外链、foreignObject、事件、资源大小及 CSP 都要保护。鼠标身份仍使用同帧 Scene，不靠 SVG 内部编号猜 GID。
- 首先验收真实 NMR 3.91 ppm 和 guide 的 Hover/Click、.15 mm 目标验证、原点/图像尺寸、取消恢复、无 YAML 只读和科学一致性，再决定是否默认使用。**这条 SVG 接入尚未实现；本次只完成原型与测量，不冒充功能。**

## 可复核产物与来源

实测脚本及数据：`I:/figpact-test-archive/Inspector-Apple-1e57ee4/display_benchmark.py` 与 `display/{results.json,before-sha256.json,after-sha256.json,nmr-120.png,nmr-600.png,ftir-120.png,ftir-600.png,nmr-same-figure.svg,ftir-same-figure.svg}`。归档保留可重跑探针，不把一次性基准塞进永久测试。360 DPI 是研究点，不新增无必要的 UI 档位。

- [Matplotlib Figure.savefig](https://matplotlib.org/stable/api/_as_gen/matplotlib.figure.Figure.savefig.html)：可写 file-like、选择 SVG/PNG、DPI 与 bbox 参数。
- [Matplotlib Artist.get_window_extent](https://matplotlib.org/stable/api/_as_gen/matplotlib.artist.Artist.get_window_extent.html)：canvas/DPI/transform 变化会影响 extent，不能复用旧测量。
- [实际安装版本 Matplotlib 3.10.8 SVG backend](https://matplotlib.org/3.10.8/api/backend_svg_api.html)：`FigureCanvasSVG.fixed_dpi=72`、`RendererSVG`、文本/path/图像绘制。
- 仓库源证据：`examples/nmr/figure_style.py:216,518-536`、`examples/ftir/figure_style.py:216,518-536`、`examples/nmr/08 NMR.py:86,1492`；未修改这些脚本。

## 最终交付记录（按设计包模板）

### 工作事实

- Gate：G1 显示与文案收口，保留并回归现有 G2；不是新 Gate 的源码编辑能力。
- 开始 HEAD：`1e57ee435850dda3055a87f574028c6a56f0a44d`。UI 在 I 盘隔离工作树完成；整合提交为 `64c5c18`、`b64d7e0`，最终收口随本报告提交。
- 实际修改：`tools/inspector/{index.html,inspector.css,inspector.js}`、`figpact/{intents.py,inspector_server.py}`、`tests/test_intents.py`、`README.md`、`SKILL.md`、`CONTEXT.md`、本报告及 `docs/INSPECTOR_UI_UX.md`。
- 未修改：用户 examples 绘图脚本、YAML、科学输入、旧 YAML Agent API、Science/Scene/Geometry 核心与 strict 出版实现。用户未跟踪的 `docs/figpact-vnext-kit/` 不加入提交。
- 已有：真实路径选取、毫米标尺、配帧校验和会话内位置示范/验证/接受/撤销。本次新增：Apple Preview 启发式面板与短句、技术信息收折、默认 600 DPI 与同帧清晰度切换。尚未实现 SVG 底图、无 YAML 编辑或文件保存。

### 风险与权限

- 没有修改用户 `.py/.yaml`、科学载荷、显示窗、科学峰位、归属或正式产物。测试的 151 个 examples 文件独立 before/after SHA-256 相同。
- 真实 NMR `fig2_nmr.main.peak.vancho.3p91` 请求上移 0.15 mm，仅关联 `fig2_nmr.main.guide.vancho.3p91` 跟随；引线指向科学峰的位置误差 **0 mm**，标签端上移 **0.15000000000000213 mm**。其他对象仍由原有影响检查约束，不新增豁免。
- Figure 初始显示 DPI 与出版导出 DPI 是两个概念，词汇记录于 `CONTEXT.md`。调用者传入的普通 Figure 不被显示参数改变：173 DPI 和原 canvas 身份保留。
- UI 科学文字复核先发现 `sample_A → sampleₐ`、`$C_A$ → Cₐ`、`$5 → 5` 的显示错误，再限制格式化为明确的数字上下标片段。浏览器重验四种原文：普通名称、大小写字母下标、数字分子式、单独美元符号；无修改科学 Figure 原文。

### 验收

- 环境：Windows 11 x64、Python 3.14.0、Matplotlib 3.10.8、Node 24.11.1、实际 Chromium；所有测试临时目录和证据放 I 盘。
- 测试代理用原生 `task`，指定 `opencode-go/step-5-preview-free`。DPI 新负例先运行失败 **2 项**（尚无 constructor `dpi` 参数），实现后全量 pytest 只运行一次：
  ```text
  D:/programs/Python/python.exe -B -X utf8 -m pytest -q -rs -p no:cacheprovider --basetemp=I:/figpact-test-archive/Inspector-Apple-1e57ee4/final-regression/pytest-tmp --junitxml=I:/figpact-test-archive/Inspector-Apple-1e57ee4/final-regression/junit.xml -o addopts=""
  312 passed, 7 skipped, 73 subtests passed in 154.96s
  EXIT=0
  ```
- 跳过 **5 项符号链接权限用例、2 项缺少旧夹具用例**；没有减少或重新标记本次测试。原环境 requests 依赖警告仍在，不隐藏。
- 最终主线 Node：`node --test tests/inspector/test_inspector.js`，**39 通过、0 失败，105.7293 ms**。UI 代理的隔离夹具浏览器检查 **31/31、9.09 s**，真实 NMR 的选择/引线锁定检查 **5.92 s**；两者不是同一套实际数据测试。
- 父代理最终真实 NMR 浏览器复核 **17 个检查通过**：点击 3.91 ppm 标签、15 次 Alt+Up、实际试算、接受 A、取消 B 保留 A、接受 B 后撤销 B 保留 A。实测 A 位移 **0.1500000000000039 mm**，目标容差 **0.01 mm**。这个浮点误差不表示物理标定精度达到小数末位。
- 父代理还真实点击 3.91 ppm 引线：中文说明不拼接锚点数组、水平/垂直输入禁用、技术详情默认折叠。普通无 YAML Figure 的 0.15 mm 示范只改变轮廓：底图不变，试算/接受禁用，临时身份明确。
- 无名称对象使用“曲线 3”等中文类别和本帧序号，不再把底层 ID 当对象名称。真实曲线点击复核：正确选中科学曲线、输入禁用、技术详情收折；该次加载的实际 browser errors 返回空。证据 `parent-browser/{final-copy-proof.json,curve-final.png}`。
- 原生 600 DPI smoke **18.8279 s**：真实 FTIR/NMR 画布 48 × 48 mm，图像 1133 × 1133 px；240/600 同帧切换、接受后的质量锁定、独立取消/撤销与科学文件保护通过。该独立 smoke 移动的是 **9.83 ppm**；3.91 ppm 由上述父代理浏览器实测，不能混记。
- 普通无 YAML、173 DPI Figure 实际导出 SVG：**24,686 字节、0.02342 s，N=1 导出阶段**；科学载荷、173 DPI、canvas 身份均保留。没有启用 Inspector SVG 功能。
- 一次父代理完整截图触发 Chromium capture 超时；关闭并重新打开自己的验证页后，最终实际截图及完整交互复核成功。初版临时驱动错误地期待 cancel 响应携带新帧，按真实只取消候选契约改为读取当前帧；没有修改后端绕过问题。

### 性能与证据

- DPI 测量的冷/热边界、N=3 中位数、单位与随机顺序见上表。没有统计完整 Agent 任务中位数/P95、tokens 或整体绘图次数，不宣称 Agent 总任务提速。
- 最终真实 NMR 从点击“试算排版”到可“保留这次调整” **2.52806 s，N=1**，包含后端重建、传输、浏览器配帧核对与刷新；不能拿 0.705 s 单次 capture 冒充这个时间。
- 归档根：`I:/figpact-test-archive/Inspector-Apple-1e57ee4/`。
  - `final-regression/{pytest-full.log,junit.xml,smoke.log,smoke/results.json}`：完整测试与原生证据。
  - `parent-browser/{nmr-proof.json,guide-proof.json,plain-proof.json}`：实际按钮、目标数值和权限。
  - `parent-browser/{candidate.png,independent-undo.png,guide-final.png,plain-final.png}`：最终主线真实 UI，而非合成夹具。
  - `parent-browser/label-fidelity-{before,after}.json` 与 `parent-label-fidelity.mjs`、`label_fidelity.py`：显示负例和可重跑复核。
  - `screenshots/` 与隔离工作树文档：UI 代理独立检查。父代理未记录全流程 console 错误计数，不将调试用空数组作为“0 console 错误”证据。

### 下一步与不做事项

- 本次显示/文案/DPI 收口：**YES**；SVG 底图和 Tern 真机验收：**尚未完成，不宣称通过**。
- 下一小步如果获批：同 SVG renderer 配帧原型与 NMR/普通 Figure 选取验收；先补证据再讨论默认切换，不跳过测量一致性。
- 不开发 Source Authoring、History、MCP、自由拖拽、大型自动排版、Rust 或无 YAML 写回；不替换现有 YAML Agent API，不把显示改善包装成 strict 出版验收。
