# R4 · 构建系统如何区分「受保护输入被改」与「合法生成物」

> 调研性质：**只读外部资料 + 只读仓库**。本文件是唯一写入产物；未改任何仓库代码，未跑测试，未做 git 操作。
> 场景：`IntentSession` 在候选生成前后各做一次 `_guard()`，负载下偶发 `STALE_REVISION` 误判（P1.5）；目标「真改必拒、没改不误拒」。
> 约定：每条事实给 URL；`[推断]` = 我的推断而非原文；查不到权威来源的写「未找到权威来源」。

---

## 0. 结论（可直接落设计）

1. **身份必须用内容哈希，不能用 `size + mtime`。** git（index）、SCons（默认 Decider）、Bazel（action key）、Shake（à la carte 记述）四家全部落在内容哈希上；用 mtime 的一侧（Make）有官方承认的 racy 缺陷，且现代 Make 官方给出的补救（`.LOW_RESOLUTION_TIME`）是**放宽**判定，方向与「真改必拒」相反。
2. **输入身份 = 声明过的受保护输入集合的内容闭包**，而不是「脚本目录下所有文件」。目录扫描会把产物、临时文件、并发进程写的日志一并算进去 —— 这正是误判的主要来源。
3. **输出不参与输入身份，但输出的*路径名*参与动作身份**（Bazel：`action key = f(输入内容哈希, 输出文件名, 命令行, 声明环境)`；输出内容只是结果）。Ninja 更进一步：`generator` 规则的输出连「命令变了」都不触发重建。
4. **动作期间输入变化 ⇒ 结果作废**：这是 TOCTOU（CWE-367）。正确形态是「动作前一次性快照 → 动作 → 按**同一快照身份**复核 → 不等则作废」，**不是**「动作后重新推导一遍集合再比」（后者会把动作自己写的东西算成输入变化）。
5. Ninja 的官方手法值得直接抄：**记录命令开始时间**（`record_mtime = edge->command_start_time_`），而不是记录输出的完成时间 —— 这样「动作期间被改的输入」不会因为输出更新而被掩盖。
6. figpact 现状里有**两条独立**的误判通道（见 §4.2 M1/M2）：`session.source_revision` 走 `size+st_mtime_ns` 元数据指纹；`intents._source_evidence` 的记录字典**含 `mtime_ns`** 且用整字典相等比较。两条都违反 §0.1。
7. 回归矩阵可直接沿用仓库里已有的两条断言骨架（`eval/verify_real_cutover.py:1178-1223`、`:1227-1307`）+ Ninja `build_test.cc` 的「虚拟文件系统 + 显式时钟 tick + 断言命令执行次数」模式。

---

## 1. 一手来源清单

| # | 主题 | 来源（一手） | URL |
|---|---|---|---|
| S1 | Make：低分辨率时间戳补救 | GNU make 手册 §4.9 Special Built-in Target Names（`.LOW_RESOLUTION_TIME`） | https://www.gnu.org/software/make/manual/html_node/Special-Targets.html |
| S2 | Make：stamp 文件模式 | GNU make 手册 §4.8 Empty Target Files to Record Events | https://www.gnu.org/software/make/manual/html_node/Empty-Targets.html |
| S3 | Make：同一时间戳的标准化讨论 | Austin Group Issue 857（POSIX make 措辞 + RATIONALE） | https://austingroupbugs.net/view.php?id=857 |
| S4 | Ninja：restat / generator / depfile | Ninja 手册（v1.13.1） | https://ninja-build.org/manual.html |
| S5 | Ninja：脏判定与命令开始时间 | `src/graph.cc`、`src/build.cc`、`src/build_test.cc` | https://github.com/ninja-build/ninja/blob/master/src/build.cc |
| S6 | Bazel：action cache / 并发改动 | Bazel 官方 Remote caching 文档 | https://bazel.build/remote/caching |
| S7 | Bazel：命中判定与输出元数据注入 | `ActionCacheChecker.java` | https://github.com/bazelbuild/bazel/blob/master/src/main/java/com/google/devtools/build/lib/actions/ActionCacheChecker.java |
| S8 | SCons：Decider 三档与坑 | SCons User Guide ch.6 | https://scons.org/doc/3.1.0/HTML/scons-user/ch06.html |
| S9 | git：racy-git 的两条机制 | Git 技术文档 racy-git | https://git-scm.com/docs/racy-git |
| S10 | git：racy 判定实现 | `read-cache.c`（`is_racy_stat` / `is_racy_timestamp`） | https://github.com/git/git/blob/master/read-cache.c |
| S11 | 理论：rebuilder 四分类与正确性定义 | *Build Systems à la Carte*（ICFP 2018, DOI 10.1145/3236774） | https://simon.peytonjones.org/assets/pdfs/build-systems-original.pdf |
| S12 | TOCTOU 定义 | CWE-367 | https://cwe.mitre.org/data/definitions/367.html |
| S13 | 乐观并发原语 | RFC 9110 §8.8.3 / §13.1.1 / §15.5.13 | https://www.rfc-editor.org/rfc/rfc9110.html |
| S14 | Windows 文件时间语义 | Microsoft Learn: File Times | https://learn.microsoft.com/en-us/windows/win32/sysinfo/file-times |
| S15 | Python `os.stat` 跨平台语义 | CPython 文档 | https://docs.python.org/3/library/os.html#os.stat_result |
| S16 | 原子替换发布 | Linux man-pages `rename(2)` | https://man7.org/linux/man-pages/man2/rename.2.html |
| S17 | Windows 文件系统 tunneling（15 s 默认） | MS KB172190 存档 + Raymond Chen | https://www.betaarchive.com/wiki/index.php?title=Microsoft_KB_Archive/172190 ； https://devblogs.microsoft.com/oldnewthing/20050715-14/?p=34923 |

