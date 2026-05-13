#!/usr/bin/env bash
# Upload notebooks to /Users/<you>/osi-demo/ on Databricks.
# Reads .env (DATABRICKS_PROFILE, DATABRICKS_HOST, DATABRICKS_TOKEN).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Source .env if present (won't override existing shell env)
if [ -f "${REPO_ROOT}/.env" ]; then
  set -a; source "${REPO_ROOT}/.env"; set +a
fi

PROFILE="${DATABRICKS_PROFILE:-DEFAULT}"

# Prefer existing DATABRICKS_HOST/TOKEN; otherwise derive from CLI profile
if [ -z "${DATABRICKS_HOST:-}" ] || [ -z "${DATABRICKS_TOKEN:-}" ]; then
  echo "Deriving host/token from CLI profile '${PROFILE}'…"
  export DATABRICKS_HOST="$(databricks auth env --profile "${PROFILE}" 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["env"]["DATABRICKS_HOST"])' 2>/dev/null || true)"
  export DATABRICKS_TOKEN="$(databricks auth token --profile "${PROFILE}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')"
fi

if [ -z "${DATABRICKS_HOST:-}" ] || [ -z "${DATABRICKS_TOKEN:-}" ]; then
  echo "ERROR: set DATABRICKS_HOST and DATABRICKS_TOKEN (in .env or shell), or DATABRICKS_PROFILE." >&2
  exit 1
fi

EMAIL="${EMAIL:-$(curl -s "${DATABRICKS_HOST%/}/api/2.0/preview/scim/v2/Me" \
  -H "Authorization: Bearer ${DATABRICKS_TOKEN}" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["userName"])')}"

TARGET="/Users/${EMAIL}/osi-demo"

echo "Workspace: ${DATABRICKS_HOST}"
echo "User:      ${EMAIL}"
echo "Target:    ${TARGET}"

databricks workspace mkdirs "${TARGET}" || true

NOTEBOOKS=(
  "01_create_metric_view.py:PYTHON"
  "02_export_to_osi.py:PYTHON"
  "03_test_queries.py:PYTHON"
  "10_nytaxi_metric_view.py:PYTHON"
  "11_tpc_sales_metric_view.py:PYTHON"
  "12_lidlplus_metric_view.py:PYTHON"
)

for nb in "${NOTEBOOKS[@]}"; do
  fn="${nb%%:*}"; lang="${nb##*:}"; base="${fn%.*}"
  src="${REPO_ROOT}/notebooks/${fn}"
  dst="${TARGET}/${base}"
  echo "  → ${dst} (${lang})"
  databricks workspace import "${dst}" \
    --file "${src}" --language "${lang}" --format SOURCE --overwrite
done

echo "Done. Open ${TARGET} in the workspace UI."
