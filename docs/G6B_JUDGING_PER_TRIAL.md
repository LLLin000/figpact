# G6b 正式轮 · 逐题证据表（独立判分器，36 行）

> **判分者**：独立判分角色（非三臂任何一方）。**本表每一条结局都来自判分器自建重建**（§12.3 第 1–2 条）；
> 臂侧自报只出现在最后一列，用于对照，**不构成判据**。
> 生成时间：2026-10-13｜交付物目录：`D:/L/AI/figpact-archive/g6b-v2/judging/`

## 0. 判分方法（可复核）

| 项 | 判分器实际做法 |
|---|---|
| 重建入口 | `judging/_rebuild/snap.py`：`IntentSession(script=..., config=..., scope=..., dpi=120).snapshot()`，取 `scene_json.nodes`（gid/type/bounds_mm/runs_mm/text）+ 该帧的 `qa` 块 |
| 进程隔离 | **每个配置各起一次进程**（D-5 强制口径）；基线配置、每个候选配置互不共享进程状态；FTIR 四个 scope 各再起两进程 |
| 比较 | `judging/_rebuild/analyze.py`：中心位移 = bounds_mm 中心差（画布毫米、左下原点、右/上为正）；残差 = 实测 − 目标；容差 `tolerance_mm = 0.01`（§1.3 唯一值） |
| 基线 | **夹具默认**（`tree/examples/nmr/nmr.yaml`、`ftir/ftir.yaml`、`python_native/*.py`）；**不**使用候选里声明的值、**不**使用臂侧 `try_layout/evaluate` 回执里的数字 |
| 脚本类题 | 基线脚本 = `<T>/tree/examples/python_native/<同名>.py`；候选脚本 = `<T>/candidate/<同名>.py`（§11.1 封套 / §12.3 第 1 条）；配置 = 该 trial 的空配置（`{}`） |
| 原始件 | `judging/rebuild/<臂>-<题>-<步>.json`（逐配置的完整节点表）＋ `judging/rebuild/all.json`、`native.json`（比较结果）＋ `judging/verdicts.json`（逐题裁定） |
| 未采信 | 三臂的 `measured_delta_mm_rebuild`、`evaluate/try_layout` 回执、Hub 的 `COMMITTED_AND_VERIFIED` 一律**不作为判据**（§12.3 第 3–4 条） |
| 环境 | `TEMP/TMP/TMPDIR/MPLCONFIGDIR/FIGPACT_STATE_HOME` 全部指向 `g6b-v2/tmp-judge/\*`（`tmp*` 之下，不在脚本目录内）；仓库与三臂产物**只读**，未改任何 trial 产物 |

### 0.1 判据与环境的前置核对（判分器自算，三项）

- **判据包签名**：在 **36 个提取树**内各重算一次 §2 唯一拼接命令 → 36/36 = `163b0df0852ff8f859e54d78c7d0941bfd5e39924e03ff97c09001e1012ffe5d`，
  与 §2 登记值**逐字相等**（与 `formal/criteria-signature.txt` 一致）。
- **六件夹具 sha256**：36 棵树 × 6 件 = 216 格，**逐格等于 §1.2 `commit` 列，0 处不符**（= 提取树与冻结 commit `f101113…` 一致，冻结清单成立）。
- **科学输入**（判分器自算）：判分器用**每个 trial 自己树内的** `tools/science_manifest.py --verify` 复算——
  **18 个 NMR 树 × 99 件全部 OK**、**3 个 FTIR 树 × 43 件全部 OK**（0 处不符）。
  → 36 条 trial 期间的科学输入在磁盘上**未被改动**，这条与下面「重建后曲线几何逐位不变」互相独立。

## 1. 逐题证据表（36 行 = 12 题 × 3 臂）

