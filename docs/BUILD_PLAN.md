# Wall-ne — Build Plan

Build a local 3D orchard simulation in which agents coordinate vehicles, perform camera-guided plant treatment, recover from failures and verify completion against measurable requirements.

**Deliverable:** a fleet simulator, a complete-care treatment mode, a procedural orchard with onboard views, and a six-axis manipulation mode with a wrist camera, simulated LiDAR and independent outcome checks. Supabase persists mission sessions, robot telemetry, movement traces and observation artifacts. An orchestrator reviews completed or blocked sessions, proposes versioned prompt adjustments and evaluates them before activation.

## 1. Product scope

The operator's fleet mission is:

> Inspect the orchard, find dry zones, and water the highest-priority areas before sunset. Keep every vehicle above its battery reserve.

Two workers can break down during execution. The team must activate a spare, retrieve disabled vehicles, redistribute unfinished work and evaluate the original mission requirements without lowering them.

The operator's plant-care mission is:

> Inspect the tree and surrounding ground, irrigate the root zone, remove weeds, apply the prescribed fertilizer and remove target pests. Preserve the crop, beneficial insects and protected groundcover. Verify each treatment and return above the battery reserve.

### Weed removal

Generate seeded grass, rosette and thistle plants with varied placement, size, leaves and orientation. Include protected clover and the crop so indiscriminate removal cannot complete the mission. The agent must identify a weed and its removal point from a fresh onboard image; hidden target identities and coordinates are unavailable to it.

Support two removal workflows:

- **Complete-care gripper:** select the fitted gripper and call `remove_weed(u,v,frame_id)`. Project the selected image point onto the ground plane. The simulator checks tool reach, faults and contact. A weed within a 0.19 m horizontal contact radius can be removed; contact with protected groundcover within that radius or the crop exclusion zone of 0.25 m causes damage and blocks successful completion. A miss or jam does not remove anything. After a jam, service the tool; after every attempt, capture a fresh image before targeting again.
- **Articulated extraction:** use wrist-camera images and measured depth to approach the central stem with open jaws. Inspect alignment, close the jaws, confirm actual contact and load, then lift. If the grip slips, reopen, inspect, reposition or adjust force, and retry within the mission budget. Carry the extracted plant to the collection bin and release it. Completion requires both extraction and collection; merely closing the gripper or lifting an empty tool is insufficient.

Keep removal progress durable so retries and restarts cannot regenerate cleared weeds. Verify every required weed against the saved target inventory, preserve protected plants, and require fresh inspection evidence. A no-weed scene can pass only after inspection and independent verification agree that no removal is required.

### Pest removal

Place target caterpillars directly on the lower trunk and include protected ladybirds. The agent inspects the trunk through the onboard camera, distinguishes targets from beneficial insects and selects a visible pest using normalized image coordinates. If the target cannot be resolved, request another observation rather than treating uncertainty as clearance.

Use a fitted mechanical vacuum and `remove_pest(u,v,frame_id)`. Project the image point onto the inspected trunk surface. The simulator checks tool reach, faults and contact using a 0.10 m radius in the trunk's horizontal/vertical plane. Contact with a protected insect damages it and blocks successful completion. A miss or jam leaves the pest present; a jam requires service before another attempt. Capture a fresh image after each removal attempt.

Pest completion requires every required target to be removed, all beneficial insects and crop tissue preserved, and current inspection evidence. Removing one visible pest does not establish that the entire stage is complete. A no-pest outcome also requires inspection and independent verification. Chemical treatment and articulated vacuum-arm control are outside this scope.

### Shared treatment logic

All treatments follow **observe → select an eligible action → execute → measure → verify**. Irrigation uses moisture and flow measurements; fertilizer follows a saved cumulative prescription and delivery ledger. Weed and pest removal use physical contact/removal outcomes and preserved-target checks. A successful command, a model's completion claim or an image alone cannot override failed physical checks. Resource, time and return limits apply throughout.

Use Three.js for rendering, Python for authoritative simulation and agent execution, HTTP polling for browser communication, and Supabase Postgres and private Storage for persistence. Scenario seeds make environmental conditions repeatable. Model responses, latency, token usage and cost must be measured independently on each run.

Implement three executable modes:

| Mode | Entry point | Decision mechanism | Completion scope |
| --- | --- | --- | --- |
| Fleet | `/` | Deterministic demo or separate live Crusoe role calls | Inspect/water orchard, recover workers, return |
| Treatment | `/treatment.html`, `irrigation` or `care` | Actual PNG heuristics or live multimodal tool calls | One plant; water, weed, fertilize, vacuum pests |
| Manipulation | `/treatment.html`, `arm` | Live image/tool decisions; optional labeled baseline/diagnostics | One weed; grasp, extract, collect, verify, return |

Keep fleet watering and articulated treatment as separate workflows within this scope. The fleet's five video feeds are spectator views, not its decision input. Use the articulated arm for the gripper task. Implement complete-care watering, fertilizer and vacuum tools as bounded treatment actions.

## 2. Non-negotiable boundaries

1. Python owns physical state, resource use, task ownership, command acceptance and success checks. The browser renders that state and supplies camera/depth observations.
2. A model chooses a task action. Deterministic navigation and inverse kinematics execute it. No model directly sets success, moisture, battery, removed flags, or protected-entity state.
3. Keep `snapshot()` for rendering separate from `observations()` for policy input. Hidden moisture, target coordinates/classes, injected fault flags and privileged inventories must not leak into model context. Exact grasp coordinates are allowed only in the labeled `known` diagnostic.
4. A completion claim is evaluated against actual evidence. Missing or stale evidence cannot pass. Failures stay in reports; never loosen acceptance checks to obtain model success.
5. Keep partial delivery, removal progress, assignments and resource ledgers durable. A restart must not regenerate removed targets or repeat completed delivery.
6. Live inference never silently falls back to deterministic agents. Missing credentials, unavailable observations, exhausted budgets and repeated invalid calls produce explicit blocked outcomes.
7. Every session pins its contract, scenario, configuration and prompt versions. A reviewer may propose a new prompt, but cannot rewrite past evidence, change a running controller's prompt or weaken physical acceptance rules.
8. Persist action receipts, state changes and their evidence with a shared sequence boundary. If persistence is unavailable, pause execution and expose the storage failure; do not silently continue with an unrecorded mission.
9. All quantities below are simulation parameters, not real agricultural or robot safety recommendations.

