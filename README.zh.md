# 光子集成电路仿真 · Photonic Integrated Circuit Simulation

**建立光子器件模型，调用本地求解器，再把真实复数 S 矩阵用于电路和优化。**

[English](README.md) · [快速开始](#快速开始) · [Lumerical](#原生-lumerical-工作流) · [实际图样](#实际仿真图样) · [文档导航](#文档导航)

[![Python compatibility](https://github.com/Bian-M-X/photonic-integrated-circuit-simulation-skill/actions/workflows/python-compat.yml/badge.svg)](https://github.com/Bian-M-X/photonic-integrated-circuit-simulation-skill/actions/workflows/python-compat.yml)
[![Agent compatibility](https://github.com/Bian-M-X/photonic-integrated-circuit-simulation-skill/actions/workflows/agent-compat.yml/badge.svg)](https://github.com/Bian-M-X/photonic-integrated-circuit-simulation-skill/actions/workflows/agent-compat.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

`photonic-workflow` 包含 Python 运行时、CLI、MCP 服务和 agent skill，
把可复用几何与材料配方、原生 **COMSOL / Ansys Lumerical** 求解、
完整复数 S 参数、电路组合、有预算的优化与可复核证据连接起来。

- **复用已有积累**：共享数值几何、材料公式、数据合同和电路工具。
- **明确后端实现**：分别构建各求解器的原生对象、模态、边界和网格。
- **检查实际证据**：保留每个声明输入的源列、原始数组、模型文件及文件哈希。

当前包版本：**0.8.0 · alpha**。下述双求解器扩展属于 **Unreleased**，详见 [CHANGELOG](CHANGELOG.md)。
核心功能无需商业求解器；原生运行需要另外安装相应产品并具备可用许可。

## 快速开始

需要 **Python 3.11+**。从源码 checkout 安装：

```powershell
git clone https://github.com/Bian-M-X/photonic-integrated-circuit-simulation-skill.git
Set-Location photonic-integrated-circuit-simulation-skill
python -m pip install -e .
photonic --version
```

创建 MZI 示例并组合电路，整个过程不启动求解器：

```powershell
photonic init demo-mzi --device-family mzi --json
photonic check --project-root demo-mzi --json
photonic circuit validate demo-mzi/circuits/assembly.json --json
photonic circuit compose demo-mzi/circuits/assembly.json `
  --output demo-mzi/data/processed/circuit_sparameters.csv `
  --summary demo-mzi/verification/circuit_summary.json --json
photonic status --project-root demo-mzi --json
```

输出包括电路复数 S 矩阵和组合摘要。内置确定性解析数据用于验证运行时，
不代表全波仿真或实物器件验收。重复执行时应使用新的项目、输出目录。

如需使用 agent skill，将 checkout 安装到智能体可发现的 skills 目录，
加载作为[操作路由](SKILL.md)的 `SKILL.md`。skill 名为 `photonic-integrated-circuit-simulation`，
Python 包与命令行名称保持为 `photonic-workflow` 和 `photonic`。

## 原生 Lumerical 工作流

安装运行时附加依赖；该命令不会下载 Ansys 产品或许可：

```powershell
python -m pip install -e ".[lumerical]"
photonic lumerical discover --install-root D:/Path/To/Lumerical --json
photonic lumerical plan examples/lumerical/device-coupler.json `
  --install-root D:/Path/To/Lumerical --json
```

运行声明的四端口光学器件，检查实际源扫描，并导出数据：

```powershell
photonic lumerical run examples/lumerical/device-coupler.json `
  --output runs/coupler-001 --install-root D:/Path/To/Lumerical `
  --local-license --threads 2 --timeout 300 --json
photonic lumerical inspect-result runs/coupler-001/receipt.json --json
photonic lumerical device-export runs/coupler-001/receipt.json `
  --output coupler.csv --project-root runs/circuit-data-001 --json
```

请将安装路径占位符换成实际位置。`--local-license` 在需要时临时使用本机已有的
许可管理器；已配置并运行的服务可不带此选项使用。本地许可不需要外部互联网。
运行器保持许可文件、服务和代理配置不变；许可求解默认串行。

每个声明输入端口都实际激励一次，保存原生 `.fsp`、逐源数组、完整的所选模式 S 矩阵、
模场检查和哈希回执。CSV 导出保留复数值及原始 JSON 字节，
同时携带通道约定和参考面。详见[完整器件工作流](references/lumerical-device-workflow.md)。

示例为 **二维标量折射率替代模型**，不代表已校准的三维 SOI 堆栈。
另有显式三维接口，已实际验证三维直波导控制。几何参数使用 μm，
光学请求中以 `_m` 结尾的长度使用米。

如果已安装的控制台命令版本较旧，可在 checkout 中使用
`./scripts/invoke-lumerical.ps1` 代替 `photonic lumerical`。
通过 `photonic lumerical --help` 查看全部 11 个命令，包括数据导入与同器件网格比较。

## 实际仿真图样

以下图像来自本机 Lumerical 原生 DFT 场监视器，光场由实际求解导出。

| 定向耦合器 · 1548.39 nm | 双总线环 · 1573.77 nm |
|---|---|
| [![定向耦合器原生电场](docs/images/lumerical/coupler_field.png)](docs/images/lumerical/coupler_field.png) | [![双总线环原生电场](docs/images/lumerical/ring_field.png)](docs/images/lumerical/ring_field.png) |

两者均为 **二维标量诊断模型**。颜色按各图自己的最大 `|E|²` 归一化，
不同图的相同颜色不代表相同绝对功率。环形器件在 **3 ps 有限时窗**处停止，
该图尚不能证明共振、Q 值或稳态已收敛。监视器添加在模型副本中，
对应输入的原生 S 源列与原记录完全一致。
详见[器件验证报告](docs/research/lumerical-device-workflow-2026-10-29.md)。

已有 COMSOL 结果继续保留：

- [二维 Hadamard 逆向设计与数值复核器](docs/showcases/hadamard-2d/README.md)。
- [SOI Euler 耦合器场图与 50:50 案例](docs/legacy-readme-zh.md#euler-splitter)。
- [原生无源器件与 PN 基准记录](docs/research/native-library-v08.md)。

## 哪些共享，哪些由求解器实现？

| 层次 | 当前可用能力 | 证据或适用边界 |
|---|---|---|
| 无求解器核心 | 项目合同、解析器件模型、复数 S 电路、审计与来源记录 | 无需商业运行环境 |
| 几何与材料 | 七类光学器件、六个数值 recipe、Li 硅与 Malitson 石英公式 | 原生几何构建和材料拟合分别检查 |
| COMSOL | 原生器件运行/校准、PN-Poisson 控制和已有伴随示例 | 保留各模型、产品自己的证据 |
| Lumerical | MODE/FDTD 诊断、逐源器件矩阵、导出、功率比较与有界候选评估 | 七类光学外形；每个物理端口选择一个模式 |
| Recipe 后端 | 六个配方都输出通用 JSON；COMSOL Java；圆弧/Euler 的 Lumerical LSF | 几何渲染不求解光场 |
| MCP | **18 个工具 / 43 个资源**：发现、计划、配方、结果检查、导出、电路与证据 | 不通过 MCP 执行求解器或任意 shell |
| 跨求解器控制 | 匹配的二维标量直波导/耦合器计划，回执绑定的功率比较 | 不隐式对齐相位，不宣称普遍精度或速度优势 |

原有 COMSOL PN、伴随路径和多物理场建模指导继续保留，尚未转为
Lumerical 原生 CHARGE/HEAT/EME/INTERCONNECT 或伴随执行链。
FDTD 中的 `ring-modulator` 当前构建**光学外形**，不包含电压驱动的 PN 响应。
对应关系见[能力迁移审计](docs/research/lumerical-capability-matrix-2026-10.md)和[双求解器工作流](references/dual-solver-workflows.md)。

## 复用建模配方

发现版本化配方，并将同一份数值几何渲染到 Lumerical：

```powershell
photonic recipe list --json
photonic recipe inspect geometry.symmetric-euler-bend --json
photonic recipe render geometry.symmetric-euler-bend `
  --input examples/recipes/symmetric-euler-bend.json `
  --renderer lumerical-lsf-fragment --instance-id euler-main `
  --height-um 0.22 --core-index 3.476 `
  --output generated/euler-main.lsf --project-root . --json
```

挤出高度与折射率由调用者显式给出。圆弧使用原生解析环扇区，
Euler 弯保留通用结果中的全部边界采样点。片段只提供几何，
包层、PML、模式和器件验收仍由目标模型负责。
材料、端口窗口等配方在原生脚本会改变其含义时保留数值输出。
详见[配方合同、Python API 与渲染器限制](references/modeling-recipes.md)。

## 用 MCP 消费同一份数据

通过明确的读、写根目录启动 stdio 服务：

```powershell
photonic-mcp --read-root D:/Path/To/Project `
  --read-root D:/Path/To/Lumerical --write-root D:/Path/To/Project/runs
```

在 MCP 客户端的 stdio 配置中接入该命令。服务使用同一份包逻辑，
安装后的 wheel 也包含只读参考资源。更新后请重启正在运行的服务，
使工具与资源目录刷新。

| 任务 | MCP 工具 |
|---|---|
| 复用配方 | `list_recipes`、`inspect_recipe`、`render_recipe` |
| 准备 Lumerical 任务 | `discover_lumerical_install`、`plan_lumerical_run` |
| 检查、导出实际结果 | `inspect_lumerical_result`、`compare_lumerical_results`、`export_lumerical_result` |
| 使用完整矩阵 | `validate_circuit`、`compose_circuit`、`validate_contract` |
| 检查项目证据 | `inspect_project`、`gate_status`、`audit_project_artifacts` |

实际许可求解仍通过显式 CLI 执行。兼容命名的 `run_java_batch` 只生成计划，
不运行 COMSOL。结果检查验证文件与记录一致性，不自动提升物理验收等级。
详见 [MCP 配置与接入边界](references/comsol-mcp-evaluation.md)。

## 对照、优化与验证

在查看两端结果前固定共同基准：

```powershell
photonic lumerical plan-benchmark straight --power-tolerance 0.03 --json
photonic lumerical compare-solvers COMSOL_RECEIPT.json LUMERICAL_RECEIPT.json `
  --power-tolerance 0.03 --json
photonic lumerical optimize-step examples/lumerical/device-optimization.json `
  --output runs/coupler-opt-plan-001 --json
```

上面的回执路径为占位符。比较要求几何、材料、通道、模型层级和波长网格匹配。
容差应在求解前声明，未通过的比较保留原结果；功率一致不表示跨求解器相位一致。
优化默认写入计划，`--execute` 才实际评估一个有预算的候选。

已有本机记录包括 **16 次器件评估 / 51 个输入源列**、两次真实候选评估与历史续跑，
以及 **3 个原生 LSF CAD 案例 / 114 项属性检查**。
这些属于限定范围的诊断，不是对所有器件或后端的验收。
最新统一工具测试、两端比较和未解决偏差见
[本轮实现报告](docs/research/lumerical-unified-tools-2026-10-30.md)。

开发环境验证：

```powershell
python -m pip install -e ".[dev,lumerical]"
python -m pytest -q
python -m ruff check src tests scripts
python scripts/test_skill_metadata.py
./scripts/sync-packaged-skill-resources.ps1
```

CI 检查代码、合同、资源镜像、分发包和安装后的行为。
许可求解证据单独记录，详见[维护与兼容性说明](docs/maintenance.md)。

## 文档导航

| 需要做什么 | 从这里开始 |
|---|---|
| 智能体路由与工具选择 | [SKILL.md](SKILL.md) · [工具选择](references/tool-selection.md) |
| 共同工程流程 | [工程工作流](references/engineering-workflow.md) · [双求解器对应](references/dual-solver-workflows.md) |
| Lumerical 运行和器件 | [安装与诊断](references/lumerical-workflows.md) · [完整器件](references/lumerical-device-workflow.md) |
| COMSOL 环境与物理模型 | [环境与运行器](references/environment-and-runner.md) · [端口与波动光学](references/wave-optics-port-models.md) |
| 可复用数值工具 | [建模配方](references/modeling-recipes.md) · [可执行器件模型](references/executable-device-models.md) |
| 电路与量子光子学 | [层次组合](references/hierarchical-device-workflow.md) · [量子知识库](references/quantum-photonic-knowledge-base.md) |
| PN 与逆向设计 | [PN 环模型](references/pn-ring-model.md) · [COMSOL 伴随](references/comsol-adjoint-inverse-design.md) |
| 其他工具集成 | [MATLAB](docs/architecture/matlab-integration.md) · [PDK 模型](docs/architecture/pdk-model.md) · [适配器合同](docs/architecture/adapter-contract.md) |
| 复现、维护与历史 | [维护说明](docs/maintenance.md) · [CHANGELOG](CHANGELOG.md) · [历史 README](docs/legacy-readme-zh.md) |

提交 issue 或贡献时，请给出输入请求、模型层级、预期行为、实际结果和最小复现。
许可文件、凭据、私有 PDK 与专有求解模型应保留在公开贡献之外。

**MIT 许可。** 本独立项目不包含商业求解器或许可文件。
COMSOL、MathWorks 和 Ansys 名称只用于标识可选集成，不表示关联或背书。
详见[来源说明](references/source-notes.md)与[法律说明](references/legal-and-trademark-notes.md)。
