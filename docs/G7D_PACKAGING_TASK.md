# G7-D 任务书：工程化发布（wheel / 包内资源 / 薄 CLI / README / 许可证）

**基线**：`D:/L/AI/figpact` @ `master`。本文件是 `docs/G7_PLAN.md` §6（阶段 D）的实施规格。
**用户裁定**：开源许可证 = **MIT**。

## 目标文件
- **新建** `LICENSE`（MIT 全文）
- `pyproject.toml`（打包配置：包内资源、许可证元数据；`figpact = "figpact.cli:main"` **保留**）
- `figpact/inspector_server.py`（改为从**包内资源**读静态文件；正式入口与演示资源解耦）
- `figpact/cli.py`（**新增**薄入口，**不改**现有命令语义）
- `README.md`（首屏 + Quickstart）
- 必要时 `MANIFEST.in`；**新建** `tests/test_packaging.py`

## 必须做的事

### 1) LICENSE = MIT
- 全文 MIT；版权行用**仓库既有元数据里的作者名**（读 `pyproject.toml`；若缺失则用 `LLLin000`）。年份用 2026。
- `pyproject.toml` 增加 `license` 元数据与 classifier（若适用），且**不得**破坏现有构建。

### 2) Inspector 静态资源进包
- 现状：依赖源码仓库下的 `tools/inspector` 路径 → **wheel 安装后不存在**。
- 改为用 `importlib.resources`（setuptools 官方建议）读取包内资源；把 `tools/inspector/*`（`inspector.js` / `index.html` / `inspector.css` 等）作为**包数据**随发行版安装。
- **不得**改变前端行为；资源查找失败要给**明确错误**（指出缺了哪个资源、期望位置），不得静默 404。

### 3) 演示资源与正式入口解耦
- 现状：`inspector_server` 依赖 `tools.inspector_demo` 与仓库 `examples` 路径。
- 正式入口**不得**依赖仓库 `examples/`；演示/示例作为可选资源，缺失时不影响正常启动。

### 4) 薄 CLI 入口（唯一推荐入口，另加不替换）
- 新增（例如）：`figpact ui --script my_plot.py [--config my_plot.yaml]`，内部**仍调用现有 `inspector_server`**，**不另写服务**。
- **兼容**：`figpact inspect <gid>`、`figpact agent`、`final-size` 等既有命令**全部保留**，语义不变。
- 无 YAML 的图：继续支持既有 `export_inspector(fig, ...)` 只读入口；**不得**因 `ui` 命令存在就声称任意脚本都能获得完整可编辑状态。
- 源文件执行：**只信任本地脚本**；**不得**在 README 或 CLI 文案里宣称 OS 沙箱安全。

### 5) README 首屏 + Quickstart
- 首屏讲**产品是什么**（两个痛点：细节修改可保存；不同尺寸小图最终规格统一）与**一条 Quickstart**（装 wheel → 起 UI → 选中标注 → 拖动 → 保存）；把历史验收内容留在原文档，**不搬迁 G0–G6b**（只加一处导航指向）。
- 必须写清**当前支持边界**（哪类脚本可编辑、哪类只能只读测量、不支持时的行为），并保留"预览≠验证、写盘≠科学验证"的口径。

### 6) wheel 干净环境安装测试（**发布前必须**）
步骤：`python -m build --wheel` → 新建 venv → 安装该 wheel → **切到完全不含源码 checkout 的目录** → 运行：
- `figpact --help`
- 启动 Inspector 并**实际加载页面**（真浏览器或既有 Playwright 门禁），证明静态资源可用
- 一个合成图示例（`export_inspector` 只读入口）
证明：静态资源、模块导入、独立重建、浏览器页面均正常。
**证据**：wheel 内文件清单（含 inspector 资源）、安装与环境路径、上述三条命令的实际输出。

## 交付证据（缺一不可）
1. `LICENSE` 全文与 `pyproject.toml` 的许可证元数据。
2. wheel 内**包含** `tools/inspector` 资源的清单（`unzip -l` 或等价）。
3. **脱离源码目录**运行的实际输出（`figpact --help`、页面加载、合成图示例）。
4. `tests/test_packaging.py` 的结果 + 既有相关套件（`tests/browser/` 全套）保持绿。
5. 明确写出**未做**的事（例如未改任何命令语义、未宣称沙箱安全、未搬迁历史文档）。

## 禁止
写桩或 mock 掉真实安装；改 `figpact/intents.py`、`figpact/source_writes.py`、`figpact/final_size.py` 的既有语义；改 `examples/*` 的科学内容；git 写操作（父代理统一提交）。


注：前端资源真值现已位于 `figpact/_inspector/`（随包发布、服务端实际加载）；不要再从 `tools/inspector/`（已删除）读取。
