# Lumerical 完整器件工作流迁移与本机测试

日期：2026-10-29。源码：`D:/Research/photonic-integrated-circuit-simulation-skill`。
安装：`D:/Apps/Lumerical`。本机原生 API 回报版本：`8.35.4413`。

## 已实现的迁移

同一套器件参数和几何构造器现在可进入 Lumerical FDTD，完成建模、材料赋值与读回、端口模态设置、逐输入端口真实求解、完整复数 S 矩阵提取、诊断、数据导出、电路组合及有预算的优化评估。原有 COMSOL 后端和多物理场代码保留。

支持七类光学几何：straight、crossing、directional-coupler、mmi2x2、ybranch、ring、ring-modulator。环支持单总线和双总线；ring-modulator 目前迁移光学结构，未自动迁移 PN 电荷或电热耦合。

`fdtd-device` 明确区分 `2d-scalar-index-surrogate` 与 `full-wave-3d`，每个物理端口选择一个基模。二维模型保留已有标量近似，并检查端口高阶束缚模截止；三维执行并不自动证明高阶模式可以忽略。旧的五类几何 LSF 导出接口继续可用，其范围与七类完整器件接口不同。

复用既有 Li 硅和 Malitson 熔石英材料公式，导入原生 Sampled data，保留原始采样、材料赋值读回及 `getfdtdindex` 拟合误差。当前材料公式的消光系数为零是明确假设。硅的最大折射率拟合误差为 **0.00404918**，熔石英为 **0.000623887**；均低于本次声明的 0.01，但不能据此宣称精确保留色散或群折射率。熔石英也不是已校准的实际工艺氧化层。

## 数据完整性与复用

每个输入端口都实际激励一次，保存独立原生 `.fsp`、端口原始 S/模展开数组和 E/H 模场。完整矩阵由这些列直接组成，未使用互易性、对称性或功率开方补列。各源之间逐端口比较实际采样轴及未经重新定相或缩放的 E/H 模场。诊断还检查实际源端口/模式读回、输入功率、模功率归一化和非源端口入射量。

`device-export` 验证回执、逐源身份、全部记录文件的大小与 SHA-256，并将导出矩阵与原始 NPZ 逐元素绑定。哈希用于检查记录的一致性，不是外部签名。导出结果另外显示原生诊断状态，转换成功不替代物理检查。

复数 CSV、原始 JSON 字节及端口方向、参考面、时间约定等元数据一起进入既有电路接口。电路数值无源性默认余量仍为 `1e-6`；调用者可显式声明不超过 0.05 的余量，本次直波导级联使用 0.005，且不改变任何 S 元素。这是电路输入的数值接受条件，不是器件无源性的物理证明。

优化复用现有 `OptimizationSpec`、候选生成器、预算/验证预留和 `OptimizationTrial`。固定几何参数映射使用微米；目标值只能从通过诊断且完整性验证的实际矩阵计算。运行中的试验先落盘，失败不混入训练数据，下一次调用从已有历史继续。优化默认只生成计划，`--execute` 才调用求解。

## 首轮本机结果

原始目录：`runs/lumerical-device-workflow-20261029/`。首轮 12 个案例全部完成实际求解，共 35 个输入源列；11 个通过当前诊断。诊断包含明确的 5% 数值预算，并非工艺或论文验收标准。

| 案例 | 端口/源列 | 最大奇异值 | 最大复数互易误差 | 当前诊断 |
|---|---:|---:|---:|---|
| straight，网格 3 | 2 | 1.000359 | 8.03e-6 | 通过 |
| straight，网格 5 | 2 | 1.000252 | 1.05e-3 | 通过 |
| directional-coupler，网格 3 | 4 | 0.969409 | 1.49e-5 | 通过 |
| directional-coupler，网格 5 | 4 | 0.969172 | 7.60e-4 | 通过 |
| crossing | 4 | 1.000478 | 7.49e-6 | 通过 |
| mmi2x2 | 4 | 0.970886 | 1.12e-5 | 通过 |
| ybranch | 3 | 0.993879 | 1.18e-5 | 通过 |
| ring 单总线 | 2 | 1.027000 | 1.32e-5 | 通过 |
| ring 双总线，网格 3 | 4 | 1.055969 | 1.82e-5 | **无源性预算失败** |
| ring-modulator 光学结构 | 2 | 1.027000 | 1.32e-5 | 通过 |
| straight，3D | 2 | 1.000710 | 3.23e-3 | 通过 |
| straight，原生采样材料 | 2 | 1.000725 | 1.85e-3 | 通过 |

粗双总线环的失败数据完整保留，没有归一化修正或放宽阈值。更细网格复测及真实优化试验见下方补充结果。

## 电路与网格比较

真实 straight 网格 3 的数据已导出并组成两个器件的级联，与包含多重反射的独立二端口闭式公式逐元素比较，最大复数误差 **2.4825e-16**。接口左右原生 E/H/index 在三个模场采样频率完全一致，没有额外定相变换。该测试验证数据交换及电路代数；没有独立求解两倍长度器件来证明全波级联等价。

网格 3→5 的最大 `|S|²` 绝对变化为：straight **1.01878e-5**，directional-coupler **0.0211960**。后者约 2.12 个百分点，仍需继续网格收敛。跨运行只比较功率，不宣称复相位或群时延收敛。参考面字符串的浮点舍入差最大约 `6.44e-20 m`，按明确的 `1e-15 m` 舍入容差记录；不对数据做平移或相位补偿。

复现脚本及结果：`runs/lumerical-device-workflow-20261029/verify_circuit.py`、`circuit-verification-final/summary.json`。初次比较因参考面十进制舍入差而拒绝的记录也保留。

