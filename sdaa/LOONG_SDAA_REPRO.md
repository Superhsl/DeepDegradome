# DeepDegradome 龙芯 SDAA 复现教程

本教程面向已取得适配源码、固定镜像及必要资产的龙芯环境。首先运行官方评价输入，再按需要执行公共 PDB 主链路或固定复合体实验。它不是在任意全新系统上自动下载全部工具的安装器。

快速入口见 [README](README.md)，验证结果见 [SDAA_ADAPTATION.md](SDAA_ADAPTATION.md)。

## 1. 工作区与前提

从包含 `DEVELOP/`、`DeepPROTACs/`、`sdaa/` 的模型源码根目录开始。外层项目保存数据、工具和输出：

~~~text
project/
├── DeepDegradome/        # 已适配的模型源码
│   └── sdaa/
├── assets/               # 官方输入及构建源码缓存
├── migration/            # 固定神经对照工作负载
├── native/               # CPU 与 LATX 运行资产
├── runs/                 # 公共 PDB 准备输入
└── outputs/              # 新运行结果
~~~

必要条件：

- loongarch64、Docker 权限、宿主 Python 3、`/dev/tcaicard0`。
- [环境锁](locks/environment.json) 中的基础镜像及完整运行镜像。
- 上游原始模型权重；不使用空文件或替代权重。
- 最小评价需要 `assets/DeepPROTACs-official-single-test/single_test/`。
- 完整主链路、固定基准及 iFitDock 实验另需对应外部资产，参见 [local-assets.json](locks/local-assets.json)。

