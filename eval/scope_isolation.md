# 多 Scope 字节级隔离验证报告

## 1. 实验设计与目标
在 `examples/nmr/` 系列图件生成（`NMR_generate_all.py`）中，验证配置作用域（Scope）的隔离性：
- **目标**：证明当修改特定 scope 的配置参数（例如 `shifts_mm.si_s2.vanoh`）时，只有属于该 scope 目标产物图的字节发生变化，其它独立 scope 对应的图件保持完全相同的字节（SHA-256 逐位一致）。
- **实验环境**：
  - 解释器：`D:/programs/Python/python.exe`
  - 目录：`D:/L/AI/figpact/examples/nmr`
  - 隔离介质：通过 `--config` 指定独立临时配置文件，不修改生产默认配置 `nmr.yaml`。

## 2. 配置改动
- **改动键**：`shifts_mm.si_s2.vanoh`
- **基线值 (Baseline)**：`0.0` (mm)
  ```yaml
  schema_version: 1
  shifts_mm:
    si_s2:
      vanoh: 0.0
  ```
- **对照值 (Modified)**：`1.5` (mm)
  ```yaml
  schema_version: 1
  shifts_mm:
    si_s2:
      vanoh: 1.5
  ```

## 3. SHA-256 字节比对表

| 文件名 | 对应作用域 (Scope) | 基线 SHA-256 (0.0 mm) | 修改后 SHA-256 (1.5 mm) | 状态 | 预期 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `Fig_S2_3_2_NMR.png` | `si_s2` (受测目标) | `a7d8e0df208d37a848fd663f49bd248ef4d461e535b23a33b830181d5a05554a` | `e2ad158469c334f2c838e20df39c1e6e9246d32fcc112b4f810a26530d6f3195` | **改变** | 符合预期（目标作用域受控调整） |
| `Fig_S1_2_1_NMR.png` | `si_s1` | `6f56921ed0ea1ee89f4ce301d77fa5116d361ac6c933789978fb1796da09003c` | `6f56921ed0ea1ee89f4ce301d77fa5116d361ac6c933789978fb1796da09003c` | **不变** | 符合预期（字节级精确隔离） |
| `Fig_S3_4_1_NMR.png` | `si_s3` | `79b870de965a0b61a2b7f06bc514ceb113db13d1e0d460687cc112185385fcbf` | `79b870de965a0b61a2b7f06bc514ceb113db13d1e0d460687cc112185385fcbf` | **不变** | 符合预期（字节级精确隔离） |
| `Fig_S4_5_1_NMR.png` | `si_s4` | `833ffa4112c8dfaf34ca4382756ecbffc3d6ee06158d4ba45da7a0ccd25873ee` | `833ffa4112c8dfaf34ca4382756ecbffc3d6ee06158d4ba45da7a0ccd25873ee` | **不变** | 符合预期（字节级精确隔离） |
| `Fig2_NMR_Combined_2x2.png` | `combined_2x2` | `e718ef44916b1cd03b29600e7dd0d1d344907f13bb140bfee17b4182932fa85c` | `e718ef44916b1cd03b29600e7dd0d1d344907f13bb140bfee17b4182932fa85c` | **不变** | 符合预期（字节级精确隔离） |

## 4. 本实验证明了什么、没证明什么

### 本实验证明了：
1. **多 Scope 隔离机制切实有效**：`shifts_mm` 配置按 scope (`si_s2`) 作用于对应绘图单元时，只对该 scope 下绑定的图元及最终渲染出的 `Fig_S2_3_2_NMR.png` 产生位移和字节改变。
2. **无关 Scope 零副作用**：同批次运行的其余 3 张独立附录谱图 (`si_s1`, `si_s3`, `si_s4`) 以及 2x2 复合总图 (`combined_2x2`)，在字节级（SHA-256）完全不受配置调整影响。

### 本实验没有证明：
1. **未覆盖全参数空间**：本实验仅测试了 `shifts_mm` 在子图 scope 间的隔离，未穷举测试全局标量参数（如字体、画布大小等）在 scope 间混用时的行为。
2. **矢量格式时间戳漂移**：未证明 PDF/SVG 的字节一致性——Matplotlib 在写出 PDF/SVG 矢量格式时默认会嵌入实时时间戳（CreationDate / dc:date）以及动态裁剪路径 ID，导致矢量文件即使无任何视觉差异也会在每次运行时产生时间戳层面的字节变动。本实验通过栅格位图（PNG，像素位图数据流稳定确定）提供了确定性的字节级隔离比对。
