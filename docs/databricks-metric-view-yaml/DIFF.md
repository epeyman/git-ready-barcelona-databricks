# Databricks Metric View YAML (spec 1.1) ↔ OSI Core Spec — Feature Diff

Field-by-field comparison of what each format models natively, what's shared, and where each has unique capabilities. Useful for OSI standardization work and for understanding the round-trip surface between the two.

## Authoritative sources used for this diff

| Format | Version cited | URL |
|---|---|---|
| Databricks Metric View YAML | **1.1** (current) | [Metric view YAML syntax reference (Microsoft Learn)](https://learn.microsoft.com/en-us/azure/databricks/business-semantics/metric-views/yaml-reference) |
| Open Semantic Interchange core spec | **`0.2.0.dev0`** (current dev), **`0.1.1`** (latest released) | [`core-spec/spec.yaml` on github.com/open-semantic-interchange/OSI](https://github.com/open-semantic-interchange/OSI/blob/main/core-spec/spec.yaml) |
| Canonical OSI example | Same repo | [`examples/tpcds_semantic_model.yaml`](https://github.com/open-semantic-interchange/OSI/blob/main/examples/tpcds_semantic_model.yaml) |

> **Version disambiguation:** Public announcements about "OSI v1.0 finalized" (January 2026) refer to a project / initiative milestone. The spec schema itself currently shows `version: 0.2.0.dev0` in the core spec file. Latest fully-released schema is `0.1.1`. There is no `1.0.0` schema version in the repository as of this write-up.

## Concrete side-by-side examples in this directory

- `orders.metric_view.yaml` — native Databricks MV YAML for the TPC-H orders model.
- `orders.osi.yaml` — OSI translation of the same model. **Validates against `core-spec/osi-schema.json`.**
- `lineitem.metric_view.yaml` — joined line-item sales with window + materialization.
- `lineitem.osi.yaml` — OSI translation of the same model. **Validates against `core-spec/osi-schema.json`.** Models the join as an OSI `relationship` (FK graph); the SQL `joins[*].on` predicate, the rolling-7-day window measure, and the materialization block ride along as JSON-encoded `data` strings under `custom_extensions[*].vendor_name: "DATABRICKS"`.

---

## 1. Parity — both formats model this natively

| Concept | Databricks Metric View 1.1 | OSI core spec |
|---|---|---|
| Spec version | `version: 1.1` | `version: "0.2.0.dev0"` |
| View / model name | (the UC view object name in the `CREATE VIEW` DDL) | `semantic_model[*].name` |
| View / model description | `comment` (top-level) | `semantic_model[*].description` |
| AI / agent guidance at model level | `comment` (informally) | `semantic_model[*].ai_context` (spec line 39 declares it as a string; the canonical TPC-DS example uses it as a structured object with `instructions` / `synonyms`) |
| Source table | `source: catalog.schema.table` | `datasets[*].source` (spec line 70) |
| Dimension name | `dimensions[*].name` | `datasets[*].fields[*].name` (spec line 155) |
| Dimension SQL | `dimensions[*].expr` (single string) | `datasets[*].fields[*].expression.dialects[*].expression` (spec lines 161-164) |
| Dimension description | `dimensions[*].comment` | `datasets[*].fields[*].description` (spec line 177) |
| Time-dimension marker | (engine infers from column type) | `datasets[*].fields[*].dimension.is_time` (spec line 171) — explicit |
| AI context per field | `dimensions[*].comment` + `synonyms` | `datasets[*].fields[*].ai_context` (spec line 181) |
| Measure / metric name | `measures[*].name` | `semantic_model[*].metrics[*].name` (spec line 194) |
| Measure / metric SQL | `measures[*].expr` (single string) | `semantic_model[*].metrics[*].expression.dialects[*].expression` (spec lines 199-202) |
| Measure / metric description | `measures[*].comment` | `semantic_model[*].metrics[*].description` (spec line 206) |
| AI context per metric | `measures[*].comment` + `synonyms` | `semantic_model[*].metrics[*].ai_context` (spec line 210) |
| Vendor extension hook | `comment` (the only extensibility lever; no structured custom-extension block) | `custom_extensions[*].{vendor_name, data}` at model / dataset / relationship / field / metric levels (spec lines 56-58, 109-111, 145-148, 183-186, 213-215) |

**Note on AI metadata shape mismatch:** Databricks Metric View 1.1 introduced `display_name`, `synonyms`, and `format` as separate top-level keys on each dimension/measure. OSI does **not** define a top-level `display_name` or `format` — these live (informally) inside `ai_context`. The canonical TPC-DS example demonstrates `ai_context.synonyms` but never uses a `display_name` field.

---

## 2. Databricks Metric View has, OSI core spec does not

Capabilities present in the native Metric View YAML (1.1) that the OSI core spec does not model first-class. These would have to be carried under OSI's `custom_extensions` if a Databricks adapter needs to round-trip them.

| Concept | Native Databricks YAML | OSI status |
|---|---|---|
| **SQL JOIN modeling** (a JOIN with an explicit predicate) | `joins:` array with `name`, `source`, `on`, `using` | ❌ Not modeled the same way. OSI has `relationships` (foreign-key graph: `from`, `to`, `from_columns`, `to_columns`), which is a structural metadata model, not a SQL JOIN operation. See §3. |
| **Snowflake-schema (nested) joins** | Nested `joins:` inside a parent join | ❌ Not modeled in OSI (`relationships` are flat). |
| **`using:` join syntax** | Alternative to `on:` | ❌ Not modeled. |
| **`rely.at_most_one_match`** join optimization hint | `joins[*].rely.at_most_one_match: true` | ❌ Not modeled. Could live under `custom_extensions`. |
| **Window measures** | `measures[*].window[*]` with `order`, `range`, `semiadditive`, `offset` | ❌ Not first-class. Would have to live under `metrics[*].custom_extensions`. |
| **Trailing / leading / cumulative ranges** | `range: trailing 7 day [inclusive\|exclusive]`, `leading`, `cumulative`, `current`, `all` | ❌ Not modeled. |
| **Semi-additive aggregation** | `semiadditive: first \| last` | ❌ Not modeled. Real semantic gap. |
| **Window frame offset** | `offset: -12 month` etc. | ❌ Not modeled. |
| **Materialization** auto-acceleration | `materialization` block with `schedule`, `mode: relaxed`, `materialized_views[*]` (`aggregated` / `unaggregated`) | ❌ Not modeled. |
| **Per-metric `FILTER (WHERE …)` scope** | Inline in `expr` SQL string | ⚠️ Captured inside the SQL string only — OSI has no structured per-metric filter field. |
| **Display format spec** | `dimensions[*].format` / `measures[*].format` (1.1) | ❌ Not modeled. |
| **`display_name` as a separate field** | `dimensions[*].display_name` / `measures[*].display_name` (1.1, ≤ 255 chars) | ❌ Not modeled. OSI puts this informally inside `ai_context`. |
| **`synonyms` as a separate field** | `dimensions[*].synonyms` / `measures[*].synonyms` (1.1, ≤ 10 items, ≤ 255 chars each) | ⚠️ Not a separate field — sits inside `ai_context` per the canonical example. |
| **Composability** — metric view as source | `source: <another metric view fqn>` | ⚠️ Not formalized. OSI references other models by name; semantics are vendor-defined. |
| **Inline SQL source** | `source: SELECT … FROM …` (with `RELY` constraint hint) | ⚠️ `datasets[*].source: string` — format is `database.schema.table` or `query` per the spec, but the latter is loosely defined. |
| **DDL integration** | `CREATE OR REPLACE VIEW … WITH METRICS LANGUAGE YAML AS $$…$$;` — first-class UC object | ❌ OSI is a contract, not a DDL. |
| **UC governance integration** | Lives as a UC view; grants, lineage, audit applied via UC | ❌ OSI is vendor-neutral by design — governance lives in the consuming engine. |

---

## 3. OSI core spec has, native Databricks YAML does not

Capabilities OSI models that have no equivalent in Databricks Metric View YAML 1.1.

| Concept | OSI core spec | Native Databricks YAML |
|---|---|---|
| **Multi-dialect expressions** — same field/metric expressed in N SQL flavors | `expression.dialects[*]` is an array; each entry has `dialect` (one of `ANSI_SQL` / `SNOWFLAKE` / `DATABRICKS` / `MDX` / `TABLEAU` / `MAQL`; default `ANSI_SQL`) and `expression` (spec lines 14-21, 161-164, 199-202) | ❌ Single `expr` string in Databricks SQL only. |
| **Explicit time-dimension marker** | `fields[*].dimension.is_time: boolean` (spec line 171) | ⚠️ Engine infers from data type. |
| **`primary_key` on datasets** | `datasets[*].primary_key: []` — array of column names, simple or composite (spec line 81) | ⚠️ Lives on the underlying UC table via `CONSTRAINT … PRIMARY KEY`, not in the metric view YAML. |
| **`unique_keys` on datasets** | `datasets[*].unique_keys: [[], [], …]` — multiple unique keys, each simple or composite (spec line 94) | ⚠️ Same — base-table constraint, not metric-view YAML. |
| **`relationships` — foreign-key graph between datasets** | `relationships[*]` with `name`, `from`, `to`, `from_columns`, `to_columns` (spec lines 117-148). Metadata-only — does NOT specify a JOIN. The consuming engine decides how to materialize the join. | ⚠️ Conceptually different — Databricks `joins:` specifies the actual SQL JOIN. They are not the same construct. |
| **`label` on fields** | `fields[*].label: string` — categorization label (e.g., `"filter"`) (spec line 174) | ❌ Not modeled. |
| **AI context at every level** | `ai_context` on `semantic_model`, `datasets`, `fields`, `metrics`, and `relationships` (spec) | ⚠️ Databricks has `comment` + (1.1) `display_name` / `synonyms` on dims and measures, but no view-level `ai_context.instructions` field. |
| **Vendor-neutral extension namespace** | `custom_extensions[*].{vendor_name, data}` at every level. `vendor_name` is free-form (e.g., `"DATABRICKS"`, `"SNOWFLAKE"`, `"DBT"`). | ❌ No structured extension point in native YAML. |
| **Cross-vendor expression routing** | A single OSI document can carry `DATABRICKS` SQL alongside `SNOWFLAKE` and `ANSI_SQL` for the same metric, enabling hub-and-spoke conversion. | ❌ Native YAML is Databricks-only by design. |

---

## 4. Same concept, different shape — translator notes

Where both formats express the same semantic but with different syntax. Critical for anyone writing a converter.

| Concept | Databricks form | OSI form (verbatim per `core-spec/spec.yaml`) |
|---|---|---|
| Top-level description | `comment: <string>` | `semantic_model[*].description: <string>` |
| AI-context container | `comment` only | `ai_context` — spec says `string`, canonical example uses a structured object with `instructions` and `synonyms` |
| Dimension/measure SQL | `expr: <single SQL string>` | `expression:\n  dialects:\n    - dialect: DATABRICKS\n      expression: <sql>` |
| Dialect identifier | implicit (always Databricks) | UPPER_CASE enum: `ANSI_SQL`, `SNOWFLAKE`, `DATABRICKS`, `MDX`, `TABLEAU`, `MAQL` (default `ANSI_SQL`) |
| Source | `source: cat.schema.tbl` | `datasets[*].source: cat.schema.tbl` |
| Global filter | `filter:` at top level | ⚠️ **OSI does not define a `filter` field on `datasets`.** Has to live under `custom_extensions` or via a wrapper view. |
| Time-dim marker | inferred | `fields[*].dimension.is_time: true` |
| Joins | `joins[*].on:` SQL predicate | `relationships[*]` — FK graph; does not express the JOIN SQL itself |
| Vendor extensions | (no native mechanism) | `custom_extensions: [{vendor_name: "DATABRICKS", data: <string>}]` — note: array of objects, **not** a map keyed by vendor |

---

## 5. Implications for OSI standardization

Where the OSI core spec would need to grow if it wants to faithfully represent Databricks Metric Views (and similarly capable vendors like Strategy Mosaic, Cube, MetricFlow):

1. **First-class `joins` (SQL operation) vs `relationships` (FK graph) distinction.** Today only `relationships` exists. Databricks `joins:` is closer to a SQL operation. These are different constructs and could coexist.
2. **First-class `window` block on metrics** — `order`, `range` (with vendor-extensible range vocabulary), `semiadditive`. Semi-additive measures are a real omission in OSI today.
3. **First-class `materialization` block** — schedule + materialized-rollup definitions. Snowflake dynamic tables, Databricks metric-view materialization, and Strategy Mosaic all have versions of this.
4. **First-class per-metric `filter` field** — for the `FILTER (WHERE …)` measure pattern, rather than burying it in the expression string.
5. **First-class `format`** on fields and metrics.
6. **First-class `display_name` and `synonyms`** as siblings of `description` rather than only living inside `ai_context`. This would close the metadata-shape gap with Databricks MV 1.1.
7. **Tighter `ai_context` schema.** The spec file declares `ai_context: string` but the canonical example uses it as a structured object. Either tighten the spec to allow both, or formalize the keys (`instructions`, `synonyms`, `example_queries`).

Until these land, a Databricks ↔ OSI converter has to carry the gap fields under `custom_extensions`.

---

## 6. Round-trip status — what survives a full OSI → Databricks → OSI cycle?

Tested against the orders + lineitem examples in this directory using the prototype `osi_bridge` exporter/importer.

| Field | OSI → Databricks → OSI |
|---|---|
| Names, descriptions | ✅ Lossless |
| Dimension and metric SQL expressions | ✅ Lossless (the `DATABRICKS` dialect entry survives) |
| Multi-dialect expressions (Snowflake, ANSI_SQL) | ⚠️ Survives if the importer is OSI-aware (this repo's importer preserves them); a hand-edited round-trip via the Databricks YAML UI would drop non-Databricks dialects |
| `dimension.is_time` flag | ⚠️ Lossy unless the column type already implies time |
| Relationships | ⚠️ Survives only as Databricks `joins` if the converter rewrites the FK graph into SQL JOINs; reverse direction is heuristic |
| Window measures | ✅ Lossless via `custom_extensions` |
| Materialization | ✅ Lossless via `custom_extensions` |
| `ai_context.synonyms` | ⚠️ Survives as `synonyms` in Databricks 1.1; lossless if both sides understand the field |
| `display_name` (Databricks 1.1 → OSI) | ⚠️ No first-class OSI field — typically folded into `ai_context` or dropped |

---

## 7. Quick translator cheatsheet

Direct field-to-field mapping for implementing a Databricks ↔ OSI converter. All OSI paths are verbatim from the spec file.

```
OSI (core-spec/spec.yaml)                                  Databricks Metric View YAML 1.1
=========================================================  ====================================
version: "0.2.0.dev0"                              ↔       version: 1.1

semantic_model[*].name                              ↔       (the UC view name in CREATE VIEW DDL)
semantic_model[*].description                       ↔       comment (top-level)
semantic_model[*].ai_context (string or object)     ↔       comment (best-effort; no first-class field)

datasets[*].name                                    ↔       (no MV equivalent — there is one dataset per MV)
datasets[*].source                                  ↔       source
datasets[*].primary_key                             ↔       (UC table constraint, not in MV YAML)
datasets[*].unique_keys                             ↔       (UC table constraint, not in MV YAML)
datasets[*].description                             ↔       comment (best-effort)
datasets[*].ai_context.synonyms                     ↔       (no view-level synonyms in MV YAML)

datasets[*].fields[*].name                          ↔       dimensions[*].name
datasets[*].fields[*].expression
  .dialects[?dialect=='DATABRICKS'].expression      ↔       dimensions[*].expr
datasets[*].fields[*].description                   ↔       dimensions[*].comment
datasets[*].fields[*].dimension.is_time             ↔       (no field — engine infers)
datasets[*].fields[*].label                         ↔       (no MV equivalent)
datasets[*].fields[*].ai_context.synonyms           ↔       dimensions[*].synonyms (1.1)

semantic_model[*].metrics[*].name                   ↔       measures[*].name
semantic_model[*].metrics[*].expression
  .dialects[?dialect=='DATABRICKS'].expression      ↔       measures[*].expr
semantic_model[*].metrics[*].description            ↔       measures[*].comment
semantic_model[*].metrics[*].ai_context.synonyms    ↔       measures[*].synonyms (1.1)
semantic_model[*].metrics[*].custom_extensions[?vendor_name=='DATABRICKS']
                                                    ↔       measures[*].window  (carried verbatim)

semantic_model[*].relationships[*]                  ↔       joins[*]  (lossy — relationships are FK
                                                                graph; joins are SQL operations)

semantic_model[*].custom_extensions[?vendor_name=='DATABRICKS']
  .joins                                            ↔       joins[*]   (carried verbatim by this prototype)
  .materialization                                  ↔       materialization (carried verbatim)
  .filter                                           ↔       filter (top-level)
  .metric_view_fqn                                  ↔       (composes the CREATE VIEW DDL, not in YAML body)
```

---

## 8. Validation

The OSI files in this directory (`orders.osi.yaml`, `lineitem.osi.yaml`) are validated against the live JSON schema (`core-spec/osi-schema.json`) using `jsonschema` Draft 2020-12 — both pass with zero errors. Quick local re-validation:

```bash
pip install jsonschema pyyaml
python3 -c "
import json, yaml
from jsonschema import Draft202012Validator
schema = json.loads(open('osi-schema.json').read())
doc = yaml.safe_load(open('orders.osi.yaml'))
errors = sorted(Draft202012Validator(schema).iter_errors(doc), key=lambda e: e.path)
print('VALID' if not errors else f'{len(errors)} errors')
"
```

The original prototype YAMLs in this repo's `examples/models/` directory (produced by `osi_bridge/exporter.py`) take some liberties with the spec — map-shaped `custom_extensions`, dataset-level `filter`, mixed-case `dialect: Databricks`, flat `expression` array, and a `display_name` field. Those are pragmatic prototype choices, not bugs in the spec, and they would need a pass to align with `core-spec/osi-schema.json` before being shared as canonical OSI artifacts.