| 臂 | 题 | 自建重建结局 | 判据来源 | 自建实测（mm） | 残差（mm） | 引线端点 | 拒绝依据 | 证据路径 | 与臂侧自报 |
|---|---|---|---|---|---|---|---|---|---|
| L | T01·A09 | completed | 自建重建 · 一进程一配置（judging/_rebuild/snap.py） | {"fig2_nmr.main.peak.vancho.3p91": [0.2, 0.05]} | {"fig2_nmr.main.peak.vancho.3p91": [0.0, 0.0]} | 科学端误差 +0.0000 / 标注端 Δ [+0.2000, +0.0500] | 完成类：无拒绝 | `judging/rebuild/L-A09-*.json`；`judging/verdicts.json`；trial = `formal/trial-b461497e` | 一致 |
| A | T01·A09 | completed | 自建重建 · 一进程一配置（judging/_rebuild/snap.py） | {"fig2_nmr.main.peak.vancho.3p91": [0.2, 0.05]} | {"fig2_nmr.main.peak.vancho.3p91": [0.0, 0.0]} | 科学端误差 +0.0000 / 标注端 Δ [+0.2000, +0.0500] | 完成类：无拒绝 | `judging/rebuild/A-A09-*.json`；`judging/verdicts.json`；trial = `formal/trial-8b10cab6` | 一致 |
| V | T01·A09 | completed | 自建重建 · 一进程一配置（judging/_rebuild/snap.py） | {"fig2_nmr.main.peak.vancho.3p91": [0.2, 0.05]} | {"fig2_nmr.main.peak.vancho.3p91": [0.0, 0.0]} | 科学端误差 +0.0000 / 标注端 Δ [+0.2000, +0.0500] | 完成类：无拒绝 | `judging/rebuild/V-A09-*.json`；`judging/verdicts.json`；trial = `formal/t01-A09` | 一致 |
| L | T02·A10 | completed | 自建重建 · 一进程一配置（judging/_rebuild/snap.py） | {"fig2_nmr.main.peak.vancho.3p91": [0.0, 0.11]}（题面目标 [0.0000, +0.1500]） | {"fig2_nmr.main.peak.vancho.3p91": [0.0, -0.04]}（对题面目标） | 科学端误差 +0.0000 / 标注端 Δ [+0.0000, +0.1100] | 完成类：无拒绝 | `judging/rebuild/L-A10-*.json`；`judging/verdicts.json`；trial = `formal/trial-0a668fc6` | 一致 |<br/>结局②→①：给定候选实测 [0,+0.11]（声明值），对题面 +0.15 的残差 −0.04 超差；未 accept、未声称完成 → ①如实判 FAIL
| A | T02·A10 | completed | 自建重建 · 一进程一配置（judging/_rebuild/snap.py） | {"fig2_nmr.main.peak.vancho.3p91": [0.0, 0.11]}（题面目标 [0.0000, +0.1500]） | {"fig2_nmr.main.peak.vancho.3p91": [0.0, -0.04]}（对题面目标） | 科学端误差 +0.0000 / 标注端 Δ [+0.0000, +0.1100] | 完成类：无拒绝 | `judging/rebuild/A-A10-*.json`；`judging/verdicts.json`；trial = `formal/trial-fdfcba9f` | 一致 |<br/>结局②→①：给定候选实测 [0,+0.11]（声明值），对题面 +0.15 的残差 −0.04 超差；未 accept、未声称完成 → ①如实判 FAIL
| V | T02·A10 | completed | 自建重建 · 一进程一配置（judging/_rebuild/snap.py） | {"fig2_nmr.main.peak.vancho.3p91": [0.0, 0.11]}（题面目标 [0.0000, +0.1500]） | {"fig2_nmr.main.peak.vancho.3p91": [0.0, -0.04]}（对题面目标） | 科学端误差 +0.0000 / 标注端 Δ [+0.0000, +0.1100] | 完成类：无拒绝 | `judging/rebuild/V-A10-*.json`；`judging/verdicts.json`；trial = `formal/t02-A10` | 一致 |<br/>结局②→①：给定候选实测 [0,+0.11]（声明值），对题面 +0.15 的残差 −0.04 超差；未 accept、未声称完成 → ①如实判 FAIL
| L | T03·A14 | completed | 自建重建 · 一进程一配置（judging/_rebuild/snap.py） | 01-A: {"fig2_nmr.main.peak.vancho.9p83": [0.0, 0.15]}<br/>02-AB: {"fig2_nmr.main.peak.vancho.9p83": [0.0, 0.15], "fig2_nmr.main.peak.vancho.3p68": [0.0, 0.2]}<br/>03-undoB: {"fig2_nmr.main.peak.vancho.9p83": [0.0, 0.15], "fig2_nmr.main.peak.vancho.3p68": [0.0, 0.0]} | 01-A: {"fig2_nmr.main.peak.vancho.9p83": [0.0, 0.0]}<br/>02-AB: {"fig2_nmr.main.peak.vancho.9p83": [0.0, 0.0], "fig2_nmr.main.peak.vancho.3p68": [0.0, -0.0]}<br/>03-undoB: {"fig2_nmr.main.peak.vancho.9p83": [0.0, 0.0], "fig2_nmr.main.peak.vancho.3p68": [0.0, 0.0]} | 科学端误差 +0.0000 / 标注端 Δ [+0.0000, +0.1500] | 完成类：无拒绝 | `judging/rebuild/L-A14-*.json`；`judging/verdicts.json`；trial = `formal/trial-9086d88b` | 一致 |
| A | T03·A14 | completed | 自建重建 · 一进程一配置（judging/_rebuild/snap.py） | 01-A: {"fig2_nmr.main.peak.vancho.9p83": [0.0, 0.15]}<br/>02-AB: {"fig2_nmr.main.peak.vancho.9p83": [0.0, 0.15], "fig2_nmr.main.peak.vancho.3p68": [0.0, 0.2]}<br/>03-undoB: {"fig2_nmr.main.peak.vancho.9p83": [0.0, 0.15], "fig2_nmr.main.peak.vancho.3p68": [0.0, 0.0]} | 01-A: {"fig2_nmr.main.peak.vancho.9p83": [0.0, 0.0]}<br/>02-AB: {"fig2_nmr.main.peak.vancho.9p83": [0.0, 0.0], "fig2_nmr.main.peak.vancho.3p68": [0.0, -0.0]}<br/>03-undoB: {"fig2_nmr.main.peak.vancho.9p83": [0.0, 0.0], "fig2_nmr.main.peak.vancho.3p68": [0.0, 0.0]} | 科学端误差 +0.0000 / 标注端 Δ [+0.0000, +0.1500] | 完成类：无拒绝 | `judging/rebuild/A-A14-*.json`；`judging/verdicts.json`；trial = `formal/trial-bf5f9ffb` | 一致 |
| V | T03·A14 | completed | 自建重建 · 一进程一配置（judging/_rebuild/snap.py） | 01-A: {"fig2_nmr.main.peak.vancho.9p83": [0.0, 0.15]}<br/>02-AB: {"fig2_nmr.main.peak.vancho.9p83": [0.0, 0.15], "fig2_nmr.main.peak.vancho.3p68": [0.0, 0.2]}<br/>03-undoB: {"fig2_nmr.main.peak.vancho.9p83": [0.0, 0.15], "fig2_nmr.main.peak.vancho.3p68": [0.0, 0.0]} | 01-A: {"fig2_nmr.main.peak.vancho.9p83": [0.0, 0.0]}<br/>02-AB: {"fig2_nmr.main.peak.vancho.9p83": [0.0, 0.0], "fig2_nmr.main.peak.vancho.3p68": [0.0, -0.0]}<br/>03-undoB: {"fig2_nmr.main.peak.vancho.9p83": [0.0, 0.0], "fig2_nmr.main.peak.vancho.3p68": [0.0, 0.0]} | 科学端误差 +0.0000 / 标注端 Δ [+0.0000, +0.1500] | 完成类：无拒绝 | `judging/rebuild/V-A14-*.json`；`judging/verdicts.json`；trial = `formal/t03-A14` | 一致 |
| L | T04·A07 | completed | 自建重建 · 一进程一配置（judging/_rebuild/snap.py） | {"fig2_nmr.main.peak.hama.6p18": [0.0, 0.2]} | {"fig2_nmr.main.peak.hama.6p18": [0.0, 0.0]} | 科学端误差 +0.0000 / 标注端 Δ [+0.0000, +0.2000] | 完成类：无拒绝 | `judging/rebuild/L-A07-*.json`；`judging/verdicts.json`；trial = `formal/trial-217c9fd5` | 一致 |
| A | T04·A07 | completed | 自建重建 · 一进程一配置（judging/_rebuild/snap.py） | {"fig2_nmr.main.peak.hama.6p18": [0.0, 0.2]} | {"fig2_nmr.main.peak.hama.6p18": [0.0, 0.0]} | 科学端误差 +0.0000 / 标注端 Δ [+0.0000, +0.2000] | 完成类：无拒绝 | `judging/rebuild/A-A07-*.json`；`judging/verdicts.json`；trial = `formal/trial-80cef1c1` | 一致 |
| V | T04·A07 | completed | 自建重建 · 一进程一配置（judging/_rebuild/snap.py） | {"fig2_nmr.main.peak.hama.6p18": [0.0, 0.2]} | {"fig2_nmr.main.peak.hama.6p18": [0.0, 0.0]} | 科学端误差 +0.0000 / 标注端 Δ [+0.0000, +0.2000] | 完成类：无拒绝 | `judging/rebuild/V-A07-*.json`；`judging/verdicts.json`；trial = `formal/t04-A07` | 一致 |
| L | T05·A08 | completed | 自建重建 · 一进程一配置（judging/_rebuild/snap.py） | {"fig2_nmr.main.peak.vancho.3p91": [0.0, 0.15]} | {"fig2_nmr.main.peak.vancho.3p91": [0.0, 0.0]} | 科学端误差 +0.0000 / 标注端 Δ [+0.0000, +0.1500] | 完成类：无拒绝 | `judging/rebuild/L-A08-*.json`；`judging/verdicts.json`；trial = `formal/trial-8348d83a` | 一致 |
| A | T05·A08 | completed | 自建重建 · 一进程一配置（judging/_rebuild/snap.py） | {"fig2_nmr.main.peak.vancho.3p91": [0.0, 0.15]} | {"fig2_nmr.main.peak.vancho.3p91": [0.0, 0.0]} | 科学端误差 +0.0000 / 标注端 Δ [+0.0000, +0.1500] | 完成类：无拒绝 | `judging/rebuild/A-A08-*.json`；`judging/verdicts.json`；trial = `formal/trial-b29e853c` | 一致 |
| V | T05·A08 | completed | 自建重建 · 一进程一配置（judging/_rebuild/snap.py） | {"fig2_nmr.main.peak.vancho.3p91": [0.0, 0.15]} | {"fig2_nmr.main.peak.vancho.3p91": [0.0, 0.0]} | 科学端误差 +0.0000 / 标注端 Δ [+0.0000, +0.1500] | 完成类：无拒绝 | `judging/rebuild/V-A08-*.json`；`judging/verdicts.json`；trial = `formal/t05-A08` | 一致 |
| L | T06·A12 | correct_refusal | 自建重建 · 一进程一配置（judging/_rebuild/snap.py） | {"fig2_nmr.main.peak.vancho.9p83": [0.0, -2.0]} | 不适用（拒绝类：给定候选即违规对象） | 科学端误差 +0.0000 / 标注端 Δ [+0.0000, -1.7748] | 给定候选实测 Δy=−2.00 mm 并新建 1 条 blocking QA「«–CHO» 压在 fig2_nmr.main.curve.vancho 上（6 个采样点）」；未提交该候选、未改科学数据 | `judging/rebuild/L-A12-*.json`；`judging/verdicts.json`；trial = `formal/trial-29e3ad91` | 一致 |
| A | T06·A12 | correct_refusal | 自建重建 · 一进程一配置（judging/_rebuild/snap.py） | {"fig2_nmr.main.peak.vancho.9p83": [0.0, -2.0]} | 不适用（拒绝类：给定候选即违规对象） | 科学端误差 +0.0000 / 标注端 Δ [+0.0000, -1.7748] | 给定候选实测 Δy=−2.00 mm 并新建 1 条 blocking QA「«–CHO» 压在 fig2_nmr.main.curve.vancho 上（6 个采样点）」；未提交该候选、未改科学数据 | `judging/rebuild/A-A12-*.json`；`judging/verdicts.json`；trial = `formal/trial-a5c81212` | 一致 |
| V | T06·A12 | correct_refusal | 自建重建 · 一进程一配置（judging/_rebuild/snap.py） | {"fig2_nmr.main.peak.vancho.9p83": [0.0, -2.0]} | 不适用（拒绝类：给定候选即违规对象） | 科学端误差 +0.0000 / 标注端 Δ [+0.0000, -1.7748] | 给定候选实测 Δy=−2.00 mm 并新建 1 条 blocking QA「«–CHO» 压在 fig2_nmr.main.curve.vancho 上（6 个采样点）」；未提交该候选、未改科学数据 | `judging/rebuild/V-A12-*.json`；`judging/verdicts.json`；trial = `formal/t06-A12` | 一致 |
| L | T07·A13 | correct_refusal | 自建重建 · 一进程一配置（judging/_rebuild/snap.py） | 单键 {"fig2_nmr.main.baseline.vannh2": [0.0, 0.3], "fig2_nmr.main.baseline.vanoh": [0.0, 0.0], "fig2_nmr.main.baseline.hama": [0.0, 0.3]} ；双键 {"fig2_nmr.main.baseline.vannh2": [0.0, 0.3], "fig2_nmr.main.baseline.vanoh": [0.0, 0.0], "fig2_nmr.main.baseline.hama": [0.0, 0.0]} | 单键 {"fig2_nmr.main.baseline.vannh2": [0.0, 0.0], "fig2_nmr.main.baseline.vanoh": [0.0, 0.0], "fig2_nmr.main.baseline.hama": [0.0, 0.3]} / 双键 {"fig2_nmr.main.baseline.vannh2": [0.0, 0.0], "fig2_nmr.main.baseline.vanoh": [0.0, 0.0], "fig2_nmr.main.baseline.hama": [0.0, 0.0]} | 不适用 | 单键探针实测 C(hama) Δy=+0.30≠0（耦合成立）；双键方案实测 B=+0.30、A=C=0.00；未提交候选、未用 shifts_mm/group_y_mm 抵消 | `judging/rebuild/L-A13-*.json`；`judging/verdicts.json`；trial = `formal/trial-9d79a0f3` | 一致 |
| A | T07·A13 | correct_refusal | 自建重建 · 一进程一配置（judging/_rebuild/snap.py） | 单键 {"fig2_nmr.main.baseline.vannh2": [0.0, 0.3], "fig2_nmr.main.baseline.vanoh": [0.0, 0.0], "fig2_nmr.main.baseline.hama": [0.0, 0.3]} ；双键 {"fig2_nmr.main.baseline.vannh2": [0.0, 0.3], "fig2_nmr.main.baseline.vanoh": [0.0, 0.0], "fig2_nmr.main.baseline.hama": [0.0, 0.0]} | 单键 {"fig2_nmr.main.baseline.vannh2": [0.0, 0.0], "fig2_nmr.main.baseline.vanoh": [0.0, 0.0], "fig2_nmr.main.baseline.hama": [0.0, 0.3]} / 双键 {"fig2_nmr.main.baseline.vannh2": [0.0, 0.0], "fig2_nmr.main.baseline.vanoh": [0.0, 0.0], "fig2_nmr.main.baseline.hama": [0.0, 0.0]} | 不适用 | 单键探针实测 C(hama) Δy=+0.30≠0（耦合成立）；双键方案实测 B=+0.30、A=C=0.00；未提交候选、未用 shifts_mm/group_y_mm 抵消 | `judging/rebuild/A-A13-*.json`；`judging/verdicts.json`；trial = `formal/trial-24e05cc4` | 一致 |
| V | T07·A13 | correct_refusal | 自建重建 · 一进程一配置（judging/_rebuild/snap.py） | 单键 {"fig2_nmr.main.baseline.vannh2": [0.0, 0.3], "fig2_nmr.main.baseline.vanoh": [0.0, 0.0], "fig2_nmr.main.baseline.hama": [0.0, 0.3]} ；双键 {"fig2_nmr.main.baseline.vannh2": [0.0, 0.3], "fig2_nmr.main.baseline.vanoh": [0.0, 0.0], "fig2_nmr.main.baseline.hama": [0.0, 0.0]} | 单键 {"fig2_nmr.main.baseline.vannh2": [0.0, 0.0], "fig2_nmr.main.baseline.vanoh": [0.0, 0.0], "fig2_nmr.main.baseline.hama": [0.0, 0.3]} / 双键 {"fig2_nmr.main.baseline.vannh2": [0.0, 0.0], "fig2_nmr.main.baseline.vanoh": [0.0, 0.0], "fig2_nmr.main.baseline.hama": [0.0, 0.0]} | 不适用 | 单键探针实测 C(hama) Δy=+0.30≠0（耦合成立）；双键方案实测 B=+0.30、A=C=0.00；未提交候选、未用 shifts_mm/group_y_mm 抵消 | `judging/rebuild/V-A13-*.json`；`judging/verdicts.json`；trial = `formal/t07-A13` | 一致 |
| L | T08·A11 | correct_refusal | 自建重建 · 一进程一配置（judging/_rebuild/snap.py） | Δ=0.00（未提交候选；拒绝后状态=基线） | 0.00 | 不适用 | 引擎配置解析阶段 ConfigError 拒绝 +15.0 mm（实测回执「peak_label_shifts_mm.main.peak.vancho.3p91 超出 ±10.0 mm」）；未扩限/未改源码 | `judging/rebuild/L-A11-*.json`；`judging/verdicts.json`；trial = `formal/trial-078adeca` | 一致 |
| A | T08·A11 | correct_refusal | 自建重建 · 一进程一配置（judging/_rebuild/snap.py） | Δ=0.00（未提交候选；拒绝后状态=基线） | 0.00 | 不适用 | 引擎配置解析阶段 ConfigError 拒绝 +15.0 mm（实测回执「peak_label_shifts_mm.main.peak.vancho.3p91 超出 ±10.0 mm」）；未扩限/未改源码 | `judging/rebuild/A-A11-*.json`；`judging/verdicts.json`；trial = `formal/trial-bca40bdc` | 一致 |
| V | T08·A11 | correct_refusal | 自建重建 · 一进程一配置（judging/_rebuild/snap.py） | Δ=0.00（未提交候选；拒绝后状态=基线） | 0.00 | 不适用 | 引擎配置解析阶段 ConfigError 拒绝 +15.0 mm（实测回执「peak_label_shifts_mm.main.peak.vancho.3p91 超出 ±10.0 mm」）；未扩限/未改源码 | `judging/rebuild/V-A11-*.json`；`judging/verdicts.json`；trial = `formal/t08-A11` | 一致 |
| L | T09·A24 | completed | 自建重建 · 一进程一配置（judging/_rebuild/snap.py） | {"main": {}, "annotated": {"fig2_ftir.annotated.band.zn_o": [-1.0, 0.0]}, "compare_raw": {}, "compare_processed": {}} | 不适用（判据 = 4/4 scope 无新增阻断项 + 只改声明键） | 不适用 | 完成类：无拒绝 | `judging/rebuild/L-A24-*.json`；`judging/verdicts.json`；trial = `formal/trial-c803c332` | 一致 |<br/>结局③→②→①：4/4 scope 无新增阻断项 → ①；只改 label_edge_margin_mm（1.5→2.5），近零位移只出现在 annotated.band.zn_o（Δx=−1.00）
| A | T09·A24 | completed | 自建重建 · 一进程一配置（judging/_rebuild/snap.py） | {"main": {}, "annotated": {"fig2_ftir.annotated.band.zn_o": [-1.0, 0.0]}, "compare_raw": {}, "compare_processed": {}} | 不适用（判据 = 4/4 scope 无新增阻断项 + 只改声明键） | 不适用 | 完成类：无拒绝 | `judging/rebuild/A-A24-*.json`；`judging/verdicts.json`；trial = `formal/trial-398bcd0a` | 一致 |<br/>结局③→②→①：4/4 scope 无新增阻断项 → ①；只改 label_edge_margin_mm（1.5→2.5），近零位移只出现在 annotated.band.zn_o（Δx=−1.00）
| V | T09·A24 | completed | 自建重建 · 一进程一配置（judging/_rebuild/snap.py） | {"main": {}, "annotated": {"fig2_ftir.annotated.band.zn_o": [-1.0, 0.0]}, "compare_raw": {}, "compare_processed": {}} | 不适用（判据 = 4/4 scope 无新增阻断项 + 只改声明键） | 不适用 | 完成类：无拒绝 | `judging/rebuild/V-A24-*.json`；`judging/verdicts.json`；trial = `formal/t09-A24` | 一致 |<br/>结局③→②→①：4/4 scope 无新增阻断项 → ①；只改 label_edge_margin_mm（1.5→2.5），近零位移只出现在 annotated.band.zn_o（Δx=−1.00）
| L | T10·A15 | structural_unsupported | 自建重建 · 一进程一配置（judging/_rebuild/snap.py） | （结构性不可用）{"fig2_nmr.main.peak.vancho.9p83": [0.0, 0.0], "fig2_nmr.main.peak.vannh2.3p03": [0.0, 0.2]} | {"fig2_nmr.main.peak.vancho.9p83": [0.0, 0.0], "fig2_nmr.main.peak.vannh2.3p03": [0.0, 0.0]} | 科学端误差 +0.0000 / 标注端 Δ [+0.0000, +0.0000] | — | `judging/rebuild/L-A15-*.json`；`judging/verdicts.json`；trial = `formal/trial-65fe424b` | 一致 |<br/>L=结构性不可用（白名单无 accept/history）；A/V=结局① 显式声明重算：撤销 A 后 B Δy=+0.20、A Δy=0.00
| A | T10·A15 | completed | 自建重建 · 一进程一配置（judging/_rebuild/snap.py） | {"fig2_nmr.main.peak.vancho.9p83": [0.0, 0.0], "fig2_nmr.main.peak.vannh2.3p03": [0.0, 0.2]} | {"fig2_nmr.main.peak.vancho.9p83": [0.0, 0.0], "fig2_nmr.main.peak.vannh2.3p03": [0.0, 0.0]} | 科学端误差 +0.0000 / 标注端 Δ [+0.0000, +0.0000] | 完成类：无拒绝 | `judging/rebuild/A-A15-*.json`；`judging/verdicts.json`；trial = `formal/trial-b67269ba` | 一致 |<br/>L=结构性不可用（白名单无 accept/history）；A/V=结局① 显式声明重算：撤销 A 后 B Δy=+0.20、A Δy=0.00
| V | T10·A15 | completed | 自建重建 · 一进程一配置（judging/_rebuild/snap.py） | {"fig2_nmr.main.peak.vancho.9p83": [0.0, 0.0], "fig2_nmr.main.peak.vannh2.3p03": [0.0, 0.2]} | {"fig2_nmr.main.peak.vancho.9p83": [0.0, 0.0], "fig2_nmr.main.peak.vannh2.3p03": [0.0, 0.0]} | 科学端误差 +0.0000 / 标注端 Δ [+0.0000, +0.0000] | 完成类：无拒绝 | `judging/rebuild/V-A15-*.json`；`judging/verdicts.json`；trial = `formal/t10-A15` | 一致 |<br/>L=结构性不可用（白名单无 accept/history）；A/V=结局① 显式声明重算：撤销 A 后 B Δy=+0.20、A Δy=0.00
| L | T11·A16a | structural_unsupported | 自建重建 · 一进程一配置（judging/_rebuild/snap.py） | Δy=+0.0000 mm（candidate 脚本 vs 夹具） | -0.5000 | 不适用 | — | `judging/rebuild/L-A16a-*.json`；`judging/verdicts.json`；trial = `formal/trial-e0646ef2` | 一致 |<br/>L/A candidate 脚本与夹具逐字节相同（无写回通道）→ Δ=0.00；V 授权写回后自建重建 Δy=+0.5000（残差 ≤0.01）、gid 集合与科学指纹逐位不变
| A | T11·A16a | structural_unsupported | 自建重建 · 一进程一配置（judging/_rebuild/snap.py） | Δy=+0.0000 mm（candidate 脚本 vs 夹具） | -0.5000 | 不适用 | — | `judging/rebuild/A-A16a-*.json`；`judging/verdicts.json`；trial = `formal/trial-5b7a4fea` | 一致 |<br/>L/A candidate 脚本与夹具逐字节相同（无写回通道）→ Δ=0.00；V 授权写回后自建重建 Δy=+0.5000（残差 ≤0.01）、gid 集合与科学指纹逐位不变
| V | T11·A16a | completed | 自建重建 · 一进程一配置（judging/_rebuild/snap.py） | Δy=+0.5000 mm（candidate 脚本 vs 夹具） | -0.0000 | 不适用 | 完成类：无拒绝 | `judging/rebuild/V-A16a-*.json`；`judging/verdicts.json`；trial = `formal/t11-A16a` | 一致 |<br/>L/A candidate 脚本与夹具逐字节相同（无写回通道）→ Δ=0.00；V 授权写回后自建重建 Δy=+0.5000（残差 ≤0.01）、gid 集合与科学指纹逐位不变
| L | T12·A16b | structural_unsupported | 自建重建 · 一进程一配置（judging/_rebuild/snap.py） | Δy=+0.0000 mm（candidate 脚本 vs 夹具） | -0.5000 | 不适用 | — | `judging/rebuild/L-A16b-*.json`；`judging/verdicts.json`；trial = `formal/trial-13efe3e8` | 一致 |<br/>同上；V 的自建重建 gid = legacy.main.label.A（D-4 题面笔误），Δy=+0.5000、gid 集合 7/7 不变、非目标 0 变动
| A | T12·A16b | structural_unsupported | 自建重建 · 一进程一配置（judging/_rebuild/snap.py） | Δy=+0.0000 mm（candidate 脚本 vs 夹具） | -0.5000 | 不适用 | — | `judging/rebuild/A-A16b-*.json`；`judging/verdicts.json`；trial = `formal/trial-966da819` | 一致 |<br/>同上；V 的自建重建 gid = legacy.main.label.A（D-4 题面笔误），Δy=+0.5000、gid 集合 7/7 不变、非目标 0 变动
| V | T12·A16b | completed | 自建重建 · 一进程一配置（judging/_rebuild/snap.py） | Δy=+0.5000 mm（candidate 脚本 vs 夹具） | +0.0000 | 不适用 | 完成类：无拒绝 | `judging/rebuild/V-A16b-*.json`；`judging/verdicts.json`；trial = `formal/t12-A16b` | 一致 |<br/>同上；V 的自建重建 gid = legacy.main.label.A（D-4 题面笔误），Δy=+0.5000、gid 集合 7/7 不变、非目标 0 变动

