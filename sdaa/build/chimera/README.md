# Chimera／Amber headless 构建

本目录提供 loongarch64 CPU 的无界面构建与运行配方，不映射 SDAA 卡。仅覆盖结构准备、加氢、SQM／Antechamber 电荷计算及其依赖，不构建全部 GUI 或 Amber 分子动力学功能。

Chimera 源模板与 x86 参考版本不同；不能称为相同版本的完整 Chimera。源码归档、各文件哈希及许可应保留，构建所需归档从现有 `assets/` 清单取得，不自动下载替代版本。

## 构建方法

在模型源码根目录，选择尚不存在的构建前缀；每阶段使用新输出目录：

~~~bash
PROJECT=$(cd .. && pwd)
PREFIX="$PROJECT/native/chimera-rebuild-$RANDOM-$RANDOM"
OUT="$PROJECT/outputs/chimera-prepare-$RANDOM-$RANDOM"
python3 sdaa/build/chimera/build_chimera.py --stage prepare \
  --native-root "$PREFIX" --output "$OUT"
~~~

依次执行 `python`、`bootstrap`、`core`、`pil`、`amber`、`install`、`package`、`runtime`。对新前缀也可选择 `all`；合并驱动未重新完成一次空白环境长构建，不将配方整理表述为新的完整重建验收。

先查看参数和锁定镜像：

~~~bash
python3 sdaa/build/chimera/build_chimera.py --help
~~~

没有编译环境时用 `environment` 阶段创建独立镜像，随后显式选择 `--compiler-image`。父运行镜像可通过 `--parent-runtime` 指定；新镜像需要独立验收。

## 兼容与运行

保留的修改包括 LoongArch 架构识别、旧 C++／Fortran 编译兼容、Python 2 依赖头文件及库路径、NumPy 平台识别、PIL 编译选项和无界面模块子集。Python 2 与共享库环境仅由子进程 launcher 设置，不全局覆盖模型的 Python 3.12 环境。

打包检查 ELF 架构并收集真实动态库依赖。所需源码及数据库的使用和再分发遵循各自许可。

## 输入准备修正

`apply_determinism.py` 应用 [chimera-determinism.patch](../../patches/chimera-determinism.patch)，并核对固定源文件哈希。默认完整运行镜像已包含该修正。

只重建修正层时，在已准备的环境中运行：

~~~bash
PROJECT=$(cd .. && pwd)
OUT="$PROJECT/outputs/chimera-layer-$RANDOM-$RANDOM"
bash sdaa/build.sh --chimera-deterministic --output "$OUT"
~~~

该命令从脚本锁定的父运行镜像构建修正层，不从零重编译全部 Chimera／Amber。固定输入验证结果及适用范围见 [SDAA_ADAPTATION.md](../../SDAA_ADAPTATION.md)。
