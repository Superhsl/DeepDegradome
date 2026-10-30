#!/usr/bin/env bash
set -euo pipefail
SOURCE=$(cd "$(dirname "$0")/../.." && pwd)
ROOT=${DEEPDEGRADOME_PROJECT:-$(cd "$SOURCE/.." && pwd)}
MODE=${1:?evaluator, generator-benchmark, or generate}
OUT=${2:?fresh absolute output directory under repro/outputs}
case "$OUT" in "$ROOT"/outputs/*) ;; *) echo 'Output must be under repro/outputs' >&2; exit 2;; esac
test ! -e "$OUT"
mkdir -p "$OUT"
KIT="$ROOT/migration/DeepDegradome-migration-kit-20261016-02"
IMAGE=${DEEPDEGRADOME_IMAGE:-sha256:e7492c8146dd2012199b4e99d8c27ed0c03fea934feeef6f1c1caa45c1aca4f3}
CONV_FP32=${TORCH_SDAA_CONV_USE_FP32:-0}
case "$CONV_FP32" in 0|1) ;; *) echo 'TORCH_SDAA_CONV_USE_FP32 must be 0 or 1' >&2; exit 2;; esac
IMAGE_ID=$(docker image inspect "$IMAGE" --format '{{.Id}}')
printf '%s\n' "$IMAGE_ID" > "$OUT/image-id.txt"
printf '%s\n' "$CONV_FP32" > "$OUT/conv-use-fp32.txt"
DEVICE=${DEEPDEGRADOME_DEVICE:-sdaa}
DEVICES=()
if [[ "$DEVICE" == sdaa ]]; then DEVICES+=(--device=/dev/tcaicard0); fi
ARGS=()
case "$MODE" in
 evaluator)
  ARGS=(/source/sdaa/scripts/benchmarks/benchmark_eval.py --workload /kit/evaluator --output /out/result --device "$DEVICE" --model-source /source/DeepPROTACs/model.py --warmup 1 --repeats 5);;
 generator-benchmark)
  ARGS=(/source/sdaa/scripts/benchmark_generator.py --workload /kit/generator --output /out/result --device "$DEVICE" --warmup 5 --repeats 5 --iterations 20);;
 generate)
  CONFIG=${3:?absolute generation config path}
  cp -- "$CONFIG" "$OUT/config.json"
  ARGS=(/source/sdaa/scripts/generate.py --config /out/config.json --checkpoint /source/DEVELOP/models/linker_design/pretrained_DEVELOP_model.pickle --device "$DEVICE");;
 *) echo 'Unknown mode' >&2; exit 2;;
esac
printf '%q ' python3.12 "${ARGS[@]}" > "$OUT/command.sh"
printf '\n' >> "$OUT/command.sh"
trap 'RC=$?; printf "%s\n" "$RC" > "$OUT/exitcode.txt"; exit "$RC"' EXIT
docker run --rm --name "deepdegradome-${MODE}-$(date +%s)-$$" --user "$(id -u):$(id -g)" "${DEVICES[@]}" \
 -e HOME=/tmp -e OMP_NUM_THREADS=1 -e OPENBLAS_NUM_THREADS=1 -e MKL_NUM_THREADS=1 -e PYTHONDONTWRITEBYTECODE=1 -e TORCH_SDAA_CONV_USE_FP32="$CONV_FP32" \
 -v "$SOURCE:/source:ro" -v "$KIT:/kit:ro" -v "$OUT:/out" -w /out --entrypoint python3.12 "$IMAGE_ID" "${ARGS[@]}" 2>&1 | tee "$OUT/run.log"