## 3. Stack, layout and setup

Runtime requirements: Python 3.9+ using the standard library, Node.js with its built-in test runner, npm, and a browser with WebGL. Record the selected runtime versions in the dependency configuration and validation report.

Pin npm dependencies to `three: 0.180.0` and `@dgreenheck/ez-tree: 1.1.0`; retain `package-lock.json`. Use native ES modules and an import map. Supabase is required for persisted execution; no React, bundler, Python framework or CDN is required. Use standard-library HTTP for the Supabase Data API and Storage API, and SQL functions exposed through RPC for atomic database writes. Commit schema migrations and permission policies alongside the application. Pure simulation tests remain independent of a database; persistence integration tests use a dedicated Supabase test project or local Supabase instance.

```text
simulator/
  engine.py               fleet world, actions, estimates, verifier
  agents.py               labeled deterministic fleet controller
  runtime.py              concurrent role calls, clock, checkpoints
  persistence.py          Supabase RPC, durable session batches, artifact references
  telemetry.py            robot health, progress events and movement recording
  review.py               bounded session review and prompt candidate evaluation
  inference.py            Crusoe/Gateway adapters and strict tool response parsing
  server.py               loopback API, .env loading, local asset serving
  treatment.py            irrigation, PNG decoding, baseline camera policy
  care.py                 four-stage treatment and protected entities
  treatment_runtime.py    image/sensor handshake, live treatment decisions
  arm.py                  six-joint FK/IK, limits, swept trajectory checks
  manipulation.py         gripper/contact/extraction state machine and trials
  lidar.py                bounded ray grid and geometric validation
web/
  index.html, app.js, style.css                 fleet UI
  scene.js, static-geometry.js                  farm presentation
  orchard-trees.js, almond-geometry.js           seeded orchard geometry
  almond-textures.js, rover-views.js             textures, feeds and performance
  treatment.html, treatment.js, treatment.css    treatment UI
  treatment-scene.js, care-garden.js             RGB/depth scene and target meshes
  weed-geometry.js, manipulator.js               procedural weeds and arm/bin meshes
  sessions.js                                  session timeline, movement playback and reviews
scripts/arm_experiments.py                       bounded experiment runner
tests/                                          whole missions and geometry/calibration
supabase/migrations/                            schema, RPC functions, indexes and access policies
.runtime/                                       ignored caches and optional downloaded exports
docs/                                           specifications, evidence and evaluation results
```

Define these commands in `package.json`:

```sh
npm start       # python3 -m simulator.server
npm test        # node --test tests/*.test.mjs && python3 -m unittest discover -s tests -v
npm run check   # node --check every JS module; Python compileall
```

Use `npm install` to create the initial lockfile; use `npm ci` for subsequent installations with the committed lockfile. Put compiler caches in `.runtime/pycache`. Ignore `.env`, `.env.*` except `.env.example`, `.runtime/`, `node_modules/`, `__pycache__/`, `*.pyc`, and `.DS_Store`.

Environment template, with empty credentials:

```dotenv
CRUSOE_API_KEY=
AI_GATEWAY_API_KEY=
SUPABASE_URL=
SUPABASE_SECRET_KEY=
SUPABASE_STORAGE_BUCKET=robot-session-artifacts
```



preference, but be able to use gemini if needed
crusoe_orchestrator_model=nvidia/Nemotron-3-Super-120B-A12B
crusoe_worker_model=nvidia/Nemotron-3-Nano-30B-A3B
crusoe_vision_model=nvidia/Nemotron-3-Nano-Omni-Reasoning-30B-A3B

Accept `AI_GATEWAY_KEY` as an alias. Credentials stay server-side. Never export keys, request authorization headers or raw error response bodies. Bind to `127.0.0.1:8765`; support `--port`. Check local Host/Origin and prevent static-path traversal. This is a local single-user app without remote authentication.

### Persistence and session model

Supabase Postgres is the durable record; the Python runtime owns live physics and validates every mutation. Private Storage holds immutable PNGs, depth scans and compressed movement chunks. The browser calls the local backend, which holds the Supabase secret key and mediates session reads and artifact access. Enable restrictive table policies and private bucket access; never expose the privileged key to the browser. Do not store image data URLs or large trajectory arrays in event rows.

A **session** is one mission attempt, including pauses and crash recovery. Resetting or evaluating another prompt creates a new session. A robot has a stable identity and a per-session record; all actions, observations and movement records belong to both the session and the relevant robot. Fleet, irrigation, care and arm sessions use the same persistence contracts while keeping their physical states separate.

Minimum schema:

| Record | Required contents |
| --- | --- |
| `sessions` | ID, mission kind, original goal and frozen contract/hash, seed, simulation/configuration version, mode/provider/model, pinned prompt-version map, status, start/end times, resume epoch, committed sequence and final verification |
| `robot_sessions` | Session/robot IDs, role, task ownership version, controller prompt version, lifecycle, latest committed health/progress projection and last heartbeat |
| `actions` | Unique session/command ID, robot/task IDs, decision ID, requested arguments, acceptance receipt, start/end revisions, actual result, cancellation/rejection and resource deltas |
| `events` | Session sequence, robot sequence and resume epoch, wall UTC and simulated time, state revision, event type, action/observation links and bounded structured payload |
| `checkpoints` | Session ID, committed sequence/revision, complete authoritative state, receipts, pending actions, resource ledgers and integrity hash |
| `artifacts` | Session/robot/action association, observation ID or movement interval, private object key, content hash, format, frame/units, capture revision, time range and readiness |
| `reviews` | Source session IDs and evidence ranges, detected failure or repeated behavior, concise diagnosis, proposed change, reviewer model/prompt version and resulting candidate ID |
| `prompt_versions` | Role, immutable prompt text/hash, parent version, source review, creation time and draft/candidate/active/retired status |
| `evaluations` | Baseline/candidate versions, frozen scenario set and budgets, child session IDs, unchanged checks, metrics, promotion decision and reason |

