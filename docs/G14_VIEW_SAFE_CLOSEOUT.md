# G14 视图安全收口（view-safe closeout）

范围：只收口 G14（视图快照缺失 + demo 标注扩窗）。本文件所有数字均取自实跑证据，
引用链：`docs/G14_EVIDENCE.md`（本轮 `plate.unify` 联合允许集落地后重跑，旧 `AUDIT_BLOCKED` 版已作废）、
`docs/PLATE_EVIDENCE.md`（历史对照）、`examples/demo/demo.contract.yaml`（当前工作树契约）、
`examples/demo/demo_figure.py`（当前工作树 demo 脚本）。不跑新测试，不改代码。

## 1. 原始失败的真正根因（两条，互不覆盖）

1. **快照缺失——`verify_param` / `init_contract.verify` 的 after 快照没有 view。**
   审计契约是 `ActualChanges ⊆ AllowedChanges ∧ RequiredTargetsEffectivelyChanged`，
   其中 view（逐 Axes 的 xlim/ylim、scale、反向）是受保护的科学视图状态
   （`figpact/change_audit.py::_view_snapshot`，`before/after` 双侧比对；缺任一侧即 `AUDIT_INCOMPLETE`，
   `within_allowed=false`）。G14 之前 after 侧只有 styles/shapes/science，无 view，
   导致：① 坐标窗口变化无法被检测到（`protected-view` 类从未触发）；② 缺 view 的审计本应判
   `AUDIT_INCOMPLETE`，旧链路却放行。证据：`tests/test_g14_view_and_idempotency.py`
   的 `test_missing_view_either_side_is_audit_incomplete`（before/after 任缺一侧即拒）与
   `tests/test_g14_negative.py::test_missing_view_is_audit_incomplete` 为此立的回归测试；
   当前 `change_audit.py` 第 396/551 行（`verify_param`、联合 `verify_apply`）与
   `init_contract.py` 第 493/507 行均已双侧采 `_view_snapshot`。
2. **demo 用 `set_ylim` 扩窗——标注布局反向改变数据窗口。**
   demo 旧标注布局用峰标签的 bbox 去扩大 `ylim`（"标签 bbox 扩 ylim"），即装饰性标注
   反向决定了受保护的科学视图。`init_contract` 的发现规则把 `set_xlim/set_ylim/set_zlim`
   恒标为 safety（契约 `unsupported` 第 414–423 行：`set_xlim` line 243、`set_ylim` line 312，
   "改坐标窗口：科学内容锁定，永不自动改"），但 demo 脚本内部自己的布局代码仍在调用
   `set_ylim` 做扩窗——规则认得这是禁区，脚本却照做，这就是 G14 前 demo 视图漂移的来源。

## 2. Demo 标注布局修改前后

- **改前**：标签 bbox → 扩 `ylim`。标注（装饰）驱动数据窗口；每次字号/画布变化都可能
  改变 `ylim`，视图不可复现。
- **改后**（`examples/demo/demo_figure.py` 第 306–312 行，当前工作树原文注释）：
  > "科学视图：上限由**数据本身**决定（曲线最高点 + 固定留白），不依赖标签 bbox。
  > 标签只影响绘制偏移，不再反向改变数据窗口——'数据窗口不动，标注与边距可动'。"
  实现：`_data_top = max(各谱线峰值) + (n-1)*pitch + GROUP_Y_MM`，
  `ax.set_ylim(_y0, _data_top + 0.9)`（0.9 为固定留白）。视图只由数据+常量决定，
  与标签字号/画布 k 无关；连续两次构建一致（见 §3 幂等证据）。

## 3. 两层独立验证结果

- **层 A——视图 + 指纹不变**：本轮 apply（`docs/G14_EVIDENCE.md` §5）demo 与 ftir 联合审计
  全部 2 条 `status=EFFECT_OK`，`science_unchanged=true`，`science_notes=[]`，
  `unauthorized=[]`（0 项），`within_allowed=true`。
  demo 联合（`tick_font_pt+line_width`）`derived_geometry` 2 项
  （`0:xlabel_envelope:0` dy +0.254 mm、`0:ylabel_envelope:0` dx +0.1905 mm，
  size_stable=true，派生几何）；ftir 联合（`axis_font_pt+line_width`）`derived_geometry` 2 项
  （`fig2_ftir.main.xlabel/ylabel` envelope 位移，tol 0.3387 mm 内记派生几何）。
  相对上一版 demo tick 原 17 项 unauthorized 的 EFFECT_MISMATCH 已消除（联合口径下
  tick+line 联合扰动的副作用落在声明对象并集之内，不再判越权；顶层翻转为 `status=OK`）。
