# R5 — 编辑器生态中「改 → 验 → 接受 → 保存」的成熟语义

> 调研范围：成熟编辑器的暂态/已提交语义、写回源码类工具的安全实践、多步编辑暂存区与「接受一个/全部」的一手设计说明，以及对本例（figpact 拖动→evaluate→保存脚本）的建议。
> 约定：**事实**带原文引用 + URL；**建议**单独成节并标注；**推断**显式标 `[推断]`。
> 本文只做外部调研，不改仓库代码。

---

## 0. 结论速览

1. **成熟编辑器几乎都把「暂态」与「已提交」分成两个显式的存储位置**，并且都定义了「外部改动」的检测与处理路径（VS Code 的 dirty-write、Figma 的 stale changes、Lightroom 的 Metadata Status）。figpact 的「拖动→evaluate 通过→待保存」正好对应其中的「待提交区 / pending buffer」。
2. **写回源码的成熟做法是「校验 → 原子替换」**，而不是「打开文件、写进去」：先比对读入时的哈希（drift check），再用「临时文件 + fsync + rename」原子落盘。见 §2.3。
3. **最贴本例的先例是 `lisplens` 的 `verify_and_write`**：拒绝写入的两种理由（`Drift`、`NewParseErrors`）与 figpact 的「源修订误判（P1.5）」几乎一一对应。
4. **「接受一个/全部」的成熟交互是「预览列表 + 逐项 include/exclude + 一次 Do Refactor」**（IntelliJ）、「pending changes banner + Apply/Discard」（Power BI）、「Accept This / Accept All」（Word）。它们的共同点是：**批量提交是一个动作，不是 N 次写盘**。
5. 反面教材：`nbconvert --inplace` 与 `papermill` 的 `output_path=input_path` —— 官方文档自己写着 "Be careful with that, since it will replace the input file."。**不要照抄**（§2.5、§5）。

---

## 1. 成熟编辑器的「暂态 / 已提交」语义

### 1.1 VS Code：dirty → save（脏标记 / 工作副本 / 备份 / 脏写冲突）

**事实 — dirty 是内存态，save 是明确的动作。**
VS Code 的「工作副本（working copy）」模型把「可编辑的东西」抽象成 `resource` + `capabilities` + 事件（`onDidChangeDirty` / `onDidChangeContent` / `onDidSave`）+ 方法（`backup` / `save` / `revert`）。Wiki 原文：

> "The fundamental pieces of a working copy are: `resource` … `typeId` … `capabilities` … events (`onDidChangeDirty`, `onDidChangeContent`, `onDidSave`) … methods (`backup`, `save`, `revert`)."
> "The contract of these methods is that after the operation succeeded, the working copy is no longer dirty."
> — <https://github.com/microsoft/vscode/wiki/Working-Copies>

**事实 — 备份（hot exit）是「备份生命周期绑定 dirty 状态」的。**
> "As soon as the working copy reports a content change, the workbench will call the `backup` method to store a backup of the unsaved state in the backup location."
> "backups are automatically deleted once the working copy is saved and no longer reports as dirty."
> "when there are backups of working copies stored on disk and the workbench is asked to open, we eagerly restore all such working copies as editors so that the user is always aware of unsaved changes."
> — <https://github.com/microsoft/vscode/wiki/Working-Copies>

备份落盘位置与开关（官方文档）：
> "VS Code backs up unsaved changes automatically so they can be restored if the app closes unexpectedly (Hot Exit)."
> `files.hotExit`: `onExitAndWindowClose` | `onExit` | `off`；备份目录 Windows 为 `%APPDATA%\Code\Backups`。
> — <https://code.visualstudio.com/docs/editing/codebasics>

**事实 — 脏写（dirty write）有专门的处理路径，且是「Compare / Overwrite / Retry / Revert」四选一。**
源码里的错误分支与用户可见文案（逐字）：

```ts
// Dirty write prevention
if (fileOperationError.fileOperationResult === FileOperationResult.FILE_MODIFIED_SINCE) {
  ...
  message = localize('staleSaveError', "Failed to save '{0}': The content of the file is newer. Please compare your version with the file contents or overwrite the content of the file with your changes.", basename(resource));
  primaryActions.push(...ResolveSaveConflictAction, ...SaveModelIgnoreModifiedSinceAction);
```
冲突解决编辑器里的帮助文案：
> "Use the actions in the editor tool bar to either undo your changes or overwrite the content of the file with your changes."
> — <https://raw.githubusercontent.com/microsoft/vscode/main/src/vs/workbench/contrib/files/browser/editors/textFileSaveErrorHandler.ts>

**对本例的含义（事实层面）**：成熟编辑器把「磁盘被外部改过」当成**保存时的一等错误**，而不是静默覆盖。figpact 的「源修订误判（P1.5）」属于同一类问题。

---

### 1.2 Photoshop / Illustrator：非破坏性编辑 与「Apply / Expand」的破坏性提交

**事实 — 非破坏性层不改像素数据。** Adobe 帮助页对调整图层/填充图层的定义是「应用颜色与色调变化而不修改像素数据」：
> 描述调整图层/填充图层为「apply color and tonal changes without altering pixel data」。
> — <https://helpx.adobe.com/photoshop/desktop/create-manage-layers/color-adjustment-fill-layers/work-with-adjustment-and-fill-layers.html>

