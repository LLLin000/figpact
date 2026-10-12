# G3：可恢复的操作历史（后端显式启用）

## 工作事实

基线：`0b9cacc89505735855bcb7842fe849773c6d70f5`。本轮完成 **Python SDK 的持久操作历史**，沿用 `IntentSession` 的接受、取消及独立撤销，不另建编辑状态机。

**当前网页入口仍是 G2 的会话内保留。** 本轮没有把持久历史接入 Inspector HTTP/UI；不要向用户承诺关闭现有网页服务后会自动恢复操作。无 YAML 的测量/示范能力也不等于无 YAML 源码编辑。

修改文件：

- `figpact/history.py`：外部状态目录、检查点、证据完整性与只读历史 CLI。
- `figpact/intents.py`：显式启用、保存操作、重启重建、版本保护、持久撤销。
- `tests/test_history.py`、`tests/test_intent_history.py`：39 项新增正向/负向测试。
- `CONTEXT.md`、`README.md`、`SKILL.md`、本报告：术语与入口边界。

未修改 `scene.py`、`geometry.py`、`science.py`、既有 YAML Agent API、正式 strict 发布、Inspector HTTP 桥或前端。

## 保存与恢复

```python
from figpact.intents import IntentSession

with IntentSession(script=script, config=config, scope="main", dpi=600,
                   history=True, state_home="I:/figpact-history") as session:
    frame = session.snapshot()
    records = session.history()
```

关闭后，以相同脚本路径、配置路径、scope 和状态目录重新打开。默认 `history=False` 仍不创建持久记录。状态目录也可由 `FIGPACT_STATE_HOME` 指定；本轮实测所有测试状态、缓存和临时文件都放在 I 盘。

- 每个检查点保存当前接受集合、操作请求、目标 GID、参数变化、实测几何、引线检查、科学/QA 证据、原帧及版本条件。
- 工作区按解析后的路径和 scope 区分；源码内容变化不会让旧历史凭空消失。
- 重新打开先检查脚本、配置、声明的科学输入、相邻输入和引擎文件指纹，再用当前源码实际构图及重放。不是把旧 PNG 当作新验证。
- 恢复核对基线、目标及最终全部图元的几何。未经授权的其他对象变化同样拒绝。
- 源码/数据/环境或重放证据不再对应时进入 `HISTORICAL_ONLY`：可看历史，不能直接接受新的修改。损坏的帧摘要在执行绘图脚本之前拒绝。
- 取消候选不落历史；独立撤销保存新的检查点，后来依赖该操作的修改会阻止静默撤销。
- 两个会话竞争同一检查点时，过期会话接受失败并保留自己的候选，不自动吞掉另一个会话已经接受的操作。

存储使用标准库 SQLite 的比较后写入事务与带摘要的不可变证据文件。拒绝把历史放在绘图源码目录内、链接跳转、硬链接数据库、外来或版本不支持的数据库；损坏历史不会被重新初始化为“空历史”。这些是操作历史保护，不是多文件科学产物的原子发布承诺。

### 只读查看，不执行脚本

```bash
python -m figpact.history list --script "examples/nmr/08 NMR.py" --config examples/nmr/nmr.yaml --scope main --state-home I:/figpact-history
python -m figpact.history show --script "examples/nmr/08 NMR.py" --config examples/nmr/nmr.yaml --scope main --state-home I:/figpact-history --id <checkpoint-id>
```

不存在历史时 `list` 不创建目录或数据库。CLI 不构图、不读科学输入内容、不重放、不修改源码。

## 风险与权限

- 未修改用户 Python/YAML、科学文件、正式图件；持久接受不等于写入配置或发布。
- 实测原有 `examples/` 的 **151 个文件**在三个进程前后逐个 SHA 比对，变化为 0。
- 3.91 ppm 和 9.83 ppm 的引线指向数据的端点均不变，标签端随标签移动。
- 只验证当前 scope；并非跨 scope 正式出版验收。
- 保存完整同帧几何与图片会占磁盘；本轮未测长期历史增长或压缩收益。
- 本轮没有新增持久 HTTP 写入口、Session Hub、浏览器身份认证或 History 界面，不能据此声称这些风险已经解决。

## 真实验收

所有测试由原生 task 指定 `opencode-go/step-5-preview-free` 运行，无模型替换。

```bash
python -B -X utf8 -m pytest -p no:cacheprovider -q -ra --tb=short --basetemp=I:/figpact-test-archive/G3-0b9cacc/full-tmp --junitxml=I:/figpact-test-archive/G3-0b9cacc/full.junit.xml
node --test tests/inspector/test_inspector.js
```

执行程序为 `D:/programs/Python/python.exe`；`TEMP/TMP/TMPDIR/MPLCONFIGDIR/FIGPACT_STATE_HOME` 指向 I 盘，`MPLBACKEND=Agg`，禁止生成 `.pyc`。