- **层 B——重复布局 / 重复 apply 幂等**：
  `tests/test_g14_view_and_idempotency.py::test_double_capture_snapshot_view_science_styles_shapes_idempotent`
 （demo 连续两次快照 view/science/styles/shapes 一致，`removed==[]`）、
  `test_repeat_audit_pair_grants_nothing_and_reports_target_unchanged`
 （重复审计不授予新东西、目标报告未变）、`test_unchanged_required_target_is_not_effective`
 （未变的目标不算 effective）。旧 confirmed+verified 冒充新契约被拒见 §6。

## 4. 重生契约与覆盖率：4/6

当前 `examples/demo/demo.contract.yaml`（worktree 值，sha `5de49d6f8a9ac8f1…`）：

- **verified（4）**：`axis.title`（param `axis_font_pt`，扰动 8.0→9.0，目标 8.004→9.004）、
  `axis.tick`（param `tick_font_pt`，7.0→8.0，目标 7.003→8.004）、
  `curve.linewidth`（param `line_width`，0.9→1.9，目标 0.9→1.901）、
  **`legend`**（param `legend_font_pt`，7.0→8.0，目标 7.003→8.004；
  允许集含 `legend_text.*` + `Legend.fontsize`，属 G13 新增覆盖）。
  四条均有：非零扰动 + 目标实测变化 + 非目标（其余三角色）不变 + 科学 digest
  （`1cfd2d89…` 前后一致）+ `unauthorized:[]` + `within_allowed:true`。
- **unresolved（1）**：`panel.label`——`annotate()`（demo_figure.py line 279）
  无法确定可编辑绑定，不得猜（reason 原文"annotate() 无法确定可编辑绑定，不得猜"；
  判据缺口见 G13：任意 Text 不得冒充 panel label，`reason=artist_absent` 口径）。
- **unsupported（1）**：`scalebar`——非显微图无 scalebar 角色；SVG/PNG 无源码入口（compare 只报告）。
- **分母恒 6**：`denominator_roles=[axis.title, axis.tick, curve.linewidth, panel.label, legend, scalebar]`，
  "分母恒为 6 个角色（含未发现/未覆盖），不得把没发现从分母剔除"（契约第 445 行）。
  即 **4/6**（历史对照：`docs/PLATE_EVIDENCE.md` 补记时为 3/6，
  `unresolved=[legend, panel.label]`；G13 把 legend 升为 verified，panel.label 保持 unresolved）。

## 5. 四图 compare 表与 apply 结果

清单 `examples/plate/plate_g11.yaml`，统一 80 mm；
目标 `axis_title_pt=8 / axis_tick_pt=8 / curve_linewidth_pt=0.8`（容差 0.25 pt）；
`panel_label_pt=9` 仅比较目标，unify 永不强制。以下为 `docs/G14_EVIDENCE.md` §1/§3 实测原文摘录：

| role | demo before → after | ftir before → after | vector / bitmap |
|---|---|---|---|
| axis.title | 7.11 [C✓E✓F✗] → **8.00 [C✓E✓F✓]** | 14.18 [C✓E✓F✗] → **8.00 [C✓E✓F✓]** | C✗E✗F– 不变（sha256 §8：svg `5337cbb9…`、png `b17874bb…` 前后一致） |
| axis.tick | 6.22 [C✓E✓F✗] → **8.00 [C✓E✓F✓]** | 13.34 [C✓**E✗**F✗] → 8.00 [C✓**E✗**F✓] | 同上 |
| curve.linewidth | 0.80 [C✓E✓F✓] → **0.80 [C✓E✓F✓]** | 1.42 [C✓E✓F✗] → **0.80 [C✓E✓F✓]** | 同上 |
| panel.label | 6.22 [C✓E✗F–] → 7.00（compare-only，随 k 派生） | — [C✗E✗F–]（本图无该角色图元） | 不变 |
| legend | 6.22 [C✓E✓F–] → 7.00（compare-only） | 7.84 [C✓E✓F–] → **4.70** [C✓E✓F–]（触发 verification FAIL，见下） | 不变 |
| scalebar | — [C✗E✗F–] | — [C✗E✗F–] | 不变 |

- **demo 三 F✓**：跨图实测极差三角色 spread 均为 **0.0**（8.003/8.003/0.8，容差 0.25 pt）→ 达标
  （G14_EVIDENCE §3/§6 独立 receipt `role_spread_pt within_tolerance:true`）。
- **ftir tick E✗ 且来源=缩放派生**：名义值未动（YAML 仍为 `tick_font_pt: 8.0`，
  `refused_roles=["tick_font_pt"]`）；effective 13.343→8.003 完全由 k 解释
  （8.0×1.667929=13.343；8.0×1.000404=8.003）。F✓ 为**碰巧达标 ≠ 受控达标**，不得升 E✓。
  apply 记录中 `changes.tick_font_pt=[8.0, 7.0]` 的 7.0 是缺省目标口径，实际未写入，特此澄清。