---

## 2. 先例逐个看

### 2.1 GNU Make：时间戳判定的原生缺陷 + 官方补救

**缺陷本体**：Make 的「脏」复用文件系统信息。*Build Systems à la Carte* §4.2.1（S11）原文：

> "Make uses file modification times, and compares files to its dependencies, which can be thought of as a dirty bit which is set when a file is older than its dependencies. The interesting property of this dirty bit is that it is not under the control of Make; rather it is existing file-system information that has been repurposed. … **Note that Make requires that file timestamps only go forward in time, which can be violated by backup software.**"

同一篇论文脚注 5（p.79:4）：

> "Technically, you can fool Make by altering the modification time of a file without changing its content, e.g. by using the command `touch`. **Make is therefore minimal only under the assumption that you do not do that.**"

→ 这两句就是「touch 即误判」与「时间戳回拨即漏判」两个方向的官方定性。

**补救一：`.LOW_RESOLUTION_TIME`（S1）** —— 官方承认低分辨率时间戳会导致错误判定，做法是**放宽**：

> "The high resolution file time stamps of many modern file systems lessen the chance of `make` incorrectly concluding that a file is up to date. Unfortunately, some hosts do not provide a way to set a high resolution file time stamp, so commands like `cp -p` that explicitly set a file's time stamp must discard its sub-second part. If a file is created by such a command, you should list it as a prerequisite of `.LOW_RESOLUTION_TIME` so that `make` does not mistakenly conclude that the file is out of date. … The `.LOW_RESOLUTION_TIME` line causes `make` to consider `dst` to be up to date if its time stamp is at the start of the same second that `src`'s time stamp is in."

**补救二：stamp 文件（S2）** —— 用「空目标文件的 mtime」记录「上次执行动作的时刻」：

> "The purpose of the empty target file is to record, with its last-modification time, when the rule's recipe was last executed. It does so because one of the commands in the recipe is a `touch` command to update the target file. The empty target file should have some prerequisites (otherwise it doesn't make sense)."

**补救三：标准化层的措辞（S3）** —— Austin Group Issue 857 的 Final Accepted Text 把「同一时间戳」显式纳入可能过期的情形，并在 RATIONALE 里给出粒度处理规则：

> "A target may also be considered out-of-date when it has the same timestamp as any of its prerequisites that have not been made up-to-date by the current invocation of make."

> "All implementations of make should make full use of the finest timestamp resolution available on the filesystems holding targets and prerequisites to ensure that targets are up-to-date even for prerequisite files with timestamps that were updated within the same second. **However, if the timestamp resolutions of the filesystems containing a target and a prerequisite are different, the timestamp with the more precise resolution should be rounded down to the resolution of the less precise timestamp for the comparison.**"

→ 对 figpact 的可移植教训：**比较不同来源的时间戳必须先把精度对齐（向下取整）**；跨盘/跨文件系统（本地 NTFS ↔ 网络盘/移动盘）时尤其如此。`[推断]` 我们的候选若在 A 盘生成、输入在 B 盘，mtime 直比必错。

### 2.2 Ninja：restat / depfile / 命令开始时间 / generator

**restat（早停，early cutoff）**（S4）：

> "restat — if present, causes Ninja to re-stat the command's outputs after execution of the command. **Each output whose modification time the command did not change will be treated as though it had never needed to be built.** This may cause the output's reverse dependencies to be removed from the list of pending build actions."

**restat 在脏判定中的特殊分支**（S5，`src/graph.cc` 注释）：

> "// If this is a restat rule, we may have cleaned the output in a previous run and stored the command start time in the build log. // We don't want to consider a restat rule's outputs as dirty unless an input changed since the last run, so we'll skip checking the output file's actual mtime and simply check the recorded mtime from the log against the most recent input's mtime"

**关键手法：记录「命令开始时间」而不是输出 mtime**（S5，`src/build.cc`）：

