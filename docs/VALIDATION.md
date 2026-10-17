# Validation

Wall-ne validates simulator mechanics separately from live model control.

## Live orchard result — October 17, 2026

W1 completed the seed-7 precision wrist mission in the main orchard at `/`, using Gemma `google/gemma-4-31b-it` entirely on Crusoe. It drove from its dock to the front-row tree, selected the weed from actual orchard RGB and LiDAR, approached, confirmed physical contact/load, extracted, collected, and returned to its dock. All seven independent checks passed. There were 14 valid model decisions across 14 requests, zero provider failures and no Gateway fallback. Total trial time was 138 seconds, with 97 seconds in inference. Reported cost was unavailable.

No weed coordinates were supplied to the controller. The scene includes surrounding orchard vegetation and structures; the wrist sensor excludes rover bodywork and uses stationary geometry aligned with range rays. This establishes one successful orchard mission; held-out seed reliability and multi-worker weeding remain untested.

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

The first live fleet attempt (`3498561b-e81d-4f40-9bbb-bb407058d2a7`) was stopped after dispatching four workers. Its service camera was obstructed by the arm, and care calls omitted required frame IDs. Its 22 calls and interrupted result are retained in [the attempt record](evaluations/fleet-care-3498561b-e81d-4f40-9bbb-bb407058d2a7.json). The service camera was moved laterally and care schemas now require frame IDs. A corrected fleet run is being evaluated separately.
