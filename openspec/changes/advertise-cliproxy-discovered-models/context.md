# Advertise CLIProxyAPI discovered models

Unify-sidecar catalog advertising lists only configured full-model IDs.
That matches OpenRouter/OrcaRouter operators who pin models from the
discovered-models browser. CLIProxyAPI on this host is prefix-routed
(`claude`, `cc/`) with an empty full-model list, so `/v1/models` showed
zero Claude IDs while OpenRouter/OrcaRouter pinned IDs still appeared.

CLIProxyAPI `/v1/models` is healthy (15 models on the last connection
test). Dashboard `GET /api/models` already appends those discovered IDs.
The public OpenAI catalog did not.

Advertise discovered IDs that `resolve_sidecar_route` would send to
CLIProxyAPI. That restores the original Claude sidecar catalog behavior
without dumping unrelated CLIProxyAPI-listed vendors into the catalog.
