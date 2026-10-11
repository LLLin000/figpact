# G0/G1：只读 Figure Inspector 交付记录

## 工作事实

- 范围仅 G0/G1。开始时 HEAD 与设计包基线一致：`fe48feef021f1f0e74472be65887632b91edf7a4`。用户未跟踪的 `docs/figpact-vnext-kit/` 保留，不加入提交。
- G0 已提交并推送 `947062e`；真实基线、差异审计及原有 strict 出图证据见 [G0_BASELINE.md](G0_BASELINE.md)。
- G1 后端独立工作树提交 `723ad1b`，主线集成为 `b1eb926`；前端独立工作树提交 `d4d70b5`，主线集成为 `23226f5`。两个分支只新增各自文件，没有共享编辑。
- 后端：`figpact/inspector.py`，复用已有 `scene.snapshot()`、科学载荷捕获和坐标换算。一次 Agg draw 的真实像素与同次测量配成一帧；PNG 从该 renderer 缓冲编码，不另外 savefig 重绘。成功和异常时都归还原 Figure canvas。
- 前端：`tools/inspector/index.html`、`inspector.js`、`inspector.css`，只有静态浏览、屏幕命中、选择和标尺；没有 Python 服务、编辑端点或每次 Hover 的后端请求。
- 运行示例：`tools/inspector_demo.py`，位于前端目录之外。只加载受信任的仓库 NMR/FTIR 样例，或者新建普通无 YAML Figure。
- 新回归：`tests/test_inspector.py`、`tests/inspector/test_inspector.js`。说明入口更新于 `README.md`、`SKILL.md`；`CONTEXT.md` 只补充只读视图、同帧观察和身份术语，不存实现决策。
- 未修改 `scene.py`、`geometry.py`、`registry.py`、`session.py`、`science.py`、`publish.py`、`patch.py`、`agent_api.py`、旧 GUI 或 NMR 绘图代码。没有第二套科学几何/排版引擎：物理对象测量仍来自 Scene；前端线段到指针距离只负责本地选择。

## 风险与权限

- G1 不修改用户绘图脚本或 YAML。G0 只修复 FTIR `preview_qa` 的 scoped view 缺少 Figure 属性导致的真实失败，不放宽 QA，不改科学计算。原基线 Git blob SHA-256 是 `0cd606d271cc32a6ab92e946921232364f5cd593ce0c85968c0395a768105981`；修复后工作文件 SHA-256 是 `524b1c86d6a5018abb1f561f32e960f15a5f2fddde80ac6935d141ea14150362`。前者明确是 Git blob，不冒充未经记录的工作树换行字节。
- 三个实际 Inspector 生产运行都独立核对 Figure 的受保护科学载荷，前后 digest 一致；NMR/FTIR 另外核对源、配置和声明科学输入的 revision。
- 对原有脚本、配置、科学输入和已有产物等 **98 个不同文件**逐文件 before/after SHA-256，变化列表为空。证据：`I:/figpact-test-archive/G0-G1-fe48fee/g1-acceptance/protected-before.json`、`protected-after.json`、`result.json`。
- 页面选择、缩放和平移只改变查看状态，不移动任何 GID；没有非目标对象的布局变化，也没有 follow 编辑。本次不运行新的 strict 发布；G0 的 FTIR 12 文件、NMR 4 文件独立 strict 结果仍单独记录，不借用 Inspector 测量结论。
- 导出只允许不存在的新目录；已有目录、文件和链接拒绝覆盖。异常只清理本次拥有的文件和目录；后来由别人建出的目录不得删除。该竞争边界先实际失败，再修复并通过回归。写入使用排他创建，不覆盖并发创建的同名文件；源码、前端和测试目录的保护按解析后的路径检查。
- renderer 执行受信任 Figure 的绘制回调；科学载荷变化会拒绝出帧，但这里不是任意 Python 的文件系统沙箱，也不是科学计算正确性的 Oracle。

## 验收

所有测试运行均通过 omp 原生 task，指定 `opencode-go/step-5-preview-free`，未替换模型。

### 命令与环境

Windows；Python 3.14.0、Matplotlib 3.10.8、pytest 9.0.2、Node v24.11.1。显式 cwd 为仓库；`MPLBACKEND=Agg`、`PYTHONDONTWRITEBYTECODE=1`；TEMP/TMP/TMPDIR/MPLCONFIGDIR 和 basetemp 均在 I 盘。