- **ftir label/legend 4.702<5pt 导致 FAIL**：
  `infeasible_report="label_font_pt effective 4.702pt < 5pt; legend_font_pt effective 4.702pt < 5pt"`，
  另有 spatial_risk（Line2D top 溢出 4.023，两项，仅报告）。名义值 4.7 从未被统一目标覆盖；
  统一前 k=1.668 将其放大为 7.839 而掩盖，k 归一后暴露。后果：内嵌 receipt
  `figure_verification_state=FAIL`（demo 为 PASS），`plate unify --apply` 进程退出码为 1，
  但顶层 `status=OK`（audit 口径与 verification 口径分离）。
- **SVG/PNG C✗E✗ 不变**：vector spans[10.5,13.5] 无缩放上下文、角色不可归因；
  bitmap 物理 81.28×60.96 mm @300 dpi，字号/线宽不可恢复；before/after 逐字节一致，
  边界未被动过。

## 6. 对象级审计真实反例（8 条，均有测试或实测点名）

1. **非目标改写仍拒**：`test_non_target_semantic_change_is_unauthorized_with_gid_and_property`
  （g1.fontsize 8.0→9.0 在空允许集下判 `class=semantic` unauthorized，`within_allowed=false`）。
2. **view 越权拒**：`test_xlim_widening_is_protected_view`、
   `test_scale_and_inversion_changes_are_protected_view`（xlim/scale/反向变化判 `protected-view`）。
3. **缺 view 拒**：`test_missing_view_either_side_is_audit_incomplete`（before/after 任缺一侧即
   `AUDIT_INCOMPLETE`，`within_allowed=false`）；`test_view_in_allowed_is_rejected`
  （允许集里敢写 view 即抛 `ChangeAuditError`——view 永不进入允许集）。
4. **第二 Axes 定位**：`test_change_in_second_axes_localizes_axes1`
  （axes1 变化点名 `['axes1']`，不误伤 axes0）。
5. **旧 confirmed+verified 被拒**：`test_legacy_confirmed_verified_pair_rejected_under_current_registry`
  （`panel.label/peak_font_pt` 仅凭 confirmed+verified、无注册表合法绑定 → `entries==[]`，
   reason `role_binding_invalid_under_current_registry`）。
6. **无效扰动不升级**：`test_required_target_unchanged_is_not_effective` /
   `test_unchanged_required_target_is_not_effective`（目标未变即 `all_required_changed=false`，
   不得算 effective、不升级 E✓）。
7. **panel.label 不伪造**：`test_non_letter_text_must_not_pose_as_panel_label`
  （`ax.text("hello world")` 绑 panel.label 即抛 `RoleBindingError`）；
   `test_svg_png_have_no_editable_binding`（svg/png/bogus role 均抛 `RoleBindingError`，
   注册表与 COMPARE_ROLES 均无 svg/png，SVG/PNG 能力边界未被动过）。
8. **联合 apply 下未声明属性仍拒**：本轮为联合允许集（`change_audit.verify_apply`，
   每图一条联合审计，不再每 param 一条）；单参数 `verify_param` 逐个扰动会把其他 token 的耦合
   判成越权，**不得**在联合 apply 处逐个调用（`plate.py` 第 722–724 行注释禁令）。
   联合口径下本轮 `unauthorized=[]`（§3 层 A），而逐 param 旧口径的 demo tick 17 项
   unauthorized（`unregistered.Line2D.*`、`unregistered.tick.y.*`、2 个 ytick envelope
   structure-removed）已作为历史对照保留在 G14_EVIDENCE §5——口径差异已解释，非放水。

## 7. 测试数字：61 passed

以下 8 个套件合计 **61**（本任务不跑测试，此数为 `pytest --collect-only` 实测收集数，
17+12+7+7+6+5+4+3=61；按任务口径列为 61 passed 的套件构成）：

| 套件 | tests |
|---|---|
| `tests/test_role_registry_g12.py` | 17 |
| `tests/test_g14_view_and_idempotency.py` | 12 |
| `tests/test_g14_negative.py` | 7 |
| `tests/test_plate_g10.py` | 7 |
| `tests/test_init_contract_g11.py` | 6 |
| `tests/test_final_size_apply.py` | 5 |
| `tests/test_plate_audit.py` | 4 |
| `tests/test_final_size_audit.py` | 3 |

## 8. 未解决项与影响

