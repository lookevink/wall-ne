# Wall-ne

A local 3D orchard laboratory with authoritative Python simulation, Three.js views, camera-guided plant care, a six-axis gripper, and durable Supabase evidence.

## Run

Python 3.9+ and Node 22+ are required. The selected validation runtimes are recorded in `docs/DEPENDENCIES.md`.

```sh
npm ci
cp .env.example .env  # only when .env does not already exist
# Fill backend credentials. Never commit .env.
npm run check
npm test
npm start
```

Open http://127.0.0.1:8765/ for fleet control, `/treatment.html` for treatment and manipulation, or `/sessions.html` for recorded evidence. Use `python3 -m simulator.server --port 8766` for another loopback port.

Apply the ordered SQL files in `supabase/migrations/` to the configured project before persisted runs. They create service-only tables, fenced atomic commit RPCs, immutable evidence, prompt gates, and the private `robot-session-artifacts` bucket. The provided wall-ne project has been provisioned during this build. Pure simulation tests need no database. Integration checks are explicit:

```sh
WALLNE_INTEGRATION=1 python3 -m unittest tests.test_persistence_integration -v
WALLNE_HTTP=1 python3 -m unittest tests.test_http_integration -v
```

Use a dedicated test project when running persistence integration tests; they create retained, labeled test sessions. The HTTP checks require the local app running.

## Modes

- **Fleet:** “Rule-based demo” is deterministic and makes no model calls. “Live Crusoe roles” uses separate bounded planner, orchestrator, worker/retriever and verifier calls. Python decides whether any command or completion claim is valid.
- **Irrigation / complete care:** “Offline PNG heuristic” finds stylized color components in actual browser PNGs. Live multimodal mode receives the same camera image and permitted sensor readings. Keep the treatment page open to supply observations.
- **Orchard weeding (default at `/`):** W1 drives to a tree, uses Crusoe wrist RGB/LiDAR control to grasp and collect one weed, and returns to its dock. Select fleet watering in the orchard menu for the fleet mission. All new live arm trials and evaluation campaigns run in this orchard; `/treatment.html` retains calibration fixtures and other tool diagnostics. Independent contact/load and completion checks remain mandatory.

Crusoe is primary; live treatment defaults to Gemma 4. The AI Gateway fallback is opt-in (`WALLNE_GATEWAY_FALLBACK=1`, off by default); when enabled, two consecutive provider/protocol failures switch the affected role to its pinned Gateway route for the rest of the session, and physical misses or rejected actions never trigger it. Gemini, Nemotron VL and Gemma remain explicit Gateway comparison conditions. See [the wrist control and routing notes](docs/WRIST_CONTROL.md). `AI_GATEWAY_KEY` is accepted as an alias for `AI_GATEWAY_API_KEY`. Missing credentials, failed inference and exhausted budgets produce blocked results; there is no silent offline fallback.

Runs are allowed to think. The only inference budgets are `WALLNE_MAX_TOKENS` (16384 output tokens), `WALLNE_INFERENCE_TIMEOUT` (300 s per call), `WALLNE_WALL_CAP` (3600 s per arm trial and campaign child) and `WALLNE_COST_CAP` ($1 reported), each overridable in `.env`. Frame, decision and simulated-time limits are mission rules and stay fixed.

## Days, seasons and timelapses

The main orchard runs on a season calendar. **Next day** ends today's mission and starts the next day's mission at dawn; there is no start button, because agents are always on. **Pause** holds the mission and the orchard clock; **Resume** continues both. The orchard menu's **Start new season** restarts at day 1 with the chosen seed; mission, controller and speed apply from the next day.

Each morning is computed from the previous day's measured end state and the night's weather. Watered soil dries according to temperature and humidity, pulled weeds re-sprout as seedlings while missed ones keep growing, and caterpillars breed, arrive or are eaten by the resident ladybird. Fertilizer comes due as nutrient deficit accrues. The day's conditions are saved with that mission's checkpoint, and after a restart the server continues the latest saved season.

