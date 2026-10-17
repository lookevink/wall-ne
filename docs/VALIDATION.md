# Validation

Wall-ne validates simulator mechanics separately from live model control.

## Live wrist result — October 17, 2026

Gemma `google/gemma-4-31b-it` completed the seed-7 precision wrist mission entirely on Crusoe. All seven independent checks passed: extraction, bin collection/release, fresh images, inventory, protected plants, battery reserve and return home. There were 14 valid model decisions across 15 requests; one HTTP 429 recovered on Crusoe without Gateway fallback. Mission time was about 155 seconds (157 seconds including export), with 112 seconds in inference. Reported cost was unavailable.

The model selected its grasp from rendered RGB and a scan, approached and descended, confirmed measured contact, lifted, carried and released the weed, verified collection, returned, and verified completion. No target coordinates were supplied to the controller. This establishes one successful live mission; held-out seed reliability is untested.

Evidence: [structured result](evaluations/arm-c2e88435-7db3-47cc-ab12-3afd7b740ec0.json), [physical checks screenshot](evaluations/precision-live-success.png), session `c29fcb66-988e-4fd8-9463-1495439c3bbe`. The result pins the executed implementation hash. Subsequent review fixes preserve the scan artifact reference and reject unsupported saved profiles; they do not change manipulation physics or operating instructions.

## Local checks

- Fleet tests cover task ownership, reserve, retrieval, faults and terminal verification.
- Treatment tests cover measured delivery, stale images, protected organisms and recovery.
- Arm tests cover kinematics, calibrated camera rays, tool-center grasp height, alignment gating, physical contact/load, slip, stronger-force recovery, extraction, bin collection and return.
- Provider tests cover response parsing, malformed envelopes, Crusoe-first routing, repeated-failure fallback, concurrency, checkpoint restoration and complete accounting.
- Renderer tests compare RGB/depth visibility layers and probe approach, aligned, offset and recovery poses. Geometric visibility probes are diagnostics, not model alignment evidence.
- Opt-in HTTP/Supabase checks cover local-origin restrictions, private artifacts, persistence fencing and immutable prompt/evaluation records.

See [precision wrist control](WRIST_CONTROL.md) for the active actuator, perception and provider contracts. Saved session outcomes remain independent evidence; passing unit tests alone does not establish live extraction.
