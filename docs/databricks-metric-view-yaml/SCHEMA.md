# Databricks Unity Catalog Metric View — YAML Schema Reference

The native YAML format used inside the `CREATE OR REPLACE VIEW … WITH METRICS LANGUAGE YAML AS $$…$$` DDL on a Databricks SQL warehouse.

## Top-level structure

```yaml
version: 0.1                       # required — currently "0.1"
source: <fqn | SELECT statement>   # required — either a fully-qualified UC table name OR an inline SELECT
filter: <SQL boolean expression>   # optional — global WHERE clause applied to source rows
joins:                             # optional — additional tables joined into the view
  - name: <alias>
    source: <fqn>
    'on': <SQL join predicate>
dimensions:                        # required — at least one dimension
  - name: <unique-identifier>
    expr: <SQL expression>
    window:                          # optional — for time dimensions, granularity controls
      - granularity: day | week | month | quarter | year
measures:                          # required — at least one measure
  - name: <unique-identifier>
    expr: <aggregate SQL expression>   # SUM, COUNT, AVG, MIN, MAX, COUNT(DISTINCT …), etc.
    window:                          # optional — windowed measures (rolling, period-over-period)
      - granularity: day | week | month | quarter | year
        order: <SQL expression>
        range: <SQL interval>
```

## Field semantics

| Field | Required | Notes |
|---|---|---|
| `version` | Yes | Currently `0.1`. Reserved for forward compatibility. |
| `source` | Yes | Three-part FQN (`catalog.schema.table`) is preferred. Inline SQL is allowed but recommend pinning a fixed source for governance. |
| `filter` | No | Applied to every query against the view. Useful for soft-delete or tenancy filters. Does NOT apply to base-table grants — use UC row filters for that. |
| `joins[*].name` | Yes (when `joins` present) | Alias used to qualify columns from the joined table inside dimension/measure expressions. |
| `joins[*].source` | Yes (when `joins` present) | FQN of the joined table. |
| `joins[*].on` | Yes (when `joins` present) | SQL join predicate. Note YAML quoting: `on` is a reserved word, use `'on'`. |
| `dimensions[*].name` | Yes | Unique identifier; what consumers reference in `GROUP BY` and `WHERE`. |
| `dimensions[*].expr` | Yes | SQL expression evaluated per row. Most commonly a column reference, but can be any deterministic expression. |
| `dimensions[*].window[*].granularity` | No | Restricts a time dimension to a fixed grain in queries. |
| `measures[*].name` | Yes | Unique identifier; queried via `MEASURE(<name>)`. |
| `measures[*].expr` | Yes | Aggregate SQL expression. Engine validates this is an aggregate; non-aggregates are rejected at CREATE time. |
| `measures[*].window[*]` | No | Defines windowed / rolling / period-over-period semantics. |

## How consumers query a metric view

Always through `MEASURE()`, never raw column references on the measure side:

```sql
SELECT
  order_priority,                       -- dimension reference
  MEASURE(total_revenue)                -- measure must go through MEASURE()
FROM peymandemoaws_catalog.osi_demo.orders_mv
WHERE order_status = 'F'                -- dimensions are queryable in WHERE
GROUP BY order_priority
ORDER BY MEASURE(total_revenue) DESC;
```

The engine rewrites `MEASURE(total_revenue)` into the underlying aggregate expression `SUM(o_totalprice)` from the YAML.

## DDL — how the YAML is registered as a Metric View

```sql
CREATE OR REPLACE VIEW <catalog>.<schema>.<view_name>
  WITH METRICS
  LANGUAGE YAML
  COMMENT '<optional description>'
AS $$
<yaml content here>
$$;
```

## What's NOT carried in this YAML (governance lives elsewhere)

- **Row filters and column masks** — applied to base tables via separate UC SQL function objects, not in this YAML.
- **Grants / access control** — managed via `GRANT … ON VIEW …` on the metric view object.
- **Synonyms / display names / descriptions for AI agents** — Databricks Metric View YAML does not currently carry these. Companion `agent_metadata.yaml` files (or the OSI v1.0 wrapper) are how they ride along.

## Reference: published spec

- Metric view creation: https://docs.databricks.com/aws/en/sql/language-manual/sql-ref-syntax-ddl-create-metric-view
- Query semantics (`MEASURE()`): https://docs.databricks.com/aws/en/sql/language-manual/functions/measure
- DESCRIBE TABLE EXTENDED output for round-trip export: https://docs.databricks.com/aws/en/sql/language-manual/sql-ref-syntax-aux-describe-table

## Two concrete TPC-DS examples in this directory

- `orders.metric_view.yaml` — flat sales orders, basic dimensions + measures
- `lineitem.metric_view.yaml` — line-item sales with more advanced measures and a join example

Both are derived from the public `samples.tpch.*` tables shipped in every Databricks workspace.
