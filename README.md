# Schwarz Git Ready Barcelona Hackathon — OSI ↔ Databricks ↔ Gemini

A working prototype that lets **Google Gemini** consume a **Databricks Unity Catalog Metric View** as an **Open Semantic Interchange (OSI v1.0)** model — and round-trip back. Built for the Schwarz Git Ready Barcelona Hackathon to demonstrate OSI as the vendor-neutral contract between semantic models and AI agents.

```
                          Gemini (Databricks-hosted FMAPI)
                                      │
                                      ▼  OpenAI-compatible tool-calling
                          OSI Bridge (this repo, FastMCP + FastAPI)
                            │                 │
            registry ◄──────┤                 ▼  databricks-sql-connector
   (file | sqlite |        │     Databricks SQL Warehouse
    lakebase | mongo)       │           └── Unity Catalog Metric View
                            ▼
                      Other vendors (Dremio, Strategy Mosaic)
                      via per-engine translators
```

The bridge loads a registry of OSI v1.0 YAML semantic models and exposes four MCP tools (`list_models`, `list_metrics`, `list_dimensions`, `query_metric`) that Gemini calls in a manual tool-calling loop. Ship multiple datasets in one bridge — the agent picks the right model per question.

## What this build adds (Barcelona Hackathon delta)

The fork extends the base OSI Bridge with a workspace-wide governance loop and a bi-directional Metric View ↔ OSI translator surfaced through the portal:

- **Workspace sync.** `Admin → Sync all to MongoDB` discovers every Metric View the SQL warehouse can see (via `system.information_schema.tables`), translates each to OSI v1.0, and upserts into a (mock) MongoDB. Discovery is scope-filterable (catalog, schema).
- **Per-MV export.** Each discovered view ships **Download OSI YAML** (streamed as a real `.osi.yaml` file) and **Upload to MongoDB** (single-view upsert with version history). The Mongo doc is OSI shape, not Databricks MV shape — verify at `/api/admin/mongo-models/<name>`.
- **Import OSI → Databricks Metric View.** Upload an OSI YAML and a target catalog/schema; the portal translates back to Databricks Metric View YAML (v0.1) and runs `CREATE OR REPLACE VIEW … WITH METRICS LANGUAGE YAML` against the warehouse. Round-trips cleanly: export `orders_mv` → import as `orders_mv_imported` → `MEASURE(total_revenue)` returns identical numbers.
- **Mock MongoDB store** (`osi_bridge/store/mongo.py`) using **mongomock** so the demo runs entirely in memory. Swapping to real Mongo is one line: pass `client=MongoClient(uri)` to `MongoModelStore`.
- **Chat hardening.** `query_metric.filters` accepts column aliases (`column | dimension | field | name | key`) and value aliases (`value | val | values`); list values render as `IN(...)`. The tool schema and system prompt now nudge Gemini to use literal dimension values from descriptions (e.g. `value='DE'` for "Germany").

### Where the new code lives

| Path | Purpose |
|------|---------|
| `osi_bridge/discovery.py` | `list_metric_views(catalogs?, schemas?)` — workspace-wide Metric View discovery |
| `osi_bridge/store/mongo.py` | `MongoModelStore` — mongomock-backed (or pymongo) registry implementation |
| `osi_bridge/importer.py` | `osi_to_mv_yaml`, `create_metric_view`, `import_osi` — the inverse of the exporter |
| `portal/app.py` (new endpoints) | `/api/admin/discover`, `/api/admin/export-osi`, `/api/admin/upload-to-mongo`, `/api/admin/sync-from-workspace`, `/api/admin/import-osi`, `/api/admin/mongo-models[/{name}]` |
| `portal/static/app.js` (new components) | `Admin` (workspace sync + per-MV actions) and `ImportOsi` (file picker → MV creation) |
| `osi_bridge/translators/_common.py` | Filter-shape aliasing + `IN(...)` list rendering |
| `portal/chat.py` | Tighter `query_metric` tool schema + system prompt that maps friendly names to literal dimension values |

### Try the new features in 30 seconds

```bash
# Already running the portal? Open the Admin tab:
open http://localhost:8000/#/admin

# Or drive the API directly:
curl -sS -X POST "http://localhost:8000/api/admin/sync-from-workspace?catalogs=peymandemoaws_catalog&schemas=osi_demo" | jq

# Round-trip one MV: export → import as a new view
curl -sS "http://localhost:8000/api/admin/export-osi?fqn=peymandemoaws_catalog.osi_demo.orders_mv" -o /tmp/orders.osi.yaml
curl -sS -X POST http://localhost:8000/api/admin/import-osi \
  -F "file=@/tmp/orders.osi.yaml" \
  -F "target_catalog=peymandemoaws_catalog" \
  -F "target_schema=osi_demo" \
  -F "target_name=orders_mv_imported"
```

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
| `osi_bridge/provisioning/` | REST-based access provisioning across the same engines, with audit-log persistence in the store |
| `osi_bridge/producer/` | Bottom-up producer journey — schema inspection, AI contract drafting, GitHub publishing |
| `osi_bridge/lineage.py` | Lineage view backed by `system.access.table_lineage` + the model store's version history |
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

## Testing everything end-to-end

See [TESTING.md](TESTING.md) for a single linear walkthrough that exercises every phase (registry → ODCS → portal → vendor adapters → provisioning → producer journey → lineage → approval). Each step lists the command, what to expect, and which credentials it needs — most of the bridge is testable offline.

## Running the demo

