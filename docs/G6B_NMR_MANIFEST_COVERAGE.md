# G6b · NMR 科学输入 Manifest 覆盖核对表（收口补充）

> **用途**：核对判分报告里「**18** 棵 NMR 树 × 99 件通过 Manifest」这一计数，与 12 题 × 3 臂里 NMR 题的实际树数（9 题 × 3 臂 = **27 棵**）之间的缺口：另外 **9 棵**究竟什么状态。
> **边界**：本文件只做**归档只读复核**——不重跑任何 Agent trial、不改判分结果、不改产品代码、不改其它文档。复核时间 2026-10-13。
> **证据根**：`D:/L/AI/figpact-archive/g6b-v2/`（只读；`I:` 已不存在）。
> **相关**：轮次偏差见 `docs/G6B_ROUND_DEVIATIONS.md`（D-2 FTIR 输入、D-7 侦察残留）；证据缺口登记见 `docs/G6B_FINAL_ADJUDICATIONS.md` §三。

---

## 0. 结论（先给结果）

| 项 | 树数 | 本次实测结果 |
|---|---|---|
| **NMR trial 树**（T01–T08、T10；9 题 × 3 臂） | **27** | **逐棵 `--verify` → rc=0，「OK: all 99 files match (size + sha256)」（27/27）** |
| 非 trial 的侦察树 `formal/_probe` | 1 | rc=0（99 件 OK）；**不计入 36 条 trial**，不计入 D1/D2 分母 |
| FTIR trial 树（T09·A24 三臂） | 3 | 逐棵 rc=0，「all 43 files match」（3/3） |
| 纯 Python 夹具 trial 树（T11·A16a、T12·A16b，共 6 棵） | 6 | **不适用**：该两题的树内**没有** NMR/FTIR 科学输入（`examples/nmr` 只有 5 个受版本控制的源文件，`examples/ftir` 只有 4 个） |

**要点**

1. 报告里的 **18 是计数缺口，不是「9 棵未核验」**：12 题里 NMR 题是 9 道（T01–T08、T10），三臂各一棵提取树 = 27 棵；**27 棵全部通过**（本次逐棵重跑，命令见 §1）。
2. 判分器侧**没有保存**产生「18」的枚举脚本或日志（§3.1 逐处核对）；因此该数字**无法从归档复现**，本项据实登记为证据缺口（§3.2）。
3. 归档中**唯一**能凑出 18 的清单，是「**trial 目录内留有可机读 NMR 核验记录**」的树：臂 L 9 棵（`evidence/science-verify.txt`）+ 臂 V 9 棵（`out/SETUP.json → science_verify`）= 18；臂 A 的 9 棵**树内没有**该记录（等价字段只写在聚合文件 `formal/armA.json`）。该对应关系可解释数字来源，但属**推断**——见 §3.2，**不得**据此说臂 A 的 9 棵未核验。
4. 「18」的更正读法：**27 棵（+1 棵非 trial 的 `_probe`）**。更正落在本文件，并由 `docs/G6B_JUDGING_SUMMARY.md` 顶部更正索引指向此处（`docs/G6B_JUDGING_PER_TRIAL.md` §0.1 的原句保留、不静默覆盖，该文件不在本次改动范围内）。

---

## 1. 复核口径（可复现）

- **工具**：每棵树**自带**的 `tools/science_manifest.py`（该树由 `git -c core.autocrlf=false archive f101113 | tar -x -C <T>/tree` 提取，`tools/` 随树携带），非工作树、非仓库当前工作副本。
- **manifest**（判分器与三臂共用同一份冻结件）：
  - NMR：`nmr-science-manifest.json` — **99 件 / 4,278,572 字节**（§10.3 冻结；`--include-untracked-only`，`ignored_relpaths` = 5 个受版本控制源文件）
  - FTIR：`ftir-science-manifest.json` — **43 件 / 8,983,804 字节**（D-2 冻结）
