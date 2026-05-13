# Databricks notebook source
# MAGIC %md
# MAGIC # TPC benchmark sales — create Metric View
# MAGIC
# MAGIC Builds `<catalog>.<schema>.<metric_view>` over a TPC benchmark fact table.
# MAGIC
# MAGIC The default source is `samples.tpch.lineitem` (universally available in
# MAGIC Databricks). To run against real TPC-DS, override the `source` widget
# MAGIC (e.g. `samples.tpcds_sf1.store_sales`) and adjust the column expressions
# MAGIC in the YAML body below to the TPC-DS column names.

# COMMAND ----------

dbutils.widgets.text("catalog",     "main",                   "Catalog")
dbutils.widgets.text("schema",      "osi_demo",               "Schema")
dbutils.widgets.text("metric_view", "tpc_sales_mv",           "Metric view name")
dbutils.widgets.text("source",      "samples.tpch.lineitem",  "Source table FQN")

CATALOG     = dbutils.widgets.get("catalog")
SCHEMA      = dbutils.widgets.get("schema")
METRIC_VIEW = dbutils.widgets.get("metric_view")
SOURCE      = dbutils.widgets.get("source")
FQN         = f"{CATALOG}.{SCHEMA}.{METRIC_VIEW}"
print(f"Source: {SOURCE}")
print(f"Will create: {FQN}")

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA} "
          f"COMMENT 'OSI ↔ Gemini hackathon demo'")

# COMMAND ----------

ddl = f"""
CREATE OR REPLACE VIEW {FQN}
  WITH METRICS
  LANGUAGE YAML
  COMMENT 'TPC benchmark sales line-items semantic model — OSI demo'
AS $$
version: 0.1
source: {SOURCE}

dimensions:
  - name: ship_mode
    expr: l_shipmode
  - name: return_flag
    expr: l_returnflag
  - name: ship_date
    expr: l_shipdate

measures:
  - name: net_sales
    expr: SUM(l_extendedprice * (1 - l_discount))
  - name: gross_sales
    expr: SUM(l_extendedprice)
  - name: units_sold
    expr: SUM(l_quantity)
  - name: line_count
    expr: COUNT(*)
$$
"""
spark.sql(ddl)
print(f"Created metric view {FQN}")

# COMMAND ----------

display(spark.sql(f"""
    SELECT MEASURE(net_sales)   AS net,
           MEASURE(units_sold)  AS units,
           ship_mode
    FROM {FQN}
    GROUP BY ship_mode
    ORDER BY net DESC
"""))
