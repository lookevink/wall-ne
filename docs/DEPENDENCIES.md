# Runtime and sources

Selected runtime: Python 3.9.6 (standard library), Node 26.3.1, npm 11.16.0.
Pinned rendering dependencies: Three.js 0.180.0 (MIT) and @dgreenheck/ez-tree 1.1.0 (MIT). Their license texts are distributed in `docs/licenses/`; EZ-Tree's embedded asset attribution remains in the installed package.

Crusoe's official [serverless inference quickstart](https://docs.cloud.crusoe.ai/quickstart/getting-started-with-serverless-inference/index.html) specifies the OpenAI-compatible base `https://api.inference.crusoecloud.com/v1` (verified October 17, 2026). Endpoint and all model IDs remain environment configurable.

The authenticated Crusoe `/v1/models` inventory was checked on October 17, 2026. Its canonical text-role IDs are `nvidia/NVIDIA-Nemotron-3-Super-120B-A12B` and `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`. The supplied shorter spellings returned HTTP 404. The adapter normalizes only those two equivalent names; it does not substitute another model family or provider. The Omni ID is unchanged. Persisted session configuration records the exact canonical ID used.
