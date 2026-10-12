# G3b：可恢复的多文件源码写入

## 工作事实

基线：`7654489ec146ce502c7a2f485555e8a8b7b16fe1`（G3b 改动位于工作树，未提交）。本轮实现 **Python 源码/配置的可恢复多文件写入**：`plan` 校验并落 before/after 不可变内容 + PREPARED journal，`apply` 复核后逐文件 temp→fsync→`os.replace`，可捕获异常受控回滚，中断后由 `recover_pending` 只读扫描判定每个文件的实际状态，历史记录可经 `restore_project` 前向恢复。

**正式表述是「可恢复的多文件写入」，不是「进程崩溃时多个源文件原子提交」。** 本模块的恢复能力来自「先写内容、再写目标、失败可回滚、中断可判定」，它**不承诺**：多个文件要么全部旧内容、要么全部新内容对任意外部观察者可见；也不承诺进程被强杀后磁盘上永远不会出现「部分新、部分旧」的中间态。**可恢复 ≠ 崩溃原子性。**

G3b 是 G4（无 YAML 编辑试点）的**前置底座**。本轮**未接线**到任何真实图件编辑：没有图件/AI 调用它，也没有改任何用户 Python/YAML。

修改文件：

- **新增** `figpact/source_writes.py`（415 行，纯 stdlib：`difflib`/`hashlib`/`json`/`os`/`uuid`/`dataclasses`/`datetime`/`pathlib`）：`SourceWriteError`、`FileChange(path, before_sha256, after_bytes)`、`plan_source_change(changes, *, state_home, reason)`、`apply_source_change(journal_id, *, state_home)`、`recover_pending(state_home)`、`restore_project(changes, *, state_home, reason)`。
- **改** `figpact/history.py`（只加不改）：`append_source_change(payload, *, expected_head, expected_file_sha256)`、`source_changes()`、`file_changes(checkpoint_id)`。既有 API、表结构、只读 CLI 未变。
- **新增** `tests/test_source_writes.py`（7 项）、`tests/test_history_file_changes.py`（5 项）。

未修改 `scene.py`、`geometry.py`、`science.py`、`intents.py`、Inspector HTTP/UI、既有 YAML Agent API 或 `examples/` 下任何文件。

## 机制与不变量

### 状态布局（全部在源码目录之外，D-10）

- **blob**：`state_home/blobs/sha256/<digest[:2]>/<digest>`。写后对文件与目录 `fsync`；内容寻址，已存在则校验复用，不重复写。
- **journal**：`state_home/source-journals/<uuid4hex>.json`，状态 `PREPARED` / `COMMITTED` / `ROLLED_BACK` / `RECOVERY_REQUIRED`；每文件状态 `PENDING` / `APPLIED` / `MISMATCH` / `ROLLED_BACK` / `RECOVERY_REQUIRED`。
- **恢复报告**：`state_home/source-journals/<id>.recovery.json`，是 `recover_pending` 唯一的写入物。

状态目录是单写者假设：模块**不加锁**、不做并发控制，外部状态目录必须与绘图源码目录分离（不污染现有缓存输入指纹）。

### 写入顺序与不变量

1. **plan 先校验，后写入。** 逐文件比对 `before_sha256` 与实际磁盘字节；任一不符即 `SourceWriteError('STALE_SOURCE: …')`，此时**不写任何 blob、不写 journal**，目标文件亦未被碰过。
2. 校验全过后才写 before/after blob，再写 `PREPARED` journal。
3. **apply 先全量复核、再改写。** 任一文件的 before 与磁盘不符即 `STALE_SOURCE`（外部改写检测优先于写入，此时一个文件都没动）；随后逐文件 temp→fsync→`os.replace`，每步后更新 journal。
4. 全部写完**复核 after**：全部一致才 `COMMITTED`；不一致则 `ROLLED_BACK` + 回滚。
5. **可捕获异常 → 受控回滚**：用 before blob 还原已改文件；无法判定的文件标 `RECOVERY_REQUIRED`，不猜测、不覆盖，journal 整体随之为 `RECOVERY_REQUIRED`。
6. **未捕获的强杀**（本轮未做信号/崩溃注入）停留在 `PREPARED`/中间态，交给 `recover_pending`。

### 恢复扫描

`recover_pending` **只读扫描**未提交 journal，用磁盘实际 SHA 与 before/after blob 为每个文件判定 `before` / `after` / `third_party`。**它绝不自动覆盖第三方内容**：`third_party` 只报告、不动字节。`COMMITTED` journal 跳过；`<id>.recovery.json` 报告文件与无关文件不当作 journal。

### 前向恢复

`restore_project` 把历史记录里的 **after** 内容作为目标、把**当前磁盘**作为 before，走一次新的 plan + apply，产生**新的前向 journal**（不是反向应用 diff）。历史记录、旧 journal 均不被改写。

### diff 与二进制

