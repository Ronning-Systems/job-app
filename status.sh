#!/bin/bash
# Show Cloud Run service status and revision history

set -e

REGION="${REGION:-us-west1}"
SERVICE_NAME="${SERVICE_NAME:-job-app}"

echo "=========================================================================="
echo "JobSync Cloud Run Status"
echo "=========================================================================="
echo "Project: $(gcloud config get-value project)"
echo "Region:  ${REGION}"
echo "Service: ${SERVICE_NAME}"
echo "=========================================================================="
echo ""

# Service info
echo "Service Details:"
echo "----------------"
gcloud run services describe "${SERVICE_NAME}" \
  --region "${REGION}" \
  --format="table(
    metadata.name,
    metadata.creationTimestamp,
    status.url,
    status.traffic[0].percent,
    status.traffic[0].revisionName
  )"

echo ""

# Traffic distribution
echo "Traffic Distribution:"
echo "--------------------"
gcloud run services describe-traffic "${SERVICE_NAME}" \
  --region "${REGION}"

echo ""

# Recent revisions
echo "Recent Revisions (last 10):"
echo "---------------------------"
gcloud run revisions list \
  --service "${SERVICE_NAME}" \
  --region "${REGION}" \
  --format="table(
    metadata.name,
    metadata.creationTimestamp,
    status.trafficPercent,
    status.active
  )" \
  --sort-by="-metadata.creationTimestamp" \
  --limit=10

echo ""

# Container image info
echo "Container Image:"
echo "----------------"
gcloud run services describe "${SERVICE_NAME}" \
  --region "${REGION}" \
  --format="value(spec.template.spec.containers[0].image)"