Use foreign keys, unique command/event identities and indexes for session/robot/time queries. Events and completed evidence are append-only; latest projections and session status are updated transactionally. Keep privileged checkpoints and target inventories out of agent-facing queries. A review receives permitted observations, action feedback and verifier outcomes, not hidden grasp coordinates or target truth.

Use an RPC transaction to atomically append a batch of events and receipts, update robot projections and save the corresponding checkpoint. Enforce one active runtime writer with a lease/fencing token and compare-and-swap on the committed revision. Retry a batch with the same identity; duplicates return its original result. Persist an accepted command before starting its effects, and persist completion before reporting it as durable. Commit physical progress at least every .5 wall seconds and at action, fault, pause and terminal boundaries. A hard crash may lose at most the uncommitted interval; restore the entire simulation to the same committed boundary, paused, before resuming.

Upload artifacts under immutable content-addressed keys before committing references. Storage uploads and Postgres transactions are separate operations: an interrupted upload must leave an explicit missing/pending artifact, never fabricated evidence. Retry uploads idempotently and clean unreferenced uploads separately. Evidence-dependent actions wait for the required artifact to be durable. A failed persistence batch pauses physical time and new dispatch, retains the pending batch for bounded retry, and displays `storage_blocked`. Local caches are not a second database or a silent persistence fallback.

### Robot telemetry and movement traces

Every robot emits telemetry independently of model decisions, including while idle or waiting on inference. Define a versioned envelope with session/robot ID, resume epoch, monotonic per-robot sequence, wall UTC, monotonic elapsed time, simulated time, state revision, action/task IDs and prompt version. Sequence and revision determine ordering; timestamps alone do not.

| Stream | Contents and cadence |
| --- | --- |
| Health heartbeat | At 1 Hz wall time: lifecycle, battery/reserve, water/fertilizer/tool resources, current task/action, waiting reason, inference age, observed faults and last progress revision |
| Action and progress events | Immediately on acceptance/start/completion/rejection/cancellation, assignment changes, contact, slip, extraction, deposit, delivered dose, jam, recovery and verifier result |
| Movement samples | At each authoritative physical update, up to 20 samples per simulated second, plus action boundaries and contact/fault transitions; record actual timestamps and sampling gaps |
| Observations | Frame/depth IDs, capture revision, camera transform/calibration, permitted sensor readings and immutable artifact references linked to the decision that used them |

For movement, record the base position and orientation, six joint angles where fitted, tool pose, jaw opening, commanded force, measured contact/load, holding state, collision feedback and resources. Declare coordinates and units: world x right/y up/z toward rover, meters, joint degrees, pose quaternion ordering, newtons, liters and simulated grams. Store requested joint/Cartesian targets separately from the sampled actual trajectory and action outcome. A rejected move remains an action record with no executed trajectory. Never fabricate motion between missing samples; playback may interpolate for display, explicitly marked as interpolation.

Batch movement samples into compressed, indexed chunks, at most two simulated seconds each and flushed at every checkpoint and action/pause/failure boundary. Each committed checkpoint must reference durable movement evidence through its committed sequence. The orchestrator reads compact summaries and fetches bounded trace/frame intervals on demand; it does not receive every motion sample in every prompt. Preserve enough evidence to correlate **observation → decision → command → movement → contact or delivery → verification**.

Track health and task progress separately. Default stale-heartbeat threshold is five wall seconds; a model wait with a current heartbeat is not a breakdown. Flag three repeated failed attempts at the same task without new evidence or physical progress as a possible loop. Track action-specific expected duration separately from legitimate idle, paused, sensor-wait and inference-wait states. The orchestrator records its decision to continue, request observation, service, re-plan, reassign, stop or escalate. Deduplicate each incident and rate-limit retries. Existing ownership and battery checks still govern all recovery commands.

### Session review and prompt adjustment

Provide a session list and a read-only timeline with robot/task filters, linked frames, requested versus actual movements, tool feedback, decisions, resource use and the final checklist. Movement playback consumes recorded state samples; it never reissues commands or makes model calls. Mark missing evidence and sampling gaps. A reproducibility export includes the scenario/configuration, prompt hashes and artifact manifest; replay is a visualization of recorded execution, not a claim of deterministic model reproduction.

After terminal success, failure or an explicit paused review boundary, the orchestrator can call `review_session(session_id, robot_id?, interval?)` to inspect bounded evidence. It writes a concise diagnosis and may call `propose_prompt_revision(role, parent_version, change, evidence_ids)`. Store the full candidate text and its diff. For example, repeated slips may justify a feedback-driven grip-force instruction, but a review must distinguish evidence from a hypothesis about the cause. Do not store hidden chain-of-thought or credentials.

Run baseline and candidate prompts as separate sessions on the same frozen scenarios, model, sensor setup, physical rules and call/time/cost caps. For the initial build, permit one candidate per review and one bounded evaluation campaign; no recursive search. Include the reviewed failure scenario as a regression case, plus at least two other placements and one protected-target or recovery case withheld from candidate generation. Freeze the evaluation manifest before testing either version. Default promotion metric: more fully verified missions, with no scenario that passed under the baseline becoming a failure; if completion is tied, require at least 10% fewer commands across successful paired missions without greater reported inference cost. Unknown cost cannot satisfy that efficiency tie-break. Require zero hard-constraint violations in candidate trials and all mandatory regression checks passing. If results are inconclusive, keep the baseline. Persist the complete comparison, including failures and cost, before a promotion decision.

