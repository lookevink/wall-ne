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
- **Manipulation:** select a live provider and a sensor condition. `known` is explicitly a supplied-coordinate diagnostic. It is not evidence of visual localization. Wrist and alignment modes enforce visual assessment plus independently measured contact/load before lifting.

Crusoe is primary; live treatment defaults to Gemma 4. Two consecutive provider/protocol failures switch the affected role to its pinned AI Gateway fallback for the rest of the session. Physical misses and rejected actions do not trigger fallback. Gemini, Nemotron VL and Gemma remain explicit Gateway comparison conditions. See [the wrist control and routing notes](docs/WRIST_CONTROL.md). `AI_GATEWAY_KEY` is accepted as an alias for `AI_GATEWAY_API_KEY`. Missing credentials, failed inference and exhausted budgets produce blocked results; there is no silent offline fallback.

## Recovery and evidence

A storage failure freezes dispatch and physical time. “Retry storage” retries the retained batch; successful retry leaves the mission paused. Restarts restore the entire committed checkpoint, configuration, pinned prompt versions and accounting. Resume through `POST /api/treatment/resume` or `POST /api/resume` with `{"session_id":"..."}`. An old writer's lease must expire before a new process can take ownership. Treatment recovery requires a new image before decisions resume.

Session playback reads recorded samples; it never reissues actions. Sequence gaps are displayed without fabricated motion. PNGs, scans and compressed traces live in private Storage, and the local server mediates reads. JSON exports are operator evidence, not model observations.

A terminal/paused-session review can propose one immutable prompt candidate. A frozen four-case baseline/candidate campaign retains every child session. Activation requires a saved passing evaluation; inconclusive results leave the baseline in place. Rollback changes only future defaults.

## Validation

See `docs/VALIDATION.md` for milestone status, exact evidence paths and incomplete gates. `docs/BUILD_PLAN.md` is the supplied contract. Successful synthetic or scripted tests do not establish live model performance. All quantities are simulation parameters, not agricultural or robot safety recommendations.