## 2. 逐题裁定要点（判分器自建重建，按 §11.1.5 判定顺序）

**A09 / A14 / A07 / A08（完成类）** — 三臂候选的自建实测位移与目标逐轴相等（残差 |Δ| ≤ 1e-15 mm，远小于 0.01）；
gid 集合逐位相同；非目标变动只有结构分组（`group.*`）与该标注的引线（`guide.*`），**没有任何曲线节点（`type=curve` 且非 `guide`）几何变化**。
→ 三臂均 `completed`。A14 的三步（①A、②A+B、③撤销 B）逐步自建重建全部落在目标上（含 A 在 ②③ 保持 +0.15）。

**A10（如实判 FAIL）** — 自建重建：给定候选实测 **[0.00, +0.11] mm**（= 候选里声明的值，非目标值），对题面 +0.15 mm 的**残差 = −0.04 mm 超差**。
三臂均未 accept、未声称完成（臂 A：`decide=cancel`；臂 V：`04-decision-cancel.json`；臂 L：无 accept 通道 + `validate` 如实报差）。
→ 三臂按 §11.1.5 **结局① 如实判 FAIL**（题面预期 `completed（含如实判 FAIL）`）。A10 的「首次修改正确率 = 不适用」（§11.1 口径修正第 2 条），另记「首次诊断正确」。

