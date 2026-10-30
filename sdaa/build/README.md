# CPU 工具构建

构建在独立容器和项目内的新前缀中进行，不向宿主机安装软件。神经网络使用 SDAA；本目录中的分子处理、准备和对接组件使用 CPU。

环境检查与常规推理见 [复现教程](../LOONG_SDAA_REPRO.md)，验证范围见 [适配报告](../SDAA_ADAPTATION.md)。

## 输入与阶段

需要固定基础镜像、编译环境，以及 `assets/` 中由源码清单锁定的归档。Rosetta 另需主源码、子模块、真实 release 元数据和数据库。准备脚本校验哈希，不自动替换版本或下载其他程序。

在模型源码根目录运行。下面是保留的分阶段构建配方，不等同于已在空白系统重新完成整套构建：

~~~bash
PROJECT=$(cd .. && pwd)
PREFIX="$PROJECT/native/rebuild-$RANDOM-$RANDOM"
OUT="$PROJECT/outputs/rebuild-prepare-$RANDOM-$RANDOM"
python3 sdaa/build/build_native.py --stage prepare --native-root "$PREFIX" --output "$OUT"
~~~

后续对同一 `PREFIX` 按 `tools`、`rosetta`、`package`、`runtime` 顺序执行，每阶段使用新的输出目录。查看参数：

~~~bash
python3 sdaa/build/build_native.py --help
~~~

准备阶段要求新前缀不存在。没有编译镜像时，先用 `--stage environment` 配合显式 `--build-image` 创建项目独立编译环境；该阶段需访问系统软件源。其余编译阶段关闭容器网络。

默认 CPU／内存配置及源归档位置以脚本和锁文件为准；`--jobs`、`--memory` 和 `--build-image` 可显式指定。新运行镜像使用独立 tag，不覆盖已验证镜像。

## 构建内容

- PyMOL 和 GLM：在独立前缀构建 Python wheel。
- pkcombu：保留原计算与错误返回，仅修正成功入口的返回状态。
- DOCK6：构建网格及球相关工具，C／Fortran 编译固定浮点收缩设置。
- Rosetta：架构识别、编译器兼容、真实版本元数据及参数生成辅助模块；自动接入近零分类补丁。
- 打包：收集实际依赖和数据库，保留 Babel 插件、数据目录及兼容入口。

Chimera／Amber 构建另见 [独立说明](chimera/README.md)。PatchDock、Cyndi、iFitDock 缺少可用核心源码，现有运行依赖 [LATX](latx/README.md)，不是通过本驱动原生重编译。

## 构建后检查

新镜像必须显式选择并重新检查，示例：

~~~bash
PROJECT=$(cd .. && pwd)
OUT="$PROJECT/outputs/rebuild-preflight-$RANDOM-$RANDOM"
DEEPDEGRADOME_NATIVE_IMAGE=deepdegradome-native:loong-rebuild \
  bash sdaa/run.sh preflight "$OUT" cpu
~~~

预检只证明组件可调用。模型数值、CPU 工具固定输入输出以及完整流程应分别验收；编译成功不代表数值等价。完整运行镜像还需要组合 Chimera 和 LATX 等外部资产，不能把基础 CPU 镜像当作完整交付镜像。
