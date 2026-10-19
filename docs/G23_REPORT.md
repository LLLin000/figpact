# G23：普通刻度的最终画布裁切 QA

## 范围

产品代码基线 `7936980`；`9f1da32` 只将新增的微小净空测试改为精确 renderer 几何，产品代码不变。本轮只补刻度裁切 QA，不做第二轮性能优化、验证合并、图例控制、自动布局或 GUI／Agent 扩展。

## 一个几何来源，两条 QA 入口

`figpact/qa.py` 的内部 `_collect_tick_geometry` 枚举实际绘制的 x/y 主／次刻度两侧 label1／label2 与 offset text。选择由 Matplotlib `Axis._update_ticks()` 给出；不可见、视图外未绘制和空文字不计，不能仅看 label 的 visible 属性。

`_measure_single` 对同一个 renderer bbox 与最终 Figure 画布、实际生效的 clip box／path／patch 求判定。`measure` 和 `check_out_of_frame`／`blocking_problems` 共用它，不新增第二份裁切算法。既有曲线、图例、图幅图像及压线规则保留，旧 `gid_filter` 不豁免刻度。

- `TICK_CLIP`：blocking，单位 mm，阈值 0，值为四边画布溢出与裁剪损失中的最大**长度**。同时存在多种裁剪矩形时求交；不把面积写成长度或因较小画布溢出漏掉更严重的内部裁剪。
- 只容忍 `1e-7 mm` 浮点噪声，不沿用图例 0.05 mm 的物理容差来吞掉真实小越界。0.01／0.03 mm 越界跨 DPI 有回归。
- 未知身份、重复键、非有限 DPI／bbox／clip、不可测量或不能证明为轴对齐矩形的裁剪路径，记录 `UNMEASURED_GEOMETRY` 并阻断。三角形、菱形、bowtie、曲线路径都不拿外接矩形冒充可证明的无裁切。
- `measure()['tick_geometry']` 另含稳定键、bbox、净空等诊断。正净空不产生裁切阻断；恰好很小的正净空也不是失败。没有为通过新测试降低净空标准或伪造 warning 消失。

当前以文字 renderer 包围盒为几何依据；它是保守文本包围盒检测，不是逐像素字形覆盖证明。最终文件另做 PDF 页面文字边界检查。任意 `bbox_inches='tight'`、未知后处理或其他外部裁切输出区域不因此获得普遍认证。

## 稳定身份，不靠文字或遍历编号

复用已有 `style_identity._axes_infos` 的稳定 Axes 身份／唯一性，然后组合轴 x/y、major/minor、有限实际位置和 label1/label2；offset 使用独立轴角色。相同文字但不同位置不会合并；改变遍历顺序不改变授权身份。重复 Axes GID、不可区分 Axes 或同轴同位置同侧重复刻度失败关闭，不用后缀编号掩盖歧义。

共享轴和合法 twinx 不因为 Axes 几何重叠就被称为身份歧义。轴外刻度本来就是正常布局：只有越过最终画布或真实 clip 才裁切，不与 Axes 边框作误判。

`qa_delta` 通过既有结构化记录机制识别新问题、恶化和不可测量，不解析报错数字。真实 Overlay 回归证明：新裁切、加重裁切、不可测量都拒绝显式草稿保存且原字节不变；继承且未恶化的既有裁切可按 G20 规则保存整图 FAIL 工作草稿，但严格 `load`／`render` 仍拒绝。

## 边界回归

新增 27 个实际 Matplotlib 几何测试，覆盖四边、主／次刻度、offset text、72／120／300／600 DPI、反向轴、共享轴／twinx、旋转标签、隐藏与视图外 tick、稳定身份与歧义、合法轴外布局、0.39 px 正净空、矩形剪裁求交、不可证明 path、非有限 clip 和 canvas＋clip 同时恶化。

其中微小净空 fixture 用实际 renderer bbox 把一个标签边缘设置到离画布 0.39 px，再断言换算后的 mm；不依赖环境字体默认值。另有 4 个真实 Overlay 消费者行为回归，而不是只测底层 helper。

## 真实 NMR 与 FTIR

`tools/g23/publication_trial.py` 只编排既有 G21 NMR／FTIR runner，复用原保存、重启、继续提交和严格导出链。G23 增量只有新刻度几何的实际 DPI 扫描与最终文件检查，不复制一套出版系统或修改科研源数据。

NMR 仍使用既有受控 68×48 mm、峰／图例 7.2 pt 修复。原生事务、两个 publication commit、新 worker 重开、后续已有 Overlay 轴标题编辑、严格 load／render 全部通过。最终 PDF 最小字形仍为 **5.04 pt**；已有两条贴边 warning 不宣称修复。

| 实际渲染 DPI | 最小刻度画布净空（mm） | 刻度裁切 | 刻度不可测量 |
|---:|---:|---:|---:|
| 72 | 0.055625 | 0 | 0 |
| 120 | 0.082083 | 0 | 0 |
| 300 | 0.071500 | 0 | 0 |
| 600 | 0.079437 | 0 | 0 |

