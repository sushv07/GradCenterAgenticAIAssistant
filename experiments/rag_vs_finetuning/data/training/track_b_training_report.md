# Track B — Official LoRA Training Report (MLX)

## Training summary

- iterations: 200 | effective batch: 2 | wall-clock: 771 s (~12.9 min)
- trainable params: 23.069M (0.303%) | optimizer: adamw | peak mem: 6.103 GB
- final train loss: 3.140 | **best val loss: 1.018 (iter 40)**

## Learning curves (val loss by iter)

- iter 1: val 3.228
- iter 20: val 1.463
- iter 40: val 1.018
- iter 60: val 3.854
- iter 80: val 6.549
- iter 100: val 6.412
- iter 120: val 5.875
- iter 140: val 5.715
- iter 160: val 5.493
- iter 180: val 5.211
- iter 200: val 5.338

## Model selection

Selected **iter 40** (val loss 1.018) — the lowest validation loss. Loss diverged after iter 40 (overfitting at LR 1e-4), so the final iter-200 checkpoint (val 5.338) was NOT selected.

## Final model

- adapter: `artifacts/adapters/track_b_selected/adapters.safetensors` (git-ignored)
- adapter checksum: `sha256:a2a09086…` | config checksum: `sha256:db521b96…`
- mlx 0.29.3 | mlx-lm 0.29.1 | Qwen2.5-7B-Instruct-4bit

## Limitations

- LR 1e-4 caused rapid overfitting/instability on 121 training examples: validation loss minimized at iter 40 then diverged; checkpoint selection (iter 40) is the mitigation.
- Single official run by design; hyperparameters were not tuned against the validation curve beyond mandated best-checkpoint selection.
- MLX greedy generation is deterministic within a fixed MLX version/hardware but not guaranteed bit-identical across versions.