Only the evaluation gate can activate a candidate for future sessions. Existing sessions retain their pinned versions; rollback changes the default for future sessions without altering history. Prompt edits cannot change physics, tools, force limits, verifier code, contracts, trial budgets or evaluation scenarios. This establishes trace-backed prompt improvement; broad autonomous optimization and statistically supported generalization claims require a larger separate evaluation campaign.

## 4. Build sequence and release gates

Work in this dependency order. Each milestone should produce a runnable, reviewable increment. Use complete missions as the primary acceptance boundary; use targeted geometry tests where they establish independent calibration or kinematic invariants.

### M0 — Scaffold and authoritative state (no prerequisites)

Create package files, Python package, server shell, test entry points and local HTML. Define serializable mission/vehicle/zone/task/action/event records and named lifecycle states. Establish stable command IDs, action receipts, monotonically numbered events and explicit terminal states. Keep rendering snapshots out of the policy interface.

**Gate:** server and local assets load; invalid/traversal requests are rejected; an empty mission can be serialized and restored. No external service needed.

### M1 — Fleet simulation and independent verifier (after M0)

Implement `Mission`, `command`, `estimate`, `tick`, `verify`, `checkpoint` and `restore` in `engine.py`.

Default simulation configuration:

| Parameter | Value |
| --- | --- |
| Scenario | Seed 7; 12 rows × 3 zones = 36 zones |
| Zone position | `x=(row-5.5)*3.5`, `z=-9+segment*8` for zero-based indices |
| Initial moisture | Python seeded RNG, integer 12..58 per zone |
| Fleet | W1–W4 active workers; W5 spare initially disabled; R1 retriever |
| Depot positions | `[-7.5+3*i, 21]` for vehicle index 0..5 |
| Water/battery | 70 water units per worker; 100% initial battery |
| Contract | Critical ≤30%; target 65%; reserve strictly >20% |
| Deadlines | Work 1,200 simulated seconds; recovery another 360 seconds |
| Travel | 1.8 m/s; towing 1.3 m/s; cross-row route via service road z=16 |
| Energy | .13 percentage points/m travel; .24 towing; .08/work-second |
| Operations | Inspect 3 s; water 2 units/s and +1 moisture point/unit; attach 4 s |
| Service | At home, 12 s; +8 battery points/s, +7 water units/s, capped at 100/70 |
| Guard | Estimate work plus safe return; reject non-service action when predicted battery ≤reserve+3; physical guard stops before crossing reserve |

Commands: orchestrator `assign(row,vehicle)` and `activate_spare`; workers `inspect`, `water`, `claim_complete`, `return`, `service`; retriever `retrieve`, `return`, `service`. Assignments have versions; reject stale/unowned work. Repeat command ID returns its original receipt without applying effects again. Advance physical actions in bounded .25-second substeps.

Breakdown cancels the current action, preserves delivered water, isolates the disabled vehicle and leaves unfinished work assignable. Retrieval physically travels, attaches, tows and parks the worker. Retrieved workers remain disabled. One retriever recovers two workers sequentially.

Freeze a canonical sorted-JSON contract hash at launch. Numerical verification checks six independent facts: every zone inspected by deadline; every originally critical zone received its required water by deadline; every minimum battery >20%; fleet home/disabled vehicles recovered by recovery deadline; no active actions; original contract hash unchanged. Evaluate criticality from original truth, so omitted observations cannot hide required work.

**Gate:** headless nominal success; two feasible breakdowns across three seeds; false claims rejected; partial watering retained; stale/duplicate commands rejected/idempotent; impossible deadline gives truthful failure/partial completion.

### M2 — Fleet policy, persistence and operational UI (after M1)

Implement a deterministic `DemoController` that assigns rows, prioritizes observed dry work, services vehicles, activates the spare, redistributes unfinished assignments and queues retrieval based on current state. Label it “Rule-based demo”; it makes no model calls.

Implement `Runtime` with a lock, clock multiplier, Supabase session/checkpoint repository, asynchronous inference boundary and committed event snapshots. Apply the schema, atomic-write and recovery rules in section 3. Create a new session on reset; restore interrupted sessions paused with their original receipts, assignments and prompt versions. Retain session history and emit heartbeat, action, progress and base-movement telemetry for every robot. Expose storage health and the latest durable sequence separately from live state.

Build `/` with mission controls, seed/mode/speed, zone/vehicle display, task/resource panels, “Break two workers,” individual breakdowns, labeled false-completion injection, definition-of-done checklist and JSON export. Support fixed multipliers 1/4/8/16; demo defaults to 8×. Fleet simulation continues while live inference is pending, provided persistence remains healthy. Show per-robot heartbeat age, waiting reason, last progress, current action and observed fault; let the orchestrator consume the same structured telemetry through its policy boundary.

**Gate:** browser can complete the same two-breakdown mission; false completion leaves physical water unchanged; restart/resume does not duplicate work; export contains full evidence. Prove atomic rollback and idempotent retry against Supabase, including an outage during partial watering. Out-of-order telemetry cannot regress the latest projection; stale heartbeat and stalled work are distinct from a healthy inference wait. Two saved sessions remain independently readable.

### M3 — Provider adapters and separate fleet roles (after M2)

Implement OpenAI-compatible Chat Completions calls with standard-library HTTP, JSON tool schema, exactly one expected function call, required tool choice, temperature .1 and max output 4096 tokens. Reject malformed JSON, wrong/multiple tool calls and invalid argument objects. Keep inference outside the simulation lock; discard stale replies after mission replacement. Use bounded retry/backoff and visible blocked states.

Configure provider base URLs through environment variables and append `/chat/completions` when making a request. Supply credentials and verify model/tool compatibility before a live run.

