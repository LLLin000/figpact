# G17：Composable Overlay Transaction

## 结果

G16 三操作保持不变；新增的是已有 Overlay 的增量状态组合，不是新 Artist、GUI 或 AST 改写。
预登记语义见 [G17_PROTOCOL.md](G17_PROTOCOL.md)。

真实 CLI 与新进程属性检查完成四阶段，所有正向阶段均严格要求 **COMMITTED + local PASS + figure PASS + exit 0**，不使用 allow-draft：

| 阶段 | ylabel A | x 主刻度 B | 持久化完整状态 | 新进程重建与整图 QA |
|---|---|---|---|---|
| 新增 A | 8 pt | 原始 10 pt | A=8 | PASS |
| 新增 B | 8 pt | 8 pt | A=8、B=8 | PASS |
| 更新 A | 9 pt | 8 pt | A=9、B=8 | PASS |
| 显式移除 A | 恢复原始 10 pt | 8 pt | B=8 | PASS |

原始 wrapper 字节不变，最终图已实际渲染并查看。stale SHA 删除请求返回失败，既有 Overlay 字节不变。
运行器 `tools/g17/run_acceptance.py` 为每阶段启动独立 CLI，随后再次用独立 Python 进程 load 并检查 ylabel/tick 实际值；
不以 JSON 中只有目标列表代替真实图属性。

## 状态语义

- `edits=[{target_id,value}]` 为增量 upsert，未提及的旧目标保持原值和旧身份声明。
- `remove=[target_id]` / CLI 重复 `--remove` 显式删除授权，原程序重新构建时恢复该对象原样式。
- 空请求在既有 Overlay 上是保留全部目标的无操作，仍需要正确 expected SHA；不是隐式清空。
- 移除最后一项产生 `targets=[]`，支持 load/render 恢复原图。回执标明清空，不虚构非零样式效果。
- 重复目标、同项增改/删除冲突、删除不存在目标、无 expected SHA 更新、stale SHA、旧身份漂移均拒绝。
- 源/config/scope/依赖必须与旧 Overlay 匹配；纯磁盘哈希与路径门在执行源模块之前检查。
- 被移除的旧对象也检查身份，不能用删除绕过对象消失/歧义的拒绝。
- 合并后的所有保留/新增/更新目标进入原 G16 独立重建与联合审计，重新核对完整属性、科学内容、视图与 QA。
  不新写一条审计链。失败默认不覆盖旧文件；显式失败草稿仍走 G16 独立负向路径。

持久化继续沿用原子安装/原子替换与单写者假设，**不是多个写者间的 CAS 事务**。
本轮不提供 GUI 撤销历史、恢复界面或自然语言编辑；显式 remove 不等于完整历史撤销系统。

## 依赖安全

`RAW` 未声明/None 合法；明确声明的文件不存在、是目录、不可读取或路径损坏时不再返回 None。
`SCIENCE_INPUTS`/`science_inputs()` 未声明可为空；声明缺失、hook 异常或不可读取则明确拒绝，不能降级成空集合。
依赖哈希不再以“missing”作为合法已声明文件的持久化值，也不跳过无法解析的路径。

当前保护的是显式 wrapper、RAW、config、science inputs，不是所有 Python import 的自动传递闭包。
辅助科学处理模块必须显式声明为受保护依赖；本轮没有新增 import 追踪器。

## G16 验收修正

`tools/g16/run_acceptance.py` 的三正向图已取消 allow-draft；首次和重复 Apply 强制 COMMITTED、整图 PASS、exit 0；
restart 同时强制局部 PASS、整图 PASS、exit 0。三个样本在严格条件下均真实通过。
4 pt 小字等失败草稿由 `tests/test_style_overlay_failures.py` 独立守护，不能混入正向成功分母。
历史 G16 报告记录的事实不回写，新运行证据另存 G17 归档。

## 回归与证据

全量首轮曾有 3 条新组合测试失败：FTIR 测试裸 build 留下全局样式，令新测试假定的 10 pt 刻度基线变为 8 pt，
再请求 8 pt 就成为 no-op。产品拒绝“未有效变化”是正确行为，未为此放宽审计。
组合测试现在显式固定其断言所需的 ambient rc 并在 teardown 恢复；所有 setup 写入增加提交断言，
避免初始失败串成误导的 REMOVE_MISSING。污染文件与组合测试实际运行 **17 passed**。

定向实际执行：**41 passed**。包含 G17 组合/依赖、G16 身份/Overlay/失败草稿/漂移，以及统计状态、plate 和源写入事务。
覆盖连续编辑、空请求不丢状态、移除最后一项、stale/冲突/重复/未知删除/QA失败不改变旧字节、
更新漂移源代码不执行、删除不能绕过消失目标、缺失 RAW/科学依赖拒绝、持久化依赖被删后加载失败。

复跑：

```bash
python tools/g17/run_acceptance.py --output-dir <fresh-directory>
python tools/g16/run_acceptance.py --output-dir <another-fresh-directory>
python -m pytest tests/test_overlay_composition.py tests/test_overlay_dependencies.py -q
```

本机完整日志、逐阶段回执、实际 PNG、Overlay：`D:/L/AI/figpact-archive/g17/release/`。
严格 G16 三样本日志：`D:/L/AI/figpact-archive/g17/g16-strict-release/`。
可复跑代码与紧凑新进程测量结果保留在 `tools/g17/`。

全量非浏览器实际执行：**581 passed / 7 skipped / 1 warning / 87 subtests passed**，耗时 1206.93 秒。浏览器本轮未复跑，不将历史结果冒充最新验证。

## 下一阶段

组合机制完成后应转向真实 GUI 连续操作流程，而非继续增加独立 CLI 能力或 Artist 类型。
本轮仅记录这一方向，不提前开发 GUI 或扩大角色注册表。