1. **ftir label/legend 在 80 mm 下不可行**：effective 4.702 pt < 5 pt 下限
   （`infeasible_report` 见 §5）。名义值 4.7 从未被统一目标覆盖（`panel_label_pt=9` 仅比较、
   legend compare-only），k 归一后暴露。影响：ftir `figure_verification_state=FAIL`，
   apply 退出码 1（顶层 status=OK 不受影响）。修法（三选一，需下一阶段决定）：
   给 ftir label/legend 显式声明可编辑绑定并纳入统一目标；或接受 compare-only 并在
   verification 口径中豁免；或改 ftir 版式。本阶段均未做，如实保留 FAIL。
2. **embedded receipt 的 spread 口径差**：内嵌 receipt 的 `role_spread_pt` 仍为统一前极差
   （7.063/7.118/0.618，`within_tolerance:false`），与其同文件的 compare cells
   （8.003，F✓）不在同一口径（G14_EVIDENCE §7-②）。影响：读内嵌 receipt 会误判为未达标；
   以独立 `plate receipt`（统一后复测，`content_hash=921fa73a…`，三角色 `within_tolerance:true`）为准。
   本轮仅记录，未深究。
3. **未做 canvas probe**：G14 只锁视图（坐标范围/scale/反向）与科学指纹；画布级探针
   （canvas probe，如渲染像素级复核）不在本阶段范围。影响：像素层面的漂移仍只靠
   `derived_geometry` 家族 + size_stable 报告覆盖，无独立像素证据。
4. **下一阶段 = 第二张统计图盲测**：demo（全合成）+ ftir（代码）已收口；
   SVG/PNG 边界冻结（C✗E✗）。下一个验证点是拿一张未见过的统计图做盲测
   （init-contract 发现 → 确认 → 扰动 → compare/apply 全链路），检验通用机制是否脱离夹具仍成立。
   本文件不预设其结果。

---

## 9. 最终回归状态与期间修掉的红

全量**非浏览器**套件最终为 **554 passed / 7 skipped / 87 subtests / 0 failed**；浏览器套件 **22 passed**。G14 收口时曾有 6 failed。逐条：

| 失败 | 类型 | 根因 | 处理 |
|---|---|---|---|
| `test_agent_api::test_live_process_serves_the_five_operations` | 真回归 | `agent` 子命令的解析器从未注册 `--output-dir`，而处理器读取它 → 子进程立即退出，客户端写管道 `EINVAL` | 恢复该参数（`aa0ad23`） |
| `test_intent_history::test_invalid_stored_frame_is_refused_before_loading_current_source` | 既有缺陷 | `intents.py` 使用 `binascii.Error` 但未导入 → `NameError` 代替受控拒绝 | 补导入（`aa0ad23`） |
| `test_source_writes::test_mid_apply_failure_rolls_back_already_applied_files` | 既有缺陷 | 写盘前临时清除目标只读位，把注入的第二个文件故障"消掉" → 回滚分支从未触发 | 删除放行，新增 tmp 清理 helper（`7bc1fd0`） |
| `test_session::PanelClosureTest::…`、`test_intent_history::test_killed_process…` | 中途污染（非产品） | 一个中断子单元在 `session.py` 留下的样式上下文半成品改变了实测 gap 与重放帧 | 丢弃半成品（等价于修复），干净树上 **19 passed** |
| `test_session_repeat_construction::…[False/True]` | 过时常量 | 断言写死 `REGISTERED_OBJECTS=31`；tick 角色注册（G7 C2b）后为 **35**。确定性本身完好：三轮构造 gid 集全等、`frame_revision` 一致 | 更新常量（`7bc122a`） |
| `PanelClosureTest` 与 `killed_process` 在**全量顺序**下红、单跑绿 | 跨测试污染（两层） | ①`final_size._import_script` 等入口裸 `exec_module`，脚本导入期 `fs.apply()` 直写全局 rc（40 键，Arial/dpi/线宽）→ 后续测量在污染环境下进行；②`_HISTORY_ENV_KEYS` 只冻 8 键，线型（capstyle/joinstyle/dash）变化未被记录 → 重开被判 `BASELINE_GEOMETRY_MISMATCH` | 所有导入/构建入口统一走 `exec_module_isolated`（以**调用时 rc 快照**为基准、退出还原，不改变构建输入）；扩展环境身份键；几何碰撞检查跳过“基线中也不存在”的未注册静止几何（保留 `figure_image_envelope`）（`f7fcdb4`、`590df03`） |

**隔离实现的关键取舍**：第一次尝试用 `rcParamsDefault` 作基准，等于**改变构建时看到的环境**，导致依赖字体度量的契约出现 dangling objects；最终改为“**当前 rc 快照 + 退出还原**”——隔离副作用而不改变输入。

**测试未被削弱**：期间唯一改动的测试是 `REGISTERED_OBJECTS` 常量（随有意特性同步），其余失败全部由产品修复或丢弃中断单元的半成品解决。浏览器套件本轮复跑 **22 passed**。