模型源码来自 [官方仓库](https://github.com/QiaoyuHu89/DeepDegradome)，基线为 `8b77f9897258064ef1d9a5ac4a42a547fb3eacea`。仅检出未适配的上游提交不能替代包含 `sdaa/` 的完整适配源码。实现补丁按固定基线单独归档；历史工作区快照不随源码交付，见 [补丁说明](patches/README.md)。

完整镜像、授权程序、数据库和运行资产不会随源码自动获取；复制源码目录也不等于复制了这些依赖。现有完整示例实验入口依赖已准备的验证工作区布局，不能据此保证任意新安装目录直接可用。

## 2. 检查环境和资产

在模型源码根目录执行：

~~~bash
unset DEEPDEGRADOME_PROJECT
PROJECT=$(cd .. && pwd)
test "$(uname -m)" = loongarch64
test -c /dev/tcaicard0
/opt/tecoai/bin/teco-smi
bash sdaa/build.sh --check
~~~

`--check` 只核对已存在的固定环境并输出 Python／Torch／torch-sdaa 版本，不安装软件。运行镜像不存在时，应先取得所锁定的镜像，不能只用相同标签代替身份校验。

核对原始权重和官方评价缓存：

~~~bash
python3 - <<'PY'
import hashlib, json
from pathlib import Path
source = Path.cwd()
project = source.parent
weights = json.loads((source/'sdaa/locks/weights.json').read_text())
for rel, expected in weights.items():
    path = source/rel
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, path
official = json.loads((source/'sdaa/locks/official-eval-inputs.json').read_text())
for item in official['files']:
    path = project/item['path']
    assert path.stat().st_size == item['bytes'], path
    assert hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256'], path
print('PASS:', len(weights), 'weights;', len(official['files']), 'cached files')
PY
~~~

共核对 13 个原权重文件和 7 个官方缓存文件。缓存来源是 [DeepPROTACs single_test 固定提交](https://github.com/Fenglei104/DeepPROTACs/tree/dfb62c4d137b7133d5ea4834a2615779630f2a52/single_test)。保留来源仓库的 LICENSE 和使用说明。

## 3. 最小官方评价示例

从 MOL2／SMILES 构造特征，使用 SDAA 执行十权重评价；不运行生成器或对接：

~~~bash
PROJECT=$(cd .. && pwd)
RUN="$PROJECT/outputs/official-eval-$RANDOM-$RANDOM"
bash sdaa/run.sh evaluate "$RUN" "$PROJECT/assets/DeepPROTACs-official-single-test/single_test"

cat "$RUN/exitcode.txt"
cat "$RUN/image-id.txt"
cat "$RUN/result/evaluation-report.json"
stat -c '%u:%g %n' "$RUN/result/evaluation-report.json"
~~~

已验证结果为退出码 0、`device=sdaa`、`ensemble_size=10`、`positive_vote_percent=50.0`。投票比例不是校准后的降解概率或实验准确率。

入口自动启动已有 Docker 镜像，不需要另行激活 Conda。源码／权重／输入只读，输出使用宿主 UID:GID。已有输出目录会被拒绝；重跑使用新目录，不清理其他任务的容器。

## 4. 公共 PDB 主链路

流程为准备 → 全局对接 → Rosetta 精修 → DEVELOP 生成 → 官方后处理 → DeepPROTACs 评价 → 汇总。

在现有完整验证工作区执行：

~~~bash
PROJECT=$(cd .. && pwd)
RUN="$PROJECT/outputs/protac-pipeline-$RANDOM-$RANDOM"
python3 sdaa/scripts/final_validation/official.py --target loong --output "$RUN"

cat "$RUN/pipeline-completion.json"
cat "$RUN/end-to-end/pipeline-summary.json"
~~~

该入口已完整执行；使用固定完整运行镜像、SDAA 0 卡和 CPU 工具。预算为 10 个全局姿态、20 次 Rosetta 尝试、4 个精修工作进程、每个可用 linker 长度采样 50 个，每个可用姿态的前 20 行原始生成结果进入后处理。

阶段数量、接受结果和实际候选以报告为准，不保证固定保留数。主要产物：

- `pipeline-protocol.json`：输入、源码和参数身份。
- `end-to-end/*-launcher.json`：阶段退出码及耗时。
- `end-to-end/*-command.json`、日志与逐阶段报告。
- `end-to-end/case/WDR5_CRBN_PROTACs.sdf`：最终结构。

标准 `bash sdaa/run.sh pipeline "$RUN"` 也提供该主流程的分阶段入口。失败现场保留；仅对符合入口校验条件的已有目录使用 `--resume`，不删除失败标记或修改旧退出码以伪造成功。

## 5. 固定复合体 iFitDock 实验

该示例从同一份固定 WDR5–CRBN 准备后特征重新运行 DEVELOP，再按排序处理一个候选。它不重新搜索蛋白复合体，也不调用 DeepPROTACs。

~~~bash
PROJECT=$(cd .. && pwd)
RUN="$PROJECT/outputs/protac-ifit-$RANDOM-$RANDOM"
python3 sdaa/scripts/final_validation/ifit.py --target loong --output "$RUN"

cat "$RUN/completion.json"
cat "$RUN/generation/generation-report.json"
cat "$RUN/postprocess/completion.json"
cat "$RUN/postprocess/results/final/postscore-report.json"
~~~

需要 `scripts/final_validation/fixed-inputs/`、完整 CPU 工具、LATX 运行资产及 `vendor/ifit_clock_x86/`。入口核对固定输入哈希，并实际重新生成，未直接使用旧生成分子。

生成预算是 7–11 个 linker 原子、每个长度 50 个，共 250 行；后处理一个候选。16 表示受约束构象初始化尝试数，MMFF 最多优化 1000 次迭代，不是固定接受 16 个或精修 16 轮。

后处理调用 RDKit／MMFF94、Open Babel、Chimera／AmberTools、DOCK6 和 iFitDock。iFitDock 使用 500 种群、500 代，受体固定；配体仍可移动。最终检查片段 RMSD≤1 Å、最短蛋白重原子距离≥1.5 Å 和 `deltaG≤-10`。该评分阈值属于实验协议，局部应变能未设硬筛选阈值。

有评分姿态时保留完整 SA 邻域支持后复算并检查实际输出；无姿态只在工具有明确正常终止证据时作为淘汰结果。段错误、超时或来源不明的空评分表仍视为失败。

`functional_postprocess_completed=true` 不等于有数值评分；同时查看 `numeric_evaluation_available`、`scored_poses`、`retained_poses`。最终 `retained.sdf` 允许为空，这不是实验活性结论。

## 6. 精度模式和分阶段入口

全链路实验固定使用默认 SDAA 卷积路径。分阶段 `generate`、`generator-benchmark` 等入口支持通过 `TORCH_SDAA_CONV_USE_FP32` 选择路径：

- `0`：默认卷积路径，不等于整个模型使用 FP16。
- `1`：强制 FP32 卷积诊断路径；不自动统一不同框架的采样随机流。

输入和权重为 FP32，不独立证明所有内部算子都按 FP32 运算。固定状态数值门槛、缓存与计时边界见 [适配报告](SDAA_ADAPTATION.md)。

`run.sh` 另支持 `preflight`、`generate`、`fragment`、`refine`、`prepare-protein`、`prepare-ligand`、`benchmark-models`、`cpu-controls`、`variants`。先查看实际入口：

~~~bash
bash sdaa/run.sh --help
python3 sdaa/scripts/final_validation/official.py --help
python3 sdaa/scripts/final_validation/ifit.py --help
~~~

CPU 预检不占卡：

~~~bash
PROJECT=$(cd .. && pwd)
RUN="$PROJECT/outputs/cpu-preflight-$RANDOM-$RANDOM"
bash sdaa/run.sh preflight "$RUN" cpu
cat "$RUN/preflight.json"
~~~

固定输入基准依赖外部冻结工作负载和对应参考，不把完整采样流程的候选数量当作概率或 logit 精度。重跑基准会实际占用设备：

~~~bash
PROJECT=$(cd .. && pwd)
RUN="$PROJECT/outputs/neural-benchmark-$RANDOM-$RANDOM"
bash sdaa/run.sh benchmark-models "$RUN"
cat "$RUN/run-summary.json"
~~~

基准中的默认生成路径允许“已完成计时但原数值门槛未通过”；总入口退出 0 不代表全部数值门槛通过，应阅读汇总中的逐项结论。CUDA 配对需要对应机器的固定镜像和相同工作负载，不能在龙芯上执行 CUDA 分支来代替参考。

## 7. 构建入口及边界

| 入口 | 用途与限制 |
| --- | --- |
| `bash sdaa/build.sh --check` | 核对已有固定环境，不重新构建 |
| `bash sdaa/build.sh --model` | 从固定基础镜像构建轻量模型封装；不包含完整 CPU 工具 |
| `build.sh --native` | 分阶段构建 CPU 工具，需源码缓存、数据库和编译环境 |
| `build.sh --chimera-deterministic` | 从保留的父运行镜像构建 Chimera 修正层 |

CPU 工具构建见 [build/README.md](build/README.md)，Chimera 见 [build/chimera/README.md](build/chimera/README.md)，LATX 见 [build/latx/README.md](build/latx/README.md)。

这些配方整理自实际构建过程；并未在任意空白系统、当前全部源码布局下重新执行一次从零长构建。新构建镜像须记录身份并独立验收，不能用编译成功替代数值验证。

## 8. 第三方 wheel

完整运行镜像已经包含依赖，不需要为最短推理再次安装。独立 wheel 校验：

~~~bash
(cd sdaa/vendor && sha256sum -c SHA256SUMS)
~~~

若需要验证独立安装，使用已具备 libGL／libGLEW 的固定依赖镜像：

~~~bash
PROJECT=$(cd .. && pwd)
RUN="$PROJECT/outputs/wheel-check-$RANDOM-$RANDOM"
mkdir -p "$RUN"

docker run --rm --network none --user "$(id -u):$(id -g)" \
  -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$PWD:/source:ro" -v "$RUN:/out" \
  --entrypoint python3.12 \
  sha256:73a58dce793e09584ad8184c53995c2fb27a07581c46c1cda6fc67f535b75d34 \
  /source/sdaa/build/wheels/install_wheels.py \
  --bundle /source/sdaa/vendor --venv /out/venv

cat "$RUN/venv/wheel-verification/validation.json"
~~~

验证包含导入、docopt 参数解析及 PyMOL CPU 操作，不只是 import。来源、架构标签、校验和与许可见 [vendor/README.md](vendor/README.md)。wheel 不替代 CPU 可执行程序、LATX、授权工具或数据库。

## 9. 结果判断

- 入口退出码、实际设备、有限数值和有效输出需共同核对。
- 原始工具返回码由入口结合实际输出解释，不能单独将 iFitDock 的返回 1 当作崩溃或成功。
- 公共 PDB 主链路不是作者配套数据的论文级复现；生成 SDF 不证明生物活性。
- 两端不同的候选、构象和搜索分支不能直接进行逐元素误差或公平硬件速度比比较。
- 原始命令、输入身份与运行输出留在外层项目；不把权重、数据库或个人实验记录写进源码说明。
