# Phase 12 - GCP Cloud Run: preparation (NOT deployed)

Status: prepared, awaiting explicit go-ahead   Date: 2026-11-23

## Decisions (owner, 2026-11-23)
1. **Access: public, `--max-instances 2`.** The API has no authentication or rate limit. If the organisation policy blocks public access, fall back to private and say so.
2. **Region:** `us-central1` (default, not yet explicitly confirmed).
3. **Project:** `project-70d1cab1-0a66-4f48-a40` ("My First Project"). A new project could not be billed (trial billing-project limit), so the existing one is used; teardown = delete the service and repo, not the project.
4. **Budget alert:** optional on the free trial (ends 17 December 2026; resources stop then unless upgraded); required before any upgrade to paid.

## Commands (run by the owner, or by me after go-ahead in a session already logged in by the owner)
```
gcloud config set project PROJECT_ID
gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com
gcloud artifacts repositories create mpm --repository-format=docker --location=us-central1
gcloud builds submit --config cloudbuild.yaml --substitutions _IMAGE=us-central1-docker.pkg.dev/PROJECT_ID/mpm/mpm-serve:phase12 .
gcloud run deploy mpm-serve --image us-central1-docker.pkg.dev/PROJECT_ID/mpm/mpm-serve:phase12 \
  --region us-central1 --memory 1Gi --cpu 1 --min-instances 0 --max-instances 2 --allow-unauthenticated
```
Fixed 2026-11-23: `gcloud builds submit` has no `-f`, so `cloudbuild.yaml` builds `Dockerfile.serve`. `.gcloudignore` keeps `models/final` in the upload (gcloud would otherwise follow `.gitignore`). Not yet run.
Model files travel with the repo through Git LFS (`models/final/*.npz`), per the owner's choice for gate G5.

## Checks after deploy
`/health` ok, page loads, point prediction, `/areas`; read logs; confirm cold-start time.

## Cost and safety notes
Scale to zero means no idle cost; cost comes from requests, Cloud Build and Artifact Registry storage (about 0.3 GB).
Set a budget alert (owner, in Billing). Teardown: `gcloud run services delete mpm-serve`, delete the Artifact Registry repo.
Memory: the model files total about 97 MB in RAM plus Python; 1 GiB is a guess to confirm from the container's measured memory.
