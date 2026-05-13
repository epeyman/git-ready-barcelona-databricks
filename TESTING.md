# Testing guide

A linear, phase-by-phase walkthrough that exercises every feature the seven commits added. Each step lists the command, what to expect, and which credentials it requires.

Two modes throughout:

- **Offline** — no Databricks / Dremio / Strategy / GitHub credentials needed. Demonstrates the contract, the rendering, and the audit story. Most of the bridge is testable this way.
- **Live** — requires `DATABRICKS_*` (always) plus optional `DREMIO_*`, `STRATEGY_*`, `GITHUB_*`. Exercises the real grants, real SQL, real commits.

Your local `.env` has `DATABRICKS_HOST`, `DATABRICKS_HTTP_PATH`, and `DATABRICKS_TOKEN` set already, so live Databricks paths just work. Dremio, Strategy, and GitHub stay offline unless you fill in the corresponding env vars.

## 0. One-time setup

```bash
cd ~/Projects/osi-databricks-gemini
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Confirm imports succeed:

```bash
python -c "from osi_bridge.registry import Registry; from osi_bridge.translators import build_query; from portal.app import app; print('imports OK')"
```

Expect: `imports OK`.

## 1. Phase 0 — multi-model registry

Verify the four shipped models load from disk and the dispatcher renders SQL for each.

```bash
python -c "
from osi_bridge.registry import Registry
from osi_bridge.translators import build_query
r = Registry.from_path('examples/models')
print('Models:', r.names())
for n in r.names():
    osi = r.get(n)
    metrics = osi['semantic_model'][0].get('metrics', [])
    if not metrics: continue
    m = metrics[0]['name']
    q = build_query(osi, [m])
    print(f'  {n}: first metric {m} -> {len(q.payload.splitlines())} line SQL')
"
```

Expect a list with `lidlplus_transactions_mv`, `nyctaxi_trips_mv`, `orders_multivendor_mv`, `orders_mv`, `tpc_sales_mv` and one rendered SQL line-count per model.

## 2. Phase 1 — ODCS parser, Confluence merge, model store

```bash
# ODCS projection for all four contracts
python -c "
from pathlib import Path
from osi_bridge.parsers.odcs import load_odcs_yaml, odcs_to_osi
for f in sorted(Path('examples/odcs').glob('*.odcs.yaml')):
    osi = odcs_to_osi(load_odcs_yaml(f))
    sm = osi['semantic_model'][0]
    ext = sm['custom_extensions']['odcs']
    print(f.name, '->', sm['name'], 'domain=', ext['domain'], 'owner=', ext['owner'])
"
```

Expect four rows with correct domain + owner.

```bash
# Ingest both OSI + ODCS into a fresh SQLite store
rm -f osi_bridge.db
python -m scripts.ingest_models \
  --store sqlite --sqlite-path osi_bridge.db \
  --osi-dir examples/models --odcs-dir examples/odcs
```

Expect a `saved <model> v1` line for each of the five OSI files (the multivendor one ingests as OSI-only since it has no companion ODCS).

```bash
# Re-ingest to bump versions
python -m scripts.ingest_models \
  --store sqlite --sqlite-path osi_bridge.db \
  --osi-dir examples/models --odcs-dir examples/odcs
python -c "
from osi_bridge.store.sqlite import SqliteModelStore
s = SqliteModelStore('osi_bridge.db')
print('orders_mv history:', s.history('orders_mv'))
"
```

Expect two versions in the history with timestamps.

Confluence merge (synthetic page — no live Confluence creds needed):

```bash
python -c "
from osi_bridge.store.sqlite import SqliteModelStore
from osi_bridge.parsers.confluence import merge_confluence_into_osi, _html_to_text
s = SqliteModelStore('osi_bridge.db')
osi = s.get('orders_mv')
page = {'title': 'Sales Glossary',
        'body_html': '<p>Revenue is <strong>net of returns</strong>.</p>',
        'url': 'https://example/wiki/123'}
page['body_text'] = _html_to_text(page['body_html'])
merge_confluence_into_osi(osi, page)
print(osi['semantic_model'][0]['ai_context']['instructions'][-200:])
"
```

Expect the Confluence text to appear at the end of `ai_context.instructions`.

## 3. Phase 2 — portal MVP

Start the portal against the SQLite store seeded above:

```bash
PORTAL_STORE=sqlite uvicorn portal.app:app --host 127.0.0.1 --port 8000
```

Expect a startup line listing the five models and `Registry loaded from sqlite: [...]`.

In another terminal:

```bash
curl -s http://127.0.0.1:8000/api/health | python -m json.tool
```

Expect `status: ok`, `persistent_access_log: true`, `git_publishing_configured: false`.

Browser tests (`http://localhost:8000`):

