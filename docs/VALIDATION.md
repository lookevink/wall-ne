# Validation

Wall-ne validates simulator mechanics separately from live model control.

## Live orchard result — October 17, 2026

W1 completed the seed-7 precision wrist mission in the main orchard at `/`, using Gemma `google/gemma-4-31b-it` entirely on Crusoe. It drove from its dock to the front-row tree, selected the weed from actual orchard RGB and LiDAR, approached, confirmed physical contact/load, extracted, collected, and returned to its dock. All seven independent checks passed. There were 14 valid model decisions across 14 requests, zero provider failures and no Gateway fallback. Total trial time was 138 seconds, with 97 seconds in inference. Reported cost was unavailable.

No weed coordinates were supplied to the controller. The scene includes surrounding orchard vegetation and structures; the wrist sensor excludes rover bodywork and uses stationary geometry aligned with range rays. This establishes one successful orchard mission; held-out seed reliability remains unestablished. Fleet integration results are recorded below.

Evidence: [structured result](evaluations/arm-56c67b3f-8f7f-48a3-a9f3-7bcb99fcaa56.json), [orchard completion screenshot](evaluations/orchard-live-success.png), session `ce3155e1-a710-4489-a176-9beb8f1c2f9b`. The implementation hash stayed unchanged throughout execution. The final UI cleanup only clears recovered stale-frame notices and labels completed missions.

## Local checks

- Fleet tests cover task ownership, reserve, retrieval, faults and terminal verification.
- Treatment tests cover measured delivery, stale images, protected organisms and recovery.
- Arm tests cover kinematics, calibrated camera rays, tool-center grasp height, alignment gating, physical contact/load, slip, stronger-force recovery, extraction, bin collection and return.
- Provider tests cover response parsing, malformed envelopes, Crusoe-first routing, repeated-failure fallback, concurrency, checkpoint restoration and complete accounting.
- Orchard tests cover drive/restore, world-coordinate grasping, collection and return, foreign-arena rejection, tree inventory agreement, playback specimen reset, zero shader displacement and camera-independent sensor geometry.
- Renderer tests compare RGB/depth visibility layers and probe approach, aligned, offset and recovery poses. Geometric visibility probes are diagnostics, not model alignment evidence.
- Opt-in HTTP/Supabase checks cover local-origin restrictions, private artifacts, persistence fencing and immutable prompt/evaluation records.

See [precision wrist control](WRIST_CONTROL.md) for the active actuator, perception and provider contracts. Saved session outcomes remain independent evidence; passing unit tests alone does not establish live extraction.

## Full-care fleet integration

Local mechanics tests complete ten distinct front-boundary trees with per-tree inspection, metered water/fertilizer, pest contact, articulated extraction, dock unloading and replenishment. Negative tests reject premature clearance, foreign-worker sensor frames, duplicate task ownership and images from another tree. Regression tests cover failed parent start commits and navigation reservation checks across action transitions. These controlled mechanics tests do not constitute live visual-control success.

Live fleet attempts use Crusoe for the orchestrator and Gemma vision workers; Gateway remains a fallback only after repeated provider/protocol failures. The following attempts had zero recorded provider failures. Unknown provider cost is retained as unknown.

| Session | Outcome | Calls | Finding |
| --- | --- | ---: | --- |
| `3498561b-e81d-4f40-9bbb-bb407058d2a7` | Stopped | 22 | Service-camera arm occlusion and missing frame IDs. Camera moved laterally and care schema tightened. |
| `698f8eca-0597-48cb-97c7-e6d7252e342e` | Stopped | 99 | All five workers dispatched; redundant image/meter actions. Care-stage availability tightened. |
| `eaef8ffa-37b4-4259-b658-ab472677a61a` | Blocked | 106 | Five trees reached extraction after measured water/fertilizer and pest treatment. Repeated approach-height moves and invalid closure calls. |
| `0447a4b3-0fda-455a-98da-17b763de54dc` | Blocked continuation | 156 cumulative | W1 completed a full-care tree and returned; W4 extracted, collected and serviced but lacked final verification. W2 grasped protected clover, and repeated recovery actions exhausted its invalid-action budget. |

The fresh mission `f7d8d782-5662-4aed-b1d3-f0929c02fdda` was stopped after 119 calls, including three isolated Crusoe timeouts, with all five trees through measured care and W4 holding a weed. There was no recorded protected-organism damage. A new version adds explicit camera-ray ground projection to improve horizontal targeting. Its continuation is recorded separately.

The continuation has new parent/worker session identities and records its source session. It preserves physical state, care evidence, resource consumption, active wall time, inference accounting and provider/model pins. Its 156 calls include source calls and must not be added to the source's 106. Saved source outcomes are unchanged. A damaged mission cannot be continued into a success claim.

Structured attempt records are in `docs/evaluations/fleet-care-<session>.json`; full parent and worker exports are in ignored `.runtime/exports/`. The corrected controller explicitly distinguishes approach and grasp heights, rejects no-op motion, and requires a raised viewpoint plus a fresh scan after a missed grasp. It describes grass, serrated rosette and thistle morphology separately from protected three-leaf clover. These instructions and gates do not themselves prove reliable visual control.


## Active fleet iteration

Session `f84e1b62-f440-4d4d-af8a-d05b3b77fb87` continues `87bf2ae5-1353-4fc4-9f12-7ab8808d5019`, which continued `f7d8d782-5662-4aed-b1d3-f0929c02fdda`. It preserves accounting and physical care, uses only the full current image for precision pixel actions (aligned crops remain saved artifacts), and distinguishes scan recovery from repeated retraction. Individual worker failures no longer halt healthy workers. The run is allowed to finish with partial results; no ten-tree live success is claimed here. The monitor exports its final record automatically to `docs/evaluations/fleet-care-f84e1b62-f440-4d4d-af8a-d05b3b77fb87.json`.

The source projection continuation finished blocked with W1 repeating an already-reached recovery pose; W4 had extracted its weed. The suspected full-image/crop coordinate ambiguity is a diagnosis hypothesis, not an experimentally isolated causal result.

Latest local checks: 17 JavaScript tests and 76 Python tests passed, with five opt-in Python integration tests skipped. Review confirmed public projection geometry, contact-check preservation and full-image-only inference. Two fleet edge cases are queued for the next stopped-run iteration: terminal workers must release navigation reservations, and restoring a failed child checkpoint must preserve the parent's partial-result policy. They are not reasons to interrupt the current manipulation attempt.
