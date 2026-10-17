# Orchard wrist control

Live runs use the main orchard at `/`. W1 drives from its dock to the assigned front-row tree, parks for camera-guided extraction, carries the collected plant back to its dock and verifies completion. Fleet watering remains a separate selectable mission. The laboratory is for fixtures and tool diagnostics.

Wall-ne uses a centered six-joint arm, a compact gripper and a rigid wrist RGB camera. The decision image and LiDAR see the arm, plants and ground; rover body geometry stays in the overview layer. Images are 640 × 360 with 70° vertical field of view and a 0.05 m near plane.

The gripper palm is .17 × .075 × .085 m and each finger is .018 × .13 × .04 m. Cartesian positions describe the center between the fingers. World axes are x right, y up, z toward the rover; distances are meters. An omitted wrist orientation means zero XYZ degrees, pointing straight down. This default is explicit in the tool schema and operating instructions.

The controller identifies the small weed from RGB, requests a focused LiDAR region, approaches above the observed crown, descends to y=.13 m, assesses visual alignment, closes at 30 N, confirms measured contact/load, and lifts vertically .20 m before carrying to the bin. Force values describe simulator parameters only. A visual assessment never establishes physical success.

Scan returns separate `image: {u,v}` from `world: {x,y,z}`. Public robot and ground geometry are filtered; remaining surfaces have no target identities. Current images and revision-tagged measurements support corrections. A selected surface height is not a grasp height. Occlusion calls for a changed view, not an unsupported alignment claim.

State-dependent tool availability enforces scanning, open-jaw approach, fresh positive alignment, physical contact acknowledgement, collection, verification and return. Stronger-force recovery can reuse the same observed grasp location. Repeated images or ineffective moves are bounded.

## Crusoe execution

Crusoe is primary, using `google/gemma-4-31b-it`. The adapter sends one `treatment_action` tool with a current action enum, flat arguments, `tool_choice: required`, temperature .1 and max_tokens 4096. Optional rx/ry/rz default to zero. Unrelated fleet and review fields are omitted from the arm schema.

Two consecutive provider or malformed-response failures switch the role to the same Gemma model on Gateway. Physical misses/rejected movements do not trigger fallback. Three Gateway failures block the mission. Requests, models, routes, failure output and accounting are retained; unknown dollar costs remain unknown. Arm missions retain 240-second wall and $1 reported-cost caps.

## Acceptance

Success requires all seven independent checks: extraction, collection/release, fresh before/after images, protected plants preserved, inventory intact, battery reserve and return home. A completed live mission is required before claiming successful visual control.

## Orchard sensor contract

The arm, weed and protected plants join the existing orchard scene. RGB and LiDAR use the same full orchard geometry and world coordinates. The actual planted tree positions drive trunk collision checks; a test verifies the physics inventory against procedural rendering. Robot bodies are excluded from the wrist sensor layer; arms, plants, ground and orchard structures remain visible. Shader wind is frozen during this condition to align range and RGB. Navigation follows a fixed apron route, independent of hidden weed coordinates. No multi-worker weeding scheduler is implemented.

Run `python3 -m scripts.arm_experiments --engine crusoe --condition precision --seed 7` with the main orchard page open. The repeatability runner and new evaluation campaigns use the same arena. Saved missions retain the arena, prompt/model pins, implementation hash, inventory, movement, scans and RGB evidence.
