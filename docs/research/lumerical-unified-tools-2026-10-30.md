# Lumerical 工具统一、配方与双求解器验证

验证日期：2026-10-30。软件版本仍为 0.8.0，以下为 Unreleased 增量。
本轮承接 [器件迁移报告](lumerical-device-workflow-2026-10-29.md)，补齐共享工具入口和可复现的跨求解器测试。

## 交付范围

| 层次 | 本轮完成 | 执行与证据边界 |
|---|---|---|
| CLI | 增加 `inspect-result`、`plan-benchmark`、`compare-solvers`，Lumerical 子命令共 11 个 | 原生执行仍使用显式 `lumerical run`；检查和比较复用同一服务 |
| MCP | 新增 5 个工具，合计 18 工具、43 资源 | 发现、计划、检查、比较、导出，不启动商业求解器 |
| 适配器注册表 | 内置 `LumericalAdapter` 工厂，支持文件发现和固定请求规划 | 通用 `execute` 仍禁用；文件存在不证明许可证或原生运行可用 |
| Recipe | 圆弧路线和 Euler 弯支持 `lumerical-lsf-fragment` | 显式提供高度、折射率和安全实例名；生成几何不等于光学求解 |
| 共享工作流 | 通用工程、器件、电路与优化流程增加 COMSOL/FDTD 分支 | 原生模式、边界、网格和求解步骤分别实现；验收原则共享 |
| 双求解器对照 | 直波导和四端口耦合器匹配几何、材料、采样和实际参考面 | 比较全部声明通道的功率，不拟合跨求解器模态相位 |

新的 MCP 工具为 `discover_lumerical_install`、`plan_lumerical_run`、
`inspect_lumerical_result`、`compare_lumerical_results`、`export_lumerical_result`。
它们调用与 CLI 相同的核心函数，并使用独立的读/写根目录、严格参数与新输出约束。
已在运行的 MCP 客户端需重新连接更新后的服务才能发现新增工具。

适配器要求明确的项目、运行和安装目录；外部安装根须显式加入允许列表。
`RunSpec` 只接受固定请求与线程数，规划限制一个串行工作进程，不创建文件或导入厂商 API。
本轮没有扩大第三方适配器执行 ABI，也没有向 MCP 暴露任意脚本或 shell。

## Recipe 的无损部分与原生验证

六个原有 canonical JSON 结果、三个原有 COMSOL Java 片段与完整返回 payload 均保持兼容。
材料和散射合同继续共享；分段端口的 COMSOL 边界选择语义没有被伪装成 Lumerical 端口对象。
新 LSF 渲染器仅声明支持可忠实转换的两类几何。

圆弧使用原生环扇区和精确直段多边形，角度跨零时拆分等价扇区；Euler 使用原始配方的全部采样边界点，
没有额外平滑或重采样。高度和折射率是渲染时显式选项，不从二维配方中猜测材料堆栈。

隐藏 FDTD CAD 会话完成三个真实案例：圆弧、Euler、跨零角圆弧，共 8 个原生对象。
在 LSF 执行后与保存模型重新打开后，合计 **114 项属性读回通过，最大差异为 0**。
检查包括顶点、坐标、挤出高度、折射率、环半径与扇区角度；没有调用光学求解器。
会话与本次临时许可管理器进程均已清理，原许可、服务与代理配置未修改。

```powershell
photonic recipe render geometry.circular-route --input examples/recipes/circular-route.json --renderer lumerical-lsf-fragment --instance-id route1 --height-um 0.22 --core-index 2.6 --json
```

## 匹配物理问题的对照结果

两个后端共享 0.30 μm 端口宽度、常数折射率 2.6/1.45、二维标量 Ez 问题、端口顺序和五个波长：
1500、1523.8095238、1548.3870968、1573.7704918、1600 nm。
Lumerical 对应原生名称为 fundamental TM mode；该名称不是三维 SOI 偏振分支的等价证明。

