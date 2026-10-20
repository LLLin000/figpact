# G25-S：外部来源多类型压力测试

## 结论与边界

本轮按用户要求完成公开脚本下载、静态审查、隔离原样运行及既有引擎压力探针。**G25-0 仍为 BLOCKED；这不是独立未见集模型评测。** 没有独立金标准签核，没有冻结 96 题，没有调用受测模型，没有模型准确率或统计泛化结论。所有下载来源已进入开发污染清单：`tools/g25s/runs/summary.json` 的 `source_records`，全部 `DEVELOPMENT_EXPOSED`、`independent_signoff=false`，不能以后转称未见测试集。

没有修改 figpact 产品代码，没有替第三方脚本补种子、改样式、删除对象或放松 QA；没有保存正式 Overlay，也没有发布。局部 PASS、整图 PASS、引擎失败及脚本环境兼容失败分别保留。

## 来源及保留物

| 来源 | 固定版本 | 下载脚本数 |
|---|---|---:|
| [Matplotlib Gallery](https://github.com/matplotlib/matplotlib/tree/d7a19fbf48918c1a99f771c954c49c14ea95fc5d/galleries/examples) | `d7a19fbf48918c1a99f771c954c49c14ea95fc5d` | 12 |
| [Matplotlib 3.10.8 Gallery](https://github.com/matplotlib/matplotlib/tree/1392cbe3c79cdb93f9282747841d648770f60249/galleries/examples) | `1392cbe3c79cdb93f9282747841d648770f60249` | 6 |
| [Scientific Visualization Book code](https://github.com/rougier/scientific-visualization-book/tree/62fa569f30333c817c13e4dc757877c1192fd15a/code) | `62fa569f30333c817c13e4dc757877c1192fd15a` | 7 |
| [Matplotlib Cheatsheet code](https://github.com/rougier/matplotlib-cheatsheet/tree/f65e2b11744ec89d4bcf269a92b8b977de2d0279) | `f65e2b11744ec89d4bcf269a92b8b977de2d0279` | 1 |

26 份是脚本版本数，不是 26 个独立图族：heatmap/pie 的兼容版本与最新版本是同源变体；去重后为 24 个 repository/upstream_path，且两个 Rougier 仓库同作者。未证明这些路径对应独立研究图族。与 G15 的八个 gallery upstream_path 无重用，不等于独立性认证。

原始字节、许可及来源记录：`tools/g25s/gallery/`、`compatible/`、`thirdparty/`，各自 `manifest.json`。Matplotlib 许可和 Rougier 代码 BSD 许可随源保留；未使用书籍正文许可充当代码许可。额外依赖/外部数据/动画及不纳入当前许可池的来源保留排除原因，没有伪造可运行记录。

覆盖热图/色条、等高线、矢量箭头、流线/遮罩/NaN、小提琴、箱线、直方、饼图/阴影、Sankey、极坐标、3D 曲面、双轴、嵌套放大图、对数误差条、堆叠面积、日期刻度、散点双图例、箭头注释、跨 Axes 连线、32-Axes GridSpec、复数域着色及集合类兼容边界。图中存在对象不意味着该对象获得编辑权限。

## 执行方法

- 环境：Windows x64，Python 3.14.0，Matplotlib 3.10.8，NumPy 2.3.3，SciPy 1.16.3；未安装新依赖。
- `tools/g25s/run_stress.py`：每份来源独立子进程，Agg，每源 240 秒超时，最多三个并发；原始脚本复制后哈希验证。脚本自身错误保留在 results 中，**子进程 exit 0 不代表样本通过**。
- 静态审查后以 Python audit hook 禁止网络/子进程及运行目录外写入；这是防御性约束，**不是 OS 级恶意代码沙箱**。
- `source_adapter.py` 完整运行原始脚本，仅抑制 GUI show，保留所有未关闭 Figure，不重写源文件、不增加 Native 契约。`fig0` 等仅是整张原始 Figure 的序号选择器，不是持久语义 panel ID。
- Rougier 的 `../../figures/...` 输出通过运行目录内 `work/code` 与对应 `figures/` 目录承接，未改 savefig 行；这些是来源脚本自身的基线导出，不是 figpact 正式保存/出版。
- 每 Figure 保存 baseline PNG、真实 inventory、可用时真实 `StyleSession` / `discover_overlay` context。每种有资格的 role 取第一个目标，进行 +0.5pt（受内部探针上限约束）样式试算；首个 role 另试现值 no-op 和 -1 越界。
- 真实 `check_plan` 另检查错 scope、过期 revision、无 Native 权限、伪造 science 控制和重复控制 ID。上下文无法产生时不伪造上下文补测。
- `style_overlay.inspect_candidate` 回执与异常原样保存，未调用 apply/commit 的正式写入路径。
- 运行计划记有 runner/adapter 哈希。聚合 summary 另保存 manifest 哈希、环境及运行后引擎源码哈希、inset 使用的安装包 `.npy` 资产哈希；这些运行后记录不是事前统计冻结，也不声称完整原生依赖闭包。

## 实测汇总

以下不包括 `gallery-first` 的初版测试工具记录；正式压力探针分母取 `gallery-probes`、`compatible-first`、`thirdparty-first`。它们仍是开发探针，不是正式模型评测。

| 指标 | 观察数 / 分母 |
|---|---:|
| 原样脚本基线可运行 | 23 / 26 |
| 原样脚本基线失败 | 3 / 26 |
| 基线保留 Figure | 51 |
| Figure 可产生真实 context | 34 / 51 |
| Figure context 失败 | 17 / 51 |
| Figure inventory 无授权目标 | 14 / 51 |
| 实际候选探针 | 129 |
| 有变化样式探针 local PASS | 47 / 55 |
| 有变化样式探针 whole-figure PASS | 37 / 55 |
| local PASS 但 whole-figure FAIL | 10 / 55 |
| 候选路径未捕获异常 | 12 / 129 |
| no-op 探针 local PASS | 0 / 37 |
| 越界探针 local PASS | 0 / 37 |
| 计划负例被入口拒绝 | 130 / 130 |
| 候选后正式 Overlay 不存在 | 129 / 129 |
| 原始下载脚本前后哈希不变 | 26 / 26 |
| 进程超时 | 0 / 26 |

no-op 37 次中含等高线的 6 次未捕获异常；不能说 37 次都返回规范拒绝。越界 37 次均有 ERROR 回执。130 次入口拒绝只证明所列结构性负例，并不证明模型能识别自然语言歧义、同文字不同 panel，或所有错误内部目标。129 次未持久化也不是正式提交/回放正确性的测试。

## 发现的问题与已有边界

| 类别 | 实际证据 | 归类与影响 |
|---|---|---|
| 等高线使 Scene 出帧抛 TypeError | 全部六张 contour Figure 的 `gallery-probes/g25s-contour/fig*/context-error.log`，及第三方 domain coloring 记录 | `scene.py:622` 对非 Text 的 ContourLabeler 调用无参 `get_text()`；该方法需要 lev/fmt。7 张 Figure 无法产生上下文。属于真实对象类型兼容缺陷。 |
| 等高线候选样式审计抛 ndarray 布尔异常 | `gallery-probes/g25s-contour/fig0/0-change-error.log` | `change_audit.py:757` 的 `vb == va` 被当作标量条件；6 张 Figure 的 change/no-op 共 12 次异常，无结构化候选回执。属于真实审计兼容缺陷。 |
| 3D / colorbar / streamplot 几何无法测量 | `gallery-probes/g25s-3d/fig0/context-error.log`；`compatible-first/g25s-compat-heatmap/fig1,fig2`；`g25s-compat-stream/fig0` | 共 4 张 Figure 出帧失败关闭。inventory/局部候选仍可能可用，不能因此宣布 Inspector 或自然语言入口可用。对象测量边界，未豁免未知几何。 |
| 对数负误差条 Scene 含 NaN anchor | `gallery-probes/g25s-log/fig2/context-error.log` | JSON 明确指出 `nodes[35].anchors.bottom` 为 NaN；场景拒绝序列化。该图的 tick change 还以 `unexplained geometry` 被局部审计拒绝，见 `0-change-receipt.json`。尚未证明该拒绝是审计误报。 |
| 带阴影饼图/Sankey 捕获自身触发科学差异 | `compatible-first/g25s-compat-pie/fig5,fig7/context-error.log`；`g25s-compat-sankey/fig0..2/context-error.log` | 无编辑的捕获过程即 `SCIENCE_CHANGED`，5 张 Figure 被拒绝。需要区分 Matplotlib 延迟绘制变化与科学指纹实现；本轮未定位更深层根因，不声称真的改了科学数据。 |
| 无控制权对象类型 | `compatible-first/g25s-compat-pie/*/inventory.json`、`g25s-compat-sankey/*/inventory.json`；第三方 annotation/direct、zoom、domain coloring | 共 14 张 Figure 零目标。饼块、Sankey、普通注释/Collection 等未获授权；属于现有 role 闭集的能力边界，不算“编辑成功”或自动扩权的理由。 |
| 非确定性第三方多 panel | `thirdparty-first/tp_book_complex_layout/fig0/0-change-receipt.json`，原始 `complex_layout.py:44` | 原始脚本未固定 `np.random.uniform`；重建图像数据不同，引擎按科学变更拒绝。32-Axes 结构可出帧但不能据此声称编辑可受理。本轮不补种子追认通过。 |
| 原始来源与安装版本不兼容 | heatmap `rotation_mode='xtick'`、pie `wedge_labels`、collection `RegularPolyCollection` 参数错误，各自 `baseline-error.log` | 3 个基线失败。新 Gallery 两个脚本需要比本机更新的接口，旧 Cheatsheet 使用旧签名。是来源环境失败，不算 figpact 编辑失败；heatmap/pie 另下载 3.10.8 原始版本，作为同源兼容补充，原失败保留。 |
| 局部成功不是整图出版通过 | 十份 `*:change` 回执 local PASS / whole FAIL，包含箱线、3D、热图、流线、日期图 | 原有重叠、字号等 QA 继续保留；不把草稿资格或 local PASS 升级成严格出版 PASS。 |

上述目录均相对于 `tools/g25s/runs/`。完整逐来源结果、计划负例、候选 effect/science/QA、stdout/stderr、原始异常及 source-record 均保留。`summary.json` 可追溯来源和计数，`visual-baseline-contact-sheet.png` 是实际已查看的六类型基线拼图。

## 测试工具首次记录不能丢弃

`runs/gallery-first` 的初版 runner 把 inventory 的 `current` 字典当作数值，导致所有编辑 probe 被跳过；它仍执行了基线、inventory、真实 context 和入口负例。修正为按 property 或 tick `uniform` 取值后，使用新目录 `gallery-probes` 补跑。原目录未覆盖；不能把初次空探针说成首次全部通过。产品实现未因此修改。

## 复现

在仓库根目录，使用已具备 Matplotlib/NumPy 的 Python；必须给一个不存在的新输出目录：

```sh
python -B -X utf8 tools/g25s/run_stress.py --manifests tools/g25s/gallery/manifest.json tools/g25s/compatible/manifest.json tools/g25s/thirdparty/manifest.json --output tools/g25s/runs/new-observation --timeout 240
```

当前 runner 保留上述 Rougier 相对输出目录布局；首次 Gallery/compatible 运行计划的 runner 哈希早于该布局补充，各自 raw run-plan 才是当时工具指纹。不得声称一份当前源码哈希涵盖所有历史工具字节。

## 下一步与未覆盖项

优先定位等高线的两个异常、带色条/3D/流线的不可测几何、饼图/Sankey 的捕获科学指纹变化；这些是有实际失败记录的工作项，而不是先扩展 Agent 或改 QA。

本轮没有覆盖所有图类、每个 Artist/轴/目标、所有数值边界、跨 panel 自然语言歧义、全量原子多编辑、持久化/冲突/重启、动画、地理投影、交互控件、真实科研 instrument 数据、所有字体/多语言、所有后端/操作系统或恶意原生代码。也没有 Native 新契约或模型首答可靠性数据。有限来源和有限探针不可能保证找到所有问题。正式 G25 仍需独立来源认证、控制/表达性审查、独立标注签核和事前冻结。
