#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
BASE=sha256:3e425da47a74a03b589f8e1c18a67dcb90c8bcbde977cc1df09fa01209b7a524
RUNTIME=sha256:e7492c8146dd2012199b4e99d8c27ed0c03fea934feeef6f1c1caa45c1aca4f3
MODE=${1:---check}
if [[ "$MODE" == --help ]]; then echo 'build.sh --check | --model | --native BUILD_NATIVE_ARGUMENTS | --chimera-deterministic --output FRESH_DIRECTORY'; exit 0; fi
test "$(uname -m)" = loongarch64
test "$(docker image inspect "$BASE" --format '{{.Id}}')" = "$BASE"
case "$MODE" in
 --check)
  test "$(docker image inspect "$RUNTIME" --format '{{.Id}}')" = "$RUNTIME"
  docker run --rm --network none --user "$(id -u):$(id -g)"     -e HOME=/tmp -e PYTHONDONTWRITEBYTECODE=1 --entrypoint python3.12 "$RUNTIME"     -c 'import platform,torch,importlib.metadata as m; assert platform.machine()=="loongarch64"; assert torch.__version__.startswith("2.12"); print("Python",platform.python_version(),"torch",torch.__version__,"torch-sdaa",m.version("torch-sdaa"))';;
 --model)
  docker build --pull=false -f "$HERE/build/Dockerfile.models" -t deepdegradome-sdaa:model-local "$HERE/build";;
 --chimera-deterministic) shift; exec python3 "$HERE/build/chimera/build_deterministic_runtime.py" "$@";;
 --native) shift; exec python3 "$HERE/build/build_native.py" "$@";;
 *) echo 'Unknown build mode' >&2; exit 2;;
esac