```text
D:/programs/Python/python.exe -B -X utf8 -m pytest -q -rs -p no:cacheprovider --basetemp I:/figpact-test-archive/G0-G1-fe48fee/g1-full-regression/pytest-tmp --junitxml=I:/figpact-test-archive/G0-G1-fe48fee/g1-full-regression/full.xml
C:/Program Files/nodejs/node.exe --test tests/inspector/test_inspector.js
D:/programs/Python/python.exe -B -X utf8 I:/figpact-test-archive/G0-G1-fe48fee/g1-acceptance/run_demos.py
```

|检查|实际结果|
|---|---|
|完整 pytest|285 passed，7 skipped，73 subtests passed；0 failed / error，exit 0|
|新后端 Inspector 用例|14 passed，1 skipped；目录竞争、科学载荷变化和 renderer 异常等负例通过|
|前端 Node 用例|25 passed，0 failed / skipped，exit 0|
|实际生产顺序|NMR → 无 YAML 普通 Figure → FTIR；三个进程 exit 0|
|原有文件保护|98 个不同文件 SHA-256 不变|

完整日志：`g1-full-regression/{pytest.stdout.log,pytest.stderr.log,full.xml,node.stdout.log}`；新后端日志在 `g1-focused-green/`。初始 RED 保留于 `g1-red-export/`、`g1-red-behavior/`、`g1-red-helpers/`、`g1-red-integrity/`；后来补充的目录竞争 RED 在 `g1-takeover-check/`。一次前端检查最初 cwd 错误、文件未找到，纠正 cwd 后的真实结果单独记录；不当作产品失败或掩盖重试。另一个新测试的缩放输入坐标算错，修正输入 `-10 + 200 × 0.25 = 40`，没有改生产换算公式或降低断言要求。

七项跳过明确保留：

- `test_agent_api.py:1020`、`:1312`，`test_publish_safety.py:402`、`:375`，`test_inspector.py:114`：本机账号不能创建对应符号链接，未实际验证这些链接案例。
- `test_effects.py:207`、`test_session.py:1409`：旧脚本夹具不在。
- stderr 有既有 RequestsDependencyWarning；没有 suppress，也未改依赖解决不属于 Gate 的问题。

### 真实页面

可直接用普通浏览器打开：

- `I:/figpact-test-archive/G0-G1-fe48fee/g1-acceptance/nmr/index.html`
- `I:/figpact-test-archive/G0-G1-fe48fee/g1-acceptance/plain/index.html`
- `I:/figpact-test-archive/G0-G1-fe48fee/g1-acceptance/ftir/index.html`

NMR 验收对象是两个独立 GID：`fig2_nmr.main.peak.vancho.3p91` 和 `fig2_nmr.main.guide.vancho.3p91`。普通样例未读取 YAML，未声明编辑绑定，`source_revision=null`；无登记 Artist 是单帧临时身份。

### 实际浏览器验收

指定 Step 5 代理使用独立命名的普通 Chromium 页签、真实鼠标/键盘输入和当前 SVG 的屏幕矩形换算；NMR 先验收，普通无 YAML Figure 后验收。**NMR 30/30、普通图 25/25 通过**；FTIR 另做真实页面视觉烟测通过。无 console error，Hover 不发 HTTP 请求，测试页签已关闭，没有操作用户原有页签。

已实测：标签/引线分别 Hover 和 Click；Hover 不覆盖已锁定选择；缩放、窗口 resize、视图滚动后仍选中正确对象；重叠按真实候选顺序轮换；折线包络空白、NaN 断口及 marker-only 假中心线不命中曲线；列表可选择不可直接命中的对象；重载帧清空临时选择；PNG、Scene 或显式 source revision 不匹配时禁用旧选择和 overlay。

|NMR 对象|左 mm|下 mm|右 mm|上 mm|
|---|---:|---:|---:|---:|
|3.91 标签|24.2452|13.5051|33.4734|16.4657|
|对应引线|28.8593|13.1810|33.5257|13.4375|

这些是 RendererAgg / DPI 120 下的未校准测量，四位小数只用于记录，不承诺该物理精度。引线实测首末端为 `[33.52568697611411, 13.180982739922522]`、`[28.8593, 13.43753054662379]` mm；清单原科学锚点是 `[3.9058301013356687, 21.22299178412972]` ppm / a.u.，界面分别显示，两者不混用、不修改。

