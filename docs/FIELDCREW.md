# FieldCrew transfer and Crusoe-first execution

October 17, 2026. The `fieldcrew` arm condition transfers the original staged wrist setup into Wall-ne. It is an explicitly labeled adaptation, not a claim of pixel-identical reproduction or live reliability.

## Provider policy

New `crusoe` sessions use Crusoe first. Treatment defaults to `google/gemma-4-31b-it`, verified in Crusoe's authenticated model inventory. Gateway advertises the same model ID. Fleet roles retain Crusoe Nemotron Super/Nano, with their matching Gateway model IDs pinned at session creation. Existing environment model overrides remain supported. The older Nano Omni override has no identical Gateway entry; its configured fallback is Super VL, and both identities are recorded.

Two consecutive transport, authentication, timeout or malformed tool-response failures switch the affected role to Gateway for the rest of that session. A valid response resets the provider failure streak. Missed grasps, rejected actions and progress stalls do not switch providers. Three consecutive Gateway inference failures block the mission. There is one provider call per durable request; the failed primary attempts remain in cost, latency and error accounting. Unknown costs stay unknown. Fallback does not bypass the 240-second arm wall limit or $1 reported-cost cap.

The immutable configuration pins both providers/models; checkpoints retain active routes. Each request records actual provider, endpoint, model and fallback status. A `provider_fallback` event records the transition reason and model identities. Explicit Gateway choices remain available for labeled controls; historical sessions are not rewritten. Review-service calls remain single-provider and do not silently retry.

## Transferred condition

The original source is `/Users/kevinloo/Documents/ChatGPT/nvidia-hackathon`. SHA-256 hashes are retained in [the source manifest](evaluations/fieldcrew-source-manifest.json). The historical wrist-results hash matches the user's handoff: `67832e320fa967388ec9c16f89ed2f4be925446dc8a7d1707f7a923855b8e689`.

- Centered arm; original wrist camera transform, 640 × 360, 70° vertical field of view, 0.05 m near plane.
- Original .17 × .075 × .085 m palm, .018 × .13 × .04 m fingers, .045/.055 m links and six .075 m base-radius joint spheres.
- Rover body visible in overview but excluded from both decision RGB and depth; articulated arm remains visible.
- Original procedural weed geometry and seed-dependent form ordering. Target locations remain hidden from model observations.
- Flat `treatment_action` arguments and a state-dependent action enum, with original observation instructions. Wall-ne action names `verify` and `return` replace `verify_stage` and `return_home`.
- One current PNG per decision, automatic captures after physical changes, historical scans with frame/revision identity, world axes/units and first-surface semantics. Scan crops remain saved as evidence but are not sent as a second image in this condition.
- Independent contact, load, slip, extraction, collection and return checks. Weak-grip recovery at the same pose with stronger force remains permitted; a stalled holding state can also increase force and reconfirm contact.

This condition pins its original system prompt as an inactive comparison version; it does not activate a global treatment prompt. An explicit `prompt_version` can override it for a separate comparison. Observation instructions and geometry are covered by the treatment implementation hash.

## Remaining differences and limits

Wall-ne retains its background/tree, clover geometry, lighting, public robot/ground scan masks, progress detector, IK implementation, durability/accounting, command-count semantics, and verifier. Its slip interrupts the remaining motion immediately. Verification needs a final call after returning, unlike the historical 30-decision sequence. These differences are recorded rather than presented as exact historical equivalence. Crusoe transport is itself a change from the historical Gateway run. The live camera/scan inputs contain no target labels or target coordinates.

The pre-transfer five-run Nemotron Gateway wrist series completed zero extractions. Its final consistency check detected an implementation change, so its report remains `interrupted`; it is not a valid frozen multi-seed reliability comparison. All five results and their exports are retained in [the series report](evaluations/wrist-repeatability-98de4eb1-8aa4-48ba-82fe-ccc072ee5c02.json).

## Checks

Local tests cover the provider threshold/reset/sticky route/restore, absence of fallback for rejected physical commands, Gateway exhaustion, flat schema/action gating, layer parity, tool dimensions, and the full 10/15/20/30 N slip-recovery sequence. These prove implementation behavior, not live visual control.

## Live routing evidence

Session `1e426540-91c5-416e-a16d-2b87efa110c0` made one valid Crusoe Gemma scan, retained two consecutive invalid Crusoe tool responses, then switched to Gateway Gemma and executed an approach. It subsequently blocked on a camera-tab disconnect/30-second sensor timeout. Four completed calls, two protocol failures, 35.66 seconds in inference, no pending calls; total cost is unknown because Crusoe supplied no dollar costs. This confirms live fallback behavior, not manipulation success. [Saved result](evaluations/arm-32842827-9142-432e-acf8-5c21c03793af.json).

Final local validation: 13 JavaScript tests and 54 Python tests passed. The five normally opt-in HTTP/Supabase integration tests were then run explicitly and all passed.

[Twenty FieldCrew visibility probes](evaluations/fieldcrew-visibility-poses.json) cover initial, approach, aligned, recovery and offset poses across seeds 7/11/23/8. All four offset controls expose the central grasp region; the nominal aligned central-region probes remain occluded. Finger probes use a 4 mm first-surface tolerance and the central region uses 3 cm. These are geometric diagnostics, not live alignment evidence.

The retained retry `1ae541e7-8af7-42b6-a4ee-c787d46c73c8` also switched after exactly two invalid Crusoe responses. Gateway Gemma then chose three unreachable approach poses, and the mission blocked after three rejected commands. Seven completed calls, two protocol failures, 64.75 inference seconds, 83.75 wall seconds, zero pending calls and unknown total dollar cost. It established no contact or extraction. [Retry result](evaluations/arm-9e1cad18-d985-491e-95c5-d66d177c996c.json). Both live runs used treatment implementation hash `52abb935726533409402acfe41af1f25a0a7346b96a95df79c000cd8a8e7d2e3`. No model/prompt promotion or fleet-weeding integration followed.