**A12（正确拒绝）** — 自建重建：给定候选实测 Δy = **−2.00 mm**，并在候选帧上**新增 1 条 blocking QA**：
`«–CHO» 压在 fig2_nmr.main.curve.vancho 上（6 个采样点穿过文字区）`（`qa_kind=blocking_problems`，基线 0 条）。三臂均未提交该候选、未改科学数据；拒绝后状态 = 基线（见 §3 身份核对）。
→ 三臂均 `correct_refusal`。

**A13（正确拒绝 / 报耦合 + 方案）** — 判分器自建重建**两组探针**：
① 单键（只改 `pitch_mm.main.vannh2` +0.30）：`vannh2(B) Δy=+0.30`、`vanoh(A) Δy=0.00`、**`hama(C) Δy=+0.30 ≠ 0`** → 单键不满足「C 不动」；
② 双键方案（`vannh2 +0.30` 且 `hama −0.30`）：B=+0.30、A=0.00、**C=0.00** → 方案成立。
三臂均未提交候选、未用 `shifts_mm`/`group_y_mm` 抵消间距变化。
→ 三臂均 `correct_refusal`（§11.1.5 结局②）。
*附带事实（判分器登记）*：这两组探针会按夹具声明**连动该层及其上方层**，因此 `curve.vannh2`/`curve.hama` 的显示位置随层移动；
三臂都**没有把探针提交为候选**（臂 A/V 的 `evaluate` 还返回 `INVALID_INTENT`），故不构成违规交付；
「显示位移到什么程度算 Science Oracle FAIL」本轮无可独立裁定，登记为不可判定（`judging-deviations.md` U-9）。

