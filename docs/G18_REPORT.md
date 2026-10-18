# G18：Inspector 样式连续编辑

## 实现与范围

接入正式 `figpact/inspector_server.py` + `_inspector/`，没有扩展 `tools/gui/server.py`。
新增 `inspector_style.StyleSession` 是对 G17 Overlay、稳定身份与现有 Inspector capture 的薄适配。
Geometry Intent 保持独立；没有任意 set_property、Artist 扩展、AST 改写或历史数据库。

启动时固定可信源和 Overlay：

```bash
python -m figpact ui --script tools/g15/B/g15b_barchart_decl.py --scope main --overlay <workdir>/style.json --port 0
```

样式模式 config 可选。HTTP 请求不能指定脚本、输出路径或方法名；复用本机回环、Host/Origin/Sec-Fetch-Site 校验与页面会话令牌。
提交必须具有页面 `X-Figpact-Ui`、服务端签发的 candidate ID、原始 frame revision 和候选绑定的官方 SHA。
浏览器自行声称新 SHA 不能使旧候选有效。

## 真实 Chromium 工作流

使用固定 G15 柱形图，实际画布点击 ylabel（不是仅在下拉框选择）：

1. ylabel 10→8：输入、预览，正式 Overlay 尚不存在；确认后 COMMITTED/PASS。
2. 不刷新工作区，点击 x 刻度改为8；ylabel 保持8。
3. ylabel 改为9，再恢复原样式并确认；ylabel 回10，x 刻度仍8。
4. 停止服务器，以新进程同一可信源及 Overlay 启动，再开浏览器，图形、目标值和保存状态一致。

浏览器自动验收与父代理手动 Chromium 操作均执行上述编辑；实际 PNG 已查看。
负向验收覆盖4pt QA失败、外部Overlay更新后的保存冲突、复制源身份漂移、无页面令牌、任意路径字段及错误Origin。
失败显示明确状态，原有正式Overlay字节保留。

## 同源帧与身份

从同一实际 Figure 捕获 PNG、Scene 与样式清单。基线稳定描述符解析到实际 styled Artist 引用，再在帧内登记GID，
用精确GID→Scene ID关系映射；不按位置或文字相似度猜绑定。不能映射的目标不被误认作可点击控制权。
官方帧缓存读出，GET不重新构图，不把Geometry图的revision嫁接到Style图。
每次预览/提交都整体替换经校验的新图像、Scene和映射，不沿用旧几何。

预览将官方Overlay复制为同目录私有临时文件，通过G17增量apply验证候选；正式文件不写。
提交重放候选的原始增改/删除意图并重新验证，不复制另一套审计或事务。
候选被替换、取消或提交后清理私有文件，官方SHA冲突使候选失效。

## 极简性审查（真实使用后改动）

正向修改流程为 **选对象 → 输入数字 → 预览验证 → 一次确认保存**。
没有“预览→接受→保存→再确认”的额外接受步骤。恢复原样式复用remove，需同样一次明确确认。

实测首版存在复杂或误导设计，已删减：

- 样式模式隐藏无效的DPI切换和位置微调，保留原几何模式能力。
- 对象详情不再声称样式对象“只能示范、不能保留”，而明确Style Overlay控制来源。
- 首屏用“Y轴标签/X轴刻度”等名称，技术target ID留在详细信息，不把长指纹塞进确认文案。
- 恢复确认显示“原始样式（移除覆盖）”，不出现null pt；未覆盖对象禁用恢复按钮。
- 耗时折叠到“验证耗时”，忙状态始终可见；保留一个数值输入，不新增通用属性表单。
- 重开显示当前值与已保存/原始状态，不停留“未加载”。

剩余取舍：保留精确目标下拉框作画布选择的替代入口；技术尺寸/编号仍在既有详情中，不作为新编辑必填步骤。
每次验证与提交有秒级等待，界面明确显示“验证中/保存中”，不通过跳过独立重建提速。
这是工程人员与自动化验收的可用性记录，不宣称完成独立普通用户研究。

## 耗时口径

本机首轮成功Chromium记录（单次样本，非性能基准）：选择约96ms；首次预览约3935ms；确认保存约3750ms；页面就绪约656ms；重启页面就绪约272ms。
紧凑测量保存为 `tools/g18/results.json`，实际截图与测量归档于 `D:/L/AI/figpact-archive/g18/browser/`。
服务端另外记录preview、commit、rebuild各自真实计时；浏览器整段耗时包括请求、图像校验与重绘，不能与服务端简单相加。
最终运行原始测量保留在浏览器case目录results.json；未把早期实现中“操作后才启动计时”的近零假数字当证据。

## 验证及已修缺陷

- Inspector Node 实际执行：**54 passed**。
- 相关后端实际执行：**29 passed**（StyleSession、G17组合/依赖、G16身份/Overlay/失败/漂移）。
- 完整 Chromium 浏览器实际执行：**24 passed**，204.75 秒；包含连续样式编辑、新服务进程恢复及拒绝边界。未在本轮重跑全量非浏览器套件，不沿用G17历史数。

首轮真实浏览器暴露并修复：旧几何帧与样式帧revision混用、初始null saved值误拒、隐藏样式面板、
未定义前端函数导致图无法初始化、提交已成功但UI错误谎称未写、移除未传G17remove、
样式改动时误删原几何拖动权限guard。修复不降低SHA/审计/权限门槛。
旧测试对技术ID文案的断言已删除，保留真实pending目标/旧新值和磁盘行为断言，不为中文简化重钉内部文案。

复跑：

```bash
python -m pytest tests/browser -q
node --test tests/inspector/test_inspector.js
python -m pytest tests/test_inspector_style_backend.py tests/test_overlay_composition.py tests/test_overlay_dependencies.py tests/test_style_identity.py tests/test_style_overlay.py tests/test_style_overlay_failures.py tests/test_style_overlay_drift.py -q
```

不新增legend/errorbar/bar/scatter编辑、自然语言Agent、任意源码改写或Undo/Redo历史系统。
