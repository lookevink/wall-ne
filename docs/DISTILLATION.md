# Robot telemetry → teacher decisions → Nemotron adapters

This pipeline performs supervised teacher distillation. A larger model chooses what it would have done from the robot's recorded inputs; a smaller model learns those tool calls. Teacher alternatives are **not executed**, and schema-valid alternatives are not evidence of physical success. Simulator evaluation remains necessary before deploying an adapter.

## Capture and evidence

New runtimes default to `capture_training_inputs: true`. Immediately before dispatch, `Runtime` uploads a compressed `policy_input` artifact containing the exact filtered observation, pinned system prompt, tool schema and camera data URLs. It links the artifact and its hash to `inference_requested`, then commits before making the original model call. Upload or commit failures use the existing storage barrier. Existing sessions restored without this configuration keep their saved behavior. No database migration is needed: the existing artifact table accepts the new kind.

The artifact contains policy inputs, never `snapshot()` or a checkpoint. Included telemetry is only what that role actually received. Exact image bytes are retained in the compressed input artifact as well as the existing camera artifacts, trading extra storage for self-contained replay. Credentials are not part of this payload.

The exporter reads Supabase Data/Storage APIs, freezes each session's committed sequence, follows child sessions and verifies artifact bytes and semantic hashes. It archives events separately in SQLite, indexes all committed artifacts and optionally downloads the full 20 Hz `movement` chunks. High-frequency traces and later outcomes remain audit evidence; they never get appended to the teacher's earlier observation. BetterStack is not involved.

Older runs have observation hashes but not complete inputs. They are counted as `legacy_skipped`; the pipeline does not invent historical observations from the latest world state. New live sessions are needed for training examples.

## Local workflow

From the repository root, using the simulator's existing `.env` for Supabase credentials:

```sh
python3 -m scripts.distill export --session SESSION_UUID --include-telemetry
python3 -m scripts.distill status
```

Repeat `--session` for independent runs. Export is idempotent; a later export picks up newly committed events. SQLite lives at `.runtime/distillation/pipeline.sqlite3`. Back it up together with datasets before moving machines. Override it with `--db PATH` **before** the subcommand.

Prepare a text teacher queue without issuing inference:

```sh
python3 -m scripts.distill label \
  --teacher nvidia/NVIDIA-Nemotron-3-Super-120B-A12B
```

When teacher inference is desired, add `--execute --max-calls 20 --cost-cap 2`. It uses `CRUSOE_API_KEY` and `CRUSOE_API_BASE_URL`, with no provider fallback. The cap is based on reported cost for that invocation, so the final call can cross it; an unknown cost stops further calls. A failed or interrupted request is never automatically retried. Inspect its stored result/provider accounting and import the recovered response if available; otherwise leave it excluded. Do not reset an ambiguous request to pending without checking whether it was billed.

Text and camera inputs are queued separately. For image observations, supply a vision-capable larger model and `--modality multimodal`. Selecting a text teacher never silently strips camera inputs. The queue can hold separate annotations from multiple teachers; dataset builds select one teacher explicitly.

Offline results can be imported with:

```sh
python3 -m scripts.distill import-labels --teacher TEACHER_ID --file labels.jsonl
```

Each line uses the captured request ID, the `policy_input_hash` from its source request, and the normalized simulator decision format:

```json
{"input_id":"REQUEST_UUID","result":{"input_hash":"POLICY_INPUT_SHA256","requested_model":"TEACHER_ID","returned_model":"EXACT_RETURNED_MODEL","response_id":"PROVIDER_RESPONSE_ID","cost":null,"decision":{"action":"inspect","arguments":{"zone":"Z1","ownership_version":1},"rationale":"Inspect the assigned zone first."}}}
```

The input payload, exact wire request and source provenance are in the SQLite `inputs` table. Offline labels and paid labels pass the same checks: identity, tool-schema types and ranges, available actions, exact feasible fleet options and current frame IDs. These checks do not validate physics. Only the action and optional short rationale become the assistant target; free-form provider reasoning is not captured as a training target.

Build a new immutable dataset directory:

```sh
python3 -m scripts.distill build \
  --teacher nvidia/NVIDIA-Nemotron-3-Super-120B-A12B \
  --output .runtime/distillation/dataset-v1
```

Outputs:

- `train.jsonl` and `validation.jsonl`: text prompt/completion conversations with tool schemas and structured tool calls.
- `multimodal.jsonl`: complete camera examples, reserved for a future vision training recipe. Never fed to a text model.
- `provenance.jsonl`: request/session/artifact IDs, teacher model and response IDs, hashes, split groups and `physical_validation: not_executed`.
- `manifest.json`: content hashes, counts, split policy and dataset identity.

Parent and continuation edges are resolved before assigning groups; the stable `season_seed` groups changing daily seeds. Every run sharing any session or root scenario seed stays in one split, including related workers, continuation sessions and season days. Missing or cyclic ancestry blocks export rather than guessing a split. Identical prompts across different seeds union their groups before deduplication. This is deliberately conservative; small collections may have an empty validation split. Collect more independent, widely spaced seeds instead of splitting neighboring decisions randomly: overlapping child-seed ranges can connect entire runs. Rebuilding with more evidence can change connected groups; treat each manifest as a separate dataset version. Existing output directories cannot be overwritten.

## Student training

