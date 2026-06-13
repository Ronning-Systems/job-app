#!/bin/bash
# One-time setup script for JobSync Cloud Run deployment
# Run this once before deploying with Cloud Build

set -e

PROJECT_ID=$(gcloud config get-value project)
REGION=${1:-us-central1}

echo "Setting up JobSync infrastructure in project: $PROJECT_ID, region: $REGION"
echo "==========================================================================="

# Enable required APIs
echo "1. Enabling required APIs..."
gcloud services enable \
  run.googleapis.com \
  sqladmin.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  artifactregistry.googleapis.com

# Create Cloud SQL instance
echo "2. Creating Cloud SQL instance (this takes a few minutes)..."
gcloud sql instances create jobsync-db \
  --database-version=POSTGRES_15 \
  --tier=db-f1-micro \
  --region=$REGION || echo "Instance may already exist, continuing..."

# Create database
echo "3. Creating database..."
gcloud sql databases create jobsync --instance=jobsync-db || echo "Database may already exist, continuing..."

# Prompt for password
echo "4. Creating database user..."
read -s -p "Enter password for jobsync DB user: " DB_PASSWORD
echo ""
gcloud sql users create jobsync --instance=jobsync-db --password="$DB_PASSWORD" || echo "User may already exist, continuing..."

# Get the Cloud SQL connection name
CONNECTION_NAME=$(gcloud sql instances describe jobsync-db --format="value(connectionName)")

# Create Secret Manager secrets
echo "5. Creating secrets..."
echo -n "postgresql+psycopg2://jobsync:${DB_PASSWORD}@/jobsync?host=/cloudsql/${CONNECTION_NAME}" | \
  gcloud secrets create jobsync-database-url --data-file=- || echo "Secret may already exist, continuing..."

read -s -p "Enter Ollama Cloud API key: " OLLAMA_API_KEY_VALUE
echo ""
echo -n "$OLLAMA_API_KEY_VALUE" | \
  gcloud secrets create ollama-api-key --data-file=- || echo "Secret may already exist, continuing..."

# Get project number for IAM
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format="value(projectNumber)")

# Grant Cloud Run access to secrets
echo "6. Granting IAM access to secrets..."
gcloud secrets add-iam-policy-binding jobsync-database-url \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

gcloud secrets add-iam-policy-binding ollama-api-key \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

echo ""
echo "Setup complete! Now deploy with:"
echo "  gcloud builds submit --config=cloudbuild.yaml"