- **工作目录**：`cd D:/L/AI/figpact-archive/g6b-v2`（归档只读）。
- **`python -B`**：抑制 `__pycache__` 写入，保证复核不改归档一个字节（与 D-7 同一纪律）。
- **`rc` 语义**（工具自带约定）：`0` = 全部匹配；`1` = 有缺失/多余/大小或内容不符；`2` = 用法或 IO 错误。

**单棵命令模板**（`<T>` = 下表 `trial 目录` 列的值）

```bash
python -B formal/<T>/tree/tools/science_manifest.py --verify nmr-science-manifest.json --root formal/<T>/tree/examples/nmr
```

**全表一键复现**（bash；输出 36 条 trial 的逐行 rc，含不适用判定）

```bash
cd D:/L/AI/figpact-archive/g6b-v2
for T in formal/trial-* formal/t[0-9][0-9]-A*; do
  [ -d "$T/tree/examples" ] || continue
  n=$(find "$T/tree/examples/nmr" -type f | wc -l)
  if [ "$n" -gt 20 ]; then
    python -B "$T/tree/tools/science_manifest.py" --verify nmr-science-manifest.json --root "$T/tree/examples/nmr" >/dev/null 2>&1
    echo "$T  NMR  rc=$?"
  elif [ "$(find "$T/tree/examples/ftir" -type f | wc -l)" -gt 20 ]; then
    python -B "$T/tree/tools/science_manifest.py" --verify ftir-science-manifest.json --root "$T/tree/examples/ftir" >/dev/null 2>&1
    echo "$T  FTIR rc=$?"
  else
    echo "$T  n/a（该题树内无 NMR/FTIR 科学输入）"
  fi
done
# 非 trial 的侦察树（不计入 36 条）
python -B formal/_probe/tree/tools/science_manifest.py --verify nmr-science-manifest.json --root formal/_probe/tree/examples/nmr
```

> 本次实测：`trial-*` 覆盖臂 L/A 的 24 棵；`t[0-9][0-9]-A*` 覆盖臂 V 的 12 棵；合计 **36 棵，无遗漏、无重复**（分类结果：NMR 27 / FTIR 3 / 不适用 6）。
> **注意**：Windows（MSYS/Cygwin bash）下路径展开**大小写不敏感**，写成 `formal/t*-A*` 会额外匹配到 `formal/trial-a5c81212`（臂 A 的 T06 树，已被 `trial-*` 覆盖）→ 重复计数成 28；故此处用 `t[0-9][0-9]-A*`。

---

## 2. 全部 NMR trial 树 → Manifest 核验状态（27 行）

列 `复核命令` 是**该行逐字可跑**的完整命令（工作目录见 §1）。27 行全部实测 **`rc=0`** 且输出 `OK: all 99 files match (size + sha256)`。

