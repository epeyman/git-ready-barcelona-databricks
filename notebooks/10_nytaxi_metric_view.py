# Databricks notebook source
# MAGIC %md
# MAGIC # NYC Taxi — create Metric View
# MAGIC
# MAGIC Builds `<catalog>.<schema>.<metric_view>` over `samples.nyctaxi.trips`.
# MAGIC Override the widgets to match your workspace, then Run All.

# COMMAND ----------

dbutils.widgets.text("catalog",     "main",                  "Catalog")
dbutils.widgets.text("schema",      "osi_demo",              "Schema")
dbutils.widgets.text("metric_view", "nyctaxi_trips_mv",      "Metric view name")
dbutils.widgets.text("source",      "samples.nyctaxi.trips", "Source table FQN")

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
  COMMENT 'NYC Taxi trips semantic model — OSI demo'
AS $$
version: 0.1
source: {SOURCE}

dimensions:
  - name: pickup_zip
    expr: pickup_zip
  - name: dropoff_zip
    expr: dropoff_zip
  - name: pickup_date
    expr: CAST(tpep_pickup_datetime AS DATE)

measures:
  - name: total_fare
    expr: SUM(fare_amount)
  - name: trip_count
    expr: COUNT(*)
  - name: avg_fare
    expr: AVG(fare_amount)
  - name: avg_trip_distance
    expr: AVG(trip_distance)
$$
"""
spark.sql(ddl)
print(f"Created metric view {FQN}")

# COMMAND ----------

display(spark.sql(f"""
    SELECT MEASURE(total_fare) AS fare,
           MEASURE(trip_count) AS trips,
           pickup_zip
    FROM {FQN}
    GROUP BY pickup_zip
    ORDER BY fare DESC
    LIMIT 10
"""))
