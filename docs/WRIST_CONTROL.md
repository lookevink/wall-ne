# Orchard wrist control

Live runs use the main orchard at `/`. W1 drives from its dock to the assigned front-row tree, parks for camera-guided extraction, carries the collected plant back to its dock and verifies completion. Fleet watering remains a separate selectable mission. The laboratory is for fixtures and tool diagnostics.

Wall-ne uses a centered six-joint arm, a compact gripper and a rigid wrist RGB camera. The decision image and LiDAR see the arm, plants and ground; rover body geometry stays in the overview layer. Images are 640 × 360 with 70° vertical field of view and a 0.05 m near plane.

The gripper palm is .17 × .075 × .085 m and each finger is .018 × .13 × .04 m. Cartesian positions describe the center between the fingers. World axes are x right, y up, z toward the rover; distances are meters. An omitted wrist orientation means zero XYZ degrees, pointing straight down. This default is explicit in the tool schema and operating instructions.

The controller identifies the small weed from RGB, requests a focused LiDAR region, approaches above the observed crown, descends to y=.13 m, assesses visual alignment, closes at 30 N, confirms measured contact/load, and lifts vertically .20 m before carrying to the bin. Force values describe simulator parameters only. A visual assessment never establishes physical success.

Scan returns separate `image: {u,v}` from `world: {x,y,z}`. Public robot and ground geometry are filtered; remaining surfaces have no target identities. Current images and revision-tagged measurements support corrections. A selected surface height is not a grasp height. Occlusion calls for a changed view, not an unsupported alignment claim.

State-dependent tool availability enforces scanning, open-jaw approach, fresh positive alignment, physical contact acknowledgement, collection, verification and return. Stronger-force recovery can reuse the same observed grasp location. Repeated images or ineffective moves are bounded.

## Crusoe execution

Crusoe is primary, using `google/gemma-4-31b-it`. The adapter sends one `treatment_action` tool with a current action enum, flat arguments, `tool_choice: required`, temperature .1 and `WALLNE_MAX_TOKENS` output tokens (default 16384). Optional rx/ry/rz default to zero. Unrelated fleet and review fields are omitted from the arm schema.

The Gateway fallback is opt-in (`WALLNE_GATEWAY_FALLBACK=1`) and off by default, so a Crusoe run stays a Crusoe run: provider or malformed-response failures back off and block the mission visibly after three. When enabled, two consecutive failures switch the role to the same Gemma model on Gateway; physical misses/rejected movements never trigger it, and the route change is recorded. Requests, models, routes, failure output and accounting are retained; unknown dollar costs remain unknown. Arm missions use `WALLNE_WALL_CAP` (default 3600 s) and `WALLNE_COST_CAP` (default $1 reported); each call waits up to `WALLNE_INFERENCE_TIMEOUT` (default 300 s). Learning runs are not rushed.

## Acceptance

Success requires all seven independent checks: extraction, collection/release, fresh before/after images, protected plants preserved, inventory intact, battery reserve and return home. A completed live mission is required before claiming successful visual control.

## Orchard sensor contract

The arm, weed and protected plants join the existing orchard scene. RGB and LiDAR use the same full orchard geometry and world coordinates. The actual planted tree positions drive trunk collision checks; a test verifies the physics inventory against procedural rendering. Robot bodies are excluded from the wrist sensor layer; arms, plants, ground and orchard structures remain visible. Shader wind is frozen during this condition to align range and RGB. Navigation follows a fixed apron route, independent of hidden weed coordinates. No multi-worker weeding scheduler is implemented.

Run `python3 -m scripts.arm_experiments --engine crusoe --condition precision --seed 7` with the main orchard page open. The repeatability runner and new evaluation campaigns use the same arena. Saved missions retain the arena, prompt/model pins, implementation hash, inventory, movement, scans and RGB evidence.

## Orchard repeatability series

`python3 -m scripts.wrist_repeatability 7,7,7,11,23,8` on 2026-10-17, recorded in `docs/evaluations/wrist-repeatability-ed71f406-4b64-4619-ac66-5f39c50e7bc6.json`: Crusoe `google/gemma-4-31b-it`, precision wrist controller in the orchard arena, Gateway fallback off, prompt `9dbe48a3`, implementation hash `16bac89f…`, six sequential fresh sessions. Repeats of seed 7 measure repeatability; seeds 11, 23 and 8 are held-out placements.

| # | Seed | Session | Result | Calls | Wall s | Inference s |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 7 | `6fcd89ab` | completed, 7/7 | 13 | 149 | 98 |
| 2 | 7 | `b95a510f` | completed, 7/7 | 13 | 168 | 100 |
| 3 | 7 | `9f594a5b` | completed, 7/7 | 14 | 190 | 118 |
| 4 | 11 | `2ba25d01` | blocked, 3/7 | 29 | 334 | 207 |
| 5 | 23 | `9bdc10ea` | completed, 7/7 | 14 | 154 | 93 |
| 6 | 8 | `4905a3d6` | completed, 7/7 | 13 | 184 | 115 |

Five of six missions completed with zero failed provider calls and no fallback. Every success had the same 13–14 decision shape: scan, approach, descend, assess, close at 30 N, confirm, lift, carry, release, verify, return. Seed 11 failed on localization: the focused scan returned the crown at z≈14.30 (a leaf surface) while the stem stood at z=14.236, so every closure at 6.5 cm horizontal offset missed the 5.5 cm contact radius, and the controller kept asserting visual alignment at the same pose until the progress detector blocked the mission. That is a one-leaf-width localization error with no visual correction, evidence for the review loop rather than a reason to loosen the verifier. Crusoe reports no dollar cost, so cost stays unknown. Six trials are a smoke test, not statistics.
