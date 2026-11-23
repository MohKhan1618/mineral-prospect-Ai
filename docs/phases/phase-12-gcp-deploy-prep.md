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

## DEPLOYED 2026-11-23
- Service `mpm-serve`, project `project-70d1cab1-0a66-4f48-a40`, region `us-central1`, revision `mpm-serve-00001-nwd`,
  1 CPU, 1 GiB, min 0 / max 2 instances, public (`--allow-unauthenticated`; the organisation did not block it).
- URL: https://mpm-serve-128504750100.us-central1.run.app
- Image: `us-central1-docker.pkg.dev/project-70d1cab1-0a66-4f48-a40/mpm/mpm-serve:phase12` (the same image tested locally in Phase 11, retagged and pushed).
- **Deviation:** Cloud Build failed with a 403 (the default compute service account could not read the build-source bucket). I did not change
  IAM; I pushed the locally built image to Artifact Registry instead. `cloudbuild.yaml` and `.gcloudignore` therefore remain untested.
- Smoke test (from this machine): `/health` ok (1.8 s), `/` 200, `/model-info` 200, `/areas` 200, bad input -> 422. `/predict/point` at
  (-108.6, 42.5) returned logit -1.1445, percentile 0.665, identical to the local container. The first prediction took about 3 s (cold start).
  Logs show the requests with no errors.
- Not checked: the page rendered in a browser against the live URL (Leaflet and tiles load from the internet); memory use under load.
- Trial ends 17 December 2026; the service stops then unless the account is upgraded.
- Teardown: `gcloud run services delete mpm-serve --region us-central1` and `gcloud artifacts repositories delete mpm --location us-central1`.

## Redeploy 2026-11-23 (frontend coordinates and units)
Revision `mpm-serve-00002-2jl`, image tag `phase12b` (built locally, pushed to Artifact Registry), same settings (max 2 instances, public). Live checks: `/health` ok, `/app.js` contains the new UTM code, `/predict/point` returns the same percentile (0.665) plus `approx_concentration`, `/areas` 200. Not checked: the live page rendered in a browser (checked only on a local server).