## 使用入口

见 [完整操作步骤](../../references/lumerical-device-workflow.md) 和 [能力迁移清单](lumerical-capability-matrix-2026-10.md)。在仓库根目录使用当前源码入口：

```powershell
./scripts/invoke-lumerical.ps1 run examples/lumerical/device-straight.json --output runs/my-straight-001 --install-root D:/Apps/Lumerical --local-license --threads 2 --json
./scripts/invoke-lumerical.ps1 device-export runs/my-straight-001/receipt.json --output device.csv --project-root runs/my-circuit-001 --passivity-tolerance 0.005 --json
./scripts/invoke-lumerical.ps1 optimize-step examples/lumerical/device-optimization.json --output runs/my-opt-step-001 --install-root D:/Apps/Lumerical --local-license --threads 2 --execute --json
```

每次求解使用新的输出目录。临时许可管理器只在本机启动，沿用已有许可文件；完成后仅清理本次创建的进程，不修改许可、Windows 服务或代理设置。

## 补充结果与最终验证

最终共完成 **16 次实际器件求解、51 个输入源列**；15 次通过当前诊断，首轮粗双总线环失败记录保留。所有 16 份回执及其完整原始文件已通过哈希和数据绑定复核。两次临时本地许可管理器均正常清理。

| 双总线环补充测试 | 仿真时窗 | 最大奇异值 | 最大复数互易误差 | 当前诊断 |
|---|---:|---:|---:|---|
| 网格 5 | 3 ps | 1.005578 | 1.20e-3 | 通过 |
| 网格 6 | 3 ps | 1.000210 | 6.96e-6 | 通过 |

首轮网格 3 时窗为 1.5 ps，因此粗→细改善不能单独归因于网格。网格 5→6 时窗一致，最大 `|S|²` 变化仍为 **0.0230788**，约 2.31 个百分点；两档网格和当前诊断不足以证明谐振谱、Q 值或群时延已收敛。

两次真实四端口耦合器优化评估均成功，每次分别求解全部四个输入源：gap=**0.2 μm** 时五个频点的平均交叉端口功率为 **0.579260**；gap=**0.249922565 μm** 时为 **0.839729**。目标值已从保存的原始矩阵重新计算并与试验记录核对，最大奇异值约为 0.969409 与 0.967698，均满足示例约束。再次调用读取两条已完成历史后，生成 gap=**0.150340472 μm** 的后续候选计划，未再次求解或消耗该候选预算。这验证了真实评估、记录与续跑链路；两次试验均属于初始化，不能宣称已找到最优值或证明 GP 搜索收益。

完整离线回归：**1639 passed，5 skipped**，48.52 s。跳过原因均为 Windows 符号链接权限，不涉及许可或光学求解。新增工作流审核测试覆盖原始数组/哈希/源身份篡改拒绝、错误单位、失败诊断、预算与历史绑定及默认无执行行为。公共接口快照、skill/UI 元数据、跨代理发现检查均通过。

新模块 Ruff 检查通过。当前本机 Ruff 为 0.12.0，仓库声明版本为 0.16.1；对全仓库检查时旧代码有 49 处 UP038 风格提示，未批量改写无关物理代码。全仓库忽略该单一既有规则后其余检查通过，`git diff --check` 通过。

Wheel 已在源码目录外的独立位置安装并验证：七类器件计划、共享材料与优化接口、无损复数数据交换及电路组合均通过。另通过原有安装包检查，42 个 MCP 资源全部可读，13 个工具完整，COMSOL/PN 准备与校验接口仍可用。安装后测试没有启动求解器，实际求解证据来自上方独立的原生测试。

机器可读结果：[lumerical-device-2026-10-29-results.json](lumerical-device-2026-10-29-results.json)。可在仓库根目录设置 `PYTHONPATH=src`，运行以下无求解复核：

```powershell
python -B scripts/verify_lumerical_device_evidence.py --runs runs/lumerical-device-workflow-20261029 --output runs/lumerical-device-workflow-20261029/reverified-results.json
```

完整本机求解驱动分别保存在该目录的 `campaign.py` 和 `finish_native_validation.py`；重复执行前须使用新的输出路径。源码包包含可复用 CLI、参数示例及验证脚本，不分发 Ansys 二进制、许可文件或本机原生场数据。

## 尚需独立实现或验收的范围

MODE FDE 和 FDTD 原生执行已有本机证据。EME、varFDTD、CHARGE/HEAT、INTERCONNECT 原生运行、COMSOL 伴随/MMA 梯度迁移、多物理场 PN 环闭环、任意多模矩阵及跨求解器全面等价仍不能从本次测试推导。已有 COMSOL 功能继续可用；迁移可复用的经验与工具，并不意味着商业求解器的不同物理模型可以无条件互换。

当前测试不能替代完整 PML/时窗/材料拟合/模态截断误差预算、宽带相位与群时延收敛、真实工艺损耗、温漂/制程角落及实验校准。

## 官方接口依据

- [FDTD ports 与原生 S 结果](https://optics.ansys.com/hc/en-us/articles/360034382554-Ports-FDTD-Simulation-Object)
- [模式展开的幅度、方向与功率归一化](https://optics.ansys.com/hc/en-us/articles/360034902433-Using-and-understanding-Mode-Expansion-Monitors)
- [getfdtdindex 拟合材料检查](https://optics.ansys.com/hc/en-us/articles/360034409694-getfdtdindex-Script-command)
- [Python API 脚本命令接口](https://optics.ansys.com/hc/en-us/articles/360041579954-Script-Commands-as-Methods-Python-API)

文档核对日期为 2026-10-29；原生执行证据以本次保存的回执和数组为准。