- **Catalog** — five model cards. Type `basket` → `avg_basket` appears with score `15.0`. Type `fare` → both NY Taxi metrics rank ~16.5. Type a metric that does not exist (`gross margin`) → the AI fallback box renders with Gemini's suggestion (this requires the Databricks Foundation Model API; if that's not enabled the box will show "AI fallback unavailable").
- **Catalog → click any model card** — Detail page renders source, owner (when ingested via ODCS), metric and dimension lists, engine pills.
- **Chat** — ask "What is the average basket in Germany by loyalty tier?". Expect the trace to expand and show `list_models → list_metrics → list_dimensions → query_metric`. The answer will quote real numbers if Databricks SQL is reachable. If the placeholder FQNs aren't real tables in your workspace, you'll see a `query_metric` failure in the trace and a graceful "I couldn't run the query" answer.
- **My requests** — empty for now; you'll come back here in Phase 4 / 6.

## 4. Phase 3 — vendor adapters

The orders_multivendor_mv model declares Databricks, Dremio, and Strategy. Render all three:

```bash
python -c "
from osi_bridge.registry import Registry
from osi_bridge import translators
r = Registry.from_path('examples/models')
osi = r.get('orders_multivendor_mv')
print('engines:', translators.available_engines(osi))
for eng in ['databricks','dremio','strategy']:
    q = translators.build_query(osi, ['total_revenue'], ['order_priority'], engine=eng)
    print(eng, '->', q.kind, 'executable=', q.metadata.get('executable', True))
    print(q.payload if isinstance(q.payload, str) else q.payload)
    print()
"
```

Expect:
- Databricks: SQL using `MEASURE(total_revenue)`.
- Dremio: SQL with `SUM(o_totalprice) AS total_revenue` (inlined expression), `executable=False` unless you set DREMIO_*.
- Strategy: a JSON REST body with `metric_set_id`, `MET-1001`, `ATT-201` (via id maps), `executable=False` unless you set STRATEGY_*.

In the portal browser:

- Catalog → `orders_multivendor_mv` shows three engine pills (databricks default in indigo, dremio + strategy in slate).
- Detail page header shows the same three pills.

## 5. Phase 4 — REST provisioning + audit log

In the portal, on `orders_multivendor_mv` (no ODCS owner → no approval gate):

- Detail page → fill `your-email` → **Request access**. Expect three pills in the result panel: each engine with status `granted` or `failed` or `skipped` depending on credentials.
- Navigate to **My requests**. The new entry appears. Click it. The audit detail panel expands with the same per-engine rows.

CLI verification:

```bash
curl -sX POST http://127.0.0.1:8000/api/access-requests \
  -H 'content-type: application/json' \
  -d '{"model":"orders_multivendor_mv","requester":"alice@schwarz.com"}' | python -m json.tool
curl -s 'http://127.0.0.1:8000/api/access-requests' | python -m json.tool
```

Expect the request id, status, and per-engine grants. Stop and restart the portal — `GET /api/access-requests` still shows the row (SQLite persistence).

Dry-run path:

```bash
curl -sX POST http://127.0.0.1:8000/api/access-requests \
  -H 'content-type: application/json' \
  -d '{"model":"orders_multivendor_mv","requester":"alice@schwarz.com","dry_run":true}' | python -m json.tool
```

Expect all engines `dry-run` with the would-have-run SQL/REST detail attached.

## 6. Phase 5 — producer journey

Browser → **Publish** tab. Leave **Dry-run** on.

1. FQN `main.retail.checkouts`, domain `retail`, owner `you@databricks.com`, short description.
2. Click **Infer**. Review the synthetic columns and the AI/heuristic pill. Heuristic mode will be used unless DATABRICKS_TOKEN can reach a Gemini endpoint.
3. Click **Publish contract**. The Done panel shows two `dry-run` files and "store: persisted".
4. Click **View in catalog** — the new `checkouts_mv` model appears with metrics and dimensions.

CLI verification:

```bash
curl -sX POST http://127.0.0.1:8000/api/producer/infer \
  -H 'content-type: application/json' \
  -d '{"fqn":"main.retail.checkouts","domain":"retail","owner":"you@databricks.com","dry_run":true}' | python -c "import sys,json;d=json.load(sys.stdin);print('cols:',[c['name'] for c in d['columns']]);print('metrics:',d['metrics_summary'])"
```

Expect a synthetic column list and three heuristic metrics (`row_count`, `total_value`, `avg_value`).

For a **live publish** to GitHub (optional):

```bash
export GITHUB_TOKEN=<pat-with-contents-write>
export GITHUB_CONTRACTS_REPO=<owner>/<repo>
# Restart uvicorn so it picks up the env vars
```

Then uncheck **Dry-run** and Publish — the two files commit to the contracts repo and the result panel shows the commit links.

## 7. Phase 6 — lineage + approval

### Lineage

In the portal, open `lidlplus_transactions_mv` → scroll to the **Lineage** section.