```cpp
    if (build_start == -1) {
      disk_interface_->WriteFile(lock_file_path_, ".", false);
      // It's necessary to write at least one byte to the lock file because
      // otherwise, certain filesystems (e.g. tmpfs on macOS; AWS FSx mounted
      // via NFS) expose a bug in their fopen() implementations where they
      // fail to update the lock file's mtime.
      build_start = disk_interface_->Stat(lock_file_path_, err);
      ...
    }
  }
  edge->command_start_time_ = build_start;
```

```cpp
    // Restat the edge outputs
    TimeStamp record_mtime = 0;
    ...
      record_mtime = edge->command_start_time_;
```

→ 这正是「动作期间输入被改」的解法：动作的**时间下界**被固定下来，任何在此之后变动的输入都能被识别，不会被「输出刚写、看起来更新」掩盖。`[推断]` 我们对应的量是「候选创建时刻 / 动作开始时刻」。

**depfile 的容错与生成物清理**（S5，`src/build.cc`）：

> "// Read depfile content. **Treat a missing depfile as empty.**"

> "// Only delete this output if it was actually modified. This is important for things like the generator where we don't want to delete the manifest file if we can avoid it."

**generator 属性（生成物特例）**（S4）：

> "generator — if present, specifies that this rule is used to re-invoke the generator program. Files built using generator rules are treated specially in two ways: **firstly, they will not be rebuilt if the command line changes; and secondly, they are not cleaned by default.**"

**动作身份包含命令行**（S4，Design goals）：

> "Outputs implicitly depend on the command line that was used to generate them, which means that changing e.g. compilation flags will cause the outputs to rebuild."

### 2.3 Bazel：输入指纹进 key，输出不进 key

**结构**（S6）：

> "Bazel breaks a build into discrete steps, which are called actions. **Each action has inputs, output names, a command line, and environment variables.** Required inputs and expected outputs are declared explicitly for each action."

> "The remote cache stores two types of data: The action cache, which is a map of action hashes to action result metadata. A content-addressable store (CAS) of output files."

→ 注意「output **names**」进动作定义，而**输出内容**只作为「action result metadata」存在。这就是「输出不参与输入指纹」的一手依据。

**动作期间输入变化（TOCTOU）**（S6，Known issues）：

> "**Input file modification during a build** — When an input file is modified during a build, Bazel might upload invalid results to the remote cache. You can enable a change detection with the `--experimental_guard_against_concurrent_changes` flag. There are no known issues and it will be enabled by default in a future release. … Generally, avoid modifying source files during build."

**命中判定与输出元数据的处理**（S7）：

> "Checks whether an `Action` needs to be executed, or whether it has not changed since it was last stored in the action cache."

> "The fingerprint, input files names, and metadata (either mtimes or MD5sums) of each action are cached in the action cache to avoid unnecessary rebuilds."

> "// Inject cached output metadata if we have an action cache hit."

> "Metadata retrieved from the filesystem overrides the cached metadata. This way, an action will not be rerun if the cached metadata is still valid, unless the filesystem state needs to be updated."

→ 两条要点：(a) 命中后 Bazel **相信**缓存里的输出元数据并注入（不重新走一遍输入推导）；(b) 但**文件系统的元数据优先于缓存元数据** —— 即「缓存说的不算，盘上说的算」，同时仍然只用于「要不要重跑」，不改变输入身份。

### 2.4 SCons：Decider 三档，以及官方自己写明的坑

**默认 = 内容签名（MD5）**（S8）：

> "By default, SCons keeps track of whether a file has changed based on an MD5 checksum of the file's contents, not the file's modification time."

**early cutoff 的正名**（S8）：

> "In essence, SCons "short-circuits" any dependent builds when it realizes that a target file has been rebuilt to exactly the same file as the last build."

**`MD5-timestamp` 的 false-negative（我们最该避免的档位）**（S8）：

> "The only drawback to using `Decider('MD5-timestamp')` is that SCons will *not* rebuild a target file if a source file was modified **within one second** of the last time SCons built the file."

**`timestamp-newer` 的方向性缺陷**（S8）：

> "One drawback to using time stamps exactly like Make is that if an input file's modification time suddenly becomes *older* than a target file, the target file will not be rebuilt. This can happen if an old copy of a source file is restored from a backup archive, for example."

### 2.5 git index：racy-git —— 与本例最贴近的正面模板

**问题定义与两条机制**（S9）：

> "If the modification that follows it happens very fast so that the file's `st_mtime` timestamp does not change, after this sequence, the cached stat information the index entry records still exactly match what you would see in the filesystem, even though the file `foo` is now different. This way, Git can incorrectly think files in the working tree are unmodified even though they actually are. This is called the "racy Git" problem … and the entries that appear clean when they may not be because of this problem are called "racily clean"."

> "1. When the cached stat information says the file has not been modified, and the `st_mtime` is the same as (or newer than) the timestamp of the index file itself …, **it also compares the contents with the object registered in the index entry to make sure they match.**
> 2. When the index file is updated that contains racily clean entries, **cached `st_size` information is truncated to zero** before writing a new version of the index file."