| Provider/use | Configuration | Model selection |
| --- | --- | --- |
| Crusoe fleet | `CRUSOE_API_BASE_URL`, `CRUSOE_API_KEY` | Super for contract planner/orchestrator/verifier; Nano for workers/retriever, as specified in the environment template |
| Crusoe treatment | Same provider configuration | Omni, as specified in the environment template |
| Gateway experiments | `AI_GATEWAY_BASE_URL`, `AI_GATEWAY_API_KEY` | `nvidia/nemotron-3.5-super-vl`, `google/gemma-4-31b-it`, `google/gemini-3.1-pro-preview` |

Make model identifiers configurable. Record the exact requested and returned identifiers for each run. A changed model or provider constitutes a separate evaluation condition.

Provider timeout: 25 s Crusoe, 55 s Gateway. Record requested/returned model, response ID, usage and latency. Missing cost is unknown, not zero. BYOK accounting adds separately reported upstream charge to Gateway charge when both are available; this is not billing reconciliation.

Fleet uses separate per-role concurrent requests (seven-worker executor), not a recursively spawned process tree. Context is reconstructed from permitted shared observations, telemetry summaries and recent events. Persist request/decision IDs, the prompt version, input evidence references and the returned tool call or concise rationale; never log authorization headers or hidden chain-of-thought. Pin role prompts when the session starts. Contract planner may choose critical threshold 15..35 and target 55..65 while coverage, reserve, deadlines and return remain fixed. Workers choose validated feasible action options. The verifier model explains evidence and possible corrections; code decides pass/fail.

**Gate:** fake-provider integration proves planning, role calls, retries, stale response handling and immutable constraints. Validate live provider compatibility separately by executing image/tool requests and a fleet mission. Report any configuration or provider failure explicitly; fake-provider tests do not establish live model performance.

### M4 — Procedural orchard and vehicle camera UI (after M2; independent of live inference)

Build the renderer around snapshots. Generate farm structures and vehicles procedurally. Use four seeded almond variants across 144 orchard trees; use EZ-Tree for 22 generic boundary trees. Almond geometry has 3–4 open-vase scaffold limbs, narrow leaves, 45–60 green hulls per variant attached to actual spur endpoints, and procedural bark/leaf/hull textures. Seeded JS geometry uses an LCG (`1664525`, `1013904223`, unsigned 32-bit state). Reuse one skeleton for near/far geometry so attachments remain consistent.

Keep low geometry clear of rover lanes; tree trunk offsets 1.05 m from lane center, lower geometry within .35 m of trunk below 1.75 m. This is visual clearance, not a new collision engine. Use shared/instanced geometry, per-camera culling/detail, distant hull omission, batched static meshes and shared wind shaders. Include dependency licenses and asset attribution with distributed source.

One WebGL renderer serves overview and five worker render targets including spare. Feeds: 640×360, target 15 fps. Overview/expanded view: target 30 fps; expanded 1280×720. Any vehicle, including retriever, can be expanded. Shared shadow map updates at up to 10 Hz. Cap overview pixel ratio at 1.5. Camera pause is separate from mission pause; respect reduced-motion preference; suspend rendering while document hidden. Show frame/feed rates, draw calls and resource counts; label CPU submission timing accurately.

**Gate:** all feeds update; expand/escape works; camera pause freezes pixels without pausing mission; wind toggles; repeated reset stabilizes resources; mobile layout and reduced motion work. Geometry tests verify seeded variation, clearance, spur attachment and reduced distant detail. Measure frame rates on the target device with its actual graphics backend, viewport size and pixel ratio recorded. Treat the specified rates as targets and report measured performance.

### M5 — One-rover irrigation from actual pixels (after M0, M3 provider boundary)

Implement separate `Treatment` state persisted as an irrigation session in Supabase; render `/treatment.html` with overview and onboard camera. Rover follows a deterministic route from z=8 to z=3.8. Camera is 640×360, vertical FOV 58°, height 1.2 m, .4 m forward offset, look vector `(0,-.6,-4)`; ground reference y=.08.

Browser supplies actual RGB(A) PNGs on request. Validate signature, dimensions, CRC, filters and bounded decompression; accept only requested captures under 2 MB. Store each accepted frame in private Storage, with its ID, hash, pose, capture revision, time and dose sequence in Postgres; link it to the requesting decision and subsequent action. A visible blue basin ring is intentional. Offline policy finds blue pixels and projects the centroid onto the calibrated ground plane; it must never read plant coordinates.

Actions: capture image, read moisture, aim nozzle from current frame `(u,v)`, dispense bounded liters, read flow, clear clog, verify treatment, return home, stop. Require correct sensor/image ordering. Start moisture 23%, tank 30 L; max pulse 5 L; effective liter adds 2 moisture points. Bad aim can waste water. A clog gives zero actual delivery; backflush and retry. Retain partial pulse delivery.

Six completion checks: moisture 65..67%, ≥21 effective L plus positive final-dose flow, fresh final-dose moisture reading, before/after images bracketing treatment, minimum battery >20%, verified return. Use numerical tolerance 1e-6, not rounded display values. Standalone budgets: 12 frames, 65 decisions, 300 simulated seconds; block at battery ≤25 as operational allowance.

Unlike fleet mode, treatment pauses simulated time for model/camera/depth waits; physical time advances at up to 4× otherwise. Block after 30 wall seconds without requested camera/depth data. Live treatment uses one outstanding inference request and blocks after three consecutive failures. Require the browser to remain open.

**Gate:** actual browser pixels complete irrigation and recover a clog; headless tests cover bad aim, missing target, stale capture, premature success and restart during partial dosing. Offline success must be labeled offline.

### M6 — Complete plant care with procedural targets (after M5 and geometry helpers)

Implement `PlantCare` as four ordered stages: irrigation → weeds → fertilizer → pests. Tool changes and preconditions are explicit. Freeze required target IDs, protected IDs, prescription and inventory hash. Maximum 64 frames, 240 decisions and 300 simulated seconds.