The default recipe targets `nvidia/Llama-3.1-Nemotron-Nano-8B-v1`, the dense Llama-family Nemotron. `--model` allows another compatible model, but this recipe uses `q_proj`/`v_proj` LoRA and refuses remote custom model code. Newer hybrid/Mamba/MoE Nemotron variants need their own tested model-loading and adapter recipe; their small active parameter count does not establish training memory requirements.

No GPU or extra packages are needed for an offline plan. The default model was CPU-checked at immutable revision `54641c1611fcff44fa4865626462445e0a153fc7`. Use that revision, or obtain a new fixed SHA from the chosen student's Hugging Face repository:

```sh
python3 -m training.train \
  --dataset .runtime/distillation/dataset-v1 \
  --revision 54641c1611fcff44fa4865626462445e0a153fc7
```

This verifies every dataset file against the manifest and reports the proposed run. It downloads nothing. Install `training/requirements.txt` in a separate Python 3.11 Linux GPU environment for actual training. The simulator keeps its standard-library-only Python runtime.

`--tokenizer-check` downloads only the pinned tokenizer and validates every text example on CPU. The trainer uses the student's native tool-calling template, rejects missing tool targets and unstable prompt boundaries, tokenizes without duplicate special tokens, and masks prompt tokens out of the loss. Overlong examples fail rather than losing their target through truncation. The real run requires nonempty train/validation splits and a BF16-capable CUDA GPU.

Add `--execute --output .runtime/distillation/adapter-v1` to train when compute is available. The model weights and tokenizer use the same immutable revision. Outputs include the run manifest, per-epoch checkpoints, final adapter/tokenizer and held-out loss. Resume with the same arguments plus `--resume .runtime/distillation/adapter-v1/checkpoint-N`; model, revision, dataset and settings must match. Adapter output directories cannot be reused accidentally.

This implementation has no automatic serving or promotion. Test the adapter against the baseline using frozen orchard seeds, including new held-out seeds. Compare completion, rejected actions, protected-organism damage, resource reserves, latency and cost. Held-out token loss alone cannot authorize deployment, and the existing prompt-promotion mechanism does not validate model adapters.

## Crusoe provisioning when capacity returns

`infra/crusoe` uses the official provider, pinned and locked to 1.1.0. It creates one GPU VM in an explicitly chosen project, zone and existing subnet. It neither searches for capacity nor automatically selects another zone. No startup script runs training.

Infrastructure access uses a configured Crusoe CLI profile (`~/.crusoe/config` or `CRUSOE_PROFILE`). This is separate from the serverless inference API key. Choose a currently available GPU SKU, a CUDA Linux image with Python 3.11 and at least 80 GiB free disk, and a subnet permitting SSH from your address and outbound HTTPS. The example SKU is illustrative, not a capacity assertion.

```sh
cp infra/crusoe/terraform.tfvars.example infra/crusoe/terraform.tfvars
# Fill project_id, location, instance_type, image, subnet_id and public-key path.
terraform -chdir=infra/crusoe init
terraform -chdir=infra/crusoe validate
terraform -chdir=infra/crusoe plan -out=trainer.tfplan
# Creates a billed VM only when explicitly run:
terraform -chdir=infra/crusoe apply trainer.tfplan
terraform -chdir=infra/crusoe output -raw trainer_host
```

Transfer only code and the selected dataset, not the local `.env`, Supabase service key or teacher credentials:

```sh
rsync -az --exclude=.git --exclude=.env --exclude='.env.*' \
  --exclude=.runtime --exclude=node_modules --exclude=.venv-training \
  --exclude=infra/crusoe/.terraform --exclude='*.tfstate*' \
  --exclude='*.tfvars' --exclude='*.tfplan' ./ ubuntu@TRAINER_HOST:wall-ne/
rsync -az .runtime/distillation/dataset-v1/ ubuntu@TRAINER_HOST:wall-ne/dataset-v1/
ssh ubuntu@TRAINER_HOST
cd wall-ne
bash training/bootstrap.sh
.venv-training/bin/python -m training.train --dataset dataset-v1 \
  --revision 54641c1611fcff44fa4865626462445e0a153fc7 --tokenizer-check
# Later, explicitly add --execute to start a training run.
```

`bootstrap.sh` checks GPU and disk availability and installs pinned training dependencies. If the model requires authenticated access, provide `HF_TOKEN` only in the training shell. After training, copy `.runtime/distillation/adapter-v1/` back before destroying the VM. VM-local checkpoints are not a durable backup. Use `terraform -chdir=infra/crusoe destroy` when the VM is no longer needed; provisioning does not include an automatic shutdown schedule.

## Validation and references

Local tests cover capture failure barriers, byte/semantic integrity, committed pagination, legacy exclusions, queue resume and unknown costs, invalid labels, modality isolation, deterministic splits, dataset tampering and completion-loss masks. The CPU tokenizer check exercises the real student template; a GPU fine-tune and physical evaluation remain unrun.

The implementation follows [Crusoe's Terraform provider](https://github.com/crusoecloud/terraform-provider-crusoe), its [compute-instance schema](https://github.com/crusoecloud/terraform-provider-crusoe/blob/main/docs/resources/compute_instance.md), the [NVIDIA Nano 8B model card](https://huggingface.co/nvidia/Llama-3.1-Nemotron-Nano-8B-v1), and [TRL 0.23.1 SFT documentation](https://huggingface.co/docs/trl/v0.23.1/sft_trainer). Training libraries are deliberately pinned rather than assuming compatibility with future releases.