| 臂 | 题 | trial 目录（`formal/` 之下） | 树内 `examples/nmr` 文件数 | 核验状态 | 臂侧机读记录 | 复核命令（实测 rc=0） |
|---|---|---|---|---|---|---|
| L | T01·A09 | `trial-b461497e` | 104 | **已核验**（99 件 OK） | `evidence/science-verify.txt` | `python -B formal/trial-b461497e/tree/tools/science_manifest.py --verify nmr-science-manifest.json --root formal/trial-b461497e/tree/examples/nmr` |
| L | T02·A10 | `trial-0a668fc6` | 104 | **已核验**（99 件 OK） | `evidence/science-verify.txt` | `python -B formal/trial-0a668fc6/tree/tools/science_manifest.py --verify nmr-science-manifest.json --root formal/trial-0a668fc6/tree/examples/nmr` |
| L | T03·A14 | `trial-9086d88b` | 104 | **已核验**（99 件 OK） | `evidence/science-verify.txt` | `python -B formal/trial-9086d88b/tree/tools/science_manifest.py --verify nmr-science-manifest.json --root formal/trial-9086d88b/tree/examples/nmr` |
| L | T04·A07 | `trial-217c9fd5` | 104 | **已核验**（99 件 OK） | `evidence/science-verify.txt` | `python -B formal/trial-217c9fd5/tree/tools/science_manifest.py --verify nmr-science-manifest.json --root formal/trial-217c9fd5/tree/examples/nmr` |
| L | T05·A08 | `trial-8348d83a` | 104 | **已核验**（99 件 OK） | `evidence/science-verify.txt` | `python -B formal/trial-8348d83a/tree/tools/science_manifest.py --verify nmr-science-manifest.json --root formal/trial-8348d83a/tree/examples/nmr` |
| L | T06·A12 | `trial-29e3ad91` | 104 | **已核验**（99 件 OK） | `evidence/science-verify.txt` | `python -B formal/trial-29e3ad91/tree/tools/science_manifest.py --verify nmr-science-manifest.json --root formal/trial-29e3ad91/tree/examples/nmr` |
| L | T07·A13 | `trial-9d79a0f3` | 104 | **已核验**（99 件 OK） | `evidence/science-verify.txt` | `python -B formal/trial-9d79a0f3/tree/tools/science_manifest.py --verify nmr-science-manifest.json --root formal/trial-9d79a0f3/tree/examples/nmr` |
| L | T08·A11 | `trial-078adeca` | 104 | **已核验**（99 件 OK） | `evidence/science-verify.txt` | `python -B formal/trial-078adeca/tree/tools/science_manifest.py --verify nmr-science-manifest.json --root formal/trial-078adeca/tree/examples/nmr` |
| L | T10·A15 | `trial-65fe424b` | 104 | **已核验**（99 件 OK） | `evidence/science-verify.txt` | `python -B formal/trial-65fe424b/tree/tools/science_manifest.py --verify nmr-science-manifest.json --root formal/trial-65fe424b/tree/examples/nmr` |
| A | T01·A09 | `trial-8b10cab6` | 104 | **已核验**（99 件 OK） | `formal/armA.json → records[0].isolation.science_manifest` | `python -B formal/trial-8b10cab6/tree/tools/science_manifest.py --verify nmr-science-manifest.json --root formal/trial-8b10cab6/tree/examples/nmr` |
| A | T02·A10 | `trial-fdfcba9f` | 104 | **已核验**（99 件 OK） | `armA.json → records[1]` | `python -B formal/trial-fdfcba9f/tree/tools/science_manifest.py --verify nmr-science-manifest.json --root formal/trial-fdfcba9f/tree/examples/nmr` |
| A | T03·A14 | `trial-bf5f9ffb` | 104 | **已核验**（99 件 OK） | `armA.json → records[2]` | `python -B formal/trial-bf5f9ffb/tree/tools/science_manifest.py --verify nmr-science-manifest.json --root formal/trial-bf5f9ffb/tree/examples/nmr` |
| A | T04·A07 | `trial-80cef1c1` | 104 | **已核验**（99 件 OK） | `armA.json → records[3]` | `python -B formal/trial-80cef1c1/tree/tools/science_manifest.py --verify nmr-science-manifest.json --root formal/trial-80cef1c1/tree/examples/nmr` |
| A | T05·A08 | `trial-b29e853c` | 104 | **已核验**（99 件 OK） | `armA.json → records[4]` | `python -B formal/trial-b29e853c/tree/tools/science_manifest.py --verify nmr-science-manifest.json --root formal/trial-b29e853c/tree/examples/nmr` |
| A | T06·A12 | `trial-a5c81212` | 104 | **已核验**（99 件 OK） | `armA.json → records[5]` | `python -B formal/trial-a5c81212/tree/tools/science_manifest.py --verify nmr-science-manifest.json --root formal/trial-a5c81212/tree/examples/nmr` |
| A | T07·A13 | `trial-24e05cc4` | 104 | **已核验**（99 件 OK） | `armA.json → records[6]` | `python -B formal/trial-24e05cc4/tree/tools/science_manifest.py --verify nmr-science-manifest.json --root formal/trial-24e05cc4/tree/examples/nmr` |
| A | T08·A11 | `trial-bca40bdc` | 104 | **已核验**（99 件 OK） | `armA.json → records[7]` | `python -B formal/trial-bca40bdc/tree/tools/science_manifest.py --verify nmr-science-manifest.json --root formal/trial-bca40bdc/tree/examples/nmr` |
| A | T10·A15 | `trial-b67269ba` | 104 | **已核验**（99 件 OK） | `armA.json → records[9]` | `python -B formal/trial-b67269ba/tree/tools/science_manifest.py --verify nmr-science-manifest.json --root formal/trial-b67269ba/tree/examples/nmr` |
| V | T01·A09 | `t01-A09` | 104 | **已核验**（99 件 OK） | `out/SETUP.json → science_verify.exit=0` | `python -B formal/t01-A09/tree/tools/science_manifest.py --verify nmr-science-manifest.json --root formal/t01-A09/tree/examples/nmr` |
| V | T02·A10 | `t02-A10` | 104 | **已核验**（99 件 OK） | `out/SETUP.json → science_verify` | `python -B formal/t02-A10/tree/tools/science_manifest.py --verify nmr-science-manifest.json --root formal/t02-A10/tree/examples/nmr` |
| V | T03·A14 | `t03-A14` | 104 | **已核验**（99 件 OK） | `out/SETUP.json → science_verify` | `python -B formal/t03-A14/tree/tools/science_manifest.py --verify nmr-science-manifest.json --root formal/t03-A14/tree/examples/nmr` |
| V | T04·A07 | `t04-A07` | 104 | **已核验**（99 件 OK） | `out/SETUP.json → science_verify` | `python -B formal/t04-A07/tree/tools/science_manifest.py --verify nmr-science-manifest.json --root formal/t04-A07/tree/examples/nmr` |
| V | T05·A08 | `t05-A08` | 104 | **已核验**（99 件 OK） | `out/SETUP.json → science_verify` | `python -B formal/t05-A08/tree/tools/science_manifest.py --verify nmr-science-manifest.json --root formal/t05-A08/tree/examples/nmr` |
| V | T06·A12 | `t06-A12` | 104 | **已核验**（99 件 OK） | `out/SETUP.json → science_verify` | `python -B formal/t06-A12/tree/tools/science_manifest.py --verify nmr-science-manifest.json --root formal/t06-A12/tree/examples/nmr` |
| V | T07·A13 | `t07-A13` | 104 | **已核验**（99 件 OK） | `out/SETUP.json → science_verify` | `python -B formal/t07-A13/tree/tools/science_manifest.py --verify nmr-science-manifest.json --root formal/t07-A13/tree/examples/nmr` |
| V | T08·A11 | `t08-A11` | 104 | **已核验**（99 件 OK） | `out/SETUP.json → science_verify` | `python -B formal/t08-A11/tree/tools/science_manifest.py --verify nmr-science-manifest.json --root formal/t08-A11/tree/examples/nmr` |
| V | T10·A15 | `t10-A15` | 104 | **已核验**（99 件 OK） | `out/SETUP.json → science_verify` | `python -B formal/t10-A15/tree/tools/science_manifest.py --verify nmr-science-manifest.json --root formal/t10-A15/tree/examples/nmr` |

