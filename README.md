# data_airlock
The Data Airlock Suite is an enterprise pre-transformation data ingestion control plane. It sits between incoming raw vendor payloads (POS, PMS, and F&amp;B systems) and downstream ETL/analytics pipelines, acting as a non-mutating perimeter guard.
Here is a brief, professional description designed to paste directly into your repository’s `README.md` or project overview:

---

# Data Airlock Suite

The **Data Airlock Suite** is an enterprise pre-transformation data ingestion control plane. It sits between incoming raw vendor payloads (POS, PMS, and F&B systems) and downstream ETL/analytics pipelines, acting as a non-mutating perimeter guard.

Instead of allowing corrupted, incomplete, or misidentified data to hit data warehouses and crash downstream jobs, the Airlock Suite inspects raw files in object storage (S3) in milliseconds, enforcing physical, structural, and financial integrity without altering a single byte.

---

### Core Principles

* **Zero Mutation:** Inspects and evaluates raw files in landing storage without casting, scrubbing, or rewriting source bytes.
* **Pass-by-Default, Fail-Closed:** Valid data flows instantly to downstream ETL; contract violations trigger immediate isolation (`QUARANTINE_FILE`, `REJECT_FILE`, or `HOLD_SET`).
* **Declarative Contracts:** Vendors and properties are configured via versioned YAML profiles rather than custom code scripts.

---

### The 4 Pre-Transformation Control Gates

1. **Gate 1: Extraction Contract (Stateless Landing)**
Verifies filename regex contracts, path-to-filename token agreement, byte-decoding integrity, row-conservation invariants, and multi-file atomic set completeness (e.g., holding partial POS drops until `headers`, `sales`, and `payments` arrive together).
2. **Gate 2: Anomaly Detection (Stateful Trends)**
Queries historical metadata to detect 30-day Day-of-Week $z$-score volume anomalies, frozen business date windows, unannounced rolling extract drift, and late delivery SLA breaches.
3. **Gate 3: Data Quality (Structural & Type Inspection)**
Verifies expected column presence, mandatory non-null constraints, ISO date formatting, and numerical range bounds.
4. **Gate 4: Revenue Reconciliation (Financial Macro-Balancing)**
Executes pre-ETL mathematical balancing (e.g., verifying `Check Header Total == Sum(Line Items) + Taxes` and `Total Sales == Total Tender Payments`).

---

### Tech Stack

* **Frontend UI (`/apps/web`):** Next.js 14 (App Router), TypeScript, Tailwind CSS, Monaco Editor, Supabase JS.
* **Backend Engine (`/services/engine`):** Python 3.11, FastAPI, Polars (high-speed Rust-backed data processing), Pydantic v2, PyYAML.
* **Database & Metadata:** Supabase (PostgreSQL + JSONB for versioned contracts & audit trails).
* **Storage & Infrastructure:** Amazon S3 / Cloudflare R2 (Raw Landing Storage), Docker + Railway (Engine Hosting).