**实现层的判定谓词**（S10，`read-cache.c`）：

```c
static int is_racy_stat(const struct index_state *istate, const struct stat_data *sd) {
	return (istate->timestamp.sec &&
		/* nanosecond timestamped files can also be racy! */
		(repo_config_values(istate->repo)->use_nanosec ? (istate->timestamp.sec < sd->sd_mtime.sec ||
		(istate->timestamp.sec == sd->sd_mtime.sec && istate->timestamp.nsec <= sd->sd_mtime.nsec)) : istate->timestamp.sec <= sd->sd_mtime.sec));
}
```
```c
	/* Racily smudged entry? */
	if (!ce->ce_stat_data.sd_size) {
		if (!is_empty_blob_oid(&ce->oid, the_repository->hash_algo))
			changed |= DATA_CHANGED;
	}
```
```c
	if (!changed && is_racy_timestamp(istate, ce)) {
		if (assume_racy_is_modified) changed |= DATA_CHANGED;
		else changed |= ce_modified_check_fs(istate, ce, st);
	}
```

→ 三条可直接搬的设计：
1. **时间戳相等/更老 ⇒ 一律复算内容**（`<=`，不是 `<`；注释明确「纳秒时间戳也会 racy」）。
2. 复算结果作为最终判据（`ce_modified_check_fs`），元数据只做快速路径。
3. **写入侧主动破坏可疑的快速路径**（把 `sd_size` 涂抹为 0），使后续检查不得不走内容比对 —— 「宁可慢一次，不可漏一次」的工程手法。

---

## 3. 通用原则（把先例抽象出来）

- **P1 输入是集合，不是目录。** 先声明「本次动作读了哪些路径」（闭包），再对这个集合取指纹。Bazel：`Required inputs … are declared explicitly`（S6）。
- **P2 身份是内容哈希。** git / SCons / Bazel / Shake 一致；mtime 只允许做加速器，且必须在「相等/更老」时降级为内容比对（S9/S10）。
- **P3 输出不参与输入身份，输出路径名参与动作身份。**（S6；Ninja `generator` 是更极端的特例，S4）
- **P4 产物分类必须显式且按路径身份，不能按后缀。** SCons 的 `MD5-timestamp` 与 Make 的 `.LOW_RESOLUTION_TIME` 都是「按规则放宽」的例子；Bazel 的声明式输入输出是「按身份收紧」的例子。仓库内已有同向约定：`figpact/agent_api.py:96-99`「Nothing is skipped by extension — a `.png`/`.pdf`/`.json` next to the script can be a scientific input」。
- **P5 动作期间输入变化 ⇒ 结果作废（TOCTOU）。** 定义见 S12：

  > "The product checks the state of a resource before using that resource, but the resource's state can change between the check and the use in a way that invalidates the results of the check."

  Bazel 的官方缓解手段就是那个 flag（S6）；Ninja 的手段是把动作的**时间下界**固化（S5）。
- **P6 「快照 → 动作 → 复核」必须用同一个身份。** 快照里存的是「集合 + 每个成员的内容哈希 + 动作开始时刻」；动作后复核的是**同一集合**的当前哈希。动作新写出的、不在快照集合里的路径**不参与**判定（否则就是「自己污染自己」）。
- **P7 乐观并发 + 原子发布。** 版本比较失败的语义在 HTTP 里有成熟定义（S13）：

  > "An origin server that evaluates an `If-Match` condition MUST NOT perform the requested method if the condition evaluates to false. Instead, the origin server MAY indicate that the conditional request failed by responding with a 412 (Precondition Failed) status code."

  并且 RFC 明确「实体标签比修改日期更可靠」：

  > "An entity tag can be more reliable for validation than a modification date in situations where it is inconvenient to store modification dates, where the one-second resolution of HTTP-date values is not sufficient, or where modification dates are not consistently maintained."

  发布侧的原子性（S16）："If `newpath` already exists, it will be **atomically replaced**, so that there is no point at which another process attempting to access `newpath` will find it missing."
- **P8 早停（early cutoff）只在**「动作身份没变 **且** 输出内容没变」时成立（SCons 的 short-circuit、Ninja 的 restat、à la carte 的 cutoff 列）。à la carte §4.2.2（S11）：

  > "A verifying trace, and other types of traces discussed in this section, support dynamic dependencies and minimality; furthermore, all traces except for deep traces support early cutoff."

- **P9 正确性的形式化（值得直接引为验收判据）。** à la carte Definition 3.1（S11）把「构建结果正确」定义为两条：

  > "result and store agree on inputs, that is, for all input keys k ∈ I: `getValue k result == getValue k store`. In other words, no inputs were corrupted during the build."
  > "The result is consistent with the tasks, i.e. for all non-input keys k ∈ O, the result of recomputing the corresponding task matches the value stored in the result: `getValue k result == compute task result`."

  映射：**候选的「输入身份」必须等于最终盘上重算出的身份**；不等则候选无效（拒），而不是把差异解释成「用户改了源」。同时注意 §4.2.2 把「记录依赖哈希的轨迹」正式命名为 **verifying trace**：

  > "Rather than storing (large) values v, the verifying trace **VT** stores only hashes, of type **Hash** v, of those values."

