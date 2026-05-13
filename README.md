# OSI ↔ Databricks ↔ Gemini Prototype

A working prototype that lets **Google Gemini** consume a **Databricks Unity Catalog Metric View** as an **Open Semantic Interchange (OSI v1.0)** model — without Cube in the middle.

```
Gemini (Databricks-hosted, OpenAI-compatible endpoint)
    │
    ▼  MCP / SSE
OSI Bridge (this repo, ~250 LOC Python)
    │
    ▼  databricks-sql-connector
Databricks SQL Warehouse
    └── Unity Catalog Metric View   ← source of truth
```

The bridge loads a registry of OSI v1.0 YAML semantic models and exposes four MCP tools (`list_models`, `list_metrics`, `list_dimensions`, `query_metric`) that Gemini calls automatically via a manual tool-calling loop. Ship multiple datasets in one bridge — agents pick the right model per question.

## What's in this repo

| Path | Purpose |
|------|---------|
| `notebooks/01_create_metric_view.py` | Creates the demo Metric View on `samples.tpch.orders` |
| `notebooks/02_export_to_osi.py` | Reads a Metric View and writes its OSI YAML |
| `notebooks/03_test_queries.py` | Sanity-check `MEASURE()` queries |
| `notebooks/10_nytaxi_metric_view.py` | NY Taxi Metric View on `samples.nyctaxi.trips` |
| `notebooks/11_tpc_sales_metric_view.py` | TPC benchmark sales Metric View (defaults to `samples.tpch.lineitem`) |
| `notebooks/12_lidlplus_metric_view.py` | Seeds a synthetic lidlplus transactions table + Metric View |
| `osi_bridge/server.py` | MCP server (registry of OSI models) Gemini connects to |
| `osi_bridge/tools.py` | Plain-Python implementations of the four bridge tools |
| `osi_bridge/registry.py` | Delegates to a pluggable `ModelStore` (file / sqlite / lakebase) |
| `osi_bridge/exporter.py` | Standalone Databricks Metric View → OSI YAML converter |
| `osi_bridge/translator.py` | Phase 0 import path — re-exports the Databricks adapter's `build_sql` |
| `osi_bridge/translators/` | Per-vendor adapter package: `databricks.py`, `dremio.py`, `strategy.py`, dispatcher in `__init__.py` |
| `osi_bridge/search.py` | Metric search ranker + Gemini-backed AI fallback |
| `portal/app.py` | FastAPI portal (catalog, search, chat, access requests) |
| `portal/chat.py` | In-process Gemini MCP-loop chat handler |
| `portal/static/index.html` + `app.js` | preact/htm single-page UI, no build step |
| `portal/app.yaml` | Databricks Apps manifest for one-command deploy |
| `osi_bridge/parsers/osi.py` | OSI YAML loader + validator |
| `osi_bridge/parsers/odcs.py` | ODCS v3 YAML → canonical OSI dict |
| `osi_bridge/parsers/confluence.py` | Confluence page → OSI `ai_context` enrichment |
| `osi_bridge/store/file.py` | File-backed model store (Phase 0 behaviour) |
| `osi_bridge/store/sqlite.py` | SQLite-backed model store for local dev |
| `osi_bridge/store/lakebase.py` | Databricks Lakebase / Postgres model store |
| `osi_bridge/store/schema.sql` | Postgres DDL for the model + version-history tables |
| `osi_bridge/metadata/*.yaml` | Per-model companion metadata (synonyms, display names) |
| `examples/models/*.osi.yaml` | Sample OSI YAML stubs — one per dataset |
| `examples/odcs/*.odcs.yaml` | Sample ODCS v3 contracts for the four datasets |
| `examples/gemini_client.py` | Minimal Gemini client (Databricks-hosted, MCP loop) |
| `scripts/ingest_models.py` | Loads OSI + ODCS + Confluence into the model store |
| `docs/ARCHITECTURE.md` | Diagrams and component responsibilities |
| `docs/DEMO_SCRIPT.md` | The 5-minute hackathon demo |
| `deploy/upload_to_workspace.sh` | Pushes notebooks into your Databricks workspace |

## Prerequisites

- Python 3.11+ (`python3 --version`)
- A Databricks workspace with Unity Catalog and a SQL warehouse
- The Databricks CLI configured with a profile pointing at your workspace
- Access to **Databricks Foundation Model APIs** (Gemini 2.5 Flash or Pro). No Google API key required.

## Step-by-step guide

### 1. Clone and install

