# Decision-Driven Cross-Cloud Disaster Recovery with Fail-Safe Restoration for Object Storage

A serverless, decision-driven disaster recovery system that replicates objects between **AWS** and **GCP** using content-aware deduplication and policy-based rules, with a manually-gated restoration pipeline to prevent accidental recovery.

Published at the 2026 IEEE International Conference on Contemporary Computing and Communications (InC4).

---

## Overview

Most organizations relying on a single cloud provider run the risk of outages, regional failures, or vendor lock-in, so cross-cloud backup is increasingly a necessity rather than a nice-to-have. But conventional cross-cloud DR tools re-copy entire objects on every change, treat all data the same regardless of size/importance, and risk unwanted bidirectional sync during recovery — wasting bandwidth, storage, and money in the process.

This project builds a fully serverless, event-driven alternative that only moves data when it's actually needed, and only restores it when a human explicitly says so. It's built entirely on managed, pay-per-use services (Lambda, Cloud Run, DynamoDB, Pub/Sub) so there's no idle infrastructure cost, and it plugs into an existing AWS/GCP setup via event triggers rather than requiring a separate always-on replication server. Three components make this possible:

- **CADRS** – SHA-256 content hashing to detect real changes and skip redundant transfers
- **RDPE** – a policy engine that decides *how* to replicate an object, based on its size and how often it's updated
- **FRSM** – a fail-safe, manually-triggered restoration mechanism (no auto-recovery, so a false alarm can never silently overwrite good data)

---

## Architecture

| AWS → GCP Replication Pipeline | GCP → AWS Recovery Pipeline |
|:---:|:---:|
| S3 event triggers Lambda, which hashes the object (CADRS), consults DynamoDB state, and RDPE decides: **Skip / Replicate Now / Delay / Batch**. | Recovery only happens on an explicit, manually published Pub/Sub message — Cloud Run validates it and restores the object to S3. |
| <img src="./cropped_architecture_pipeline1.png" alt="AWS to GCP Replication Pipeline" width="320"/> | <img src="./cropped_architecture_pipeline2.png" alt="GCP to AWS Recovery Pipeline" width="220"/> |

---

## Repo Structure

```
.
├── lambda_aws.py                  # AWS Lambda: S3 trigger, CADRS hashing, RDPE policy, DynamoDB updates
├── GCP restoration cloud run.py   # GCP Cloud Run: FRSM restoration logic
├── Literature survey/             # Reference papers
├── Cross_Cloud_final_Cam_ready.pdf
└── .gitignore
```

---

## Highlights from the Paper

- Eliminated **9/10 redundant transfers** in repeated-upload tests via CADRS
- RDPE correctly classified all test cases across SKIP / REPLICATE_NOW / DELAY / BATCH
- Estimated cost: **~$1.8/month** for 1,000 uploads and 10 GB replicated data
- Object-level failure isolation with automatic retry for pending replications

For full results, cost breakdown, comparison with tools like AWS DataSync/Skyplane, and limitations, see the paper.

---

## Citation

R. Keerthana Prasad, N. Sukhitha Bhushan, and Aparna R, "Decision-Driven Cross-Cloud Disaster Recovery with Fail-Safe Restoration for Object Storage," 2026 IEEE InC4.
