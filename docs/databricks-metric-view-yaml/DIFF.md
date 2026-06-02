# Databricks Metric View YAML (spec 1.1) ↔ OSI v1.0 — Feature Diff

Field-by-field comparison of what each format models natively, what's shared, and where each has unique capabilities. Useful for OSI standardization work and for understanding the round-trip surface between the two.

**Sources:**
- Databricks: [Metric view YAML syntax reference](https://learn.microsoft.com/en-us/azure/databricks/business-semantics/metric-views/yaml-reference) (spec 1.1)
- OSI: [Open Semantic Interchange v1.0](https://github.com/open-semantic-interchange/specification)

Concrete side-by-side examples for the same TPC-H models live alongside this file:
- `orders.metric_view.yaml` ↔ `orders.osi.yaml`
- `lineitem.metric_view.yaml` ↔ `lineitem.osi.yaml`

---

## 1. Parity — both formats model this natively

| Concept | Databricks Metric View 1.1 | OSI v1.0 |
|---|---|---|
| Spec version | `version: 1.1` | `version: "1.0"` |
| View / model description | `comment` (top-level) | `semantic_model[0].description` + `ai_context.instructions` |
| Source table | `source: catalog.schema.table` | `datasets[0].source` |
| Global query filter | `filter:` (top-level) | `datasets[0].filter` |
| Dimension name | `dimensions[*].name` | `datasets[0].fields[*].name` |
| Dimension SQL expression | `dimensions[*].expr` | `datasets[0].fields[*].expression[*].sql` |
| Dimension description | `dimensions[*].comment` | `datasets[0].fields[*].description` |
| Dimension display name | `dimensions[*].display_name` (1.1) | `datasets[0].fields[*].ai_context.display_name` |
| Dimension synonyms | `dimensions[*].synonyms` (≤ 10, 1.1) | `datasets[0].fields[*].ai_context.synonyms` |
| Measure name | `measures[*].name` | `metrics[*].name` |
| Measure aggregate SQL | `measures[*].expr` | `metrics[*].expression[*].sql` |
| Measure description | `measures[*].comment` | `metrics[*].description` |
| Measure display name | `measures[*].display_name` (1.1) | `metrics[*].ai_context.display_name` |
| Measure synonyms | `measures[*].synonyms` (1.1) | `metrics[*].ai_context.synonyms` |

**Implication:** All the AI/BI-discovery metadata (display names, synonyms, descriptions) that OSI exposes via `ai_context` is now also expressible in native Databricks Metric View YAML 1.1. Round-trip is lossless for this surface.

---

## 2. Databricks has, OSI v1.0 does not (yet)

Capabilities present in the native Metric View YAML that OSI v1.0 does not model first-class. The OSI Bridge implementation in this repo carries them under `custom_extensions.databricks` so they round-trip back into native YAML on the Databricks side, but they are opaque to Dremio, Strategy Mosaic, or any other OSI consumer.

| Concept | Native Databricks YAML | OSI v1.0 status |
|---|---|---|
| **Star-schema joins** | `joins:` array with `name`, `source`, `on`, `using` | ❌ Not first-class. Carried as `custom_extensions.databricks.joins`. |
| **Snowflake-schema joins** (nested) | Nested `joins:` inside a parent join | ❌ Not first-class. |
| **`using:` join syntax** | Alternative to `on:` for shared column names | ❌ Not modeled. |
| **`rely.at_most_one_match`** — join optimization hint | `joins[*].rely.at_most_one_match: true` (many-to-one promise) | ❌ Not modeled. Databricks-specific planner hint. |
| **Window measures** | `measures[*].window[*]` with `order`, `range`, `semiadditive`, `offset` | ❌ Not first-class. Window spec rides under `metrics[*].custom_extensions.databricks.window`. |
| **Trailing / leading / cumulative ranges** | `range: trailing 7 day [inclusive\|exclusive]`, `leading`, `cumulative`, `current`, `all` | ❌ Not modeled. |
| **Semi-additive aggregation** | `semiadditive: first \| last` | ❌ Not modeled. Semi-additive is a real semantic gap. |
| **Window frame offset** | `offset: -12 month` etc. (DBR 18.1 + 1.1) | ❌ Not modeled. |
| **Materialization** — auto-acceleration | `materialization` block with `schedule`, `mode: relaxed`, `materialized_views[*]` (`aggregated` / `unaggregated`) | ❌ Not modeled. Carried under `custom_extensions.databricks.materialization`. |
| **Materialization schedule syntax** | `every 6 hours`, cron, etc. | ❌ Not modeled. |
| **`FILTER (WHERE …)` measure scope** | Inline in `expr`: `SUM(col) FILTER (WHERE flag = 'X')` | ⚠️ Captured inside the SQL string only — OSI does not have a structured per-metric filter field. |
| **Display format spec** | `dimensions[*].format` / `measures[*].format` (1.1) | ❌ No equivalent yet. |
| **Composability** — metric view as source | `source: <another metric view fqn>` | ⚠️ OSI can reference another OSI model by name but composability semantics are vendor-defined. |
| **Inline SQL source** | `source: SELECT … FROM …` (with `RELY` constraint hint) | ⚠️ OSI `datasets[0].source` accepts FQN; inline SQL is non-standard. |
| **DDL integration** | `CREATE OR REPLACE VIEW … WITH METRICS LANGUAGE YAML AS $$…$$;` — first-class UC object | ❌ OSI is a contract, not a DDL — has no DDL representation. |
| **UC governance integration** | Lives as a UC view; grants, lineage, audit applied via UC | ❌ OSI is vendor-neutral by design — governance lives in the consuming engine. |
| **Time dimension detection** | Engine infers from column type | ✅ OSI is more explicit: `dimension.is_time: true` field. (See §3) |

---

## 3. OSI has, native Databricks YAML does not

Capabilities OSI v1.0 models that have no equivalent in Databricks Metric View YAML 1.1 today.

| Concept | OSI v1.0 | Native Databricks YAML |
|---|---|---|
| **Multi-dialect expressions** — same metric in N vendor SQL flavors | `expression[]` is an array; each element has `dialect` (`Databricks` / `Dremio` / `Strategy Mosaic` / `Snowflake` / `Trino` / `ANSI` / …) and `sql`. | ❌ Single `expr` string in one dialect (Databricks SQL). |
| **Explicit time-dimension marker** | `dimension.is_time: true` on the field | ⚠️ Engine infers from data type; no explicit flag in YAML. |
| **AI-targeted instructions at model level** | `semantic_model[0].ai_context.instructions` — free-text guidance for LLM agents | ⚠️ Approximated via `comment` at view level. |
| **Vendor extension namespace** | `custom_extensions.<vendor>` on the semantic model, on each metric, on each field | ❌ No structured extension point. |
| **Cross-vendor routing** | A single OSI contract is consumed by multiple engines via per-vendor translators | ❌ Native YAML is Databricks-only by design. |
| **Contract integration** (ODCS) | Common pattern: `custom_extensions.odcs` holds the data-contract owner, domain, SLAs | ❌ Out of scope for a Metric View — would live in UC tags / external systems. |
| **Confluence / external doc linkage** | Common pattern: `custom_extensions.confluence` holds the page URL | ❌ Not modeled. |
| **Lineage / provenance attribution** | Common pattern via `ai_context.instructions` referencing the source view | ⚠️ Lives in UC lineage as a separate system. |
| **Vendor neutrality as a first-class property** | Whole spec is designed for vendor swap | ❌ Native YAML is intentionally Databricks-shaped. |

---

## 4. Same concept, different shape

Where both formats express the same semantic but with different syntax. Important when writing translators.

| Concept | Databricks form | OSI form | Translator note |
|---|---|---|---|
| Description | `comment:` (single string) | `description:` + optional `ai_context.instructions:` (multi-purpose) | Use Databricks `comment` for the description; AI instructions go in `ai_context`. |
| Display name | `display_name:` | `ai_context.display_name:` | Lift/drop the `ai_context.` prefix. |
| Synonyms | `synonyms: [a, b, c]` | `ai_context.synonyms: [a, b, c]` | Same. |
| SQL expression | `expr: <sql>` (single string) | `expression: [{dialect: Databricks, sql: <sql>}]` (array) | Translator picks the entry whose `dialect == 'Databricks'`; falls back to first entry. |
| Source | `source: cat.schema.tbl` | `datasets[0].source: cat.schema.tbl` | Nest one level deeper in OSI. |
| Global filter | `filter:` (top-level) | `datasets[0].filter` | Nest one level deeper in OSI. |
| Time dimension | Inferred from column type | `dimension.is_time: true` explicit | Round-trip is lossy: OSI → Databricks drops the flag (engine re-infers); Databricks → OSI must walk the schema to mark date/timestamp columns. |

---

## 5. Implications for OSI standardization

Where OSI v1.0 should grow if it wants to be a faithful interchange format for Databricks Metric Views (and similarly capable vendors like Strategy Mosaic):

1. **First-class `joins` block** — star and snowflake. Field names already align across vendors (`name`, `source`, `on`/`using`). Optimization hints (`rely`) should be vendor-extensible.
2. **First-class `window` block on metrics** — `order`, `range` (with vendor-extensible range vocabulary), `semiadditive`. Semi-additive measures are a real omission in OSI v1.0.
3. **First-class `materialization` block** — schedule + materialized-rollup definitions. Strategy Mosaic has a similar concept; Snowflake's dynamic tables have it; Databricks has it; OSI should model it.
4. **First-class `filter` field on metrics** — for the `FILTER (WHERE …)` measure pattern, rather than burying it in the SQL string.
5. **First-class `format` block on dimensions and metrics** — number/date format strings.
6. **Inline SQL source** — formalize how to handle non-FQN sources (with PK/FK constraint declarations).

Until these land in OSI, the Databricks adapter in this repo carries them under `custom_extensions.databricks` so round-trips are lossless on the Databricks side. Other adapters (Dremio, Strategy Mosaic) can read or ignore.

---

## 6. Round-trip status — what survives a full OSI → Databricks → OSI cycle?

Tested against the orders + lineitem examples in this directory.

| Field | OSI → Databricks → OSI |
|---|---|
| Names, descriptions, display names, synonyms | ✅ Lossless |
| Dimension and metric SQL expressions | ✅ Lossless (Databricks dialect entry survives) |
| Multi-dialect expressions (Dremio, Strategy) | ⚠️ Survives if the Databricks importer is OSI-aware (this repo's `osi_bridge.importer` preserves them); a hand-edited round-trip via the YAML UI would drop non-Databricks dialects |
| `filter` (top-level) | ✅ Lossless |
| `dimension.is_time` flag | ⚠️ Lossy unless the column type already implies time |
| Joins (under `custom_extensions.databricks`) | ✅ Lossless via this repo's importer |
| Window measures (under `custom_extensions.databricks`) | ✅ Lossless via this repo's importer |
| Materialization (under `custom_extensions.databricks`) | ✅ Lossless via this repo's importer |
| ai_context.instructions on the semantic model | ⚠️ Maps to view-level `comment` — survives but the AI-instruction framing is implicit |

---

## 7. Quick lookup table for the translator code

When implementing `osi → databricks_mv_yaml` and `databricks_mv_yaml → osi`:

```
OSI                                                    Databricks Metric View YAML 1.1
================================================       ====================================
version: "1.0"                                  ↔      version: 1.1
semantic_model[0].description                   ↔      comment (top-level)
semantic_model[0].ai_context.instructions       ↔      (no first-class field — fold into comment)
datasets[0].source                              ↔      source
datasets[0].filter                              ↔      filter
datasets[0].fields[*].name                      ↔      dimensions[*].name
datasets[0].fields[*].expression                ↔      dimensions[*].expr
   .where dialect == "Databricks"
datasets[0].fields[*].description               ↔      dimensions[*].comment
datasets[0].fields[*].ai_context.display_name   ↔      dimensions[*].display_name
datasets[0].fields[*].ai_context.synonyms       ↔      dimensions[*].synonyms
datasets[0].fields[*].dimension.is_time         ↔      (no field — engine infers)
metrics[*].name                                 ↔      measures[*].name
metrics[*].expression.where dialect=="Databricks" ↔    measures[*].expr
metrics[*].description                          ↔      measures[*].comment
metrics[*].ai_context.display_name              ↔      measures[*].display_name
metrics[*].ai_context.synonyms                  ↔      measures[*].synonyms
metrics[*].custom_extensions.databricks.window  ↔      measures[*].window
semantic_model[0].custom_extensions.databricks
  .joins                                        ↔      joins (top-level)
  .materialization                              ↔      materialization (top-level)
  .metric_view_fqn                              ↔      (used to compose the CREATE VIEW DDL, not in YAML)
```
