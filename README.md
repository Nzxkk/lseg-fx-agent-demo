# LSEG FX Agent Demo

This repository contains a standalone local demo for LSEG/Refinitiv FX signal research.

Main app:

```bash
cd lseg_fx_connector
./run_web_app.sh 8766
```

Then open:

```text
http://127.0.0.1:8766/
```

Notes:

- LSEG/Refinitiv market and Reuters news data require a valid local Workspace/Eikon session and data entitlements.
- LLM report/news scoring requires a Qwen/OpenAI-compatible API key configured locally or entered in the page.
- Runtime outputs are written to `lseg_fx_connector/output/` and are intentionally ignored by Git.