这些正净空均合法，不为历史 PASS 给特殊豁免。120 DPI 的余量约 0.388 px，仍然很紧。**DPI 扫描只证明 tick-clip 合法，不证明各 DPI 整图所有 QA 清洁**：72 DPI 另出现 3 条 resolution-sensitive `TEXT_ON_DATA`，实测计数为 3751／4175／3532，已保留在结果中。Strict PASS 证据基于原生 120 DPI 构图与原脚本实际导出路径。

实际 strict probe、二次提交安装产物、严格 Overlay PDF 都重新读取：每页约 192.76×136.06 pt（68×48 mm），最小字形 5.04 pt，31 个可提取词的 bbox 均在页面内；PNG 为 1606×1133。父进程实际查看安装 PNG；不声称外部审阅者取得过私有 PDF，也不把 PDF 可提取词边界检查当成所有绘制元素的像素证明。

FTIR 既有 annotated 候选局部 Native 预览通过，但整组 strict 仍退出 1，compare 图原有 4 条文字压线保留，未生成正式 annotated PDF。没有过滤旧规则或将 collector 自身退出 0 当成出版通过。

最终私有证据为 `g23-out5/g23_tick_summary.json`、其 `g21-nmr/`／`g21-ftir/` 原始回执与产物；科研数据和图像不进入公开仓库。

## 构图证据：记录，不复用

`tools/g23/build_evidence.py` 只观察真实构图与真实审计快照。每次 build 记录调用链、scope、配置和已声明输入文件哈希、耗时、构图后的观测输出哈希；已有 verifier 实际执行 `_snapshots` 时再记录权威科学 digest、视图／QA／整份快照哈希。不为采集预先执行 manifest、提前 draw 或省略任何构图。

真实 FTIR 观测到启动 2 次、预览 12 次、确认 12 次、重开 11 次，共 37 次核心 build；28 份实际审计快照，结束 GC 后 manager 为 0。每个 build 都具有输入和观测输出指纹。预览的职责仍为身份探针 1、Apply 独立验证对 4、当前草稿 QA 基线 1、候选 baseline descriptors 1、磁盘加载验证对 4、最终渲染 Figure 1。

观测记录包含真实耗时，但 hashing／并发回归会改变时序，**不是新的性能 benchmark**。相同输入或输出哈希不作为合并独立验证的授权；本轮没有缓存或减少次数。原始逐构图记录在仓库外 `g23/build-evidence-final/build_evidence.json`，公开摘要不包含私有路径。

README 同时明确接入协议责任：构图入口返回的 Figure 由调用方关闭；manifest／layout_contract 自己额外创建的临时 Figure 由脚本创建者在 finally 中逐个关闭并释放引用，异常和多 scope 一样。不能 `close('all')` 关闭外部 Figure；G22 的两个示例证明不等于所有第三方脚本自动满足 ownership。

## 最终回归与冻结

产品代码 `7936980`，最终测试 fixture 及发布工具为 `9f1da32` 对应内容；最终文档／证据提交不改变产品代码。完整套件重新执行，未以 targeted 或 collect-only 冒充：

| 检查 | 最终实际结果 |
|---|---|
| 全量非浏览器 | **665 passed、7 skipped、95 subtests passed**；1778.44 秒 |
| 完整真实 Chromium | **28 passed**；684.74 秒 |
| Inspector Node | **54 passed** |
| 实际出版链与 DPI／PDF 检查 | NMR Strict PASS；FTIR Strict FAIL；微小正净空合法 |
| 实际构图观察 | 预览 12、确认 12、重开 11；未合并验证 |

首次全量非浏览器有 1 个失败：微小净空测试依赖先前测试残留的全局字体样式，实际净空变成 2.32 mm，并非产品漏报；改用精确 renderer 几何后完整重跑通过。首次 Chromium 有 1 个授权失败，页面控制台记录 `ERR_NETWORK_IO_SUSPENDED`／Failed to fetch；没有改产品权限或测试期望，等其他工作完成后单独重跑完整 Chromium 通过。初次失败不从记录中删除，也不将原因推断写成产品已修复。

仍观察到 requests 依赖版本 warning、demo Figure 累积 warning，以及 NaN DPI 故障注入触发的 Matplotlib cast warning；没有压制这些 warning 或放宽 QA。最终两个完整 Python 套件顺序执行。

公开验收摘要：[results.json](../tools/g23/results.json)。复跑入口：

```text
python tools/g23/publication_trial.py --help
python tools/g23/build_evidence.py --script "<只读FTIR副本/plot_ftir.py>" --config "<FTIR配置>" --output-dir "<新私有证据目录>"
```

publication trial 使用私有隔离源目录、全新输出目录，并让严格子进程的 `PYTHONPATH` 包含仓库根；G21/G22 归档不改写。G23 到此冻结：不扩展成性能工程，不实现口语 Agent、图例新权限或自动排版。