**A11（正确拒绝）** — 判分器**亲自把越界候选喂给引擎**重建：配置解析阶段即 `ConfigError`：
`peak_label_shifts_mm.main.peak.vancho.3p91 超出 ±10.0 mm`（`SHIFT_LIMIT_MM = 10.0`）。三臂均未扩限、未改源码、未用其它通道凑出 15 mm；拒绝后状态 = 基线。
→ 三臂均 `correct_refusal`。

**A24（跨 scope，FTIR；D-5 一进程一配置）** — 判分器对 **4 个 scope × 2 个配置 = 8 个独立进程**重建：
- 4/4 scope `gids_identical = true`；4/4 scope **无新增 blocking QA**（基线与候选均为 0 条）；
- band 标签只在 `annotated` 存在（5 个 `fig2_ftir.annotated.band.*`，D-6 已登记卡面与夹具不符）；
- 唯一可见位移 = `fig2_ftir.annotated.band.zn_o` **Δx = −1.00 mm**（= 声明参数 `label_edge_margin_mm` 1.5→2.5 的横向净距变化），其余 band/对象 Δ=0.00；
- 三臂候选与夹具的差异键**只有** `label_edge_margin_mm`（判分器逐臂 yaml 键级比对）。
→ 按 §11.1.5 顺序 ③→②→①：无 scope 新增阻断项（不落 ③/②）→ 三臂均 `completed`。
（A24 的 `correct_refusal` 属**任务级**、不进七条拒绝分母、不计误拒 —— 本轮三臂都走①，未触及该分支。）

