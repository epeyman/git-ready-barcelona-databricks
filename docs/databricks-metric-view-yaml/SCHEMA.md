# Databricks Unity Catalog Metric View — YAML Schema Reference

Authoritative source: [Metric view YAML syntax reference (Microsoft Learn)](https://learn.microsoft.com/en-us/azure/databricks/business-semantics/metric-views/yaml-reference). The same spec is documented for AWS and GCP. This file mirrors the spec at version **`1.1`** (current).

## Top-level fields

| Field | Type | Required | Description |
|---|---|---|---|
| `version` | string | Yes | YAML spec version. Current = `1.1`. Older metric views may show `0.1`. |
| `comment` | string | No | View-level description. Surfaces in Unity Catalog. |
| `source` | string | Yes | Any table-like UC asset (3-part FQN), another metric view (composability), or an inline SQL `SELECT`. |
| `filter` | string | No | SQL boolean expression applied to every query. |
| `joins` | array | No | Star/snowflake joins to other tables or SQL queries. Supports nesting. |
| `dimensions` | array | Conditional | Required if `measures` is absent. |
| `measures` | array | Conditional | Required if `dimensions` is absent. |
| `materialization` | object | No (experimental) | Configure materialized-view acceleration with a refresh schedule. |

## `source`

Three-part FQN:
```yaml
source: samples.tpch.orders
```

Or inline SQL (set `RELY` on PK/FK constraints for performance):
```yaml
source: |
  SELECT * FROM samples.tpch.orders o
  LEFT JOIN samples.tpch.customer c ON o.o_custkey = c.c_custkey
```

## `joins[*]`

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | Yes | Alias used to qualify columns from the joined table. |
| `source` | string | Yes | FQN of the joined table, or a SQL `SELECT`. |
| `on` | string | Conditional | Boolean join predicate. Required if `using` is not specified. |
| `using` | array | Conditional | List of shared column names. Required if `on` is not specified. |
| `joins` | array | No | Nested joins for snowflake-schema modeling. |
| `rely.at_most_one_match` | bool | No (default `false`) | Many-to-one promise. When `true`, the analyzer plans more efficient queries. **Not validated at runtime** — set only if guaranteed; otherwise aggregates return wrong results. |

Note: the source-side rows are referenced under the namespace `source`; the joined-side rows under the join's `name`. The example reference uses `source.l_orderkey = orders.o_orderkey`. If no prefix is given inside an `on`, it defaults to the joined table.

## `dimensions[*]`

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | Yes | Column alias used in `SELECT` / `WHERE` / `GROUP BY`. |
| `expr` | string | Yes | SQL expression returning a scalar. May reference source columns, joined columns, or previously-defined dimensions. |
| `comment` | string | No | Per-dimension description. Surfaces in UC. |
| `display_name` | string | No (1.1+) | Visualization label, ≤ 255 chars. |
| `format` | map | No (1.1+) | Display format spec. |
| `synonyms` | array of string | No (1.1+) | Up to 10 alternate names for AI/BI discovery, each ≤ 255 chars. |

Dimensions do **not** have `window`. Window specs live on measures.

## `measures[*]`

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | Yes | Alias; query via `MEASURE(<name>)`. |
| `expr` | string | Yes | Aggregate SQL expression. Supports `FILTER (WHERE …)` to scope a measure. |
| `comment` | string | No | Per-measure description. |
| `display_name` | string | No (1.1+) | Visualization label, ≤ 255 chars. |
| `format` | map | No (1.1+) | Display format spec. |
| `synonyms` | array | No (1.1+) | Up to 10 alternate names for AI/BI discovery. |
| `window` | array | No (experimental) | Windowed / cumulative / semiadditive aggregations. See below. |

## `measures[*].window[*]`

| Field | Type | Required | Description |
|---|---|---|---|
| `order` | string | Yes | Dimension that orders the window. Should be deterministic (date/timestamp). |
| `range` | string | Yes | Window extent — see values below. |
| `semiadditive` | string | Yes | `first` or `last` — semi-additive aggregation method. |
| `offset` | string | No (DBR 18.1 + YAML 1.1) | Shift the window frame, e.g. `-12 month`, `1 year`, `-3 days`, `7 day`. `null` if shifted frame falls outside data. No effect on `range: all`. |

**Supported `range` values:**

- `current` — rows whose order value equals the anchor row
- `cumulative` — rows with order value ≤ anchor
- `trailing <n> <unit> [inclusive | exclusive]` — e.g. `trailing 7 day`
- `leading <n> <unit> [inclusive | exclusive]` — e.g. `leading 3 month`
- `all` — every row regardless of order

`inclusive`/`exclusive` requires DBR 18.1 + YAML 1.1; default is `exclusive`.

## `materialization` (experimental)

Top-level fields:

| Field | Type | Required | Description |
|---|---|---|---|
| `schedule` | string | Yes | Refresh schedule (same syntax as MV `SCHEDULE` clause, e.g. `every 6 hours` / `cron …`). `TRIGGER ON UPDATE` not supported. |
| `mode` | string | Yes | Must be `relaxed`. |
| `materialized_views` | array | Yes | One or more materializations. |

`materialized_views[*]`:

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | Yes | Identifier of the materialization. |
| `type` | string | Yes | `aggregated` or `unaggregated`. |
| `dimensions` | array of dim names | Conditional | Required for `aggregated` if `measures` is empty. |
| `measures` | array of measure names | Conditional | Required for `aggregated` if `dimensions` is empty. |

`unaggregated` materializes the base row set; `aggregated` materializes a pre-aggregated rollup along the listed dimensions/measures so matching queries skip the full scan.

## DDL — registering the YAML as a Metric View

```sql
CREATE OR REPLACE VIEW <catalog>.<schema>.<name>
  WITH METRICS
  LANGUAGE YAML
  COMMENT '<optional description>'
AS $$
<yaml content>
$$;
```

Update with `ALTER VIEW <name> AS $$ … $$;` — see the spec's "Upgrade to YAML 1.1" section for how YAML comments vs UC comments interact.

## Query semantics — `MEASURE()`

```sql
SELECT
  order_priority,                       -- dimension
  MEASURE(total_revenue)                -- measure must always go through MEASURE()
FROM <catalog>.<schema>.orders_mv
WHERE order_status = 'F'
GROUP BY order_priority
ORDER BY MEASURE(total_revenue) DESC;
```

## YAML formatting gotchas (from the spec)

- **Column names with spaces** — wrap in backticks: `` expr: '`First Name`' `` (single-quote the value).
- **Backtick-starting expressions** — wrap the whole thing in double quotes; YAML cannot start an unquoted value with a backtick.
- **Colons inside expressions** — always double-quote the whole expression: `expr: "CASE WHEN col = 'A:B' THEN 1 END"`.
- **Multi-line expressions** — use a block scalar `|`:
  ```yaml
  expr: |
    CASE WHEN revenue > 100 THEN 'High' ELSE 'Low' END
  ```

## What's NOT in this YAML (lives elsewhere in UC)

- Row filters and column masks — applied to base tables via separate UC SQL function objects.
- Grants — `GRANT … ON VIEW …` on the metric view object.

## Concrete examples in this directory

- `orders.metric_view.yaml` — flat orders model, all 1.1 metadata fields shown (comment, display_name, synonyms).
- `lineitem.metric_view.yaml` — join (with `rely`), `FILTER (WHERE …)` measure, **window measure**, and a **`materialization` block**.