- **Weeds:** seed zero has none; otherwise `3 + seed % 3`. Sample two patch centers, clustered positions with at least .4 m clearance from each other and protected entities, bounded to the visible work strip. Forms: rosette, grass, thistle; seeded size, leaf count and rotation. Generate actual 3D curved blades/broad leaves, petioles, stems and crown; do not substitute icons. Removal state survives restart. Two clover patches are protected.
- **Fertilizer:** saved target `18 + seed % 5` simulated grams; stock 40 g; pulse ≤5 g and ≤remaining prescribed amount. Read prescription and application meter. Track delivered versus effective amounts. Misses/jams do not count; durable partial delivery must prevent repeat dosing. Leaf color is not the prescription or proof of uptake.
- **Pests:** seed zero has none; otherwise `2 + seed % 2`. Enlarged stylized purple-brown caterpillars sit directly on the lower trunk at heights `.42 + i*.23`; one red spotted ladybird is protected. No separate trunk-sized pest platforms. Pest camera FOV 30°, look-down .45, look-forward 3.28. Image rays target the visible trunk surface. Use mechanical vacuum removal.
- **Faults:** nozzle clog, gripper jam, fertilizer-nozzle jam, vacuum jam. Failed actions produce observed feedback; service and fresh inspection are necessary. Damage to protected entities fails completion.

Offline recognition uses image color components, not entity lists: blue basin; dark-green weeds with pointed forms; purple-brown pests; preserve lighter clover and red ladybirds. This is a deliberately stylized detector, not learned biology. Each relevant action invalidates target images; phase/revision must match. Live mode receives the same rendered image plus permitted measurements, tools and history.

Complete-care verification combines eleven checks: the six irrigation checks from M5; required weeds cleared; prescribed fertilizer effectively delivered with a current meter reading; required pests removed; contract and target/protected inventories unchanged; and crop, groundcover and beneficial insects preserved. Each treatment stage requires inspection evidence before it can be marked complete.

**Gate:** seed 8 browser mission clears five weeds, reaches 65% moisture, delivers 21 g prescribed/effective fertilizer, removes pests, preserves protected entities and passes all 11 checks after return. Seed 0 verifies justified no-removal. Tests cover held-out seeds, all faults, partial fertilizer restart, overdose rejection, false clearance and target-inventory tampering. Evaluate live-model full-care completion separately from the deterministic image-heuristic run.

### M7 — Six-axis manipulation with real action consequences (after M5, M6 weed renderer)

Create a separate `Manipulation` mission; do not replace the simpler complete-care tools. Generate one seeded weed with Python RNG `seed+510`: x uniform(-.55,.5), z uniform(1.15,1.65), form, size .9..1.2, 9..15 leaves and rotation.

Implement forward/inverse kinematics in `arm.py`: upper link 1.45 m, forearm 1.25 m, tool .16 m; limits in degrees `[-180,180],[-175,100],[-165,0],[-180,180],[-90,90],[-180,180]`. World x right, y up, z toward rover. XYZ Euler `(0,0,0)` points the tool down. Base is `(robot.x,.8,robot.z-.5)`; initial tool position `(0,.8,2.2)` at the observation station. Accept six joint angles or Cartesian `(x,y,z,rx,ry,rz)`.

Interpolate in joint space; sample swept trajectories at ≤2° joint increments with ground/trunk checks along links. Motion duration `max(.4,max_joint_delta/45)` seconds. This is kinematics plus explicit contact rules, not rigid-body dynamics. Rendering follows FK points and orientation. Extend session motion recording to all six joints, tool pose, jaw state and contact/load feedback, retaining requested targets and actual motion separately. Flush traces at grasp, slip, extraction, release and interruption boundaries.

| Interaction | Condition |
| --- | --- |
| Jaw opening / force | 0..0.12 m / 0..45 N; both required for set_gripper |
| Stem grip | Horizontal distance <.055 m; y 0.09..0.22 m; vertical tilt <25°; opening ≤.025 m; force ≥8 N |
| Root resistance | Holding load grows with vertical lift; sideways motion >.12 m loses grip |
| Slip | Lift >.08 m with force <26 N |
| Extraction | Vertical lift ≥.18 m while still holding |
| Collection | Bin `(x=.95,y=.48,z=2.5)`, horizontal release distance <.24 m, release y>.48 and <1.3 m |
| Protected groundcover | Closing near protected plants can damage them; damage cannot pass verification |

A strong grasp alone is not success. Seven checks: extracted, deposited and no longer held, fresh before/after evidence, crop/clover preserved, target inventory intact, minimum battery >20%, verified rover home. Maximum 50 frames and 50 commands; retain 300 simulated-second/25% operating guards.

**Gate:** a whole scripted test mission must grasp, slip at weak force, reopen/regrasp, extract, checkpoint while carrying, release in bin, verify and return. Bad position, wrong orientation, unreachable path, stale frame, force loss and out-of-bin release cannot pass. Test FK/IK consistency independently.

### M8 — Sensor conditions, staged grasping and wrist camera (after M7)

Implement six selectable experiment conditions with unchanged contact/acceptance rules:

| Trial | Observation and behavior |
| --- | --- |
| `baseline` | Fixed overview camera: FOV45°, height1.8, forward offset.15, look `(0,-1.45,-2.5)`; ground-plane projection tool |
| `known` | Baseline plus explicitly supplied initial grasp XYZ; diagnostic only |
| `depth` | Closer side camera FOV55°, height1.15, right offset.75, forward offset.9, look `(-.75,-.95,-1.45)`; first-surface depth tool |
| `lidar` | Side camera plus camera-aligned 13×13 region scan; initial nonempty scan required before moving |
| `alignment` | Same LiDAR plus explicit fresh visual assessment and contact acknowledgment |
| `wrist` | Same staged protocol, with RGB/LiDAR rigidly mounted on the tool |

`scan_lidar(u,v,span,frame_id)` requires normalized u/v in 0..1, span .04..0.5 (default .24). Clip the selected square to the image; generate 169 ordered rays. Browser returns first visible mesh hits, respecting foliage alpha cutouts, arm occlusion and layer visibility. Ignore display-only overlays. Return `[u,v,x,y,z]` rows, null misses, frame/revision and bounds; no object IDs or target snapping. Validate count, finiteness, request/frame/revision identity, distance .05..6 m and lateral ray error ≤.005 m atomically. Scans from an earlier scene revision remain visible but are labeled stale after motion. A later empty scan does not erase the prior nonempty-scan prerequisite.