27/27 输出 **`OK: all 99 files match (size + sha256)`**、退出码 `0`、0 处不符。
树内 `examples/nmr` 文件数 = 104 = **99 件科学输入** + 5 件受版本控制源文件（`08 NMR.py`、`NMR_generate_all.py`、`figure_style.py`、`nmr.yaml`、`SKILL.md`，即 manifest 的 `ignored_relpaths`）。

### 2.1 非 NMR 的 9 棵 trial 树（逐行给出「不适用 + 原因」）

| 臂 | 题 | trial 目录 | 夹具 | 核验状态 | 原因（实测） |
|---|---|---|---|---|---|
| L | T09·A24 | `trial-c803c332` | FTIR | **已核验（FTIR 43 件 OK）** | `examples/nmr` 无科学输入；FTIR 43 件 `rc=0`（该臂自建 `evidence/ftir-science-manifest.json`，按 D-2 冻结口径同一份 43 件）。命令：`python -B formal/trial-c803c332/tree/tools/science_manifest.py --verify ftir-science-manifest.json --root formal/trial-c803c332/tree/examples/ftir` |
| A | T09·A24 | `trial-398bcd0a` | FTIR | **已核验（FTIR 43 件 OK）** | 同上，`rc=0`。命令：`python -B formal/trial-398bcd0a/tree/tools/science_manifest.py --verify ftir-science-manifest.json --root formal/trial-398bcd0a/tree/examples/ftir` |
| V | T09·A24 | `t09-A24` | FTIR | **已核验（FTIR 43 件 OK）** | 同上，`rc=0`（该臂首跑用 31 件临时副本，按 D-2 冻结 manifest 重跑）。命令：`python -B formal/t09-A24/tree/tools/science_manifest.py --verify ftir-science-manifest.json --root formal/t09-A24/tree/examples/ftir` |
| L | T11·A16a | `trial-e0646ef2` | python_native | **不适用** | 该题夹具是 `simple_figure.py`，树内 `examples/nmr` 仅 5 个源文件、`examples/ftir` 仅 4 个 → **该题树内不存在**任何科学输入集合，manifest 无对象可核 |
| A | T11·A16a | `trial-5b7a4fea` | python_native | **不适用** | 同上 |
| V | T11·A16a | `t11-A16a` | python_native | **不适用** | 同上（`out/SETUP.json → science_manifest = null`，臂侧自身也如实记 null） |
| L | T12·A16b | `trial-13efe3e8` | python_native | **不适用** | 同上 |
| A | T12·A16b | `trial-966da819` | python_native | **不适用** | 同上（`armA.json → records[11].isolation.science_manifest = null`） |
| V | T12·A16b | `t12-A16b` | python_native | **不适用** | 同上 |