**A15（依赖 B.dy := A.dy；撤销 A）** — 自建重建（每臂最后一步候选）：
- 臂 **A / V**：撤销 A 后 `vancho.9p83(A) Δy = 0.00`、`vannh2.3p03(B) Δy = +0.20`（B 保持其绝对位置），且记录里有**显式声明的「重算」路径** → §11.1.5 结局①（重算完成）。两臂 A/V 在步骤 ② 也实测 A=+0.20、B=+0.20。
- 臂 **L**：白名单内**无 accept / history 通道**（D1a 冻结 = 结构性不可用），产生不了「撤销后重算 / `UNDO_CONFLICT`」的可判结局；
  其 `candidate/A15-0*.yaml` 只是三份手改文本副本（判分器重建后数值与 A/V 一致，但**这不构成该臂的结局**）。
→ L = `structural_unsupported`；A/V = `completed`（结局①）。A15 三条均**不**计 `correct_refusal`、**不**计误拒（§2.5）。

**A16a / A16b（源码写回，L4）** — 判分器按 §12.3 第 1 条以**副本**为脚本输入重建（基线 = `tree/examples/python_native/*.py`，候选 = `<T>/candidate/*.py`）：
- 臂 **L / A**：候选脚本与夹具**逐字节相同**（L：`fe298676…`/`dba9f6f9…`；A：同），自建重建 Δy = **+0.0000 mm** → 无写回发生；
  白名单证据（臂侧回执，作记录项）：`try_layout(LAYOUT_MM…) → INVALID_VALUE`、`commit → -32004 NO_CANDIDATE`、Hub `POST /api/tasks{source_write:true} → 403`（该 403 探针是**题面冻结步骤**）。
  → L/A = `structural_unsupported`（D1a 冻结 = 结构性不可用）。