- Mode pill is `live` (you have `DATABRICKS_*` set). Upstream / downstream lists are empty if the placeholder FQNs don't exist in your UC. Contract revision log shows two versions (from the two ingestions in step 2).
- Unset `DATABRICKS_HOST` in `.env`, restart the portal — the mode pill becomes `synthetic` and the lists render the demo `_raw` upstream and `reporting.dash.*` downstream.

CLI:

```bash
curl -s http://127.0.0.1:8000/api/models/lidlplus_transactions_mv/lineage | python -m json.tool
```

### Approval gating

`lidlplus_transactions_mv` has an ODCS owner — requests on it require approval.

As the analyst:

1. Detail page → **Request access** as `analyst@schwarz.com`. The result panel shows an amber `pending_approval` pill and the line "Pending approval by lidlplus.platform@schwarz.com."
2. Navigate to **My requests**. The request is there with status `pending_approval`.

As the owner:

3. **Approvals** tab. Type `lidlplus.platform@schwarz.com`, click **Sign in**. The queue shows the pending request.
4. Type a reason ("standard tier"), click **Approve**. The queue empties; the request now appears in **My requests** with the engine grant statuses (the same fan-out behavior from Phase 4 fires now, not on submit).
5. Submit a second request from any model with an owner. As the owner, **Reject** with a reason. The request shows `rejected` with the reason recorded.

CLI:

```bash
# Submit a request that goes to pending_approval
curl -sX POST http://127.0.0.1:8000/api/access-requests \
  -H 'content-type: application/json' \
  -d '{"model":"lidlplus_transactions_mv","requester":"analyst@schwarz.com"}' | python -m json.tool

# Filter the queue to the owner
curl -s 'http://127.0.0.1:8000/api/access-requests?owner=lidlplus.platform@schwarz.com&status=pending_approval' | python -m json.tool

# Approve (paste the id from the previous response)
curl -sX POST http://127.0.0.1:8000/api/access-requests/<id>/approve \
  -H 'content-type: application/json' \
  -d '{"approver":"lidlplus.platform@schwarz.com","reason":"standard tier"}' | python -m json.tool

# Try to approve again — expect HTTP 409
curl -sX POST http://127.0.0.1:8000/api/access-requests/<id>/approve \
  -H 'content-type: application/json' \
  -d '{"approver":"lidlplus.platform@schwarz.com"}' -w '\nHTTP %{http_code}\n'
```

Bypass approval with `auto_approve`:

```bash
curl -sX POST http://127.0.0.1:8000/api/access-requests \
  -H 'content-type: application/json' \
  -d '{"model":"lidlplus_transactions_mv","requester":"analyst@schwarz.com","auto_approve":true}' | python -m json.tool
```

Expect the request to skip `pending_approval` and go straight to the engine fan-out.

## 8. MCP path (parallel to the portal)

The OSI Bridge MCP server still serves the same tools to external agents:

```bash
python -m osi_bridge.server --store sqlite --sqlite-path osi_bridge.db
# In another terminal:
python examples/gemini_client.py "What is the average basket in Germany by loyalty tier?"
```

Expect a tool-calling loop with `list_models → list_metrics → list_dimensions → query_metric` and a natural-language answer (or a graceful error if your warehouse doesn't have the placeholder FQNs).

## What runs offline vs. needs credentials

| Step | Offline ok | Needs Databricks | Needs Dremio | Needs Strategy | Needs GitHub |
|---|---|---|---|---|---|
| 1 — registry + render | yes | — | — | — | — |
| 2 — ODCS parse, store, Confluence | yes | — | — | — | — |
| 3 — portal API + UI (catalog, detail, requests) | yes | — | — | — | — |
| 3 — portal chat | partial (renders, won't run queries) | yes (for chat to call Gemini + actually return numbers) | — | — | — |
| 4 — vendor adapter rendering | yes | — | — | — | — |
| 4 — adapter execute | — | yes (Databricks) | yes | yes | — |
| 5 — provisioning fan-out (dry-run) | yes | — | — | — | — |
| 5 — provisioning fan-out (live grants) | — | yes | yes | yes | — |
| 6 — producer infer (heuristic) | yes | — | — | — | — |
| 6 — producer infer (Gemini-enriched) | — | yes | — | — | — |
| 6 — producer publish (live to git) | — | — | — | — | yes |
| 7 — lineage (synthetic mode) | yes | — | — | — | — |
| 7 — lineage (live mode) | — | yes | — | — | — |
| 7 — approval gating | yes | — | — | — | — |
| 8 — MCP server + Gemini client | partial | yes (Gemini + queries) | — | — | — |

## Reset between runs

```bash
rm -f osi_bridge.db          # wipe the model store + audit trail
pkill -f "uvicorn portal"     # stop the portal
pkill -f "osi_bridge.server"  # stop the MCP server
```
