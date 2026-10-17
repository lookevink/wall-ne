# Execution evidence

Validated on 2026-10-17 with Python 3.9.6, Node 26.3.1 and npm 11.16.0. All quantities are simulation parameters. This report separates deterministic validation, browser pixel policies, supplied-coordinate diagnostics and live inference.

| Milestone | Status | Evidence and remaining gate |
| --- | --- | --- |
| M0 | validated | Local server, vendored Three/EZ-tree, Host/Origin/traversal and secret-free export checks in `tests/test_http_integration.py`; actual HTTP integration passed. |
| M1 | validated | `tests/test_fleet.py`: complete missions on seeds 7/8/31, numerical contract checks, rejected false claims, duplicate/stale actions and impossible deadline. |
| M2 | validated | `evaluations/browser-fleet.json`: seed 7 demo completed all six checks after W1/W2 failures. `tests/test_persistence_integration.py` actually passed against configured Supabase: atomic retry, fencing, partial-work outage freeze/recovery and checkpoint integrity. Browser partial-water process restart retained five effective liters and continued without duplicate dosing; original failed session retained. |
| M3 | implemented; deterministic validated | Strict tools, role isolation, pinned models/prompts, stale-result handling, bounded rejected responses and retained failed-call charges tested. Crusoe Omni accepted an actual PNG/tool compatibility probe. `evaluations/live-fleet-crusoe.json`: supplied model spelling returned three HTTP 404 responses. Canonical IDs were verified through the provider inventory. `evaluations/live-fleet-crusoe-canonical.json`: 34 real calls, two injected failures, stopped at the 180-second test cap; full live completion remains incomplete. No provider fallback occurred. |
| M4 | validated at recorded viewport | Browser: 30.0 overview fps / 15.0 onboard-feed fps, 160 draw calls, 168 geometries, 445×435 viewport, DPR 1.5, ANGLE Metal / Apple M1 Max. Rover camera selection works. Geometry/calibration tests pass. Performance is measured for this viewport, not a claim about all hardware or full-screen resolution. |
| M5 | validated within full-care run | Actual browser PNG policy completed watering to 65% and returned. Deterministic clog recovery and stale-image rejection pass. |
| M6 | implemented; nominal browser validated | `evaluations/browser-care-seed8.json`: all 11 checks, five weeds, two pests, 21 effective liters, 21 g fertilizer, no protected damage. Headless held-out and no-target cases pass. `evaluations/browser-care-seed0.json`: real browser seed 0 completed all 11 checks after an injected nozzle clog; empty weed and pest stages were independently verified. |
| M7 | validated (scripted) | `tests/test_treatment.py`: complete weak-grip slip/reopen/regrasp/extract/carry-checkpoint/deposit/return, FK/IK and negative cases. This is not live-model success. |
| M8 | validated (scripted and browser sensors) | Full staged alignment/wrist missions pass. Python/Three rays agree under translated/rolled poses. Initial/aligned real renderer fixture screenshots saved. Actual live browser returned a validated nonempty 169-ray scan and executed arm moves. |
| M9 | implemented; live demonstration incomplete | Every experiment retains a unique Supabase session and local summary. Initial Crusoe failed tool protocol; initial Gemini exposed missing argument schema. Corrected Gemini wrist run reached physical grasp attempts but failed localization and hit 240 seconds. No live seven-check success established yet. |
| M10 | implemented; gate integration validated | Recorded motion pagination and chronological playback; bounded actual-image/load review; immutable candidates; frozen four-case paired campaign; code/model/sensor pins; interruption retry. Actual database tests rejected failed activation and immutable edits, promoted an isolated synthetic test role and rolled it back while retaining both records. Live evidence-linked campaign outcome is recorded separately below. |

## Reproducible checks

`npm ci`, `npm run check`, and `npm test` passed during the build. The suite includes real geometry/ray checks and behavioral Python tests. Explicit service checks were run, rather than treating their default skips as passes:

```sh
WALLNE_INTEGRATION=1 PYTHONPYCACHEPREFIX=.runtime/pycache python3 -m unittest tests.test_persistence_integration -v
WALLNE_HTTP=1 PYTHONPYCACHEPREFIX=.runtime/pycache python3 -m unittest tests.test_http_integration -v
```

Final local suite: nine JavaScript tests plus 42 Python tests (37 passed, five service checks skipped by default). Four Supabase integration cases and the HTTP case were explicitly run and passed. The activation case additionally verified new-session-only adoption and old-session pins. Prompt gate fixtures use a unique `integration-test-*` role and never become an execution role. Synthetic saved passing evaluations are labeled test-only and are not evidence of model improvement.

## Evidence identities and limitations

