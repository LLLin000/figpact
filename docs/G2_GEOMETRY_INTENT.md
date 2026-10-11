# G1 界面收口 / G2 Geometry Intent 交付记录

## 工作事实

- 范围：用户批准的 G1 小幅界面收口，以及 G2 示范、实际目标验收和会话内单操作隔离。起始 HEAD：`3f6e3e33d9fa0e735e1228d7ba57c3ffb29b0166`。设计包最初基线为 `fe48feef021f1f0e74472be65887632b91edf7a4`；G0/G1 已完成的差异和真实基线不重新冒充本次结果，见 [G0](G0_BASELINE.md)、[G1](G1_INSPECTOR.md)。用户未跟踪的 `docs/figpact-vnext-kit/` 不加入提交、不修改。
- UI 使用 omp 配置的 **UI / google-antigravity/gemini-3.8-flash:auto**，在 I 盘独立工作树实现并自行测试、修正。四文件提交 `2aecdd5` 集成为主线 `89f9093`。父代理随后亲自实测并修复取消后选择、整帧恢复及无选中对象时撤销入口的集成边界。
- Python 后端与测试由父代理实现；测试使用 omp 原生 task，明确指定 **opencode-go/step-5-preview-free**，不是在 Eval 中批量起代理。
- 前端只有 `tools/inspector/{index.html,inspector.js,inspector.css}`；后端会话在 `figpact/intents.py`，受信任本机桥在 `figpact/inspector_server.py`，测试在 `tests/test_intents.py`、`tests/test_inspector_server.py`、`tests/inspector/test_inspector.js`。入口说明更新于 `README.md`、`SKILL.md`；`CONTEXT.md` 只新增领域术语，不存实现决策。
- 未修改 `scene.py`、`geometry.py`、`registry.py`、`science.py`、`session.py`、`runtime.py`、`agent_api.py`、`publish.py`、`patch.py`、旧 GUI 或 FTIR/NMR 科学脚本。复用既有配置重建、科学保护和 QA，不建第二套几何或出版引擎。

## 使用与边界

```bash
python -m figpact.inspector_server --example nmr --scope main
python -m figpact.inspector_server --example plain
```

打开打印的本机地址。静态无 YAML 导出仍可使用 `figpact.inspector.export_inspector()`。

- 点击对象查看实际毫米位置、尺寸、稳定/临时身份与关联引线。中心工作区使用实际容器宽高适配、居中；缩放保留锚点。
- 方向键只是临时几何意图：0.1 mm；Alt 0.01 mm；Shift 0.5 mm。15 次 Alt+↑ 汇聚为一个 +0.15 mm 操作；也可输入 dx/dy。不会逐次重建 Python，不直接移动真实 Artist 或写文件。
- 试算只选择唯一、真实、毫米单位、只作用于许可目标和显式关联引线的 YAML 绑定。扩大到整组曲线的参数不会因同时能移动标签就被选中；多个同样合法的绑定返回歧义。
- 目标从已接受配置的绝对参数集合重建，不在原 Artist 上累积 transform。最终显示的实际 Figure 会运行当前 scope QA，再生成配对图片和几何；科学载荷、四个 bbox 角位移、引线科学端/标签端及未授权对象变化分别检查。
- 目标容差不能豁免科学端固定要求。固定端采用独立的同 renderer 数值差异阈值；不把该阈值解释为已标定物理精度。
- 试算不改变已接受状态。接受仅保存在当前进程；取消只丢弃当前候选；独立撤销重新构建剩余已接受目标。有后续依赖时拒绝撤销，不做全局 reset。
- 候选图片、Scene、命中路径与 revision 一起验证和切换；取消一起恢复已接受整帧。决策始终绑定已接受 revision。陈旧响应、失败决策不能假装成功；Escape 与取消按钮使用同一后台取消操作。
- 120/240 DPI 只在尚无待处理/已接受操作时整帧重建；之后返回 `QUALITY_LOCKED`。普通无 YAML Figure 没有可信重建入口，质量、试算、接受按钮禁用，仍可测量和展示 desired-only 轮廓。
- 当前 G2 适配器只有单 scope；跨 scope 绑定明确拒绝为 `NEEDS_AUTHORING`，不假装全版本验收。没有绑定、科学清单缺失、非支持的变换或无法证明的关联也拒绝，不修改源码来补映射。
- 接受不是 YAML 草稿、源代码保存或 strict 出图。关闭服务会丢失内存操作；正式保存/出版仍走已有 YAML Agent API，不替换它，也没有新增 HTTP 保存/出版端点。

