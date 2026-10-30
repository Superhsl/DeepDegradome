# DeepDegradome 龙芯 SDAA 适配

DEVELOP 生成器和 DeepPROTACs 评价器使用 SDAA；结构准备、分子处理和对接工具使用 CPU。支持原始权重推理、公共 PDB 功能流程，以及固定复合体的单候选 iFitDock 实验。

## 快速开始

前提：loongarch64、Docker 权限、`/dev/tcaicard0`，并已准备 [环境锁](locks/environment.json) 对应的镜像与外部资产。入口不自动下载镜像、权重或授权工具。

在包含 `sdaa/` 的模型源码根目录执行：

~~~bash
unset DEEPDEGRADOME_PROJECT
PROJECT=$(cd .. && pwd)
RUN="$PROJECT/outputs/official-eval-$RANDOM-$RANDOM"

bash sdaa/build.sh --check
bash sdaa/run.sh evaluate "$RUN" "$PROJECT/assets/DeepPROTACs-official-single-test/single_test"

cat "$RUN/exitcode.txt"
cat "$RUN/result/evaluation-report.json"
~~~

该示例使用 DeepPROTACs 官方 `single_test` 输入，从 MOL2／SMILES 构造特征并执行十权重评价。已验证退出码为 0、正类投票为 50.0%。投票比例不是实验降解概率；本示例不包含分子生成和对接。

`--check` 仅核对已有环境，不重新构建。输出目录必须尚不存在；使用新目录重跑。

## 完整功能示例

以下完整示例在已准备的固定验证工作区运行，依赖外部资产和既有目录布局；入口自动启动固定镜像，使用 SDAA 0 卡及 CPU 工具。完整前提、输出文件和其他模式见 [复现教程](LOONG_SDAA_REPRO.md)。

公共 PDB 主链路：

~~~bash
PROJECT=$(cd .. && pwd)
RUN="$PROJECT/outputs/protac-pipeline-$RANDOM-$RANDOM"
python3 sdaa/scripts/final_validation/official.py --target loong --output "$RUN"
cat "$RUN/pipeline-completion.json"
cat "$RUN/end-to-end/pipeline-summary.json"
~~~

固定 WDR5–CRBN 复合体：重新生成并处理一个候选，执行 iFitDock 实验链路：

~~~bash
PROJECT=$(cd .. && pwd)
RUN="$PROJECT/outputs/protac-ifit-$RANDOM-$RANDOM"
python3 sdaa/scripts/final_validation/ifit.py --target loong --output "$RUN"
cat "$RUN/completion.json"
cat "$RUN/postprocess/results/final/postscore-report.json"
~~~

主链路采用有界预算；iFitDock 实验使用固定的准备后特征，不重新搜索蛋白复合体。

## 验证摘要

| 项目 | CUDA／x86 | SDAA／龙芯 |
| --- | ---: | ---: |
| 公共 PDB 主链路生成行数 | 1250 | 1000 |
| 主链路最终保留分子 | 6 | 2 |
| 主链路阶段耗时合计 | 30.966 分钟 | 59.004 分钟 |
| iFitDock 示例新生成行数 | 250 | 250 |
| iFitDock 示例最终保留 | 0 | 0 |
| iFitDock 示例阶段耗时合计 | 11.258 分钟 | 28.719 分钟 |

两条链路均完成功能运行；不同候选及搜索分支的结果不能证明全流程严格等价，也不能直接用于硬件速度比。iFitDock 的无姿态终止和有评分后被筛除分别记录。

DEVELOP 默认 SDAA 卷积路径未通过原固定输入的 `1e-5` 概率误差门槛；强制 FP32 的所测固定状态通过。DeepPROTACs 固定特征对照的分类与投票一致。PatchDock、Cyndi、iFitDock 的核心通过 LATX 执行 x86 程序，尚非原生重编译。

作者配套输入的论文级复现、生物学准确率和训练未在本适配中验收。完整结果、计时口径与适用范围见 [适配报告](SDAA_ADAPTATION.md)。

## 目录

| 路径 | 内容 |
| --- | --- |
| `build.sh`、`run.sh` | 环境检查、构建与分阶段运行入口 |
| `runtime/`、`compat/` | Torch 生成器、Session 接入及化学接口兼容 |
| `build/` | 镜像、CPU 工具和 wheel 的构建配方 |
| `scripts/` | 当前推理、完整示例及精度性能基准所需脚本 |
| `locks/` | 源码、镜像、权重、外部资产与依赖身份 |
| `patches/` | 外部源码补丁及应用说明 |
| `vendor/` | 必要 wheel、辅助库、校验清单和许可 |

外层项目的资产、工具运行包、数据库和输出不随本目录自动提供。wheel 与授权软件的分发范围见 [vendor 说明](vendor/README.md)。

独立历史诊断脚本、旧备用验证入口及未启用的试验补丁不随源码交付。当前完整链路及基准的依赖脚本、固定输入与许可证继续保留。
