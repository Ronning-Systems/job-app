#!/bin/bash
# Migrate traffic to the latest Cloud Run revision
# Run this after deploy.sh to shift traffic to the new version

set -e

REGION="${REGION:-us-west1}"
SERVICE_NAME="${SERVICE_NAME:-job-app}"

echo "=========================================================================="
echo "JobSync Cloud Run Traffic Migration"
echo "=========================================================================="
echo "Project: $(gcloud config get-value project)"
echo "Region:  ${REGION}"
echo "Service: ${SERVICE_NAME}"
echo "=========================================================================="
echo ""

# Show current traffic split
echo "Current traffic distribution:"
gcloud run services describe "${SERVICE_NAME}" \
  --region "${REGION}" \
  --format="table(status.traffic[].map().basion(),status.traffic[].map().percent())"

echo ""
echo "Migrating 100% traffic to latest revision..."
echo ""

gcloud run services update-traffic "${SERVICE_NAME}" \
  --region "${REGION}" \
  --to-latest

echo ""
echo "✓ Traffic migration complete!"
echo ""
echo "Service URL:"
gcloud run services describe "${SERVICE_NAME}" \
  --region "${REGION}" \
  --format="value(status.url)"