**事实 — Illustrator 的 `Expand Appearance` 就是「非破坏性 → 破坏性」的显式提交动作。** 官方帮助页：
> "Expand Appearance converts an object's appearance attributes (live effects, fills, strokes) into editable objects."
> "If an object has appearance attributes, Object > Expand is greyed out; use Object > Expand Appearance first, then Object > Expand."
> — <https://helpx.adobe.com/illustrator/desktop/manage-objects/arrange-objects/expand-objects.html>

**要点提炼**：这里的「提交」语义不是「保存文件」，而是「把可回退的表达式求值成不可回退的实体」。**保存（Ctrl+S）与非破坏性/破坏性无关**——两者正交。

> 说明：「Photoshop 的 Apply 按钮」在官方文档中没有一个统一的、可引用的通用定义（`Apply Image`、`Apply Layer Style` 等是不同命令）。**未找到**能概括"统一 Accept/Apply 语义"的一手页面，故本节只引 Illustrator 的 Expand 与调整图层的非破坏性定义。

---

### 1.3 参数化 CAD：FreeCAD 的事务栈 vs Fusion 的 timeline（两者不是一回事）

**事实 — FreeCAD 有显式的 open/commit/abort 事务 API。** `App::Document` 类参考逐字：
> `openTransaction(const char *name=nullptr)` — "Open a new command Undo/Redo, an UTF-8 name can be specified."
> `commitTransaction()` — "Commit the Command transaction. Do nothing If there is no Command transaction open."
> `abortTransaction()` — "Abort the actually running transaction."
> `hasPendingTransaction()` — "Check if a transaction is open."
> `isTransactionEmpty()` — "Check if a transaction is open and its list is empty."
> `recompute(...)` — "Recompute touched features and return the number of recalculated features."
> — <https://freecad.github.io/SourceDoc/d8/d3e/classApp_1_1Document.html>

**事实 — 不是所有改动都进 undo 栈。** FreeCAD 文档逐字：
> "By default changes to View properties are not added to the undo stack and cannot be undone and redone with Std Undo and Std Redo. But it is possible to change this by setting the fine-tuning parameter **AutoTransactionView** to `true`."
> — <https://wiki.freecad.org/Property_View>（`Property_editor` 重定向至此；镜像仓库：<https://github.com/FreeCAD/FreeCAD-documentation>）

**事实 — Fusion 的「设计历史」是持久化在文件里的 feature timeline，与 undo 栈不同。** 直接建模模式不记录 timeline，切到参数化模式时把已有几何收成**一个 Base Feature**：
> "Geometry created in this mode cannot be converted into individual parametric features later."
> "Switching from Direct to Parametric Mode creates a Base Feature from the existing geometry (first feature) and restarts parametric tracking."
> — <https://help.autodesk.com/cloudhelp/ENU/Fusion-Designs/files/ASM-DESIGN-MODELING-MODES.htm>，切换步骤见 <https://help.autodesk.com/view/fusion360/ENU/?contextId=LP-STEPS-P13N-SNP-GS-OTH-CRD-6>

**对本例的关键区分（事实层面）**：CAD 里有两层历史——(a) **可撤销的事务栈**（内存态、进程内、通常不写进文件），(b) **持久化的建模历史**（feature tree，写进文件）。figpact 要补的是 (a) 的闭环，**不**应引入 (b)。这正好支持「补齐闭环但不重写 History」。

---

### 1.4 Blender：修饰器栈的 Apply / Apply All（及失败模式）

**事实 — 修饰器是非破坏性的；`Apply` 使其成真并删除修饰器。** 官方手册逐字：
> "Modifiers are automatic operations that affect an object's geometry in a non-destructive way."
> "They work by changing how an object is displayed and rendered, but not the geometry which you can edit directly."
> Extras › Apply: "Makes the modifier 'real': converts the object's geometry to match the applied modifier's results, and deletes the modifier."
> Warning: "Applying a modifier that is not first in the stack will ignore the stack order (it will be applied as if it was the first one), and may produce undesired results."
> — <https://docs.blender.org/manual/en/latest/modeling/modifiers/introduction.html>

**事实 — 存在「保留非破坏性」的轻量提交变体**（值得注意的设计）：
> "Apply as Shape Key — Stores the result of that modifier in a new relative shape key and then **deletes** the modifier from the modifier stack."
> "Save as Shape Key — Stores the result of that modifier in a new relative shape key and **keeps** the modifier in the modifier stack."
> — 同上

**事实 — 「全部应用」是一个独立命令，且会失败。**
> "Apply All — Applies all modifiers on all selected objects in 3D Viewport."
> Known Limitations: "Sometimes applying modifiers can fail for some objects."
> — <https://docs.blender.org/manual/en/4.1/addons/interface/modifier_tools.html>

**提炼**：批量「Apply All」必须能**部分失败**并能报告哪些失败了；不能假设全成。

---

### 1.5 Figma：自动保存 + 版本历史 + 离线 pending buffer（最接近「暂存区」的产品论述）

这是本次调研里**唯一一篇官方工程博客级的一手设计说明**，直接讨论「未保存」的可见性与丢数据风险。逐字引用（多段）：

> "The most intuitive way to save a document is how it has always been done: serialize the in-memory representation of the document as a backup file and write it to disk. … Unfortunately, in the context of a cloud-based application, this approach isn't practical both from a technical and product standpoint."

