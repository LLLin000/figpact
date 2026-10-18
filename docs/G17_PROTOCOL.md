# G17 Composable Overlay Transaction

只组合已有 G16 三操作，不新增 Artist、GUI、AST 改写或验证链。
`edits=[{target_id,value}]` 为增量 upsert，未提及目标必须保留；
`remove=[target_id]` 显式删除授权，删除后由原始程序恢复该对象样式。
同一请求重复目标、同时 upsert/remove、删除不存在目标均拒绝。
更新已有文件必须先校验 expected SHA，包括相同状态重试；源、scope、依赖及旧身份漂移拒绝。
最后一个目标可被移除，空 Overlay 可重建原图，不能伪称产生非零样式变化。

合并后完整 targets 经 G16 独立重建、对象联合审计、科学保护、整图 QA 后才写入。
所有历史保留目标仍需核对目标值与授权范围，不能仅验证最后一项。
沿用 Overlay 原子安装/替换与单写者约束，不宣称多写者 CAS。
声明依赖不存在、不可读取、hook 异常明确拒绝；未声明依赖才是合法空集。
只覆盖显式 wrapper/RAW/config/science_inputs，不自动追踪全部 Python import 传递依赖闭包。

固定验收样本为 G15 barchart：
A=ylabel Length(mm) 字号8；B=x主刻度字号8；更新A=9；移除A。
每阶段调用独立 CLI 进程，重新打开检查完整 saved targets 与实际属性，B从加入后始终为8。
最终A恢复原始10，B仍8。stale SHA、非法删除、QA失败不改变已有文件。
G16 三正向样本取消allow-draft，强制COMMITTED+整图PASS+CLI0；失败草稿保留独立负向回归。
G15原文/声明/报告/R0R1分数与G16历史证据不回写，新结果单独记录。