文本文件（UTF-8 且不含 NUL）生成 unified diff（`--- a/<path>` / `+++ b/<path>`）；二进制文件 `is_binary=True`、`diff=None`，内容仍由 blob 保真往返。

### 历史侧的记录约束

`append_source_change` 校验 `kind='source_change'` 与 `file_changes[]` 形状（每项 `path` / `before_sha256` / `after_sha256` / `is_binary` / `before_blob` / `after_blob` / `diff`），并要求调用方声明的 `expected_file_sha256` **精确覆盖每条路径且与磁盘字节一致**；不符即拒绝——不写 blob、不落检查点、head 不动。磁盘复核发生在 CAS 事务**之前**（本模块不持锁：检测与写入之间仍有窗口，靠调用方的写入流程兜底）。

## 风险与权限

- **可恢复 ≠ 崩溃原子性**：不承诺多文件对外可见的原子切换；不承诺强杀后磁盘永不出现部分暴露。本轮未做信号/崩溃注入，`recover_pending` 只保证「事后可判定、不误覆盖」。
- **无锁、单写者假设**：状态目录不支持并发写；检测与写入之间、检查与 CAS 之间存在窗口，靠调用方流程兜底。
- **不修用户文件**：模块只写自己的私有状态文件与被点名的目标源文件；不复制科学数据、不碰 git、不加依赖、不执行用户脚本。本轮未接线到真实图件编辑，`examples/` 未被改动。
- **状态在源码目录之外**：blob 与 journal 一律落在 `state_home`（D-10），不进绘图源码目录、不进缓存输入指纹。

## 真实验收

全部由父代理亲自运行，命令：

```bash
pytest tests/test_source_writes.py tests/test_history_file_changes.py tests/test_history.py -q
```

| 本轮运行 | 通过 | 失败 | 跳过 | 实际耗时 |
|---|---:|---:|---:|---:|
| 源码写入 + 历史 + 既有历史存储 | 35 | 0 | 0 | pytest 26.60 s |

35 = 新增 7（`test_source_writes.py`）+ 新增 5（`test_history_file_changes.py`）+ 既有 23（`test_history.py`）。本轮**未跑全量**，也未运行前端 Node 测试、lint 或格式化。

覆盖到的真实行为：

- **正常 plan→apply**：两个文件落盘一致、`COMMITTED`，plan 阶段不碰目标文件，无临时文件残留。
- **before 不符**：`SourceWriteError`，目标字节不变，journal 目录与 `blobs/` 下均无新内容。
- **中途失败**：plan 之后把第二个目标置为只读，`os.replace` 在 Windows 上报 `PermissionError`，失败点落在「第一个已 APPLIED、轮到第二个」的中间阶段 → journal `ROLLED_BACK`，第一个文件回到 before，第二个未被改也未被删，无临时文件残留，`failure` 文案含第二个文件名。
- **目标被换成目录 → 被拒绝**：apply 前把目标文件替换为目录后，Windows 上读目录抛 `PermissionError`（Errno 13），实现抛 `SourceWriteError('…无法读取磁盘内容（…）')`。**注意它走的是「读取阶段拒绝覆盖」分支，并未落到哈希比较的 `STALE_SOURCE` 分支**；结果同样是一个文件都不写（第一个保持 before、目录与其中的占位文件字节不变）。测试按这一真实可观察行为断言并已注明。
- **`recover_pending` 判定**：三种真实磁盘状态（未写=before / 已写=after / 第三方改写=third_party）判定正确，`third_party` 文件字节不变，journal 文件内容未被改写。
- **`restore_project`**：产生新的前向 journal，旧 journal 未被动。
- **二进制往返**：字节一致，`is_binary=True`、`diff=None`。

### 已知未做

- **G4 尚未开始**：本 Gate 只是它的底座；本轮未接线到任何真实图件编辑。
- **未做锁/并发**：状态目录按单写者假设，无并发控制。
- **未纳入 source fingerprint 扫描**：按 D-10，状态在源码目录外。
- 本轮只跑上述三项针对性测试，**未跑全量 Python / 前端 Node**，故不宣称全量回归通过。

## 边界与未完成项

- **可恢复的多文件源码写入：已验证**（上表 35 项针对性测试）。**崩溃原子性与并发安全：未验收。**
- 未修改用户 Python/YAML 与 `examples/`；未提供 UI 写回入口，未接 Inspector、Hub 或 Agent 路径。
- 未开发 G4 的 `PythonNativeAdapter` / `SourceAuthoringAdapter`，未做无 YAML 编辑试点。
- 未做锁、多写者协调、长期 blob 增长或压缩收益评估。
- 后续 G4 若接真实源码写回，应另行验收：写入来源授权、崩溃/强杀注入下的实际恢复、以及跨会话 `restore_project` 的真实图件往返；不能只因本 Gate 单测通过就称这条用户链路已完成。