A deployment of this portal is live at https://git-ready-portal-7474644741537065.aws.databricksapps.com (`fevm-peymandemoaws` workspace). See [DEMO.md](DEMO.md) for the five-minute pitch, the twenty-minute full hackathon story, talking points by audience, and a troubleshooting checklist.

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

For the Schwarz Git Ready Barcelona Hackathon hackathon the bridge ships four models out of the box:

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

### 13. Access provisioning + audit log (Phase 4)

Hitting **Request access** on a metric detail page now fans out to every engine the OSI declares:

- Databricks → `GRANT SELECT ON TABLE <fqn> TO \`<email>\`` via the SQL warehouse
- Dremio → `POST /api/v3/catalog/by-path/<path>/privileges` with `{"principal":…,"privileges":["SELECT"]}`
- Strategy Mosaic → `PUT /api/v1/projects/<id>/permissions/users/<email>` with `{"role":"consumer"}` (override the role via `STRATEGY_PERMISSION_ROLE`)

Engines whose credentials are missing return `status: "skipped"` with the exact call they would have made, so the demo still shows the contract on machines that aren't wired up to every vendor. Pass `"dry_run": true` in the POST body to render without calling anything.

Each request and its per-engine outcomes are persisted to the `osi_access_requests` / `osi_access_grants` tables when `PORTAL_STORE` is `sqlite` or `lakebase`; the file-backed mode falls back to an in-memory log. The **My requests** page in the portal lists them and a row click renders the audit detail.

```bash
# All three engines visible in one request
curl -sX POST http://localhost:8000/api/access-requests \
  -H 'content-type: application/json' \
  -d '{"model":"orders_multivendor_mv","requester":"alice@schwarz.com"}' | jq
```

### 14. Producer journey (Phase 5)

The portal's **Publish** page lets a data producer point at a UC table, get a Gemini-drafted OSI + ODCS pair, and commit it to a contracts repo in one click:

1. **Describe.** Provide the source FQN, a domain, an owner email, and a short description.
2. **Infer.** The bridge runs `DESCRIBE TABLE EXTENDED <fqn> AS JSON` against your warehouse, hands the column list to Gemini, and returns a complete OSI + ODCS YAML pair.
3. **Publish.** Both YAMLs are committed to the GitHub contracts repo (`GITHUB_CONTRACTS_REPO`) and the new model is upserted into the local store so the catalog sees it immediately.

Set `GITHUB_TOKEN`, `GITHUB_CONTRACTS_REPO`, and (optionally) `GITHUB_BRANCH` / `GITHUB_OSI_SUBDIR` / `GITHUB_ODCS_SUBDIR` to enable the real Git path. Without these, **Publish** runs in dry-run mode: it records the diff that would have been committed and still persists to the local store, so the demo path works offline.

```bash
curl -sX POST http://localhost:8000/api/producer/infer \
  -H 'content-type: application/json' \
  -d '{"fqn":"main.retail.checkouts","domain":"retail","owner":"retail@schwarz.com","dry_run":true}' | jq .metrics_summary
```

### 15. Lineage + owner-approval gating (Phase 6)

Every model detail page now carries a **Lineage** section. Upstream and downstream tables come from a live query against `system.access.table_lineage` when the SQL warehouse is reachable; otherwise a synthetic projection (the FQN's `_raw` upstream and a couple of plausible downstream consumers) renders so the demo still tells the story. The contract version log on the same panel comes from `osi_model_versions` — every ingestion is one row.

```bash
curl -s http://localhost:8000/api/models/lidlplus_transactions_mv/lineage | jq
```

Access requests on any model that declares an ODCS owner (in `custom_extensions.odcs.owner`) now start in `pending_approval` instead of firing the engine fan-out immediately. The new **Approvals** page in the portal lets a model owner "sign in as" themselves, see the queue filtered to their models, and approve or reject:

```bash
# Approve a pending request and let the bridge fire grant_all.
curl -sX POST http://localhost:8000/api/access-requests/<id>/approve \
  -H 'content-type: application/json' \
  -d '{"approver":"lidlplus.platform@schwarz.com","reason":"standard tier"}' | jq

# Or reject with a reason — audit trail captures both.
curl -sX POST http://localhost:8000/api/access-requests/<id>/reject \
  -H 'content-type: application/json' \
  -d '{"approver":"lidlplus.platform@schwarz.com","reason":"duplicate"}'
```

Pass `"auto_approve": true` in the original request POST to bypass approval for self-service tiers. Models without an `odcs.owner` (the multi-vendor fixture, for example) skip approval and go straight to the fan-out exactly as Phase 4 did.

### 16. (Stretch) Bring your own vendor

Drop a `osi_bridge/translators/<vendor>.py` implementing `build_query` + `execute` + `ENGINE_NAME`, add it to the priority tuple in `osi_bridge/translators/__init__.py`, and any OSI model with a `custom_extensions.<vendor>` block becomes addressable. For provisioning, add a matching `osi_bridge/provisioning/<vendor>.py` exposing `grant()` and register it in `osi_bridge/provisioning/service.py`.

## Architecture and demo script

- `docs/ARCHITECTURE.md` — components, why no Cube, vendor-swap pattern.
- `docs/DEMO_SCRIPT.md` — the five-minute panel walkthrough.

## Security notes for forks

- `.env` is gitignored; never commit real tokens.
- The `agent_metadata.yaml` is the demo's metadata — replace with your own for your domain.
- The bridge has no auth on the MCP endpoint by default — bind it to `localhost` (`OSI_BRIDGE_HOST=127.0.0.1`) for any non-demo usage, or front it with mTLS / an API key check.

## License

Apache 2.0.