---

## 4. 映射到 figpact

### 4.1 三类清单（以仓库现状为准）

证据：`examples/ftir/` 目录内容（脚本 `plot_ftir.py`、配置 `ftir.yaml`、helper `figure_style.py`、原始仪器数据目录 `2084_*/`、以及产物 `Fig2_*.png/pdf/svg/tiff` 与 `SKILL.md` **同处一个目录**）；`.gitignore` 列出的 `__pycache__/`、`*.py[cod]`、`figpact-stage-*/`、`ftir-stage-*/`、`examples/**/Fig2_*`。

| 类别 | 具体对象 | 判定依据 |
|---|---|---|
| **受保护输入**（进指纹） | 绘图脚本 `*.py`（含同目录 helper / 被 import 的模块） | 契约里的 `script`；`figpact/session.py:117` 的 `script_fingerprint` 扫 `script.parent` |
| | 配置 YAML | `source_revision` 以 `config.read_bytes()` 起头（`figpact/session.py:211-212`） |
| | **显式声明的科学输入**（仪器原始数据、处理元数据，可能不在脚本目录） | `SCIENCE_INPUTS` / `science_inputs()`（`figpact/session.py:158-187`），`required=` 参数 |
| | **引擎实现自身**（`figpact/*.py`） | `engine_fingerprint()`（`figpact/session.py:146-154`）—— 见 M6 |
| **合法生成物**（不进指纹） | 契约声明的 outputs（`Fig2_*.png/pdf/svg/tiff`） | `declared_output_stems()`（`figpact/session.py:189-197`）→ `state['artifact_outputs']` |
| | 发布中间体 `.tmp_<name>` | `figpact/publish.py:59-63`（同目录临时文件 + `os.replace`） |
| | `__pycache__/`、`*.pyc` | `session.py:130-131`、`agent_api.py:126-127` 显式跳过 |
| | stage 目录（`figpact-stage-*/`、`ftir-stage-*/`） | 仅 `.gitignore` 声明；**指纹代码不排除** → 见 M3 |
| | `.figpact-*` 前缀临时物 | 只有 `agent_api.source_fingerprint` 跳过（`agent_api.py:129-130`）；`session.script_fingerprint` **不跳过** → 见 M3 |
| **灰区（必须显式声明，二选一）** | 扩展名像产物但实为科学输入的文件（`.png/.pdf/.json/.tiff`） | 仓库已明确（`agent_api.py:96-99`）；当前靠「声明的输入优先于排除」实现（`session.py:124-126`） |
| | 脚本自己写出的**未声明**新变体（如 `_annotated.*`） | 现状**既不排除也不算输入** → 直接进指纹 |
| | 同目录文档（`SKILL.md` 等） | 现状**会被算进指纹**（`rglob('*')` 全量扫） |
| | 诊断 / proof 渲染缓存 | 需显式分类，否则见 M3 |

### 4.2 误判最可能路径（带仓库行号证据）

**M1 · 元数据指纹把 `touch` 当「改」**（最直接的一条）
`figpact/session.py:117-138` 的 `script_fingerprint` 逐文件累加 `f'{p}:{stat.st_size}:{stat.st_mtime_ns}'`；`IntentSession._current_source()`（`figpact/intents.py:614-618`）调 `source_revision` → `module_revision` → `script_fingerprint`；`_guard` 在 `intents.py:620-627` 用 `!=` 判定 `STALE_REVISION`。
→ 任何受保护输入被 `touch`（内容一字未变）→ 指纹必变 → **误拒**。这与 `agent_api.source_fingerprint` 文档的承诺（`agent_api.py:90-92`「Content, not mtime: a touched-but-unchanged file is not a change」）自相矛盾。

**M2 · 记录字典含 `mtime_ns`，整字典相等比较**
`figpact/intents.py:101-103` `_file_record` 返回 `{'sha256', 'size', 'mtime_ns'}`；基线在 `intents.py:240` 捕获（`self._source_files = self._live_source()`）；`_source_fresh()`（`intents.py:328-333`）做 `self._live_source() == self._source_files` **整字典比较**，其中每个文件记录都含 `mtime_ns`。
→ 即使哈希完全相同，只要 mtime 变了就判「不新鲜」；`_guard` 因此也拒。这是 M1 的同源第二通道。

