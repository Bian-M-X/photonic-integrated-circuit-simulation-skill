# Lumerical 扩展与本机验证（2026-10-29）

现有 skill 已加入 Lumerical 原生调用、几何复用和复数 S 数据交换。
本机 MODE/FDTD 真实求解、耦合器 CAD 读回，以及离线回归均已通过。
使用的是本机现有许可证，无需外网。没有修改许可证文件、系统环境、服务配置或代理。

## 已实现的范围

- 原生接口识别安装父目录、版本目录和产品目录，提供 MODE 矩形波导 FDE、FDTD 均匀介质传播和器件 CAD 读回诊断。
- 复用原有几何生成器，支持直波导、交叉、定向耦合器、2×2 MMI 和 Y 分支；保留原几何、端口顺序、中心线和面积，输出 SI 单位 JSON 与 LSF。
- 完整复数 S 数据接入既有电路 CSV，保留端口、模式、方向、参考面、相位约定和源文件字节副本。光谱和矩阵同步排序；时间约定转换仅在显式请求时进行。
- 隐藏独立会话、线程预算、总超时和仅针对本次进程树的清理；保留原始数组、原生模型、版本、日志及 SHA-256。
- `--local-license` 临时调用现有 localhost 许可管理器，或复用已运行的本机服务；仅向工作进程指定地址，退出时仅清理自己创建的许可进程。
- 更新 skill 路由、示例、MCP 参考资源及打包镜像。COMSOL 路径继续保留。

## 实际结果

本机安装为 `D:/Apps/Lumerical/v261/Lumerical`（2026R1，build 4413）。
测试用常数折射率芯层 3.476、包层 1.444；这是声明的测试模型，不是工艺材料标定。

| 检查 | 结果 | 适用边界 |
|---|---|---|
| MODE 矩形波导 | 1550 nm，500×220 nm 截面；主模有效折射率在 100/160 单元网格下分别为 2.443126765、2.442924702；差值约 −2.02×10⁻⁴。材料、几何和有限场检查均通过。 | 同一高 TE 分支、单波长、两档网格；不能代替完整模式/窗口/PML 收敛。 |
| FDTD 均匀介质 | 1500–1600 nm、5 个频率点；网格精度 3/5 时最大相位误差为 0.0738237/0.0288942 rad；幅值误差为 2.65×10⁻⁴/1.65×10⁻⁴。 | 均匀介质、周期横向边界，尚无波导端口或完整器件 S 矩阵。 |
| FDTD 功率 | 两档网格的最大功率误差为 7.25×10⁻⁷、1.72×10⁻⁶，均通过既定 5% 诊断阈值。 | 功率误差并未单调改善，两个观测均保留；不宣称严格收敛。 |
| 迁移几何读回 | 在真实 FDTD CAD 会话中重建原有定向耦合器的上下两条多边形波导；顶点、厚度、材料名称及折射率读回一致，并保存 `.fsp`。 | 几何/材料赋值证据，不是耦合器场或性能证据。 |
| 全量离线回归 | **1560 通过、5 跳过**，其中 Lumerical 测试 82 项；跳过均因 Windows 符号链接权限。 | 不把 mock 或合成数据当作原生场求解。 |
| 安装后迁移 | 五类几何导出、完整复数 S 导入和双器件级联通过，与独立复数乘积吻合；原有安装包检查通过。 | S 示例为明确标注的合成非互易数据。 |

原生模型、原始数组、版本和日志位于 `runs/lumerical-local-license-20261029/`。
其中 `mode-waveguide/`、`mode160/` 保存 `.lms` 与场数组，
`fdtd-sampled-plane/`、`fdtd5/` 保存 `.fsp`、复数监测场及相位基准，
`geometry-readback/` 保存耦合器 CAD 与读回记录。
结构化结果与每份 receipt 的 SHA-256 见 [验证数据](lumerical-native-2026-10-29-results.json)。
全量日志和 JUnit 分别为该 runs 目录内的 `pytest-final.log`、`pytest-final.xml`。

## 保留的失败与修正

最初未指定本机许可地址时，MODE/FDTD 在 `appOpen` 返回空服务器地址错误。
随后查明：许可证指向 `localhost:1055`，Windows 许可服务停止，用户配置缺少地址。
当前进程没有启动该 Windows 服务的权限，但现有 `lmgrd.exe` 的临时本机应用模式可正常取得许可。
因此错误不能解释为必须连接外网或缺少许可证。后续使用现有本地许可成功完成求解。
临时进程已退出，原服务配置未改动。

第一轮 FDTD 实际求解完成，但用请求的 CAD 监测位置计算相位时误差为 0.38746 rad，未通过原定 0.15 rad 阈值。
监测面会吸附到网格，实际两面的间距比请求值多约 51.85 nm。
改用 E 数据集导出的实际 `x` 坐标后，相位误差为 0.07382 rad；细网格进一步降至 0.02889 rad。
修正不改变阈值，也没有拟合相位补偿；原请求面、实际面及两种相位误差均保留。
原失败记录位于 `fdtd-uniform/`，更早的启动失败保存在 `runs/lumerical-validation-20261029/`。

## 直接使用

在仓库根目录运行。脚本使用当前源码，不依赖全局旧版 `photonic`：

```powershell
.\scripts\invoke-lumerical.ps1 discover --install-root D:\Apps\Lumerical --json
.\scripts\invoke-lumerical.ps1 run examples\lumerical\mode-waveguide.json --output runs\mode-local-001 --install-root D:\Apps\Lumerical --local-license --threads 2 --json
.\scripts\invoke-lumerical.ps1 run examples\lumerical\fdtd-uniform.json --output runs\fdtd-local-001 --install-root D:\Apps\Lumerical --local-license --threads 2 --json
.\scripts\invoke-lumerical.ps1 run examples\lumerical\geometry-readback.json --output runs\cad-local-001 --install-root D:\Apps\Lumerical --local-license --threads 2 --json
```

输出目录必须是新路径。已有本机许可服务也可以用 `--license-server 1055@localhost`；
该选项仅设置本次子进程环境，与 `--local-license` 互斥。
`discover` 和 `plan` 不启动许可会话。细网格可在请求中分别设 `mesh_cells: 160`、`mesh_accuracy: 5`。

完整迁移说明见 [Lumerical 工作流](../../references/lumerical-workflows.md)。
现有 `.mph`/Java 物理场、网格、端口及研究不会自动转换为等价 Lumerical 模型。
二维标量几何外延为有限高度也会改变模型层级。环/PN 几何迁移、EME、DEVICE、INTERCONNECT、
真实器件完整 S 参数和跨求解器场等价性仍需独立实现或验证。未自动通过任何器件 G/M 验收门。
