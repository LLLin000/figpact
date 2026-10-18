# G18：正式 Inspector 的 Verified Style Overlay

仅扩展 figpact/inspector_server.py + figpact/_inspector/，不扩 tools/gui。
Geometry Intent 与 Style Overlay 权限入口分开；不新增任意 set_property、Artist 类型、Agent 或历史数据库。
可信 script/config/scope/overlay 路径仅在服务启动时指定；浏览器只提交已发放的 target/revision/candidate IDs 和有限数值。
复用回环、同源与页面会话 token。预览不得写正式 Overlay；提交必须通过页面确认和当前 SHA/同源版本检查。
图片、Scene、样式对象映射来自同一实际 Figure；对象映射凭实际 Artist 引用/稳定身份，不猜位置或相似文本。

## 固定浏览器任务

G15 barchart，原始 ylabel/刻度10pt。真实Chromium执行：
1. 画布点击ylabel，输入8，预览验证，查看旧/新值与影响范围，确认保存COMMITTED+PASS。
2. 不刷新工作区选x刻度，改8保存；ylabel仍8。
3. ylabel改9保存，再显式恢复原样式并确认；ylabel回10，刻度仍8。
4. 停服务，新进程同一可信入口和Overlay，重新打开图、清单与保存状态一致。
5. 外部Overlay更新、身份/源漂移、QA失败、过期保存冲突必须明确拒绝，保留原有字节。
6. 完整浏览器套件、Inspector Node、相关后端分别记录实际执行数；不复用旧数字。

## 极简性与耗时

正向单次修改期望：选对象 → 改数值 → 验证预览 → 一次明确确认保存。
恢复原样式使用现有remove，不设计Undo/Redo历史系统。
即时选中反馈与耗时后端验证明确区分；不为提速省略独立构图/审计。
逐阶段记录选择、预览、提交验证、同帧重绘的实测耗时（本机单轮样本，非性能基准）。
记录不必要点击、重复确认、冗余信息、旧几何控件对样式用户的干扰，并优先删除非必要设计。
允许精确映射失败时从对象列表选择，但不把fallback当作画布点击已通过。