**M3 · 动作期间/之后新出现的文件进指纹**
`_source_evidence`（`intents.py:137-190`）与 `script_fingerprint`（`session.py:117-138`）都 **`rglob` 整个脚本目录**；`files` 字典以**绝对路径为键**，新增文件 ⇒ 新键 ⇒ 字典不等。
三个具体来源：
- `_rebuild()` 会开**第二个** `FigureSession(state['script'], state['config'], ...)`（`intents.py:695-709`）→ 模块导入产生 `__pycache__`（已排除），但脚本若有模块级写盘（缓存、`savefig`、临时文件）就落进指纹。
- `publish()` 在**目标文件自己的目录**写 `.tmp_<name>`（`publish.py:59-63`）；目标是脚本目录时，`.tmp_Fig2_*.png` 既不在 outputs 里、也不在 `__pycache__`/`.figpact-*` 跳过名单里 → 发布中的窗口期必然改变指纹。
- 同目录其它进程写入（浏览器套件截图、日志、诊断文件）同理。

**M4 · 排除集合在「基线」与「复核」之间不是同一个**
基线用的是捕获时刻的 `state['artifact_outputs']`（`intents.py:240` → `intents.py:137` 的 `exclude`），复核用的是**当前** `state['artifact_outputs']`（`intents.py:614-618`）；两者都来自「此刻的 core state」，而契约/输出声明在会话过程中可能变化（例如首次 evaluate 之后输出集合被补齐）。
→ 集合本身变了 ⇒ 指纹必不同 ⇒ 与「源有没有改」无关的**误拒**。这正是 P1.5 记的「重建后复校源修订的竞态」的结构性版本。

**M5 · 反向误判（漏拒）**
`size + mtime_ns` 指纹在「同尺寸 + 同时间戳」的就地改写前完全失效：
- Windows FAT32 的 mtime 分辨率是 **2 秒**（S15 原文：`on Windows systems using the FAT32 file systems, st_mtime has 2-second resolution`）；Python 也明确 `st_mtime_ns … many systems do not provide nanosecond precision`。
- 文件时间只在「写句柄关闭」时保证被反映（S14 原文：`The only guarantee about a file time stamp is that the file time is correctly reflected when the handle that makes the change is closed.`），NTFS 还会延迟 last-access 更新至多 1 小时。
- 备份/拷贝恢复、`os.utime` 回拨、`cp -p` 类操作都会让 mtime 变老或不变（S1、S8、S11 均点名）。
- git 的实现注释直接提醒：`/* nanosecond timestamped files can also be racy! */`（S10）。
→ 结论：metadata 指纹**两头都错**（touch 误拒、就地改写漏拒），不能作为唯一判据。

**M6 · 引擎自身文件进指纹**
`source_revision` = 配置字节 + `module_revision`（含 `engine_fingerprint()`，`session.py:146-154`，同样用 `size+mtime_ns` 扫 `figpact/*.py`）；`_source_evidence` 还额外把 `engine_files` 放进待比较字典（`intents.py:137-190`）。
→ 开发/热更/任何进程 touch 引擎文件 ⇒ 误判 `STALE_REVISION`。`[推断]` 对「引擎版本变了要作废缓存」是合理的，但它不该和「用户改了源」共用同一个错误码与同一条比较路径。

**M7 · 窗口大小 = 整个重建时长**
`evaluate()` 的顺序是 `_rebuild(...)` → `if self._guard(request): return STALE_REVISION`（`intents.py:794-798`）。即：**判定发生在动作之后**，窗口覆盖整段重建 + 捕获 + QA。
→ 与 `docs/G6B_FINAL_ADJUDICATIONS.md` 记录的「负载下偶发（同一 evaluate 纯 HTTP 连打 90 次全 OK；带诊断的全套 9 次全绿）」在形态上吻合：负载越重、窗口越长、M3/M4 命中的概率越高。`[推断]` 这也是 P1.5 记录里「方向：重建前一次性快照修订并据此判定，而非重建后再比」的成因。

### 4.3 最小改动方向（只给顺序与接口，不给代码）

1. **统一判据到内容哈希。** 陈旧判定路径上只允许内容哈希（可复用 `intents._file_record` / `_source_evidence` 或 `agent_api.source_fingerprint`）；`size/mtime_ns` 从「判定」降级为「是否需要复算哈希」的加速器，并按 S10 的 `<=` 语义（相等/更老 ⇒ 强制复算）+ 按 S3 的「精度向下对齐」处理跨盘。
2. **比较时做投影。** 比 `{path: sha256}`，不比 `{path: {sha256, size, mtime_ns}}`（否则 M2 依旧）。
3. **快照前移并冻结。** 在动作**开始前**一次性固定：受保护输入集合 + 每个成员的内容哈希 + 动作开始时刻（Ninja 的 `command_start_time_` 思路，S5）。动作后按**同一集合**复核。
4. **排除集合闭包化。** 动作前把 `outputs ∪ .tmp_* ∪ __pycache__/*.pyc ∪ stage 目录 ∪ 显式声明前缀` 一次冻结成路径身份集合；动作新写出的、不在集合里的路径不参与判定（这是消灭 M3/M4 的正手）。
5. **有界重试 + 可诊断证据。** 复核失败 → 作废 → 重试**一次** → 仍失败才返回 `STALE_REVISION`，且响应里带「哪些路径、哪个字段、前后值」；否则 P1.5 这类抖动无法定位（现状只回一句「重建期间源文件发生变化」）。
6. **引擎版本与用户源分开表达。** `[推断]` 引擎变化应当是「会话失效 / 需重开」，不该复用「源改了」的错误码语义（M6）。