> 「不适用」= 该 trial 的夹具不使用 NMR/FTIR 科学输入（协议 §10.3 的 99 件 / 43 件与之无关），**不是**未核验、也不是未通过。

### 2.2 非 trial 的侦察树 `formal/_probe`（不计入 36 条）

| 树 | 状态 | 复核命令 | 说明 |
|---|---|---|---|
| `formal/_probe/tree` | 已核验（99 件 OK，`rc=0`） | `python -B formal/_probe/tree/tools/science_manifest.py --verify nmr-science-manifest.json --root formal/_probe/tree/examples/nmr` | 轮次侦察/预检树，**不是** trial：不进 D1/D2 分母、不进任何结论 |

---

## 3. 「18」这个数是怎么来的（追因：逐处核对 + 推断分列）

### 3.1 判分器侧：该数字**没有**可复现的产生过程（本次逐处核对）

| 核对对象 | 结果 |
|---|---|
| `judging/_rebuild/*.py`（`run.py` / `run_extra.py` / `snap.py` / `analyze.py` / `table.py`） | **无任何 manifest / science-input 复核代码**（全文检索 `manifest`、`verify`、`science_manifest` 零命中） |
| `judging/rebuild/*.json`（102 件逐题原始件）+ `all.json` + `verdicts.json` | **无** per-tree manifest 字段；`all.json` 的 36 个键是重建比较结果；`snap.py` 写出的字段只有 `canvas_bounds_mm/config/nodes/qa/scope/script/...` |
| 归档内 `*.sh` / `*.py`（含 `formal/harness/*`、`harness/*`、根目录预检脚本） | 没有任何**跨树遍历 + manifest 校验**的脚本（唯一的 per-trial 科学核验代码是臂 A 自己的 `formal/harness/leak_check.py`，只覆盖臂 A 的 12 棵，见 §3.2） |
| `judging/per-trial-evidence.md`（及 `docs/G6B_JUDGING_PER_TRIAL.md` 副本） | 「18 个 NMR 树 × 99 件」**只以一句结论出现**，无逐树清单、无命令、无日志 |
| 树内科学输入的**时间戳** | 27 棵 NMR 树副本的最新时间 = **17:58:42**，全部早于判分期（`judging/` 目录时间 18:31–18:54）→ 排除「判分时这 9 棵还没有副本」这一可能 |