Staged tools:

- `assess_alignment(frame_id,stem_between_fingers,depth_consistent,evidence)`: strict booleans, current frame/revision, evidence 8..600 characters. Both true allow closure with empty jaws. This is a model claim, never geometric truth. A new image or movement invalidates it.
- `set_gripper(opening,force)`: physical contact is independently computed. After any grip-force change, contact must be acknowledged again before carrying.
- `confirm_contact(frame_id,evidence)`: requires fresh frame plus actual holding/contact and positive load. It cannot manufacture contact.
- `open_gripper()`: full .12 m opening, zero force. A missed grasp or slip requires reopening before repositioning and reassessment.

Configure the wrist camera as follows: 640×360, vertical FOV70°, near .05 m. Relative to the tool center, position `(0,.04,.22)`, direction `(0,-.12,-.28)`, up `(0,1,0)`. Transform all three through FK rotation and translate position by tool position. Use the full transformed up vector in both Python and Three.js, including roll. No automatic weed tracking. Camera prompt explains that movement changes image coordinates and new scans measure current geometry. Tell the model to inspect both finger faces and the central stem, and use contact/load feedback before lifting.

Check that the palm and wrist housing do not obstruct the fingers or stem. Inspect initial and known-aligned renderer fixtures before a live run. Fixture coordinates must never leak into live policy observations.

**Gate:** Python and Three.js rays agree at corners/center/off-center pixels under multiple translated/rolled poses. Changing hidden weed location cannot change camera transform. Full staged mission covers false positive alignment, stale assessment, missed grip, weak-grip slip, force adjustment, checkpoint restore, extraction, collection and return. Camera/LiDAR rendering must be exercised in a real browser in addition to headless tests.

### M9 — Bounded experiments and evidence UI (after M3, M8)

Implement `scripts/arm_experiments.py` against the local API with the treatment page open. Reset to seed7 per condition. Poll to terminal outcome; stop at 240 wall seconds or $1 reported cost per trial. Simulator retains its 50-command limit. Stop on runner exceptions/interruption rather than leaving inference unattended.

```sh
python3 scripts/arm_experiments.py              # Gemini baseline; all three known; Nemo/Gemma depth
python3 scripts/arm_experiments.py --lidar       # Nemo/Gemma LiDAR
python3 scripts/arm_experiments.py --alignment   # Nemo/Gemma staged side camera
python3 scripts/arm_experiments.py --wrist       # Nemo/Gemma staged wrist camera
```

Provide a fixed-camera control run for each selected model through the UI. Save every run under a unique identifier with its seed, condition, model, provider, sensor configuration, prompt version, timestamps, actions, errors, acceptance checks, usage and cost. Store authoritative records in Supabase Postgres and image/scan/movement artifacts in private Storage. The comparison UI queries those saved sessions. Optional downloaded exports belong under `.runtime/` and evaluation summaries under `docs/evaluations/`; neither replaces the stored session. Never overwrite a completed run when starting a new evaluation.

UI shows model/provider, actual calls, tokens, reported cost, arm joints, grip/load/contact, protocol stage, current/stale LiDAR, before/after frames, independent checklist, action journal and labeled comparison rows. Camera heading identifies the wrist view. Available tools and trial selectors must reflect mode; offline mode cannot masquerade as a live LiDAR/alignment/wrist trial.

Evaluate each condition on the same initial scene and unchanged physical acceptance rules. Begin with seed 7, then repeat on additional seeds and placements. Compare completion, confirmed contacts, slips, recovery attempts, decisions, wall time and reported cost. Report the number of trials and all failed outcomes; do not infer reliability from one success.

A successful manipulation run must locate the stem from its permitted observations, establish contact, respond to any slip, extract the weed, carry it to the bin, release it, verify completion and return home. A supplied-coordinate diagnostic measures action execution separately from visual localization. Synthetic tests, deterministic policies and live inference must have separate labels.

**Gate:** results preserve the identity and outcome of every run; caps and interruption cleanup work; comparison rows accurately reflect exported evidence. Demonstrate at least one complete live manipulation mission with all seven acceptance checks passing. If no tested model completes it, retain the failure evidence and leave the live demonstration gate incomplete.

### M10 — Session playback and evaluated prompt review (after M9)

Build the session list, robot-filtered evidence timeline and movement playback described in section 3. The orchestrator reviews a failed or completed session through bounded evidence tools, saves its diagnosis and proposes an immutable prompt candidate. Implement one bounded baseline/candidate evaluation campaign and the promotion/rollback gate. Show the prompt diff, supporting frames/actions, all trial outcomes and why the candidate was accepted or rejected. Keep review and evaluation inference costs separate from execution costs.

**Gate:** reproduce a saved robot path and six-joint motion without actuating the simulator or calling inference. Review a slip or failed grasp using its actual frames and load history; link the resulting prompt candidate to that evidence. Evaluate it against a pinned baseline, retaining every trial. Prove that failed/inconclusive candidates remain inactive, accepted candidates apply only to new sessions, rollback preserves history, and a prompt cannot change the verifier or contract. Acceptance does not require a candidate to win; it requires an honest, functioning improvement gate.

## 5. Public integration seams

Use the same seams for agents, UI, test fixtures and replay analysis. JSON request/response; UI snapshot polling; no WebSocket requirement.

