# Demo guide — GIT READY data portal

A scripted walkthrough of the deployed portal, written so anyone can pick it up and run a five-minute or twenty-minute version of the demo. For local-only verification (no deployment), use `TESTING.md` instead.

## Live deployment

**URL:** https://git-ready-portal-7474644741537065.aws.databricksapps.com

**Auth:** Databricks SSO against the `fevm-peymandemoaws` workspace. Anyone with access to that workspace can open the URL.

**Backing resources** (all in `fevm-peymandemoaws`):
- Four Metric Views in `peymandemoaws_catalog.osi_demo` — `orders_mv`, `nyctaxi_trips_mv`, `tpc_sales_mv`, `lidlplus_transactions_mv`
- One Delta table `peymandemoaws_catalog.osi_demo.lidlplus_transactions` (5000 synthetic rows seeded by the lidlplus notebook)
- Four notebooks in `/Users/peyman.nasirifard@databricks.com/osi-demo/`
- One Databricks App `git-ready-portal` whose service principal `c2028963-1eb7-4e57-bd1f-2409aa7505f6` holds SELECT on the metric views

## Five-minute demo (the elevator pitch)

Goal: prove the contract, the conversational interface, and the multi-engine story in five minutes.

1. **Open the portal.** Catalog page shows the five OSI models, each with an engine pill. Point out `orders_multivendor_mv` — three engine pills (databricks, dremio, strategy) on one contract. "One semantic contract, three engines."

2. **Type `basket` in the search bar.** `avg_basket` from lidlplus surfaces first (score 15.0). Synonym chips show "basket size, aov" — the AI fallback also resolves cross-vocabulary search.

3. **Type `gross margin`** (a metric that does not exist). An amber AI-fallback panel appears with Gemini's suggestion: which models could approximate it, the owner email, and a one-sentence next step. *"When the metric doesn't exist, the portal points the user at the team that owns the closest data."*

4. **Click into `lidlplus_transactions_mv`.** Show the ODCS metadata (owner `lidlplus.platform@schwarz.com`, domain `retail`), the dimensions panel with the time-pill on `transaction_date`, the synonym chips on each metric. Scroll to the **Lineage** panel — contract revisions visible from the model store's version history.

5. **Open the Chat tab.** Ask:
   > *What is the average basket in Germany by loyalty tier?*
   The agent's tool trace expands: `list_models → list_metrics → list_dimensions → query_metric`. The trace shows the rendered SQL using `MEASURE()` against the metric view. The final answer is grounded in real numbers from the warehouse. *"No SQL written by the LLM — the metric definition lives in the contract, the agent only picks dimensions."*

End of five-minute demo.

## Twenty-minute demo (the full hackathon story)

Adds the producer journey, the multi-vendor rendering, the provisioning flow, and the approval queue.

### A. Top-down discovery (5 minutes — as above)

Same as steps 1–5 of the five-minute demo.

### B. Multi-vendor execution (3 minutes)

1. Back to the **Catalog**. Click `orders_multivendor_mv`. Three engine pills in the header.

2. Open a terminal next to the browser and run:
   ```bash
   curl -s 'https://git-ready-portal-7474644741537065.aws.databricksapps.com/api/models/orders_multivendor_mv' \
     -H "Authorization: Bearer $(databricks auth token --profile fevm-peymandemoaws | jq -r .access_token)" \
     | jq '{engines, default_engine, fqn}'
   ```
   Show that the model declares Databricks, Dremio, and Strategy as addressable engines, default Databricks.

3. In the Chat tab, ask:
   > *Use the strategy engine — show me total revenue by order priority on the orders_multivendor model.*

   The trace shows the agent call `query_metric` with `engine="strategy"`. The response carries `kind: "rest"` and the rendered Mosaic REST body, marked `executable: false` because no `STRATEGY_*` env vars are configured. *"Same contract, two engines, neither hand-coded for this query."*

4. Run the same question forcing Dremio. Trace shows `kind: "sql"`, the inlined-expression SQL (different from the Databricks `MEASURE()` form), also `executable: false`. *"OSI is the contract, vendors are interchangeable."*