> "The alternative to saving the entire file is to write to disk only the changes made since the document went offline. … To restore changes, it suffices to apply this diff on top of the latest version of the document."
> 原型流程："User makes changes, which get stored in an in-memory **pending changes buffer** → Contents of the pending change buffer are committed to disk on a regular interval → … → Pending changes are deserialized and applied on top of the document"

> "our multiplayer system is meant to handle small conflicts during editing. … Our system does not understand *user intent* … and therefore may not be able to effectively merge large-scale changes without creating a *mess*."

> "To optimize for making the common case work smoothly, we automatically create a version history checkpoint (a feature in Figma similar to a Git commit) **before and after applying the diff**. This allows the user to easily revert the merge in the event in these special cases."

> "if we have extra changes on disk, that's *also* a problem. From a UX perspective, it's quite confusing for the user to be prompted about unsaved changes that have, in reality, already been saved to the server."

> "we consider the document to be in an unsaved state until the changes are acknowledged by the server **and** cleared from disk."

> "When a technical solution isn't available yet, we can also help mitigate the issue via product solutions."
> — <https://www.figma.com/blog/behind-the-feature-autosave/>

**事实（帮助中心）**：版本历史大约每 30 分钟自动存检查点；离线编辑存在浏览器本地（IndexedDB），离线改动最多保留 30 天（Safari 7 天）；重连后弹出离线改动面板由用户复核/合并。
> — <https://help.figma.com/hc/en-us/articles/360040328553-What-can-I-do-offline-in-Figma>，<https://help.figma.com/hc/en-us/articles/360038006754-View-a-file-s-version-history>

---

### 1.6 Lightroom：catalog（编辑态真源）vs XMP sidecar（写回文件的显式动作）

**这是「编辑态 vs 磁盘真态」最贴本科的模型。** 事实：
> "Lightroom Classic uses XMP to store metadata. For raw files with proprietary formats, XMP is saved in a separate sidecar file to avoid corrupting the original."
> "Lightroom Classic can automatically write adjustments and settings metadata to XMP if you enable 'Automatically Write Changes Into XMP' … If you do not enable automatic writing, changes remain in the catalog unless you manually Save Metadata To File."
> — <https://helpx.adobe.com/lightroom-classic/desktop/organize-photos-in-lightroom-classic/metadata-basics-actions.html>

**事实 — 存在「脏」指示器**：`Metadata File Needs To Be Updated` 用于提示「catalog 里有、磁盘文件里没有」的改动。
> — 同上（Metadata basics and actions）

**提炼**：非破坏性编辑可以宽松（自动/连续写「目录」），但**写回源文件是一个显式的、可关闭的动作**，并且有「待写回」的可见状态。figpact 的「候选」应类比 catalog，「保存脚本」类比 Save Metadata to File。

---

### 1.7 崩溃恢复的 RECOVERY 语义：Vim swap / Emacs auto-save

**事实 — Vim：swap 文件承载「上次未保存的改动」，恢复是显式的、且明确要求先验证再覆盖原文。**
> "`:rec[over] [file]` — Try to recover [file] from the swap file. If [file] is not given use the file name for the current buffer. **The current contents of the buffer are lost. This command fails if the buffer was modified.**"
> "**Be sure that the recovery was successful before overwriting the original file or deleting the swap file.** It is good practice to write the recovered file elsewhere and run 'diff' to find out if the changes you want are in the recovered file. Or use `:DiffOrig`. Once you are sure the recovery is ok delete the swap file."
> swap 文件更新时机："The swap file is updated after typing 200 characters or when you have not typed anything for four seconds."（`'updatecount'` / `'updatetime'` 可调）
> — <https://vimhelp.org/recover.txt.html>（同一文档的仓库源：<https://github.com/vim/vim/blob/master/runtime/doc/recover.txt>）

**事实 — Emacs：auto-save 文件 `#file#`；恢复只填 buffer，**保存才写回原文**。**
> "This visits *file* and then (after your confirmation) restores the contents from its auto-save file `#file#`. You can then save with `C-x C-s` to put the recovered text into *file* itself."
> "When `recover-session` is done, the files you've chosen to recover are present in Emacs buffers. **You should then save them. Only this—saving them—updates the files themselves.**"
> 会话记录："Emacs records information about interrupted sessions in files named `.saves-pid-hostname~` in the directory `~/.emacs.d/auto-save-list/`."
> — <https://www.gnu.org/software/emacs/manual/html_node/emacs/Recover.html>

**提炼**：恢复态**永远不写回原文**，而是「恢复到缓冲区 / 另一个文件」，由人确认后再保存。这与 figpact「中断后磁盘真态」的表达直接相关。

---

### 1.8 对照表