## 风险与权限

- 本次 G2 不写用户 `.py/.yaml`、科学输入或正式产物。SDK 实际烟测逐文件比较 **151 个 examples 文件**的 before/after SHA-256，变化数为 0；证据在 `real-smoke-final/{before-sha256.json,after-sha256.json,results.json}`。
- 实测许可影响仅包括目标标签及其显式关联 guide 的标签端；曲线、峰位、归属、窗口及其他对象保持。科学端实际误差为 0 mm；原声明科学锚点仍为 `[3.9058301013356687, 21.22299178412972]` ppm / a.u.。
- 这里只执行启动时明确指定的受信任本地脚本；不是任意 Python 文件系统沙箱。桥仅绑定 `127.0.0.1`，校验 Host/Origin/Sec-Fetch-Site、JSON 类型与有限请求大小，只服务三项固定静态资源、配帧和 G2 决策；不接收 HTTP 脚本路径、任意文件读取或执行命令。
- 科学一致性是受保护载荷一致，不是科学计算本身正确性的证明。QA 通过表示没有相对基线新增阻断，返回检查明示基线/当前问题数量；不是独立全 scope strict。

## 验收

环境：Windows、Python 3.14.0、Matplotlib 3.10.8、pytest 9.0.2、Node v24.11.1。Python 使用 `-B -X utf8`、`MPLBACKEND=Agg`、`PYTHONDONTWRITEBYTECODE=1`；所有 TEMP/TMP/TMPDIR/MPLCONFIGDIR、basetemp、日志、截图和可重跑驱动均位于 I 盘。

```text
D:/programs/Python/python.exe -B -X utf8 -m pytest -q -rs -p no:cacheprovider --basetemp I:/figpact-test-archive/G2-3f6e3e3/final-regression/pytest-tmp --junitxml I:/figpact-test-archive/G2-3f6e3e3/final-regression/final.xml
C:/Program Files/nodejs/node.exe --test tests/inspector/test_inspector.js
D:/programs/Python/python.exe -B -X utf8 I:/figpact-test-archive/G2-3f6e3e3/smoke_real.py I:/figpact-test-archive/G2-3f6e3e3/real-smoke-final
```

| 检查 | 实际结果 |
|---|---|
| 最终完整 pytest | 310 passed、7 skipped、73 subtests passed；0 failed/error，exit 0；140.97 s，进程 wall 143.13 s |
| G2 新后端用例 | 共 25 项，纳入完整回归；目标 .15/实际 .11 拒绝、未授权对象变化、过期输入、依赖撤销、普通图不写回、字体环境、QA 和科学端豁免负例 |
| 最终前端 Node | 39 passed，0 failed/skipped，exit 0；104.61 ms，进程 wall 0.24 s |
| 真实 SDK 生产链 | NMR → FTIR 只读 → 普通 Figure，exit 0；151 原文件 SHA-256 不变 |
| 主线真实 NMR 浏览器 | 从零接受/零候选开始，真实鼠标/键盘/按钮驱动；240→120、15 次示范、试算/接受 A、试算/取消 B、重新接受/撤销 B、Escape 清候选、科学 guide 点击、质量拒绝全部实测 |
| 普通无 YAML 浏览器 | 真实 Matplotlib Figure；临时文字选择、+.15 mm desired-only 轮廓、原 PNG 不变；试算/接受/质量禁用 |

七项跳过没有冒充通过：

- `tests/test_agent_api.py:1020/:1312`、`tests/test_publish_safety.py:402/:375`、`tests/test_inspector.py:114`：本机账号/平台不能创建对应符号链接，五项链接案例未实测。
- `tests/test_effects.py:207`、`tests/test_session.py:1409`：两个旧夹具不在。

### 真实 NMR 数值

对象：`fig2_nmr.main.peak.vancho.3p91`；独立 guide：`fig2_nmr.main.guide.vancho.3p91`。独立 B：`fig2_nmr.main.peak.hama.6p18`。

| 对象/量 | 原值 | 实际候选 |
|---|---|---|
| A bbox，下/上 mm | 13.505131832797424 / 16.465687041130757 | 13.655131832797426 / 16.61568704113076 |
| A 实际 dy mm | 0 | 0.15000000000000213 |
| guide 科学端 mm | [33.52568697611411, 13.180982739922522] | 完全相同 |
| guide 标签端 mm | [28.859299999999998, 13.43753054662379] | [28.859299999999998, 13.587530546623794] |