---

## 5. 测试设计参考：真变必拒 / 无变不误拒 的回归矩阵

### 5.1 两个可抄的先例

**(a) Ninja 的虚拟文件系统 + 显式时钟**（S5，`src/build_test.cc`）：
- `struct BuildTest : … { FakeCommandRunner command_runner_; VirtualFileSystem fs_; … }`
- 用 `fs_.Create("in", "")`、`fs_.Tick()` 控制时间前进，断言 `command_runner_.commands_ran_.size()`。
- 现成用例：`TEST_F(BuildWithLogTest, RestatTest)`、`TEST_F(BuildWithLogTest, RestatMissingFile)`（注释："If a restat rule doesn't create its output, and the output didn't exist before the rule was run, consider that behavior equivalent to a rule that doesn't modify its existent output file."）。

→ 要点：**时间与文件系统都要可注入**，否则「同尺寸同 mtime」这类场景在真机上无法稳定复现。

**(b) 仓库已有的两条断言骨架**（`eval/verify_real_cutover.py`）：
- `:1178-1223` `science_input_revision_semantics`：只改「声明为该作用域产物」的文件 ⇒ revision **必须不变**；改声明的科学输入 ⇒ revision **必须变**（断言名 `artifact_change_kept_revision` / `input_change_bumped_revision`）。
- `:1227-1307`：源文件内容变更后，旧候选不能提交（`STALE_REVISION`）、配置副本一字节不动。

→ 这两条已经是「真变必拒 / 无变不误拒」的雏形，扩成矩阵即可。

### 5.2 矩阵（行 = 事件，列 = 期望）

| # | 事件 | 期望 | 依据 |
|---|---|---|---|
| 1 | 无任何变化，重复 evaluate | 不拒 | P6 |
| 2 | `touch` 受保护输入（内容相同） | **不拒** | S8/S11（touch 不是变更）；当前会拒 → M1/M2 |
| 3 | 就地改写、尺寸与 mtime 均不变（`os.utime` 伪造） | **必拒** | S9/S10（racy 复算内容） |
| 4 | 改写输入内容（尺寸变 / 不变） | 必拒 | S8 |
| 5 | 输出图被重写或删除 | 不拒 | S6（输出不进输入身份） |
| 6 | 新增未声明输出变体（如 `_annotated.*`） | 不拒（或显式声明后不拒） | P4；当前会拒 → M3 |
| 7 | 发布进行中，脚本目录存在 `.tmp_*` | 不拒 | `publish.py:59-63`；当前会拒 → M3 |
| 8 | `__pycache__` 新建/删除 | 不拒 | `session.py:130-131` |
| 9 | stage 目录被写入 | 不拒（需补进排除集） | `.gitignore`；当前会拒 → M3 |
| 10 | 声明的科学输入被删除 | 必拒（"MISSING" 也是一种身份） | `agent_api.py:132-135` |
| 11 | 并发进程在脚本目录写日志/截图 | 不拒 | P1 |
| 12 | 引擎文件被 touch | 不拒（但应另走「会话失效」语义） | M6 |
| 13 | 时钟回拨 / 备份恢复（mtime 变老） | 必拒（内容变了的话） | S8/S11 |
| 14 | 把 mtime 量化到 2 秒后写入（模拟 FAT32/网络盘） | 必拒 | S15/S14 |
| 15 | 重建**期间**改写受保护输入（动作中途） | 必拒 | S6/S12；建议用「动作开始时刻」做下界（S5） |
| 16 | 基线后契约新增一个 output（排除集变化） | 不拒 | P6；当前会拒 → M4 |
| 17 | 同一 evaluate 并发/高负载连打 N 次 | 全部不拒、零 `STALE_REVISION` | `docs/G6B_FINAL_ADJUDICATIONS.md` P1.5 的 90 次先例 |

### 5.3 工程手段

- 注入**虚拟时钟 + 虚拟文件系统**（Ninja 模式），把「同秒/同纳秒/2 秒粒度」变成可确定复现的用例。
- 在 `_rebuild` 前后各插一个 hook 制造「动作期间写入」，覆盖 #15。
- 每次失败输出 evidence（路径 + 字段 + 前后值），否则矩阵只能给出「又抖了」。
- 抖动类（#17）用「重复 N 次 + 零容忍」而不是「一次通过」。

---

## 6. 方案候选与风险