```bash
git clone https://github.com/<your-fork>/osi-databricks-gemini.git
cd osi-databricks-gemini
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 2. Authenticate to your Databricks workspace

```bash
databricks auth login --host https://<your-workspace>.cloud.databricks.com --profile <your-profile>
databricks current-user me --profile <your-profile>   # verify
```

### 3. Edit `.env`

Set at minimum:

| Variable | What to put |
|----------|-------------|
| `DATABRICKS_PROFILE` | the CLI profile name from step 2 |
| `DATABRICKS_HOST` | `https://<your-workspace>.cloud.databricks.com` |
| `DATABRICKS_HTTP_PATH` | the SQL warehouse path (`Compute → SQL Warehouses → your warehouse → Connection details → HTTP path`) |
| `DATABRICKS_TOKEN` | a PAT (`User Settings → Developer → Access tokens`) or any OAuth Bearer token |
| `OSI_CATALOG` | a catalog you have CREATE access to. Often `main`; on FEVM workspaces typically `<workspace>_catalog` |
| `OSI_SCHEMA` | default `osi_demo` is fine |
| `OSI_METRIC_VIEW` | default `orders_mv` is fine |
| `GEMINI_MODEL` | `databricks-gemini-2-5-flash` or `databricks-gemini-2-5-pro` |

### 4. Push notebooks to your workspace

```bash
bash deploy/upload_to_workspace.sh
```
Uploads the three notebooks to `/Users/<you>/osi-demo/`.

### 5. Create the Metric View

Open `01_create_metric_view` in your workspace and attach it to a serverless or all-purpose cluster. Set the widgets at the top to match your `OSI_CATALOG` / `OSI_SCHEMA` / `OSI_METRIC_VIEW`, then **Run All**. You should see five rows in the sanity query at the bottom (revenue by `order_priority`).

### 6. Export to OSI YAML

Two paths — pick one.

**6a. From your laptop (recommended for the bridge demo):**
```bash
python -m osi_bridge.exporter \
  --fqn "$OSI_CATALOG.$OSI_SCHEMA.$OSI_METRIC_VIEW" \
  --out examples/models/orders.osi.yaml
```
The exporter auto-merges the matching `osi_bridge/metadata/<view>.yaml` (or pass `--metadata` explicitly).

**6b. From the workspace notebook:** open `02_export_to_osi`, set the widgets, **Run All**. Output lands at `/Workspace/Users/<you>/osi-demo/model.osi.yaml` — copy it under `examples/models/`.

### 7. Start the OSI Bridge MCP server

The bridge serves every `*.osi.yaml` in a directory as a separately addressable model:
```bash
python -m osi_bridge.server --models-dir examples/models
```
You should see:
```
[OSI Bridge] Loaded 4 model(s) from examples/models: ['lidlplus_transactions_mv', 'nyctaxi_trips_mv', 'orders_mv', 'tpc_sales_mv']
[OSI Bridge] MCP server listening on http://localhost:8000/sse
```
Single-file mode still works for back-compat: `--osi-model examples/models/orders.osi.yaml`.

### 8. Run the Gemini client

In another terminal (with `.venv` activated):
```bash
python examples/gemini_client.py "What was total revenue by order priority?"
```
You'll see the MCP tool calls Gemini issues, then a natural-language answer with concrete numbers.

### 9. Adding more datasets

For the GIT READY hackathon the bridge ships four models out of the box:

| Model name | Dataset | Notebook |
|-----------|---------|----------|
| `orders_mv` | TPC-H orders (`samples.tpch.orders`) | `01_create_metric_view.py` |
| `nyctaxi_trips_mv` | NYC yellow-cab trips (`samples.nyctaxi.trips`) | `10_nytaxi_metric_view.py` |
| `tpc_sales_mv` | TPC benchmark sales line items (default: `samples.tpch.lineitem`) | `11_tpc_sales_metric_view.py` |
| `lidlplus_transactions_mv` | Synthetic lidlplus transactions (seeded by the notebook) | `12_lidlplus_metric_view.py` |

Run the notebook for whichever datasets you want, re-export each with `osi_bridge.exporter`, drop the resulting YAMLs into `examples/models/`, and the bridge picks them up on restart.

### 10. Ingest into a model store (Phase 1)

The bridge can read OSI models from disk *or* from a database. For the hackathon's "YAML in DB instead of files" requirement, run the ingestion CLI once, then start the server in `--store sqlite|lakebase` mode.