| 系统 | 暂态存放处 | 提交动作 | 「未保存」可见性 | 外部/并发改动处理 |
|---|---|---|---|---|
| VS Code | 内存 working copy + Backups 目录 | Save（Ctrl+S） | 标签页/资源管理器脏点；hot exit 重开即恢复 | `FILE_MODIFIED_SINCE` → Compare / Overwrite / Revert |
| Photoshop / Illustrator | 图层/外观（非破坏性） | `Expand Appearance`（选择性地） | 与保存正交；文档标题有未保存标记 | 无（本地单文档） |
| FreeCAD | 内存 undo 事务栈 | `commitTransaction()` | 未找到权威来源描述其 UI 指示 | 事务 API 有 abort；View 属性默认不入栈 |
| Fusion | 内存（direct 模式） | 切到 parametric 时收成 Base Feature | 未找到权威来源 | 导入文件的 timeline 会丢 |
| Blender | 修饰器栈（求值态） | Apply / Apply All | 未找到权威来源 | 批量 Apply 可能部分失败 |
| Figma | 内存 pending buffer + IndexedDB | 上送服务器并 ack + 清盘 | 工具栏离线/云图标；协作面板提示 | 生成本地分支 → 合并，前后各打 checkpoint |
| Lightroom | catalog（`*.lrcat`） | Save Metadata to File（写 XMP/内嵌） | `Metadata File Needs To Be Updated` | 单机，无并发 |
| Vim | `.swp` / `.swo` … | `:w` | swap 存在即告警（E325） | 检测到其他实例在编辑同一文件 |
| Emacs | `#file#` auto-save | `C-x C-s` | 模式行 modified 标记 | 无 |

---

## 2. 写回源码类工具的安全实践

### 2.1 black：写回模式是显式的枚举；默认原地写

**事实** — `WriteBack` 枚举 `NO / YES / DIFF / CHECK / COLOR_DIFF`；CLI 语义（官方文档逐字）：
> "**Black will reformat entire files in place.**"
> `--check` — "Don't write the files back, just return the status. Black will exit with: code 0 if nothing would change; code 1 if some files would be reformatted; or code 123 if there was an internal error."
> `--diff` — "Don't write the files back, just output a diff to indicate what changes Black would've made. They are printed to stdout so capturing them is simple."
> — <https://black.readthedocs.io/en/stable/usage_and_configuration/the_basics.html>，实现见 <https://github.com/psf/black/blob/main/src/black/__init__.py>

**事实 — black 不做原子写、也没有跨文件事务。** `format_file_in_place` 在 `write_back is YES` 时直接对目标路径 `open(..., "w")` 写入；代码路径中**没有** tempfile + `os.replace`。
> — <https://github.com/psf/black/blob/master/src/black/__init__.py>（`format_file_in_place` / `format_stdin_to_stdout`）

`[推断]` 因此 black 在一次多文件运行中被中断时，`[INFERENCE]` 已处理与未处理的文件会呈现「部分已格式化」状态——但**未找到**官方声明证实这一行为，故仅作推断。

### 2.2 jscodeshift：默认**会**写盘；`--dry` / `--print` 是 opt-in；返回字符串决定是否算「已改」

**事实** — CLI 选项（README 逐字）：
```
-d, --(no-)dry                dry run (no changes are made to files)
                              (default: false)
-p, --(no-)print              print transformed files to stdout, useful for development
                              (default: false)
-s, --(no-)silent             do not write to stdout or stderr
                              (default: false)
```
返回值语义（README 逐字）：
> "If a string is returned and it is different from passed source, the transform is considered to be successful. If a string is returned but it's the same as the source, the transform is considered to be unsuccessful. If nothing is returned, the file is not supposed to be transformed (which is ok)."
运行摘要示例：`Results: 0 errors 2 unmodified 3 skipped 5 ok`
> — <https://raw.githubusercontent.com/facebook/jscodeshift/main/README.md>

> ⚠️ **修正一处常见误解**：二手资料常写「jscodeshift 默认 dry-run」；README 的实际默认是 **`--dry` = false，即默认写文件**。

**事实** — jscodeshift 不原生支持「输出到另一个文件」，社区做法是 `-p -d -s` 加 stdout 重定向。
> — <https://github.com/facebook/jscodeshift/issues/160>

**事实** — 底层 recast 是「非破坏性 pretty-printer + 自动 source map」。
> — <https://github.com/benjamn/recast/blob/master/README.md>

### 2.3 原子写与字节校验：三个可引用的实现

**(a) `lisplens`（Rust）—— 最完整的「校验 → 原子写」契约，逐字：**
> "The safety contract is simply: **never make a file's syntax worse.** An edit is refused if the file drifted since the read it was based on (strict, file-level; ADR-0017), or if it would introduce new parse errors; otherwise the new content is written atomically, preserving the target's permissions and following symlinks to their target."

拒绝写入的两类错误（逐字）：
```rust
pub enum WriteError {
    /// The file changed since the read the edit was based on: its current
    /// file-level hash does not match the expected one.
    Drift { expected: String, actual: String },
    /// The edit would introduce parse errors not present before it (ADR-0005),
    /// compared by lispexp's position-stable ErrorKind, not by count …
    NewParseErrors { introduced: Vec<String> },
    Io(std::io::Error),
}
```
原子写实现（逐字）：
> "Write `content` to `path` atomically: write a sibling temp file, copy the target's permissions onto it, then rename it over the target (atomic within one filesystem)."
对应测试：`refuses_a_drifted_file` 断言文件内容**保持不变**；`refuses_an_edit_that_introduces_parse_errors` 同样断言原文未变。
> — <https://docs.rs/lisplens/latest/src/lisplens/write.rs.html>

