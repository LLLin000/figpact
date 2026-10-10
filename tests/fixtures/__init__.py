"""原生夹具：与绘图源码无关的声明式接缝 + 固定种子的科学载荷。

- `fixture_data`：固定种子的载荷（FTIR 曲线、NMR 谱与峰、四张显微图），
  不读任何仪器原始文件，也没有任何输出副作用。
- `_native`：夹具共用的管路（CLI / 构建 / 渲染 / strict / 契约记录构造与自检）。
- `native_ftir` / `native_nmr` / `native_panels` / `native_mixed`：四张可发布的原生图，
  每张都声明 SCOPES / FIGURE_ID / CONFIG_PATH / SCHEMA / load_config / list_params /
  load_science / build_scene / build_figure_and_registry / layout_contract /
  science_manifest / science_selfcheck / SCIENCE_INPUTS。
- `native_negatives`：**故意带缺陷**的夹具（未接线参数、错绑字号、隐蔽的科学改动、
  真实文字重叠），只用于效果校验与拒绝路径的素材，永远不可发布。

导入这些模块不建 Figure、不渲染、不写文件、不打印。
"""