| Endpoint family | Required routes |
| --- | --- |
| Fleet reads | `GET /api/state`, `/api/export` |
| Fleet mutations | `POST /api/reset`, `/start`, `/pause`, `/breakdown`, `/false-claim`, `/retry`, `/abort` (all under `/api`) |
| Treatment reads | `GET /api/treatment/state`, `/export`, `/frame/<id>?mission=<id>` |
| Treatment mutations | `POST /api/treatment/reset`, `/start`, `/pause`, `/clog`, `/fault`, `/stop`, `/frame`, `/depth` |
| Session reads | `GET /api/sessions`, `/api/sessions/<id>`, `/api/sessions/<id>/events?after=<sequence>`, `/api/sessions/<id>/robots/<robot>/telemetry`, `/api/sessions/<id>/motions`, `/api/sessions/<id>/artifacts/<artifact>`, `/api/sessions/<id>/export` |
| Reviews and prompts | `POST /api/sessions/<id>/review`, `/api/prompt-candidates`, `/api/evaluations`, `/api/prompt-versions/<id>/activate`, `/api/prompt-versions/<id>/rollback`; matching read routes for review, prompt and evaluation records |
| Local assets | `/vendor/three.module.js` and related Three build modules; `/vendor/ez-tree/…` from package build |

Treatment reset accepts `kind` (`irrigation`,`care`,`arm`), seed, mode (`pixels`,`vision`), engine (`crusoe`,`nemotron`,`gemma`,`gemini`), trial for arm. Frame submission carries request ID and PNG data URL. Depth submission carries request ID and one point or ordered region points. Reject cross-mission/stale observations. Do not expose an unrestricted “set world state” endpoint.

Session reads use bounded pagination and committed-sequence cursors. Agent review tools expose filtered projections, while the local operator can inspect privileged exports separately. Activation requires a saved passing evaluation; direct activation cannot bypass that check. Telemetry is emitted by the authoritative runtime, never accepted as arbitrary browser-written robot state.

Minimum model observation: mission, available actions, resources, current phase/tool, fresh frame metadata, measured sensors, feedback and bounded recent history. Arm additionally exposes known base/tool pose, joint limits, jaw/contact/load telemetry, bin location and calibrated camera. Known robot kinematics and bin location are permitted; hidden weed XYZ is not.

## 6. Acceptance and execution checklist

The milestone order is the build plan. Track each item as not started / implemented / validated, with an evidence path; do not mark a whole milestone done solely because files exist.

- [ ] M0: bootable local app and state/asset boundaries.
- [ ] M1: whole fleet mission and numerical verifier.
- [ ] M2: recoverable fleet demo, Supabase sessions, durable partial progress, robot telemetry and outage recovery.
- [ ] M3: strict adapters and tested role orchestration; separately label live Crusoe status.
- [ ] M4: procedural orchard and working multiview renderer.
- [ ] M5: real-pixel irrigation with clog recovery.
- [ ] M6: full plant care, no-target case, protected entities and dosing ledger.
- [ ] M7: articulated grasp/extraction/disposal with negative cases.
- [ ] M8: calibrated wrist/LiDAR and staged-contact whole-mission tests.
- [ ] M9: bounded live trials, preserved failures and honest comparisons.
- [ ] M10: session movement playback, evidence-linked prompt review and gated candidate evaluation.

Apply Supabase migrations, provision the private bucket and configure backend credentials before persistence/browser gates. Final commands: `npm ci`, `npm run check`, `npm test`, `npm start`. Open both pages and perform browser gates; keep treatment page open while it supplies observations. Export a nominal and failed mission. Restart during partial work, resume, and verify no duplicate outcomes. Check console/asset errors and that credentials are absent from exports.

Create automated tests covering the categories below. Require all tests to pass before release; measure coverage by observable behavior rather than a fixed test count.

| Test family | Main guarantee |
| --- | --- |
| missions/runtime | contract, failure recovery, idempotency, partial work, restart, provider isolation |
| persistence/telemetry | atomic state/evidence commits, duplicate batches, writer fencing, outage pause/recovery, sequence ordering, heartbeat versus progress, private artifact access |
| session replay/prompt review | trace/observation correlation, gaps labeled, playback without actuation, bounded review inputs, immutable prompt versions, fair evaluation and gated promotion/rollback |
| treatment/care | evidence freshness, measured delivery, faults, prescription, protected entities, no-target cases |
| manipulation/grasp protocol/wrist | real contact/extraction, slips, motion limits, stale claims, complete collection/return |
| arm experiments/LiDAR | caps/cleanup, cost semantics, diagnostic isolation, bounded validated scans |
| geometry/depth/static assets | repeatable scene, clearance/detail, RGB/ray agreement, occlusion/alpha, local serving |

Use seed 7 for the initial arm comparison and seed 8 for the full-care browser acceptance case. Also run held-out scenarios to measure generalization; do not silently replace a failure with a favorable seed. Future provider unavailability should be reported as an external limitation, with deterministic validation still completed.

## 7. Out of scope

- Fleet-to-treatment task handoff, tool-aware treatment reassignment, and spare continuation of a partially completed articulated job.
- Multi-seed live fleet reliability benchmarking.
- Articulated irrigation, fertilizer and pest-control tools.
- Learned segmentation, noisy hardware sensors, learned motor control, ROS integration and physical robots.
- Real nutrient diagnosis, chemical selection, weather, crop physiology and agricultural prescriptions.
- Distributed robot execution and arbitrary natural-language farm missions.
- Unbounded autonomous prompt search, tool/code self-modification and large-scale learning campaigns. Bounded session review, prompt candidate evaluation and gated activation are included.

## 8. Design principles

- Position cameras so the plant part and both tool contact surfaces can be inspected together.
- Treat surface localization and plant-part identification as separate decisions.
- Require physical contact/load evidence before lifting; a visual alignment claim cannot substitute for it.
- Make failure feedback actionable and preserve it across retries, sessions and prompt versions.
- Use telemetry to detect health and progress separately; use recorded motion and observed outcomes to evaluate a prompt change.
- Evaluate target selection, grip-force control and recovery as separate capabilities within complete missions.
- Separate deterministic validation, live-model performance and supplied-coordinate diagnostics in every report.
- Keep physical acceptance rules unchanged across model comparisons. Record camera mount, field of view, prompt, budgets and provider as evaluation conditions.