> 注意一个细节契约：解析错误按 **ErrorKind 多重集**比较，因此「只是把已有错误的行号往后挪」不算新增错误（测试 `allows_an_edit_that_only_shifts_an_existing_error`）。这对「误判」很关键。

**(b) 就地截断写 = 数据丢失风险（pnpm PR 正文逐字）：**
> "`PackageManifest::save` rewrote `package.json` in place with `fs::File::create` (which truncates) followed by `write_all`. If the process is killed (OOM, CI timeout, Ctrl-C) or the disk fills between the truncate and the completed write, the file is left empty or partial and the user's dependency declarations are lost **with no recovery path**."
> 修法："writes the serialized manifest to a sibling temp file, fsyncs it, then renames it over the target, so a crash or write error never leaves a truncated `package.json` behind."
> 测试：`save_leaves_the_original_intact_when_the_write_cannot_complete` "asserts a failed write leaves the original `package.json` byte-for-byte intact"。
> — <https://github.com/pnpm/pnpm/pull/12642>

**(c) 只 rename 不够，还需要 fsync（npm `write-file-atomic` issue 逐字）：**
> "Even after `fs.renameSync` completes, a crash (e.g., blue-screen) can leave the target file corrupted."
> — <https://github.com/npm/write-file-atomic/issues/16>

**旁证**：Syncthing 社区结论——「大多数 Unix 应用避免就地更新，依赖写新文件 + 原子 rename 来保证完整性」。
> — <https://github.com/syncthing/syncthing/issues/3897>

### 2.4 补丁 vs 原地：`git apply` 的 all-or-nothing 与 `.rej`

**事实（官方文档逐字，git 2.55）：**
> `--check` — "Instead of applying the patch, see if the patch is applicable to the current working tree and/or the index file and detects errors. Turns off 'apply'."
> `--reject` — "**For atomicity, `git apply` by default fails the whole patch and does not touch the working tree when some of the hunks do not apply.** This option makes it apply the parts of the patch that are applicable, and leave the rejected hunks in corresponding `*.rej` files."
> `--3way` — "Attempt 3-way merge … possibly leaving the conflict markers in the files in the working tree for the user to resolve."
> — <https://git-scm.com/docs/git-apply>

**提炼**：这里有两个可直接复用的原语——**`--check`（先验证不改盘）** 与 **默认 all-or-nothing、部分应用必须显式开启且失败片段落盘成 `.rej`**。figpact 若允许「只保存部分候选」，应显式区分这两种模式。

### 2.5 papermill / nbconvert 把执行结果写回源文件的教训

**事实 — nbconvert `--inplace` 官方自警告（逐字）：**
> "Specifying `--inplace` will overwrite the input file instead of writing a new file."
> "If you want to convert a notebook in-place, you can specify the output file to be the same as the input file: `jupyter nbconvert --to notebook mynb --output mynb`. **Be careful with that, since it will replace the input file.**"
> "By default, `nbconvert` will abort conversion if any exceptions occur during execution of a cell. If you specify `--allow-errors` (in addition to the `--execute` flag) then conversion will continue and the output from any exception will be included in the cell output."
> — <https://nbconvert.readthedocs.io/en/stable/usage.html>

**事实 — papermill 的保存时机更激进**：引擎在执行开始与结束时各保存一次，且可在执行途中按 `autosave_cell_every` 周期性写盘；`output_path` 若指向输入文件即覆盖。
> — <https://github.com/nteract/papermill/blob/main/papermill/engines.py>，<https://papermill.readthedocs.io/en/stable/reference/papermill-workflow.html>

**事实 — papermill 自己也知道这是坑**：社区 issue 提议把 IO 与执行分离，让 Python API operate on nbformat 对象而不是路径。
> — <https://github.com/nteract/papermill/issues/200>

**教训（事实层面）**：
1. 「执行结果写回源文件」会把**瞬时状态**与**权威源码**混在同一个文件里；
2. 中途周期性写盘（autosave）会让「半执行完的产物」落到权威路径上；
3. 官方文档层面只能给出「先备份」这种弱保证。

---

### 2.6 失败回滚与「恢复态」：写回工具的收敛结论

把 §2.1–§2.5 的失败处理归拢成一张表（全部为事实，出处见上）：

| 工具 | 写失败/中断后的磁盘状态 | 是否有显式「恢复态」 |
|---|---|---|
| `git apply`（默认） | **无变化**（all-or-nothing，"does not touch the working tree"） | 无（本就无需） |
| `git apply --reject` | 已应用部分 + `*.rej` 落盘 | 有：`.rej` 文件 |
| `lisplens` `verify_and_write` | **无变化**（Drift / NewParseErrors 直接拒绝；测试断言原文未动） | 无（拒绝即安全） |
| pnpm 原子写 | **无变化**（测试 `save_leaves_the_original_intact_when_the_write_cannot_complete` 断言 byte-for-byte intact） | 无 |
| black（`--check`/`--diff`） | **无变化**（"Don't write the files back"） | 无 |
| black（默认原地） | `[推断]` 可能半格式化 | **未见**官方恢复机制 |
| `nbconvert --inplace` | 输入文件被替换 | **无**（文档仅一句 caution） |
| Vim | 原文不动；改动在 `.swp` | **有**：`.swp`/`.swo`…，`vim -r` / `:recover` |
| Emacs | 原文不动；改动在 `#file#` | **有**：`#file#` + `~/.emacs.d/auto-save-list/.saves-pid-hostname~` |
| VS Code | 原文不动；改动在 Backups 目录 | **有**：hot exit 重开时自动恢复为 dirty |