### C. Access provisioning + audit (4 minutes)

1. Detail page for any model — best is `orders_multivendor_mv` because it has three engines and no ODCS owner, so the fan-out fires immediately.

2. Fill the request form, click **Request access**. The result panel renders three engine pills:
   - Databricks → `granted` if SP has SELECT on the FQN, else `failed` with the UC error
   - Dremio → `skipped` (no `DREMIO_*` env vars)
   - Strategy → `skipped`

3. Navigate to **My requests**. The row appears with the rollup status (`partial` if Databricks granted and the others skipped). Click it — the audit detail expands.

4. Submit a second request with `dry_run: true` via curl to show the safe-preview path:
   ```bash
   curl -sX POST 'https://git-ready-portal-7474644741537065.aws.databricksapps.com/api/access-requests' \
     -H "Authorization: Bearer $(databricks auth token --profile fevm-peymandemoaws | jq -r .access_token)" \
     -H 'content-type: application/json' \
     -d '{"model":"orders_multivendor_mv","requester":"alice@schwarz.com","dry_run":true}' | jq
   ```
   Every engine returns `dry-run` with the exact SQL or REST body it would have sent.

### D. Owner approval (3 minutes)

The lidlplus model has an ODCS owner — requests on it require approval.

1. As an analyst, request access on `lidlplus_transactions_mv`. The result panel shows the amber `pending_approval` pill: *"Pending approval by lidlplus.platform@schwarz.com."*

2. Open the **Approvals** tab. Type `lidlplus.platform@schwarz.com`, click **Sign in**. The pending request appears in the queue.

3. Type a reason ("standard tier"), click **Approve**. The queue empties — `grant_all` fires *now*, not at submit. The audit row is prepended with a synthetic `approval · granted` entry naming the approver.

4. Bonus: submit another request and **Reject** it with a reason ("duplicate"). The audit detail captures the rejection row.

### E. Producer journey (5 minutes)

1. Click the **Publish** tab. Leave Dry-run checked.

2. Fill the form:
   - **Source FQN:** `peymandemoaws_catalog.osi_demo.lidlplus_transactions` (the underlying Delta table the lidlplus notebook seeded)
   - **Domain:** `retail`
   - **Owner email:** your email
   - **Description:** "Loyalty transaction events for the GIT READY demo"

3. Click **Infer**. The page renders the inferred column list (real columns from `DESCRIBE TABLE EXTENDED`), a `gemini` or `heuristic` pill on the AI path, the proposed metrics, and read-only OSI + ODCS YAML previews. *"From a raw UC table to a complete OSI plus ODCS pair in one click."*

4. Click **Publish contract**. Two files appear as `dry-run` with byte counts; the `store: persisted` pill confirms the new model is now in the catalog. Click **View in catalog** — the new `lidlplus_transactions_mv_mv` (or however the modeler named it) is browsable.

5. Optional live commit: uncheck Dry-run, set `GITHUB_TOKEN` and `GITHUB_CONTRACTS_REPO` on the app config in the Databricks UI, redeploy, and the same flow commits to GitHub with clickable commit URLs.

## Talking points by audience

### For data engineers
- **Why no LLM SQL:** the agent only picks dimensions and filters; the metric formula lives in `MEASURE()` on the warehouse side. Reproducible, audit-able, identical answers across consumers.
- **Why a translator-per-vendor:** Dremio doesn't have `MEASURE()`. The bridge inlines OSI's `metrics[].expression[]` with `dialect: Dremio` preferred. Strategy is REST-not-SQL, so the same dispatcher routes to a different code path entirely.
- **Where the schema lives:** `osi_bridge/store/schema.sql` for Postgres / Lakebase, mirrored in `osi_bridge/store/sqlite.py` for local dev. Two tables: current state plus an append-only version log so contract revisions are a first-class audit object.

### For data governance / compliance
- ODCS contracts are the source-of-truth — domain, owner, support channel, quality rules live there. OSI is the runtime projection the agent reads.
- Every access request lands a row in `osi_access_requests`; every per-engine outcome appends to `osi_access_grants`. The audit detail page is queryable and append-only.
- Approval gating: requests on owner-bearing models go to `pending_approval` *before* engines fire. The approver's identity and reason are stamped into the audit log.