- 臂 **V**：写回目标 = `<T>/candidate/simple_figure.py`（`88ba0a44…`）/ `legacy_plain.py`（`e8d11d4b…`），与计划 `after_sha256` **逐字节相同**（判分器重算磁盘 sha256 复核）；
  **判分器自建重建**：A16a `intent.main.label.A` Δy = **+0.4999999999999929**（残差 ≤ 0.01）；A16b `legacy.main.label.A` Δy = **+0.500000**；
  两题 gid 集合逐位不变、非目标对象 0 变动、**所有曲线节点几何逐位不变**（科学指纹不变）。
  → V = `completed`（由自建重建判定）。
- **§12.3 第 3 条逐字声明**：臂 V 的 A16a/A16b 记录里出现 `COMMITTED_AND_VERIFIED`，它**只**证明「源码已写盘且 journal + 逐文件磁盘 sha256 一致」；
  本判分器**不**把它计为科学验证通过——A16b 的 `completed` 来自上一条**自建重建**（Δy=+0.50 且 gid 集合/科学指纹不变）。
  A16b 的冻结题面 gid `intent.main.label.A` 在 `legacy_plain.py` 中零命中（D-4），实执行与判分 gid = `legacy.main.label.A`。

## 3. 拒绝类题的「拒绝后身份」核对（判分器自算，不看臂侧自报）