**收敛结论（事实层面）**：成熟工具呈现两种正交的策略——
- **(A) 拒绝即安全**：写前校验不通过就**不写**，磁盘保持原样（git apply 默认、lisplens、pnpm、black `--check`）。此时**不需要**任何恢复态。
- **(B) 旁路恢复**：改动放在**原文之外的独立载体**里（`.swp` / `#file#` / Backups），原文始终未被触碰，由用户显式确认后再写回。

**两者都避免了「半写状态」。** 相反的做法（black 默认原地、nbconvert `--inplace`）恰恰**没有**官方的恢复路径——这是「不要照抄」的核心依据（§5）。

---

## 3. 多步编辑的暂存区与批量提交

### 3.1 Git index：三棵树，批量提交是一个动作

**事实（官方文档逐字）：**
> "The 'index' (also known as the 'staging area') is what you use to prepare the contents of the next commit."
> "You can also add only part of your changes to a file with `git add -p`."
> "This command can be performed multiple times before a commit. It only adds the content of the specified file(s) at the time the add command is run; if you want subsequent changes included in the next commit, then you must run `git add` again to add the new content to the index."
> — <https://git-scm.com/docs/git-add>

三种文件状态（Pro Git）：**modified（工作区） / staged（索引） / committed（仓库）**。
> — <https://progit3.com/book/what_is_git_section/>

**事实 — hunk 级交互**：`git add -p` 对每个 hunk 询问 `y`（stage）/ `n`（skip）/ `q` / `a`（stage 该文件剩余全部）/ `d` / `s`（split）/ `e`（手动编辑）。
> — <https://www.popsci.blog/unlock-git-power-master-git-add-p>（二手；一手见 git-add 文档的 `--patch` 选项）

### 3.2 Power BI / Power Query：pending changes banner + Close & Apply + Discard

**事实** — 语义是「暂存 + 显式应用」：
> Power Query 的变换以 Applied Steps 形式暂存，直到 `Close & Apply` 才应用到数据模型。
> 关闭编辑器时给出三选一：**Apply changes** / **Keep changes**（保留待应用）/ **Discard changes**（回退到编辑前状态）。
> 未应用时界面显示 banner："There are pending changes in your queries that haven't been applied"。
> — <https://www.thebricks.com/resources/guide-how-to-discard-pending-changes-in-power-bi>，<https://community.fabric.microsoft.com/discussions/power-bi-designer/there-are-pending-changes-in-your-queries-that-havent-been-applied-doesnt-goes-a/1142424>
> ⚠️ 这两个来源是社区/教程级，**未找到**等价的微软官方文档页逐字描述该三选一对话框；引用时按「社区可复现的行为」看待。

**提炼**：「待应用」有专门的 UI 载体（banner）、专门的动词（Apply / Keep / Discard），且**状态不只是布尔**。

### 3.3 IntelliJ：Refactoring Preview + Include/Exclude + Do Refactor

**事实** — 这是「接受一个 / 接受全部」的最完整一手设计：
> "Click Preview to see potential changes and the list of usages."
> "use **Do Refactor** (Alt+D) to apply changes to all visible results."
> "**Include** (Insert) to add an excluded item back, **Exclude** (Delete) to remove an item from the list (excluded items appear **struck through** and are not affected by Replace All or Do Refactor)"
> "The **Do Refactor** action applies all confirmed changes across usages, not individual ones."
> — <https://www.jetbrains.com/help/idea/find-tool-window.html>，<https://www.jetbrains.com/help/idea/rename-refactorings.html>，<https://www.jetbrains.com/help/idea/refactoring-source-code.html>

**提炼**：候选列表是**可包含/排除的列表**（不是队列），最终只有一个「Do Refactor」动作。冲突要单独呈现（`Refactor Anyway` / `Open in Find Window`）。

### 3.4 Word：Accept This / Accept All / Accept All Changes Shown

**事实** — 官方列出了「单个 / 全部 / 仅当前可见范围」三档：
> 单个：`Accept This Change`、`Accept and Move to Next`
> 全部：`Accept All Changes`、`Accept All Changes and Stop Tracking`
> 按可见范围：`Accept All Changes Shown`
> 注意：当 Show Markup 限定到特定人员时，部分"Accept All Changes"选项不显示。
> — <https://support.microsoft.com/en-us/word/training/track-changes-in-word>

### 3.5 Blender：Apply All（见 §1.4），且会部分失败

### 3.6 设计模式总结（事实层面）

| 系统 | 候选载体 | 逐项接受 | 全部接受 | 丢弃 | 失败呈现 |
|---|---|---|---|---|---|
| Git | index | `git add -p` | `git add -A` → `commit` | `git restore` | 冲突标记 |
| Power BI | pending changes | 编辑 Applied Steps | Close & Apply | Discard Changes | banner 常驻 |
| IntelliJ | Refactoring Preview 列表 | Include/Exclude | Do Refactor | 关窗 | 冲突对话框 |
| Word | 修订标记 | Accept This Change | Accept All Changes | Reject All | 按 Show Markup 过滤 |
| Blender | 修饰器栈 | Apply | Apply All | Delete | 逐对象报"apply 失败" |