### For business users
- Type a KPI in the search bar; if it exists, you get a definition + a Request-access button. If not, Gemini suggests adjacent domains and surfaces the owner email so you can ask.
- Chat answers come from the actual warehouse, not from the LLM's training data. Click "tool calls" on any answer to see the exact SQL the warehouse ran.

### For executives
- One contract registers a metric once; consumers (dashboards, REST APIs, agents) all compute it the same way regardless of which engine runs underneath.
- "Time-to-insight" for a new dataset: producer points at a UC table → AI drafts the contract → owner reviews → access fans out across Databricks, Dremio, Strategy in one click. Today that takes a week of email and a JIRA ticket per engine.

## Reset between demos

Browser-side state is hash-based and self-resets per tab. Server-side state to reset:

```bash
# As a workspace admin or the app's deployer
unset DATABRICKS_HOST DATABRICKS_TOKEN DATABRICKS_HTTP_PATH DATABRICKS_AUTH_TYPE DATABRICKS_CONFIG_PROFILE
databricks apps restart git-ready-portal --profile fevm-peymandemoaws
```

Restart wipes the SQLite-on-disk in the app container, which means:

- Access requests + audit grants are cleared
- Producer-published-via-dry-run models are forgotten
- The four shipped models reload from `examples/models/*.osi.yaml`

Note: the *real* Metric Views in `peymandemoaws_catalog.osi_demo.*` survive restart (they live in UC, not in the app container). So the demo's primary content is durable.

## Troubleshooting

**Catalog page is empty.** The app container couldn't load the OSI YAMLs. Check `GET /api/health` — if `models` is empty, the deploy is broken; redeploy from the repo with `databricks apps deploy git-ready-portal`.

**Chat answers are gibberish.** The Databricks Foundation Model API for Gemini isn't enabled on this workspace, or the SP doesn't have permission to call it. Visit Workspace settings → Serving → Foundation Model APIs.

**Chat trace shows `query_metric` failed.** The SP doesn't have SELECT on the FQN, or the warehouse is unreachable. Verify:
```bash
# Re-grant if needed:
databricks api post /api/2.0/sql/statements --profile fevm-peymandemoaws -- --json '{
  "warehouse_id":"093e6cb9eab4603d",
  "statement":"GRANT SELECT ON TABLE peymandemoaws_catalog.osi_demo.<view> TO `c2028963-1eb7-4e57-bd1f-2409aa7505f6`"
}'
```

**Request access fan-out always shows `failed` for Databricks.** Check the metric_view_fqn in the OSI YAML; placeholder `<catalog>` was never substituted. Look at `examples/models/<model>.osi.yaml` and confirm `metric_view_fqn` is `peymandemoaws_catalog.osi_demo.<view>_mv`. If wrong, fix it and redeploy.

**Pending approvals don't appear in the Approvals queue.** Make sure the email entered in the Sign-in box exactly matches the OSI model's `custom_extensions.odcs.owner` value. Case-sensitive.

**App container slow to start after restart.** Databricks Apps cold-start takes ~30 seconds; the first request after restart can hang briefly. Subsequent requests are warm.

## Upgrade paths (not yet wired up)

- **Tier C: durable audit trail.** Provision a Lakebase Postgres instance, set `PORTAL_STORE=lakebase` and `OSI_BRIDGE_PG_DSN=...` on the app, redeploy. Access requests, audit grants, and contract versions now survive restart.
- **Live Dremio / Strategy execution.** Set `DREMIO_BASE_URL` + `DREMIO_TOKEN` and `STRATEGY_BASE_URL` + `STRATEGY_TOKEN` on the app config. The provisioning fan-out and the query dispatcher will both light up for those engines.
- **Real GitHub commits from the producer journey.** Set `GITHUB_TOKEN` + `GITHUB_CONTRACTS_REPO` on the app config; uncheck Dry-run on **Publish**.
- **Production identity.** Replace the Approvals page's localStorage-based "sign in as" with a FastAPI dependency reading `X-Forwarded-User` from the Databricks Apps runtime.