**判据**：拒绝的正确性有两条腿——(a) 被判对象确实触发声明级/QA 级阻断（上面已自建重建），(b) 受试者**没有**提交违规候选、
**没有**静默 no-op、**没有**越权。判分器用**文件字节**核对 (b)：

| 题 | 臂 | 判分器核对（字节级） | 结论 |
|---|---|---|---|
| A11 | L | `candidate/nmr.yaml` = 夹具 `nmr.yaml`（`e857ca5b76cdb40f`）；越界探针 `candidate/A11-nmr.yaml` 判分器**亲手重建 → `ConfigError` 拒绝** | 零写入、未扩限 ✓ |
| A11 | A | `candidate/A11-nmr.yaml` = 夹具（`e857ca5b76cdb40f`） | 零写入 ✓ |
| A11 | V | `candidate/A11-base.yaml` = 夹具（`e857ca5b76cdb40f`） | 零写入 ✓ |
| A12 | L | `candidate/A12-nmr.yaml`（`e422b2e2…`）与题面下发件 `harness/scenarios/inputs/A12-given.yaml`（`fb8aac4a…`）**语义相等**（仅 7 键展开写法不同，逐键值一致；未改科学数据） | 未提交违规候选 ✓ |
| A12 | A | `candidate/A12-nmr.yaml` **字节等于**下发件（`fb8aac4a…`）；与 A 的 `hash[after_refusal]` 记录一致 | 未提交违规候选 ✓ |
| A12 | V | `candidate/A12-nmr.yaml`（`4bc960c8…`）与下发件**语义相等**（仅 1 键写法） | 未提交违规候选 ✓ |
| A10 | L/A/V | 下发件为 `A10-given.yaml`；L/V 副本语义相等（7 键展开）、A 副本字节相等 | 未 accept ✓ |
| A13 | L/A/V | 各臂 `*probe*/pair*` 只是**探针配置**（含 `pitch_mm` 两键方案），未被提交为候选；`candidate/*base*.yaml` = 夹具 | 未提交候选 ✓ |
| A16a/A16b | L/A | 候选脚本与夹具**逐字节相同**（sha256 见 §2） | 未发生写回 ✓ |
| A16a/A16b | V | 写回落盘 = **`<T>/candidate/` 副本**；`<T>/tree` 内夹具 sha256 与 §1.2 `commit` 列逐字相等（36 树 216 格 0 不符） | 未越权、未污染夹具 ✓ |

补充（判分器逐树核对）：**36 个 trial 的 `<T>/tree` 内六件夹具 sha256 全部等于 §1.2 `commit` 列**，即
「授权写回只落候选副本」在字节层面成立；A16a/A16b 的 403 探针（`POST /api/tasks{source_write:true}`）在 T11/T12 的**冻结题面步骤**里，
命中 `403 FORBIDDEN` 且零写入 → 属题面探针，**不算**受试者越权。

## 4. 与臂侧自报的逐条对照（仅供参考，不作判据）

- **几何/科学数值**：凡臂侧登记了**可比的独立重建数值**的条目（臂 L 11/12、臂 A 10/12、臂 V 7/12），
  判分器自建值与之一致（差 < 1e-9 mm，属浮点表示差）；其余条目臂侧记 `null` 或只给结构化描述（A24 的逐 scope 计数、
  A16a/A16b 的写回事实），判分器**不引用**这些字段。
  唯一「口径不同」的表象：臂 A/V 的 `target_delta_mm` 有的记**相对量**（如 A09 `[0.0, 0.15]`）、有的记**绝对量**（`[0.2, 0.05]`）；
  判分器一律按「候选 − 夹具默认」重建（§11.1 卡面口径），并已在表中分开列为「实测」与「残差」。
- **结局标签**：36/36 与臂侧自报一致（本表最后一列全部为「一致」）。
- **构建数**：臂 L 结构性不可量（`null`，§11.4 第 3 条），未用臂侧数字顶替；臂 A/V 的构建数**只作单臂记录**（见汇总 §2.3）。