The clock runs at the chosen daylight length while the mission runs, then sweeps through sunset to night once the mission settles. Optional auto-advance begins the next day after nightfall. It starts a new paid live mission every day and stops itself after two blocked days. Sun, sky, mist, headlights and wet-soil decals are operator-view effects; decision cameras always render under the calibrated lighting.

**Record timelapse** (orchard menu) saves the main view as captioned 1080p JPEG frames in `.runtime/timelapse/<reel>/`, across as many days as you record. Keep the tab visible while recording, since hidden tabs do not render. **Render video** stitches the reel with ffmpeg. You can also render from the command line:

```sh
python3 -m scripts.timelapse            # latest reel
python3 -m scripts.timelapse --list
```

### Season film

`/film.html` renders a deterministic multi-day film as a 2×2 grid: overview, care-row close-up, W3's onboard camera and an almanac panel. Frames come from `simulator/film.py`, which steps the season in fixed simulated-time increments. A scripted controller reads simulator truth and issues the ordinary care commands, so arm kinematics, collision checks and per-tree checks still decide every outcome. No model is called and nothing is persisted as evidence, so a film is a presentation of the simulation, not of live model performance. The same seed always produces the same frames. Rendering is promise-driven, so it also runs in headless Chrome. Add `&reel=<id>&from=<n>` to resume an interrupted reel. The reel's `manifest.json` records the seed, day count and controller.

## Recovery and evidence

A storage failure freezes dispatch and physical time. “Retry storage” retries the retained batch; successful retry leaves the mission paused. Restarts restore the entire committed checkpoint, configuration, pinned prompt versions and accounting. Resume through `POST /api/treatment/resume` or `POST /api/resume` with `{"session_id":"..."}`. An old writer's lease must expire before a new process can take ownership. Treatment recovery requires a new image before decisions resume.

Session playback reads recorded samples; it never reissues actions. Sequence gaps are displayed without fabricated motion. PNGs, scans and compressed traces live in private Storage, and the local server mediates reads. JSON exports are operator evidence, not model observations.

A terminal/paused-session review can propose one immutable prompt candidate. A frozen four-case baseline/candidate campaign retains every child session. Activation requires a saved passing evaluation; inconclusive results leave the baseline in place. Rollback changes only future defaults.

## Validation

See `docs/VALIDATION.md` for milestone status, exact evidence paths and incomplete gates. `docs/BUILD_PLAN.md` is the supplied contract. Successful synthetic or scripted tests do not establish live model performance. All quantities are simulation parameters, not agricultural or robot safety recommendations.

## Telemetry, incidents and the orchestrator

Every robot emits telemetry independently of inference: a health sample at each 0.05 s physics substep and a 1 Hz heartbeat, carrying position, battery, water, lifecycle, waiting reason, fault, progress markers and, for arm workers, six joint angles, tool pose, jaw opening, force, load and contact. Samples are chunked into ≤2-simulated-second gzip artifacts and committed with the session's events; heartbeats are also kept in memory for queries.

Health is computed by code from those heartbeats (`healthy`, `healthy_wait`, `stale_heartbeat`, `stalled`, `possible_loop`, `disabled`) and incidents are opened once per robot and kind while a condition holds (breakdown, stale heartbeat, stall, loop, storage), then closed when it clears. In live fleet mode a new incident engages the orchestrator at once with two non-physical tools: `query_telemetry(robot, since_sim_time)` returns a bounded heartbeat history in its next observation, and `respond_incident(incident_id, decision, reason)` records `continue`, `retrieve`, `reassign`, `stop` or `escalate`; escalate pauses the mission for a human. Neither tool can change physical state, and three queries in a row without a physical decision count as a failure.

On the orchard page, selecting a machine opens its telemetry panel: health, state, task, battery, water, heartbeat age, time since progress, fault, arm joints and load, the robot's last model decision in its own words, and its recent events. Open incidents and escalations show in the strip beside the status badge.
