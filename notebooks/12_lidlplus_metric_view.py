# Databricks notebook source
# MAGIC %md
# MAGIC # lidlplus transactions — seed synthetic table + Metric View
# MAGIC
# MAGIC The real lidlplus data isn't available in this workspace, so the notebook
# MAGIC seeds a small synthetic `lidlplus_transactions` table (~5000 rows across
# MAGIC five EU markets, four loyalty tiers, three payment methods) and creates
# MAGIC a Metric View on top. Swap `source` for the real customer table once
# MAGIC available — the OSI contract stays identical.

# COMMAND ----------

dbutils.widgets.text("catalog",     "main",                       "Catalog")
dbutils.widgets.text("schema",      "osi_demo",                   "Schema")
dbutils.widgets.text("table",       "lidlplus_transactions",      "Source table name")
dbutils.widgets.text("metric_view", "lidlplus_transactions_mv",   "Metric view name")
dbutils.widgets.text("rows",        "5000",                       "Synthetic rows to generate")

CATALOG     = dbutils.widgets.get("catalog")
SCHEMA      = dbutils.widgets.get("schema")
TABLE       = dbutils.widgets.get("table")
METRIC_VIEW = dbutils.widgets.get("metric_view")
ROWS        = int(dbutils.widgets.get("rows"))

TABLE_FQN = f"{CATALOG}.{SCHEMA}.{TABLE}"
MV_FQN    = f"{CATALOG}.{SCHEMA}.{METRIC_VIEW}"
print(f"Will seed table: {TABLE_FQN}")
print(f"Will create MV:  {MV_FQN}")

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA} "
          f"COMMENT 'OSI ↔ Gemini hackathon demo'")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Seed synthetic transactions

# COMMAND ----------

import pyspark.sql.functions as F

countries        = ["DE", "FR", "ES", "PL", "IT"]
loyalty_tiers    = ["none", "bronze", "silver", "gold"]
payment_methods  = ["cash", "card", "lidlpay"]

base = (
    spark.range(ROWS)
    .withColumnRenamed("id", "transaction_id")
    # ~2 years of history ending today
    .withColumn(
        "transaction_date",
        F.date_sub(F.current_date(), (F.rand(seed=1) * 730).cast("int")),
    )
    .withColumn(
        "country",
        F.element_at(F.array(*[F.lit(c) for c in countries]),
                     (F.rand(seed=2) * len(countries)).cast("int") + 1),
    )
    .withColumn(
        "store_id",
        F.concat(F.col("country"), F.lit("-"),
                 F.lpad(((F.rand(seed=3) * 200).cast("int") + 1).cast("string"), 4, "0")),
    )
    .withColumn(
        "customer_id",
        F.concat(F.lit("cust-"),
                 F.lpad(((F.rand(seed=4) * 10000).cast("int") + 1).cast("string"), 6, "0")),
    )
    .withColumn(
        "loyalty_tier",
        F.element_at(F.array(*[F.lit(t) for t in loyalty_tiers]),
                     (F.rand(seed=5) * len(loyalty_tiers)).cast("int") + 1),
    )
    .withColumn(
        "payment_method",
        F.element_at(F.array(*[F.lit(p) for p in payment_methods]),
                     (F.rand(seed=6) * len(payment_methods)).cast("int") + 1),
    )
    # Basket €4–€85, with gold tier skewed higher
    .withColumn(
        "total_amount",
        F.round(
            F.when(F.col("loyalty_tier") == "gold",
                   F.lit(20.0) + F.rand(seed=7) * 80.0)
             .otherwise(F.lit(4.0) + F.rand(seed=8) * 60.0),
            2,
        ),
    )
)

(base.write.mode("overwrite")
     .option("overwriteSchema", "true")
     .saveAsTable(TABLE_FQN))
print(f"Seeded {ROWS} rows into {TABLE_FQN}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create Metric View

# COMMAND ----------

ddl = f"""
CREATE OR REPLACE VIEW {MV_FQN}
  WITH METRICS
  LANGUAGE YAML
  COMMENT 'lidlplus loyalty transactions semantic model — synthetic OSI demo'
AS $$
version: 0.1
source: {TABLE_FQN}

dimensions:
  - name: country
    expr: country
  - name: store_id
    expr: store_id
  - name: loyalty_tier
    expr: loyalty_tier
  - name: payment_method
    expr: payment_method
  - name: transaction_date
    expr: transaction_date

measures:
  - name: total_revenue
    expr: SUM(total_amount)
  - name: transaction_count
    expr: COUNT(*)
  - name: avg_basket
    expr: AVG(total_amount)
  - name: unique_customers
    expr: COUNT(DISTINCT customer_id)
$$
"""
spark.sql(ddl)
print(f"Created metric view {MV_FQN}")

# COMMAND ----------

display(spark.sql(f"""
    SELECT MEASURE(total_revenue)     AS revenue,
           MEASURE(transaction_count) AS transactions,
           MEASURE(avg_basket)        AS avg_basket,
           country,
           loyalty_tier
    FROM {MV_FQN}
    GROUP BY country, loyalty_tier
    ORDER BY revenue DESC
"""))
