# 必要依赖与辅助库

## Python wheel

本目录保留 PyMOL 3.1.0 的 loongarch64／Python 3.12 wheel，以及 docopt 0.6.2 的纯 Python wheel。固定运行镜像已包含依赖，常规推理无需重复安装。

在本目录内执行校验：

~~~bash
sha256sum -c SHA256SUMS
~~~

来源、构建身份、架构标签、SHA256 和许可位置见 [third-party-wheels.json](../locks/third-party-wheels.json)、[sources.json](../build/wheels/sources.json) 与 `licenses/`。PyMOL 还需要系统 libGL／libGLEW；安装配方和验证方法见 [复现教程](../LOONG_SDAA_REPRO.md#8-第三方-wheel)。

`build/wheels/install_wheels.py --bundle` 支持显式选择本目录，不能用普通 x86 wheel 替代龙芯构建。wheel 受现有 Git 忽略规则管理，不因文档存在而自动纳入源码发布；二进制交付另行保留校验与许可。

## iFitDock 初始化控制库

`ifit_clock_x86/` 提供辅助 C 源码和已验证的 x86 共享库，供固定复合体实验中的 iFitDock 子进程复放时间种子。

它不是 Python 依赖或龙芯原生库；龙芯通过 LATX 传入。仅作用于 x86 子进程的 `time()`，不改变父进程单调计时或 Torch／SDAA 推理。架构、固定值与哈希见该目录 `manifest.json`。

原对接程序、LATX sysroot、Rosetta／Chimera 源码和数据库不由这些 wheel 或辅助库替代，各自遵循来源许可。