浏览器发现并修复一项真实问题：放大后 `viewport.focus()` 使 scrollTop 在按下与松开之间从 160 变成 153，同一屏幕点的 y 从 13.3093 mm 变成 13.6775 mm，误选标签。改为原生 `focus({preventScroll:true})` 后，真实 down/focus/up 均保持 scrollTop=160，零中途滚动，正确选中引线。修复前后事件日志、截图和可重跑脚本均保留于 `g1-browser/red-focus/`，没有 mock focus 或源码字符串断言。三个演示页面只同步这一前端修复，PNG/Scene/frame 不变。修复后 Node 25/25 再通过；Python 后端未再变化，没有重复跑整个 Python 套件。

证据根：`I:/figpact-test-archive/G0-G1-fe48fee/g1-browser/`。完整结果 `results.json`；可重复浏览器入口 `repro/run-all.mjs`（在具备 browser 全局的 omp JavaScript Eval 中加载）；截图 `nmr-guide.png`、`nmr-zoom.png`、`nmr-resize.png`、`plain.png`、`plain-invalid.png`、`plain-final.png`、`ftir.png`。测试中两项自写预期错误明确纠正：轮换涵盖全部真实重叠对象，不限两个；`loadFrame` 用 invalid UI 状态报告拒绝，而不是 Promise throw。未修改产品来迎合错误预期。

Tern smoke 已尝试，但环境返回 `app.tern:true requires running inside a Tern pane (TERN_PANE_SOCKET and TERN_PANE are not set)`。因此 **Tern 嵌入未实际验收**，没有冒充 Chromium fallback 为 Tern 成功；按工单不阻断普通浏览器。

## 性能（实际单次烟测，不是基准或 P95）

|样例|生产函数计时|包括 Python 启动/导入的进程计时|
|---|---:|---:|
|NMR|2.204 s|3.223 s|
|普通无 YAML Figure|0.050 s|0.593 s|
|FTIR|1.027 s|1.587 s|

每个样例 N=1，与完整回归有并行时段；不能宣称独立性能基准、median/P95 或 Agent 总任务提速。生产函数计时开始于公共导入之后，不能当冷启动总时间。后端一次 capture 执行一次真实 draw，单 draw/同帧 PNG 在回归中核对；不统计这些结果为 strict 时间。未统计完整 Agent 往返、tokens 或随机配对对照。

## 支持范围与未实现项

- 只读原图、毫米包络和锚点、真实连续折线段命中、文字/图例/面板包络选择、固定 4 CSS px 指针容差加描边半径、Click 锁定与 Alt+Click 重叠轮换、搜索/列表、视图缩放和平移。
- 图像与几何的实际摘要、PNG 尺寸及 revision 链必须匹配才启用选择；重新加载帧清空选择，不存跨帧身份。调用者提供 expected source revision 时不匹配也拒绝。
- `calibrated=false`：mm 是 renderer DPI 下的出版坐标，不是屏幕上拿尺量的毫米；测量不确定度未校准，不能凭小数位数声明 0.001 mm 精度。
- 中心线加半径是保守命中模型，不是准确墨迹轮廓。虚线空段、端帽和 marker 墨迹有明确限制；marker-only 和不支持的几何不制造幽灵连接线，只能列表选择。文字/旋转文字包络也不等于字形轮廓。
- 静态离线页面不实时监控原文件，不自动知道页面打开之后源文件又改了；需重新导出。没有接入参数不影响测量，但不能由此取得编辑权限。
- 导出目前需要源码 checkout 中的 `tools/inspector/` 资源；没有宣称独立 wheel 已包含网页资源。
- 未实现 Source Authoring、无 YAML 编辑、History、MCP、拖拽编辑、自动布局或替换已有 YAML Agent API；不推进 G2–G6。

## 下一步

**本 Gate：YES（普通 Chromium 的 G0/G1 范围）**。无阻断项；Tern 嵌入和其他浏览器/操作系统未实测，未承诺超出范围的兼容性。当前只提交推送已验收范围；后续 Gate 需新的用户授权。不启动 Source Authoring、History、MCP、拖拽编辑、自动布局或无 YAML 编辑。
