# Ultra-fast full-care experiment

Branch: `codex/ultra-fast-care`. Opt in with **Full-care controller → Ultra fast live vision**, or send `care_controller: "ultra_fast"` when creating a full-care run. Standard mode remains the default.

Run from this checkout with its normal `.env` and dependencies:

```sh
python3 -m simulator.server --port 8766 --no-recover
```

Keep `http://127.0.0.1:8766/` open for real rendered RGB/depth, then:

```sh
python3 -m scripts.fast_care_benchmark --start
```

This starts ten trees at 16× simulation speed, measures elapsed wall time from reset through terminal outcome, and requires ten verified completions, all five workers, return/reserve/preservation checks and ≤180 seconds to pass. Attaching without `--start` is observational only. Synthetic controller tests do not establish live demo performance.

## What changed

- Five independent assignments start together; routine metered care, measured contact handling and bounded arm motion run in code through the normal physical command guards.
- Vision still identifies pests/root crowns and assesses alignment from actual current images. RGB components provide candidate image points; public gripper geometry filters robot surfaces. No target inventory or simulator weed coordinates enter the controller.
- Pest transitions probe the independent verifier once per geometry revision. A rejected probe goes to vision; it cannot clear a remaining pest.
- Short stage-specific observations and named tools reduce model work. Crusoe falls back after one provider failure to Gateway Gemini 2.5 Flash, with a six-second socket timeout and a 512-token output budget. Gateway reasoning is explicitly disabled for this model. Provider failures remain accounted; physical failures cannot turn into success.
- LiDAR filters instanced geometry once per scan by its exact bounding sphere and the six-metre sensor range, then raycasts the unchanged nearby triangles. A recorded orchard scan fell from 959 ms to 80 ms (12×), with all 169 returns equal within 1e-8 m. See `evaluations/ultra-fast-depth.json`; reproduce with `node scripts/benchmark_depth.mjs <recorded-api-state.json>` containing a pending depth request.
- Browser sensor uploads run independently and do not hold the fleet poll loop. Busy worker locks no longer stall every fleet snapshot. The requested simulation speed is honored instead of silently using 4×.

Gateway reasoning uses the documented `reasoning.enabled` control: https://vercel.com/docs/ai-gateway/sdks-and-apis/openai-chat-completions/reasoning . Model routes are pinned in each saved session. Live responses, rather than API availability alone, determine whether the route works well enough.

## Fire-and-forget telemetry

In this mode, frames, scans, movement samples, heartbeat/checkpoint records and inference accounting are durably queued in `.runtime/outbox/<session>.sqlite` before control proceeds. SQLite uses WAL and `synchronous=FULL`. Local disk persistence is the only evidence barrier on the running control path; a disk failure still stops progress.

Each session has a separate background sender. It uploads artifacts before their checkpoint, preserves FIFO event sequences and immutable batch IDs, renews the original writer lease, and retries uncertain acknowledgements. Network I/O happens outside queue and runtime locks. Closing or replacing a worker does not stop its sender. Startup resumes pending deliveries without resuming robot motion or issuing model calls.

The UI and `/api/state` expose pending operations, sync errors, locally queued sequence and cloud-committed sequence separately. Physical completion and cloud synchronization are different outcomes. Saved artifacts remain readable locally while cloud delivery is pending. The local files are retained after synchronization; there is no automatic disk-retention policy yet.

Cloud restore, continuation and season recovery wait for preexisting local queues to drain. A fleet restore checks that condition once, then allows its own new restore records. Fenced writers and damaged/incomplete outbox files retain their evidence and surface errors. They require reconciliation rather than silently skipping records. Initial session creation, prompt pinning and lease acquisition still contact Supabase before the worker starts.

This uses a local durable outbox rather than pgmq: sending the queue insertion over the same remote network would still put that round trip on the robot's control path. The existing Supabase commit RPC already provides atomic, idempotent replication; no database migration is required.

## Validation and limits

Final verification: 19 JavaScript tests passed; 123 Python tests ran (118 passed, 5 integration tests skipped); syntax checks passed. Specific tests cover nonblocking enqueue under a stalled upload, artifact-before-checkpoint ordering, uncertain cloud acknowledgements, restart replay, fencing, incomplete outboxes, restore guards, model-envelope accounting, independent pest clearance and ordinary physical verification.

Live results are recorded in `docs/evaluations/ultra-fast-*.json`. A report with `passed: false` is a failed demo target, even when several individual trees completed. The remaining risks are visual root localization, malformed provider responses, recovery loops and navigation serialization. A higher RPM allowance cannot repair those failures.

## Measured results (seed 7)

These are successive development runs, not a controlled comparison: provider routing, RGB candidates and the sensor path changed between runs.

| Configuration | Verified trees | Terminal wall time | Calls / failures |
| --- | ---: | ---: | ---: |
| Fast controller, synchronous storage | 3 / 10 | 184.00 s | 58 / 18 |
| Background outbox, earlier vision route | 4 / 10 | 180.66 s | 65 / 29 |
| RGB candidates, before LiDAR optimization | 2 / 10 | 181.39 s | 34 / 5 |
| Final combined experiment | **5 / 10** | **180.93 s** | **73 / 13** |

The final run **failed the three-minute demo target**. All five workers were used; inventory and reserve checks passed. Tree completion, care verification and return checks did not pass. It completed three trees by 75 seconds and five by 140 seconds. Repeated rejected grasp actions blocked W2; remaining extraction work hit the wall-clock cap. The final report is `evaluations/ultra-fast-66c64dfc-d0cf-4bc4-989d-db907cd27be6.json`.

The synchronous-storage run recorded about 37–100 seconds per worker in artifact uploads plus checkpoint commits (overlapping across workers, not additive wall time). The final run progressed with over 160 telemetry operations queued and reached its terminal outcome while uploads were still pending. Cloud delivery is no longer a prerequisite for control progress. Local durable enqueue remains synchronous; this is not a zero-I/O controller.

The final run averaged about 24 inference calls per minute across the fleet, far below the supplied 600 RPM allowance. Increasing RPM alone cannot resolve visual localization failures, provider latency or recovery loops. The next performance experiment should improve root-crown selection and bounded recovery without weakening the independent contact checks.
