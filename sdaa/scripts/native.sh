#!/usr/bin/env bash
set -euo pipefail
SOURCE=$(cd "$(dirname "$0")/../.." && pwd)
ROOT=${DEEPDEGRADOME_PROJECT:-$(cd "$SOURCE/.." && pwd)}
MODE=${1:?preflight, generate, evaluate, fragment, refine, prepare-protein, prepare-ligand, or evaluator-benchmark}
OUT=$(realpath -m "${2:?fresh output directory under repro/outputs}")
case "$OUT" in "$ROOT"/outputs/*) ;; *) echo 'Output must resolve under repro/outputs' >&2; exit 2;; esac
test ! -e "$OUT"
IMAGE=${DEEPDEGRADOME_NATIVE_IMAGE:-sha256:e7492c8146dd2012199b4e99d8c27ed0c03fea934feeef6f1c1caa45c1aca4f3}
CONV_FP32=${TORCH_SDAA_CONV_USE_FP32:-0}
case "$CONV_FP32" in 0|1) ;; *) echo 'TORCH_SDAA_CONV_USE_FP32 must be 0 or 1' >&2; exit 2;; esac
IMAGE_ID=$(docker image inspect "$IMAGE" --format '{{.Id}}')
MOUNTS=(-v "$SOURCE:/source:ro" -v "$OUT:/out")
DEVICES=()
case "$MODE" in
 preflight)
  SCOPE=${3:-all}
  ARGS=(/source/sdaa/scripts/preflight_native.py --scope "$SCOPE" --output /out/preflight.json)
  if [[ "$SCOPE" != cpu ]]; then DEVICES+=(--device=/dev/tcaicard0); fi;;
 generate)
  TASK=${3:?linker, pharmacophore, or scaffold}
  CONFIG=$(realpath "${4:?task config; input files must use /inputs paths}")
  MOUNTS+=(-v "$(dirname "$CONFIG"):/inputs:ro")
  ARGS=(/source/sdaa/scripts/native_pipeline.py generate --task "$TASK" --config "/inputs/$(basename "$CONFIG")" --output /out/result --device sdaa)
  DEVICES+=(--device=/dev/tcaicard0);;
 prepare-protein|prepare-ligand)
  INPUT=$(realpath "${3:?input PDB for protein or MOL2 for ligand}")
  test -f "$INPUT"
  MOUNTS+=(-v "$INPUT:/input-file:ro")
  ARGS=(/source/sdaa/scripts/native_pipeline.py "$MODE" --input /input-file --output /out/result);;
 evaluate|fragment|refine)
  INPUT=$(realpath "${3:?input directory}")
  MOUNTS+=(-v "$INPUT:/input:ro")
  ARGS=(/source/sdaa/scripts/native_pipeline.py "$MODE" --input /input --output /out/result)
  if [[ "$MODE" == evaluate ]]; then DEVICES+=(--device=/dev/tcaicard0); ARGS+=(--device sdaa); fi;;
 evaluator-benchmark)
  KIT="$ROOT/migration/DeepDegradome-migration-kit-20261016-02"
  MOUNTS+=(-v "$KIT:/kit:ro")
  ARGS=(/source/sdaa/scripts/benchmarks/benchmark_eval.py --workload /kit/evaluator --output /out/result --device sdaa --model-source /source/DeepPROTACs/model.py --warmup 1 --repeats 5)
  DEVICES+=(--device=/dev/tcaicard0);;
 *) echo 'Unknown native stage' >&2; exit 2;;
esac
mkdir -p "$OUT"
printf '%s\n' "$IMAGE_ID" > "$OUT/image-id.txt"
printf '%s\n' "$CONV_FP32" > "$OUT/conv-use-fp32.txt"
printf '%q ' python3.12 "${ARGS[@]}" > "$OUT/command.sh"
printf '\n' >> "$OUT/command.sh"
trap 'RC=$?; printf "%s\n" "$RC" > "$OUT/exitcode.txt"; exit "$RC"' EXIT
docker run --rm --network none --cpus 4 --memory 16g --name "deepdegradome-native-${MODE}-$(date +%s)-$$" \
 --user "$(id -u):$(id -g)" -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 -e OMP_NUM_THREADS=1 -e OPENBLAS_NUM_THREADS=1 -e MKL_NUM_THREADS=1 -e PATH=/home/py312/bin:/opt/deepdegradome/chimera/bin:/opt/deepdegradome/bin:/opt/deepdegradome/kcombu/bin:/opt/deepdegradome/dock6/bin:/opt/deepdegradome/rosetta/main/source/bin:/home/py312/lib/python3.12/site-packages/openbabel/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin -e TORCH_SDAA_CONV_USE_FP32="$CONV_FP32" "${DEVICES[@]}" "${MOUNTS[@]}" -w /out \
 --entrypoint python3.12 "$IMAGE_ID" "${ARGS[@]}" 2>&1 | tee "$OUT/run.log"
