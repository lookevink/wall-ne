# Authoritative boundaries

`engine.py`, `treatment.py`, `care.py` and `manipulation.py` own physical state. Commands return stable receipts; world checkpoints serialize receipts, inventories, ledgers and pending actions. `observations()` is a filtered policy projection; `snapshot()` is privileged operator/rendering state.

`Runtime` is a session writer with an independent fencing identity. It commits accepted commands before stepping physics. Every physical step is sampled; progress, telemetry, receipts and the matching checkpoint share a database sequence boundary. Artifacts upload first under content hashes. A failed commit retains the same batch ID and blocks new work. The server never treats a local cache as a persistence substitute.

`TreatmentRuntime` coordinates request-specific browser captures and scans. Python decodes actual bounded PNG bytes, validates frame/revision identity, and waits for durable artifacts before using evidence. The renderer computes first-surface depth from visible geometry; Python validates rays and independently computes tool contact. No browser API accepts arbitrary robot telemetry or a replacement world state.

`arm.py` provides analytic six-joint FK/IK and sampled swept-link collision checks. `manipulation.py` adds measured grip/load, side-slip, root resistance, extraction and release-in-bin rules. These are explicit kinematic simulation rules, not a rigid-body or hardware model.

`inference.py` sends one required tool call per request outside the simulation lock. Only the validated command seam mutates the world. `review.py` filters evidence and applies the fixed promotion metric; `evaluation.py` runs finite paired sessions under a frozen manifest. SQL additionally protects immutable prompt contents and activation requirements.