任务容差 0.01 mm；实测最大数值误差约 `3.9e-15` mm，只有同 renderer 数值意义。`calibrated=false`，不承诺打印或显示器精度。浏览器 B 使用 +0.1 mm；取消和撤销后 A 的已接受 **frame revision 精确相同**，不是只检查撤销按钮文字。

### 负例先行与真实发现

- 初版 `figpact.intents` 尚不存在时保留收集失败 RED；目标 .15/实际 .11 等新行为随后真实通过。
- Windows HTTP 提前拒绝未读 POST body 真实产生 `WinError 10053`；改为有界清读/关闭连接后原 23 项绿色。字体环境丢失、单标签错选组绑定、无关候选清掉 A 三项也保留 RED，再修根因。
- 标量几何快路径没有执行最终实际 Figure 的 scope QA，保留 `RESERVED_NOTE_COLUMN` 真实 RED（错误 OK），复用既有 QA 后拒绝；没有把绘制 PNG 直接等同 QA。
- 用户 `tolerance_mm=100` 曾使移动科学端的错误 guide 被接受，保留真实 RED；独立固定端检查后为 `SCIENCE_CHANGED`，不得接受。
- UI 最初报告与截图不一致：`ui-live/real-nmr-final-report.json` 实际有 `PENDING_OPERATION`、`UNDO_CONFLICT`，没有计作通过。后来的主要按钮截图在 `ui-browser-final/`；最终主线证据独立放在 `parent-browser/`，不混用直接 SDK 与浏览器成功。
- 父代理真实发现取消后选另一个对象触发 `restoreAcceptedPreview is not defined`；修复前后 JSON/截图均在 `parent-browser/{red-selection,green-selection}.*`。接受后撤销按钮被隐藏，也由实际按钮链发现并修复；最终新页无 console/page error。
- 父浏览器驱动两次尝试因过期模块缓存仍使用 Puppeteer 的不支持 SVG focus 调用而失败，另一次发现上述隐藏按钮；明确是独立失败尝试，不计通过。最终驱动使用真实鼠标给 viewport 原生焦点，不改产品去迎合测试。普通图首次记录用错 `#ghost-outline` 选择器，改为实际 `.ghost-outline` 后确认存在，未改产品。

证据根：`I:/figpact-test-archive/G2-3f6e3e3/`。

- 完整测试：`final-regression/{stdout.log,stderr.log,exit.txt,final.xml}`。
- 最终 SDK：`real-smoke-final/{results.json,stdout.log,stderr.log,exit.txt,before-sha256.json,after-sha256.json}`。
- 最终主线按钮/实际 HTTP 响应：`parent-browser/results.json`；guide 与无 YAML：`guide-results.json`、`plain-results.json`；截图 `nmr-candidate.png`、`nmr-after-independent-undo.png`、`plain.png`。
- 可重跑实际按钮入口：`parent-browser/nmr-buttons.mjs`，供有 browser 全局的 omp JS Eval 使用；只用鼠标/键盘/按钮，网络响应仅用于记录，不直接 fetch 代替 UI 动作。所有早期失败保留，不删除失败来美化结果。

## 性能（单次烟测，不是 median/P95）

| 区间 | 实测秒数 |
|---|---:|
| NMR SDK 会话建立（已完成公共导入） | 1.867 |
| NMR 完整实际候选试算 | 1.598 |
| 浏览器 Evaluate 按钮到可接受状态（含本机往返与前端校验） | 1.698 |
| NMR 240 DPI 整帧重建 | 0.795 |
| FTIR 只读测量/配帧 | 1.184 |
| SDK 全链进程 wall | 12.62 |

每项 N=1，无随机配对对照；会话建立数字不包含 Python 启动/公共导入。候选实际 renderer/QA 比旧热几何数字慢，不用 36.2 ms 代替它。未统计总 build/draw 次数、Agent 总生命周期、tokens 或整体任务 median/P95；不宣称一秒以内、80% 首改成功或 50% 总提速。

## 下一步

**本 Gate：YES，限已实测 G1 收口与 G2 单 scope、显式 YAML 绑定的垂直链。** 普通 Chromium 和本机 SDK 已实测；Tern、其他浏览器/操作系统仍未实测。不能把它称作任意 Matplotlib 图自主编辑能力。

不做：Source Authoring、无 YAML Python 写回、持久 History、MCP/Hub、自由拖拽、通用自动排版、Rust、替换 YAML Agent API 或为速度降低科学/QA 标准。进一步 Gate 或跨 scope 适配需独立授权；当前保留既有 FTIR/NMR 出图链，不为了新抽象重写科学脚本。