在运行前声明所有矩阵元素的最大功率差预算为 **0.03，即 3 个绝对功率百分点**。
直波导比较 20 个元素，耦合器比较 80 个元素，没有补列、插值、相位拟合或矩阵修复。

| 对照配置 | 最大绝对功率差 | 原 0.03 标准 |
|---|---:|---|
| 直波导：COMSOL 0.04/0.14/0.02 μm 网格与 FDTD mesh 5 | 0.0000128528 | 通过 |
| 耦合器：同上初始网格，横向余量 1.2 μm | 0.0520321 | **失败，保留** |
| 耦合器：COMSOL 0.025/0.10/0.01 μm 与 FDTD mesh 6，余量仍 1.2 μm | 0.0474452 | **失败，保留** |
| 耦合器：保持细网格，两后端横向余量同时扩至 4 μm | 0.0225582 | 通过 |

COMSOL 网格三数依次为 core/cladding/port 最大尺寸。
两者开放域实现不同：COMSOL 为有限外边界散射条件，FDTD 为延伸波导及 PML。
扩域测试在细网格仍失败后，按边界敏感性的物理原因单独记录；它改变仿真外域，保持核心器件与采样不变。
阈值始终没有放宽，前两次耦合器失败也没有被删除。

这些结果说明：直波导功率一致性很好；耦合器对外域设置敏感，在已测试扩域配置下达到筛选预算。
一次扩域后的通过不是完整收敛证明，也不足以认定其中一个求解器更准确或更快。
复相位、群时延、Q 值、三维器件及真实工艺仍需独立误差预算和验证。

实际法向参考面的舍入容差为 1e-15 m；COMSOL 横向包围框使用显式 1 pm 容差，
用于处理其读回中出现的单精度边界坐标量化。此容差只作用于几何读回，不改变任何 S 或功率标准。
比较前验证 COMSOL 源码/编译文件/原始控制台及完整源列，也验证 FDTD 回执与原始 NPZ 的绑定。

```powershell
photonic lumerical plan-benchmark directional-coupler --power-tolerance 0.03 --json
photonic lumerical compare-solvers COMSOL_RECEIPT.json FDTD_RECEIPT.json --power-tolerance 0.03 --json
```

## 软件验证与安装

最终完整回归：**1718 passed，6 skipped，37.80 s**。跳过均为 Windows 符号链接权限。
首次调用缺少源码导入路径，未完成测试收集；日志保留，补上当前 `src` 路径后完成上述回归。
CI 指定的 Ruff 0.16.1 全仓检查通过，未忽略规则。公共接口快照、资源镜像、skill/UI 元数据均已更新。
Wheel 已在源码目录外独立安装验证：原有 COMSOL/PN 准备、电路与模板检查通过，
43 个 MCP 资源均可读。通过真实 JSON-RPC stdio 对已保存的四端口原生数据调用全部五个新增工具，
无损导出保留原始 JSON 字节，并实际生成 LSF 配方文件；测试不调用商业求解器。
该安装后协议测试由 `scripts/test_lumerical_mcp_installed.py` 复现。

原始私有运行目录为 `runs/lumerical-reuse-20261029/`，沿用任务开始日命名。
它保留预声明计划、初次/细化/扩域请求、原生模型、日志、回执与负面结果。
公开记录：[lumerical-unified-tools-2026-10-30-results.json](lumerical-unified-tools-2026-10-30-results.json)。
商业软件、许可文件、原生模型和大型场数组不随源代码发布。

## README 与现有能力

中英文 README 按“目的→快速上手→真实图例→能力范围→文档”重排，
参考项目与组织模式记录于 [README 设计说明](../maintenance/readme-design-2026-10-30.md)。
旧版详细内容保留为历史文档，真实光场图显示模型级别及有限时窗边界。

原 COMSOL、PN/Poisson、伴随/MMA 与多物理场代码继续保留。
当前 Lumerical 原生范围仍是已实现和测试的 MODE/FDTD 路线；EME、CHARGE/HEAT、INTERCONNECT、
完整多模与跨求解器相位等价没有因本轮工具统一而自动获得验证。