| 方案 | 内容 | 收益 | 风险 / 代价 |
|---|---|---|---|
| **A（推荐基线）** | 判据统一为内容哈希；比较做 `{path: sha256}` 投影；快照前移并冻结集合；排除集闭包化（outputs ∪ `.tmp_*` ∪ pycache ∪ stage ∪ 前缀） | 直接消灭 M1/M2/M3/M4；改动局限在指纹与 `_guard` 的调用顺序 | 每次候选全目录哈希的开销（可用 SCons 的 MD5-timestamp 思路做加速，但必须带 `<=` 复算语义）；需保证快照与复核用**同一个** `output_dir` |
| **B** | A + 有界重试一次 + evidence（路径/字段/前后值） | 把「自己污染自己」与「用户真改」区分开；P1.5 可诊断 | 语义要写清：重试只在「受保护输入集合内容未变」时允许，否则等于放行陈旧结果 |
| **C（结构解）** | 把产物/中间物/缓存全部挪到专用输出目录（`output_dir` 与脚本目录分离），脚本目录回归「纯输入」 | 从结构上消灭 M3/M4；与 Bazel「声明式输入输出」同构 | 需要改契约/发布路径与现有 examples（产物当前与脚本同目录，见 §4.1）；迁移成本最高，收益最稳 |
| **D** | 保留 mtime 做加速，内容哈希兜底（SCons `MD5-timestamp` 档） | 性能最好 | S8 自己写明的 1 秒窗口漏判；必须叠加「mtime 相等/更老 ⇒ 强制复算」，等于实现 git 的 `is_racy_stat`（S10）。跨盘还需精度向下对齐（S3） |
| **E** | 记录「动作开始时刻」（Ninja 手法，S5），任何 mtime ≥ 该时刻的受保护输入视为可疑、强制复算哈希 | 正面处理「动作期间被改」 | 需要单调时钟 + 处理时钟回拨；单独用不够，须与 A 组合 |

**共同风险**：跨盘/网络盘 mtime 语义（S3/S14/S15）；Windows 侧 `st_ctime` 不可用（S15：`Changed in version 3.12: st_ctime is deprecated on Windows`，且 NTFS tunneling 会复原创建时间，S17）；灰区文件（未声明却被写出的产物）只能靠声明纪律解决；性能上「全目录哈希」在 examples 里包含仪器原始数据目录，需评估体量（`[推断]` 建议只对**声明集合**取哈希，而不是继续 `rglob` 整个脚本目录）。

---

## 7. 不要照抄的地方

1. **不要把 `.LOW_RESOLUTION_TIME` 那套「同一秒内视为未变」搬过来**（S1）—— 那是**放宽**判定，方向与「真改必拒」相反。
2. **不要用 Make 式「目标比前提新」的方向性比较**（S11 §4.2.1 已指出它要求时间戳单调向前）—— 我们判的是「输入集合身份是否变」，不是「谁更新」。
3. **不要把 SCons 的 `MD5-timestamp` 当默认档**（S8 自己写明 1 秒内改动不重建）。
4. **不要依赖 Bazel 的 `--experimental_guard_against_concurrent_changes`**：官方仍标 experimental，且它只覆盖「别把无效结果传上缓存」，不覆盖「本地候选是否仍有效」（S6）。
5. **不要按后缀排除产物**（`agent_api.py:96-99` 已明确 `.png/.pdf/.json` 可能是科学输入）。
6. **不要引入 Bazel/Shake 级架构**（action graph + CAS + 远程缓存 + 调度器）。à la carte 的四类 rebuilder 里，我们需要的只是 **verifying trace**（记录依赖哈希、动作后复核，S11 §4.2.2）；dirty-bit（Make）不够、constructive trace 过重。
7. **不要在 Windows 上用 `st_ctime`**（S15：3.12 起在 Windows 弃用；S17：NTFS tunneling 会复原创建时间）。
8. **不要把「输出元数据」当作输入身份的一部分**（S7 的「注入输出元数据」是为了跳过重跑，不是为了改变输入身份）。

---

## 附录 A：引用位置速查

- Make `.LOW_RESOLUTION_TIME` / stamp 文件 / POSIX 措辞：S1、S2、S3
- Ninja restat / generator / 命令开始时间 / depfile：S4、S5
- Bazel action cache / 并发改动 / 输出元数据注入：S6、S7
- SCons Decider 三档与 1 秒坑：S8
- git racy-git 两条机制 + `is_racy_stat`：S9、S10
- 正确性定义 / verifying trace / cutoff：S11（§3.6、§4.2、Table 1）
- TOCTOU：S12；乐观并发与 412：S13；原子替换：S16
- Windows/Python 时间语义：S14、S15、S17
- 仓库内证据：`figpact/session.py:117-154,189-213`、`figpact/intents.py:93-190,240,328-333,614-633,695-721,794-798`、`figpact/agent_api.py:89-137,166-193,406-424`、`figpact/publish.py:45-68`、`eval/verify_real_cutover.py:1178-1223,1227-1307`、`docs/G6B_FINAL_ADJUDICATIONS.md`（P1.5 行）、`.gitignore`、`examples/ftir/`