```bash
# Local dev — SQLite store, parses both OSI + ODCS
python -m scripts.ingest_models \
  --store sqlite --sqlite-path osi_bridge.db \
  --osi-dir examples/models \
  --odcs-dir examples/odcs

# Lakebase / Postgres — same files, real Lakebase instance
export OSI_BRIDGE_PG_DSN="postgresql://<user>:<oauth-token>@<lakebase-host>:5432/databricks_postgres?sslmode=require"
python -m scripts.ingest_models --store lakebase --osi-dir examples/models --odcs-dir examples/odcs

# Optional Confluence enrichment (merges page body into ai_context.instructions)
export CONFLUENCE_BASE_URL=https://schwarz.atlassian.net
export CONFLUENCE_TOKEN=...
python -m scripts.ingest_models --store sqlite --sqlite-path osi_bridge.db \
  --osi-dir examples/models --confluence-map orders_mv=1234567
```

Then point the server at the store:
```bash
python -m osi_bridge.server --store sqlite --sqlite-path osi_bridge.db
# or
python -m osi_bridge.server --store lakebase   # reads $OSI_BRIDGE_PG_DSN
```

Each ingestion appends an immutable row to `osi_model_versions` — the audit trail Schwarz needs for contract-revision history.

### 11. Run the portal (Phase 2)

```bash
# Make sure the SQLite store has been populated by step 10.
PORTAL_STORE=sqlite uvicorn portal.app:app --host 0.0.0.0 --port 8000
# Then open http://localhost:8000
```

The portal serves three pages:

- **Catalog** — typeahead search across every metric, ranked by name/synonym/display-name match. Zero-hit searches trigger an AI fallback that asks Gemini to suggest the closest model and surface the owner.
- **Metric detail** — full OSI projection for one model (metrics, dimensions, source FQN, ODCS owner/domain), plus a "Request access" form whose POST is logged in-memory (Phase 4 will turn this into real REST provisioning).
- **Chat** — wraps the Gemini MCP loop in-process. Every question becomes `list_models` → `list_metrics` → `list_dimensions` → `query_metric`, with the full tool trace visible in a collapsible details panel.

Deploy as a Databricks App:
```bash
databricks apps deploy --source-code-path . --app-name git-ready-portal
```
See `portal/app.yaml` for the manifest and env-var configuration.

### 12. Multi-vendor execution (Phase 3)

The bridge has three vendor adapters: `databricks`, `dremio`, `strategy`. Each one renders an OSI metric request into the format the engine wants (SQL with `MEASURE()` for Databricks, inlined-expression SQL for Dremio, REST body for Strategy Mosaic) and can execute it when the right credentials are present.

`examples/models/orders_multivendor.osi.yaml` declares all three engines on the same OSI contract. Try the dispatcher:

```bash
python -c "
from osi_bridge.registry import Registry
from osi_bridge import translators
r = Registry.from_path('examples/models')
osi = r.get('orders_multivendor_mv')
for eng in ['databricks','dremio','strategy']:
    q = translators.build_query(osi, ['total_revenue'], ['order_priority'], engine=eng)
    print(eng, '->', q.kind, q.payload if isinstance(q.payload,str) else list(q.payload.keys()))
"
```

From the chat / `query_metric` tool, pass `engine="dremio"` (or `"strategy"`) to force the adapter. When the engine has no credentials configured, the response includes the rendered query and `executable: false` so the portal can still demo the contract — same OSI, three engines, one tool call.

Set `DREMIO_BASE_URL` / `DREMIO_TOKEN` and `STRATEGY_BASE_URL` / `STRATEGY_TOKEN` (see `.env.example`) to enable actual execution.

### 13. (Stretch) Bring your own vendor

Drop a `osi_bridge/translators/<vendor>.py` implementing `build_query` + `execute` + `ENGINE_NAME`, add it to the priority tuple in `osi_bridge/translators/__init__.py`, and any OSI model with a `custom_extensions.<vendor>` block becomes addressable.

## Architecture and demo script

- `docs/ARCHITECTURE.md` — components, why no Cube, vendor-swap pattern.
- `docs/DEMO_SCRIPT.md` — the five-minute panel walkthrough.

## Security notes for forks

- `.env` is gitignored; never commit real tokens.
- The `agent_metadata.yaml` is the demo's metadata — replace with your own for your domain.
- The bridge has no auth on the MCP endpoint by default — bind it to `localhost` (`OSI_BRIDGE_HOST=127.0.0.1`) for any non-demo usage, or front it with mTLS / an API key check.

## License

Apache 2.0.
