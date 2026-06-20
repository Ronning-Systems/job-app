#!/bin/bash
# Rollback script for JobSync Cloud Run deployment
# Reverts traffic to the previous revision

set -e

REGION="${REGION:-us-west1}"
SERVICE_NAME="${SERVICE_NAME:-job-app}"

echo "=========================================================================="
echo "JobSync Cloud Run Rollback"
echo "=========================================================================="
echo "Project:  $(gcloud config get-value project)"
echo "Region:   ${REGION}"
echo "Service:  ${SERVICE_NAME}"
echo "=========================================================================="
echo ""

# List recent revisions
echo "Recent revisions:"
gcloud run revisions list \
  --service "${SERVICE_NAME}" \
  --region "${REGION}" \
  --format="table(metadata.name,metadata.creationTimestamp,status.trafficPercent)" \
  --sort-by="-metadata.creationTimestamp" \
  --limit=5

echo ""

# Get the second-to-last revision (previous one)
PREVIOUS_REVISION=$(gcloud run revisions list \
  --service "${SERVICE_NAME}" \
  --region "${REGION}" \
  --format="value(metadata.name)" \
  --sort-by="-metadata.creationTimestamp" \
  --limit=2 \
  | tail -1)

if [ -z "${PREVIOUS_REVISION}" ]; then
    echo "Error: Could not find a previous revision to rollback to"
    exit 1
fi

echo "Rolling back to revision: ${PREVIOUS_REVISION}"
echo ""

gcloud run services update-traffic "${SERVICE_NAME}" \
  --region "${REGION}" \
  --to-revisions "${PREVIOUS_REVISION}=100"

echo ""
echo "✓ Rollback complete! Traffic is now routed to ${PREVIOUS_REVISION}"