→ 结论：判分器这次 manifest 复核**是即席执行、未留脚本与日志**；「18」不是从 `judging/` 的产物里能算出来的数。

### 3.2 归档里唯一凑出 18 的清单（可核对的事实）+ 推断

**事实（可核对）**——「trial 目录**内部**留有可机读 NMR 核验记录」的树，恰好 18 棵：

| 臂 | 树内记录路径 | 棵数 | 证据 |
|---|---|---|---|
| L | `formal/trial-*/evidence/science-verify.txt`（内容含 `rc=0`、`root: …\tree\examples\nmr`、`OK: all 99 files match`） | 9 | 文件系统实测（9 个文件，9 个不同 trial 目录） |
| V | `formal/t0N-*/out/SETUP.json → science_verify = {"cmd": "python tools/science_manifest.py --verify <manifest> --root <T>/tree/examples/nmr", "exit": 0, "stdout": [… "OK: all 99 files match (size + sha256)"]}` | 9 | 文件系统实测 |
| A | **树目录内无此记录**（`formal/trial-*/evidence/` 目录**不存在**；`raw.json` 中零命中） | 0 | 等价字段只写在聚合文件 `formal/armA.json → records[i].isolation.science_manifest`（9 处 `OK: all 99 files match`、1 处 FTIR `all 43 files match`、2 处 `null`） |
| | **合计** | **18** | |

**推断（未观察到判分器的枚举脚本，故只能标为推断）**：判分器很可能按「**树目录内是否有可机读的 `--verify` 记录**」计数，于是只数到臂 L（9）+ 臂 V（9）= 18，漏掉臂 A 的 9 棵（其记录在聚合文件里）。

**必须同时写明的两点**：

1. 该推断**不构成**「臂 A 的 9 棵未核验」的证据——本次逐棵重跑，臂 A 的 9 棵**全部 `rc=0`**（§2 表）。
2. 同一句结论里的 FTIR 计数「**3 个 FTIR 树**」与上述推断口径**不一致**：按同一口径（「树目录内留有记录」）只会数到 **1 棵**——臂 L 的 `formal/trial-c803c332/evidence/ftir-science-manifest.json`（另有 `evidence/summary.json → ftir_science_manifest`）；臂 V 的 `formal/t09-A24/`（`out/` 的 `SETUP.json` 只记首跑的 31 件临时副本，无冻结 43 件的 verify 记录）与臂 A 的 `formal/trial-398bcd0a/`（无 `evidence/` 目录）都不含该记录。而 FTIR = 3 恰好等于**实测**的三臂 A24 树数（三棵树都含 43 件副本且 `rc=0`）。
   → **同一句里的两个数字不是同一套枚举口径的产物**，这也佐证「18」属计数缺口（而不是「9 棵 FTIR 之外的树漏了」）。

### 3.3 影响与更正

- **更正**：`docs/G6B_JUDGING_PER_TRIAL.md` §0.1 的「**18** 个 NMR 树 × 99 件全部 OK」应读作「**27** 棵 NMR trial 树 × 99 件全部 OK（另 1 棵非 trial 的 `_probe` 树同为 rc=0）」。原句保留、不静默覆盖；该文件不在本次改动范围，故在此登记，并由 `docs/G6B_JUDGING_SUMMARY.md` 顶部更正索引指向本文件。
- **对结论的影响**：**无**。27 棵全部 rc=0，NMR 科学输入在 trial 期间未被改动这一条（与「重建后曲线几何逐位不变」互相独立）在**全覆盖**下依然成立；本缺口只影响**计数表述**，不影响任何 D1/D2/安全结论。
- **登记为证据缺口**：见 `docs/G6B_FINAL_ADJUDICATIONS.md` §三「三项证据缺口」第 1 项——「覆盖率数字缺少可复现的产生过程」。若要彻底闭合，只需把 §1 的循环脚本连同输出存进 `judging/`（本轮不重跑、不补写归档）。