**共性**：候选列表 + 显式排除 + 单一提交动作 + 部分失败可见。

---

## 4. 对本例（figpact）的建议

> 以下为**建议**，不是事实。目标是：补齐「拖动 → evaluate → 保存脚本」的闭环，**不重写 History**。

### 4.1 三态模型（建议）

| 态 | 存放处 | 含义 |
|---|---|---|
| `committed` | 磁盘脚本文件 | 唯一真源（SSOT）。用文件**内容哈希**标识 |
| `pending` | GUI 会话内存中的候选列表 | 已通过 evaluate、但**未写盘**的候选。每条绑定 `base_hash`（读取脚本那一刻的哈希） |
| `drifted` | 派生 | `pending[*].base_hash != 当前磁盘哈希` → 说明脚本被外部改过，pending 已失效 |

事实依据：VS Code 的 working copy（内存 dirty + 磁盘 raw）与 Lightroom 的 catalog/XMP 二分是同构的（§1.1、§1.6）。`base_hash` 的事实依据是 lisplens 的 `Drift{expected,actual}`（§2.3a）。

### 4.2 「拖动 → evaluate 通过」之后（建议）

1. evaluate 通过 → 候选 **append 到 `pending` 列表**，带 `base_hash` 与 diff 摘要。**不写盘**。
2. UI 上 pending 应是**可 include/exclude 的列表**（学 IntelliJ 的 Refactoring Preview，§3.3），不是队列。
3. 每条候选显示其对脚本文本的具体改动（学 `--diff` 模式，§2.1）。

### 4.3 「保存」= 一个原子动作（建议）

保存全部候选时，按这个顺序（每步都有先例）：

1. **drift check**：重读磁盘脚本、算哈希，与 `base_hash` 比对。不一致 → 报「脚本已被外部修改」，给 `覆盖 / 重载 / 取消`（学 VS Code dirty-write，§1.1）。
2. **一次性生成整脚本文本**：把所有 pending 折叠成**一次**内容生成，而不是逐条 `apply`（逐条写 = N 次写盘 = black 的教训，§2.1）。
3. **原子落盘**：同目录临时文件 → 写 → flush/fsync → `os.replace`（§2.3b、§2.3c）。
4. **写后复核**：重新读回磁盘、重新 evaluate。真态 = 新的哈希；pending 清空。

### 4.4 失败 / 中断的「磁盘真态」（建议）

因为 §4.3 是**单次原子写**，磁盘只可能处于两种状态之一：**旧脚本** 或 **新脚本**。不存在「写了一半」。因此：

- **不要**在脚本文件里写任何 marker / 注释 / `# RECOVERY`。脚本是源码 SSOT，混入元数据正是 nbconvert/papermill 的坑（§2.5）。
- 若需要「写盘前进程崩了，pending 丢失」的兜底，用一个**独立 sidecar**（如 `<script>.figpact.pending.json`）承载 pending，且它是**可随时删除的缓存**，绝不参与脚本的解析。先例：VS Code Backups 目录、Emacs `#file#`、Vim `.swp`（§1.1、§1.7）。
  - `[推断]` 若 figpact 当前没有崩溃恢复需求，此 sidecar **可以不做**（YAGNI）。
- 恢复态的正确形态是「恢复到内存候选」，不是「直接写回原文」——Vim 与 Emacs 的文档都反复强调「先验证再覆盖」（§1.7）。

### 4.5 与 P1.5（源修订误判修复）的关系（建议）

P1.5 的本质就是 lisplens 的 `Drift`：候选基于旧版本的脚本，但保存时磁盘已变。
最小修法：**把 `base_hash` 变成候选的一等字段**，保存前必检；而不是在 evaluate 里做推断性判断。错误类型化的先例：`WriteError::Drift` vs `WriteError::NewParseErrors`（§2.3a）。

---

## 5. 不要照抄的地方

| 反面教材 | 出处 | 为什么不抄 |
|---|---|---|
| `output_path == input_path` 直接覆盖执行结果 | nbconvert `--inplace`（§2.5） | 官方文档的保证只有一句 "Be careful with that, since it will replace the input file."；**未找到**「自动备份」的保证 |
| 执行中途周期性把中间态写进权威文件 | papermill `autosave_cell_every`（§2.5） | 半成品会落到 SSOT 上 |
| 默认就写盘、`--dry` 才是 opt-in | jscodeshift `--dry (default: false)`（§2.2） | figpact 的保存必须是显式且偏保守的动作 |
| 逐文件原地截断写、无跨文件事务 | black `format_file_in_place`（§2.1） | 断电/中断可截断文件；对 figpact 应一次原子写 |
| 用 CRDT/delta 做多端合并 | Figma autosave（§1.5） | figpact 是单机单文件；引入会外溢到 History 重写 |
| 退出即备份、重开自动恢复整套机制 | VS Code Hot Exit（§1.1） | 机制本身不小；除非确有崩溃恢复需求 |
| 把可变事务栈持久化进文档 | FreeCAD/Fusion 的区分（§1.3） | figpact 明确不重写 History |
| 直接「Accept All」破坏性改源不可逆 | Word（§3.4） | 没有 drift check，无法发现外部改动 |

---

## 6. 未找到权威来源 / 开放问题

