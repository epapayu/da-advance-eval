#!/bin/bash
set -e

PROJECT_ID="praxis-magnet-508004-d7"
REGION="us-central1"
SECRET_NAME="bigtable-mcp-tools-secret"
SERVICE_NAME="mcp-toolbox-bigtable"
CONFIG_FILE="mcp_config/tools.yaml"

echo "=== Step 1: Managing Secret Manager Configuration ==="
if gcloud secrets describe "${SECRET_NAME}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo "Secret ${SECRET_NAME} exists. Adding new version..."
  gcloud secrets versions add "${SECRET_NAME}" \
    --data-file="${CONFIG_FILE}" \
    --project="${PROJECT_ID}"
else
  echo "Creating secret ${SECRET_NAME}..."
  gcloud secrets create "${SECRET_NAME}" \
    --replication-policy="automatic" \
    --project="${PROJECT_ID}"
  gcloud secrets versions add "${SECRET_NAME}" \
    --data-file="${CONFIG_FILE}" \
    --project="${PROJECT_ID}"
fi

echo "=== Step 2: Granting IAM Permissions to Service Account ==="
PROJECT_NUM=$(gcloud projects describe "${PROJECT_ID}" --format="value(projectNumber)")
SA="${PROJECT_NUM}-compute@developer.gserviceaccount.com"

echo "Binding secretAccessor to ${SA}..."
gcloud secrets add-iam-policy-binding "${SECRET_NAME}" \
  --member="serviceAccount:${SA}" \
  --role="roles/secretmanager.secretAccessor" \
  --project="${PROJECT_ID}" --quiet || true

echo "Binding bigtable.admin to ${SA}..."
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA}" \
  --role="roles/bigtable.admin" --quiet || true

echo "=== Step 3: Deploying Cloud Run MCP Service ==="
gcloud run deploy "${SERVICE_NAME}" \
  --image="us-central1-docker.pkg.dev/database-toolbox/toolbox/toolbox:latest" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --set-secrets="/etc/toolbox/tools.yaml=${SECRET_NAME}:latest" \
  --set-env-vars="TOOLBOX_CONFIG=/etc/toolbox/tools.yaml" \
  --args="--config=/etc/toolbox/tools.yaml","--address=0.0.0.0","--port=8080" \
  --port=8080 \
  --allow-unauthenticated \
  --quiet

echo "=== Step 4: Exporting Cloud Run Service URL ==="
SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --format="value(status.url)")

echo "Deployed Service URL: ${SERVICE_URL}"

# Update .env if present
if [ -f .env ]; then
  sed -i "s|^BIGTABLE_MCP_URL=.*|BIGTABLE_MCP_URL=${SERVICE_URL}|" .env
  echo "Updated BIGTABLE_MCP_URL in .env"
fi