| 本轮运行 | 通过 | 失败 | 跳过 | 实际耗时 |
|---|---:|---:|---:|---:|
| 全量 Python | 351 | 0 | 7 | pytest 347.23 s；命令墙钟 350.12 s |
| 前端 Node | 39 | 0 | 0 | Node 248.97 ms；命令墙钟 0.73 s |
| 存储针对性测试 | 23 | 0 | 0 | pytest 21.11 s |
| 操作历史 + 既有 G2 针对性测试 | 39 | 0 | 0 | pytest 37.79 s |

全量另有 **73 个 subtest 通过**，不重复计为 73 个顶层 Python 用例。JUnit 共 431 项包含 subtest 和跳过项。

7 项跳过如实保留：

- `tests/test_agent_api.py:1020,1312`：当前 Windows 账号不能创建目录符号链接，两个逃逸验证未运行。
- `tests/test_inspector.py:114`：不能创建符号链接，导出链接目标测试未运行。
- `tests/test_publish_safety.py:375,402`：不能创建符号链接，来源/目标链接逃逸测试未运行。
- `tests/test_effects.py:207`、`tests/test_session.py:1409`：旧脚本夹具不在，两个兼容用例未运行。

负向测试覆盖：源码目录写入、只读 CLI 建库、外来/不支持数据库、硬链接、坏证据、实际进程中止后的检查点、相同大小及 mtime 的科学文件变化、改变源码后不执行它、两个真实会话争抢、伪造目标/非目标几何、依赖撤销、反复恢复漂移。曾先发现并保留红例证据，再修复；未把失败改成跳过。

### 真实 NMR：两个操作、两个新进程、撤销 B 保留 A

实测脚本：`examples/nmr/08 NMR.py`，配置：`examples/nmr/nmr.yaml`，scope `main`，600 DPI。驱动和完整 JSON/PNG 证据留在 `I:/figpact-test-archive/G3-0b9cacc/native-final/`，未加入仓库。

| 操作 | 目标 GID | 要求位移 mm | 实测位移 mm | 引线科学端误差 mm |
|---|---|---|---|---:|
| A | `fig2_nmr.main.peak.vancho.3p91` | `[0, 0.15]` | `[0, 0.1500000000000039]` | 0 |
| B | `fig2_nmr.main.peak.vancho.9p83` | `[0.20, 0]` | `[0.19999999999999218, 0]` | 0 |

这只是同一渲染环境下的数值误差，不是宣称物理测量精度达到浮点尾数。

- 进程 62628 接受 A、B：2 个操作检查点。
- 新进程 55964 重新构图恢复 A、B；撤销 B 后 A 的 bbox 不变，B 回到基线：重启与撤销后共 4 个检查点。
- 再开进程 60408：只恢复 A，B 仍在基线；共 5 个检查点。
- 每次 PID、session ID 不同；恢复比对容差 `0.001 mm`，请求目标容差 `0.01 mm`。
- `science / QA / target / impact` 均 PASS，当前 scope 无新增阻断；父代理实际查看恢复后的 PNG。
- 版本变化拒绝、同样大小/mtime 的输入变动、坏帧在执行源码前拒绝由独立负向测试验证；没有修改真实 NMR 数据来制造这些错误。

## 本轮性能，不沿用旧的速度数字

| 单次实测路径 | 耗时 | 该进程 Agg.draw 调用数 |
|---|---:|---:|
| 首次 SDK 构造 | 8.75 s | 整个首次进程 69 |
| A 真实试算 | 8.76 s | 未单独计数 |
| B 真实试算 | 8.19 s | 未单独计数 |
| 恢复 A+B 的 SDK 构造 | 25.27 s | 包含随后撤销的进程共 94 |
| 再次恢复 A 的 SDK 构造 | 16.25 s | 整个再次恢复进程 44 |

每项 **n=1**，构造计时不含 Python 启动、导入和计时前文件清单读取。`Agg.draw` 计数不是 Figure build 数，也不是正式输出次数。未单独计 Figure build、完整 Agent 端到端 median/P95、工具往返或 tokens；未随机配对旧流程作对照。因此本轮不宣称 History 更快，不用旧的 2.53 s 代替新数据。

## 验收边界与未完成项

- **后端显式启用的操作历史：已验证。** 实际 Inspector 网页跨会话恢复：本轮未接入/未验收。
- 未修改原 Python/YAML，不提供源码 Diff 写回；Source Authoring 属 G4。
- 未开发 History GUI、共享 Session Hub、MCP、自由拖拽、自动排版或 SVG 底图。
- 未证明跨 scope 出版、任意普通无 YAML Figure 可持久编辑或完整 Agent 效率优势。
- 后续若接 HTTP/UI，应单独验收访问授权、历史态展示和实际浏览器重启恢复；不能只因 SDK 已通过就称这条用户链路已完成。