- Nominal care: `f64d4c1e-6835-40dd-b897-975bc70cf677`, offline PNG policy, seed 8, completed.
- Original care failure/restart: `2c0755a9-866d-48a6-b532-4b4b9bb3e7b4`, aborted after visual occlusion prevented weed removal. The pending duplicate-image upload was recovered without losing progress. Rendering and artifact-reference fixes followed; the failed run was not replaced.
- Recoverable fleet demo: `32105258-5fe8-4039-9ddc-eece2b119831`, seed 7, completed.
- Crusoe wrist: `5ae2d8ec-6699-43ba-9db2-acebdd82d2db`, blocked on invalid tool responses. Its pre-fix signed-zero checkpoint hash does not survive JSONB numeric normalization. Original evidence is available with an explicit failed integrity flag; resumption remains blocked. New checkpoints use semantic numeric canonicalization, verified against the database.
- Gemini wrist before explicit argument schema: `d8ce95c3-aecb-4dd9-87d8-9ae8cdbe88b4`, blocked after empty scan arguments, $0.037192 reported.
- Gemini wrist after schema fix: `10cb1d93-c726-4d0a-9026-8ab15857a8c9`, blocked at 240 seconds after missed contact, 16 completed calls, $0.944626 reported at stop. An outstanding call was not harvested by that older runtime; final cost is incomplete. The runtime and runner now settle outstanding-call accounting without executing stopped decisions.

`evaluations/browser-care-zero.json` originally duplicated the seed-8 session and does not establish a zero-target case; it is retained with a correction. No-target browser validation must use an independently verified seed-0 identity.

Authoritative state/events are in Supabase Postgres; immutable image/depth/movement objects are in the private bucket. `.runtime/exports/` files are optional operator copies. Unknown cost stays unknown. The $1 reported-cost cap stops further dispatch after reported usage; an already dispatched request can exceed that amount. No tested result establishes physical robot reliability.

Additional retained results: seed-0 care `2fa57c90-7f40-49f0-bf7c-49b1d73aa31f` completed all eleven checks; Gemini wrist `8a9a9ba4-8383-4712-8a7d-9c3c31fb6eb1` failed at the time cap, 11 calls and $0.604114 including discarded late-response accounting. Failed Gemini review `19dc7ed6-717e-4416-af0d-44a4c099ec51` used $0.063318 and returned no candidate (output token limit). Gemma review `649fd1f2-0b32-4110-8bb2-3891772c786f` produced candidate `cf79647c-5560-4ce7-9898-2fc6d81e2645` from three actual frames, three motion chunks and twelve linked event sequences; review cost $0.0009582. The candidate remains inactive until a passing evaluation exists.

Browser playback loaded 274 recorded arm samples and 87,072 fleet samples, including the final fleet timestamp 719.93 s. Evidence screenshots: `evaluations/arm-playback.png`, `evaluations/fleet-playback.png`. Session cursor pagination and W1-only heartbeat retrieval were checked against real saved sessions.


## Final safety audit and interrupted comparison

The audit added durable inference request identities, prompt/evidence references, response correlation, explicit unknown-cost recovery after a process interruption, and accounting for completed calls discarded after a terminal decision. Storage failure prevents dispatch. Terminal frames, scans and injected faults are rejected. A returned call that crosses the reported-cost cap cannot execute; a completed trial with unresolved or unknown accounting cannot qualify for promotion. Sensor-code hashes are checked after each trial, before comparison and at activation. Saved reviews/prompts/evaluations support individual reads and cursor pagination.

Campaign `e0650fd8-f9b9-4be5-97b2-eb19bb4a8a00` is completed with `passed=false`: its seed-7 baseline was blocked with eight commands and unknown total cost; its candidate was aborted with four commands and $0.220266 after safety fixes changed the frozen implementation. The seed-11 child was retained but blocked before inference. `evaluations/paired-wrist-campaign.json` preserves the complete manifest and outcomes. This is an interrupted comparison, not evidence that the candidate improved or regressed. It remains inactive; the one-campaign limit was not bypassed.

The fixed-camera controls also failed: Nemotron 3.5 VL exhausted its command/frame budget; Gemma encountered timeouts and missed contact; Gemini damaged protected clover. None is a successful wrist-camera comparison. The complete model/sensor matrix and repeatable live extraction remain incomplete. Main-fleet weed control is not integrated; treatment remains a separate laboratory.

After the safety changes, all four Supabase integration cases and the HTTP case passed again. Actual API checks confirmed atomic rejection of a mixed valid/invalid breakdown request, saved-record lookup and timestamp cursor pagination. The updated orchard rendered without browser console errors at 29.8 overview / 15.1 feed fps, 986×720, DPR 1.5, Apple M1 Max. Screenshot: `evaluations/final-orchard.png`.