1. **Photoshop 没有统一的「Apply/Accept」通用语义**——官方文档层面未找到能概括该模式的单一页面（§1.2 已注明）。
2. **Power BI「Apply / Keep / Discard」三选一对话框**：未找到微软官方文档逐字描述，仅有官方社区帖与第三方教程（§3.2 已标注为社区级）。
3. **FreeCAD / Fusion / Blender 的「未保存状态」UI 指示**：未找到官方文档页面描述其具体指示器，故对照表留空。
4. **black 在多文件运行中被中断的行为**：未找到官方声明，§2.1 的说明已标 `[推断]`。
5. **figpact History 现有结构**：本次为纯外部调研，未查看仓库代码，因此 §4 的建议与现有 History 的兼容性未经核实。

---

## 附：一手来源清单

- VS Code Working Copies Wiki — <https://github.com/microsoft/vscode/wiki/Working-Copies>
- VS Code 脏写处理源码 — <https://raw.githubusercontent.com/microsoft/vscode/main/src/vs/workbench/contrib/files/browser/editors/textFileSaveErrorHandler.ts>
- VS Code Basic editing（Hot Exit）— <https://code.visualstudio.com/docs/editing/codebasics>
- Illustrator Expand objects — <https://helpx.adobe.com/illustrator/desktop/manage-objects/arrange-objects/expand-objects.html>
- Photoshop 调整/填充图层 — <https://helpx.adobe.com/photoshop/desktop/create-manage-layers/color-adjustment-fill-layers/work-with-adjustment-and-fill-layers.html>
- FreeCAD App::Document 类参考 — <https://freecad.github.io/SourceDoc/d8/d3e/classApp_1_1Document.html>
- FreeCAD Property View（View 属性不入 undo）— <https://wiki.freecad.org/Property_View>
- Fusion 建模模式 — <https://help.autodesk.com/cloudhelp/ENU/Fusion-Designs/files/ASM-DESIGN-MODELING-MODES.htm>
- Blender 修饰器导论 — <https://docs.blender.org/manual/en/latest/modeling/modifiers/introduction.html>
- Blender Modifier Tools（Apply All）— <https://docs.blender.org/manual/en/4.1/addons/interface/modifier_tools.html>
- Figma autosave 工程博客 — <https://www.figma.com/blog/behind-the-feature-autosave/>
- Figma 离线能力 — <https://help.figma.com/hc/en-us/articles/360040328553-What-can-I-do-offline-in-Figma>
- Figma 版本历史 — <https://help.figma.com/hc/en-us/articles/360038006754-View-a-file-s-version-history>
- Lightroom 元数据基础 — <https://helpx.adobe.com/lightroom-classic/desktop/organize-photos-in-lightroom-classic/metadata-basics-actions.html>
- Lightroom XMP/ACR sidecar — <https://helpx.adobe.com/lightroom-classic/desktop/organize-photos-in-lightroom-classic/create-xmp-acr-files.html>
- Vim recover.txt — <https://github.com/vim/vim/blob/master/runtime/doc/recover.txt>
- Neovim recover — <https://neovim.io/doc/user/recover/>
- GNU Emacs 恢复 — <https://www.gnu.org/software/emacs/manual/html_node/emacs/Recover.html>
- black 基础用法 — <https://black.readthedocs.io/en/stable/usage_and_configuration/the_basics.html>
- black 源码 — <https://github.com/psf/black/blob/master/src/black/__init__.py>
- jscodeshift README — <https://raw.githubusercontent.com/facebook/jscodeshift/main/README.md>
- jscodeshift issue #160（输出到别的文件）— <https://github.com/facebook/jscodeshift/issues/160>
- recast README — <https://github.com/benjamn/recast/blob/master/README.md>
- lisplens 安全写实现 — <https://docs.rs/lisplens/latest/src/lisplens/write.rs.html>
- rustfmt write_file — <https://doc.rust-lang.org/stable/nightly-rustc/rustfmt_nightly/source_file/fn.write_file.html>
- pnpm 原子写 PR — <https://github.com/pnpm/pnpm/pull/12642>
- write-file-atomic issue #16（fsync）— <https://github.com/npm/write-file-atomic/issues/16>
- git-apply — <https://git-scm.com/docs/git-apply>
- git-add — <https://git-scm.com/docs/git-add>
- Pro Git 三种状态 — <https://progit3.com/book/what_is_git_section/>
- nbconvert CLI 用法（inplace 警告）— <https://nbconvert.readthedocs.io/en/stable/usage.html>
- papermill engines — <https://github.com/nteract/papermill/blob/main/papermill/engines.py>
- papermill issue #200（IO 与执行分离）— <https://github.com/nteract/papermill/issues/200>
- IntelliJ Find tool window（Do Refactor / Include / Exclude）— <https://www.jetbrains.com/help/idea/find-tool-window.html>
- IntelliJ Rename refactorings — <https://www.jetbrains.com/help/idea/rename-refactorings.html>
- IntelliJ Code refactoring — <https://www.jetbrains.com/help/idea/refactoring-source-code.html>
- Word Track changes — <https://support.microsoft.com/en-us/word/training/track-changes-in-word>
- matterof writer.rs（dry-run/atomic/backup 选项集合）— <https://docs.rs/matterof/latest/src/matterof/io/writer.rs.html>
