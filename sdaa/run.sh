#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
MODE=${1:-help}
if [[ "$MODE" == help || "$MODE" == --help ]]; then
  echo 'Usage: bash sdaa/run.sh MODE FRESH_OUTPUT [ARGUMENTS]'
  echo 'Modes: preflight, generate, evaluate, fragment, refine, prepare-protein, prepare-ligand,'
  echo '       generator-benchmark, evaluator, benchmark-models, pipeline, cpu-controls, variants'
  exit 0
fi
shift
OUT=${1:?Provide a fresh output directory}; shift
case "$MODE" in
 benchmark-models) exec python3 "$HERE/scripts/paired_neural/run_comparison.py" --target loong --output "$OUT" "$@";;
 pipeline) exec python3 "$HERE/scripts/full_comparison/run_pipeline.py" --target loong --output "$OUT" "$@";;
 cpu-controls) exec python3 "$HERE/scripts/full_comparison/run_cpu_controls.py" --target loong --output "$OUT" "$@";;
 variants) exec python3 "$HERE/scripts/full_comparison/run_variant_checks.py" --output "$OUT" "$@";;
 generator-benchmark|evaluator) exec bash "$HERE/scripts/run_neural.sh" "$MODE" "$OUT" "$@";;
 *) exec bash "$HERE/scripts/native.sh" "$MODE" "$OUT" "$@";;
esac
