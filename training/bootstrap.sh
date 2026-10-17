#!/usr/bin/env bash
# Run inside the uploaded repository on the GPU VM. Does not train or download weights.
set -euo pipefail
cd "$(dirname "$0")/.."
nvidia-smi
python3.11 -m venv .venv-training
.venv-training/bin/python -m pip install -r training/requirements.txt
.venv-training/bin/python - <<'PY'
import shutil
import torch
assert torch.cuda.is_available(), 'CUDA is unavailable'
assert torch.cuda.is_bf16_supported(), 'BF16 GPU support is required'
assert shutil.disk_usage('.').free >= 80 * 1024**3, 'Need at least 80 GiB free for weights and checkpoints'
print('Training environment ready. No weights downloaded and no training started.')
PY
