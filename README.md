# JobFit AI

An AI/NLP resume-to-job-description match analyzer. Upload a PDF resume and paste a job
description — JobFit AI extracts skills, computes semantic similarity, checks basic ATS
signals, and returns a match score with actionable recommendations.

No database. No authentication. No paid APIs. No external LLM calls — all NLP runs locally
using `sentence-transformers` (all-MiniLM-L6-v2) and scikit-learn.

## How the score works


- **Semantic similarity** — cosine similarity between sentence-transformer embeddings of
  the full resume and job description text.
- **Keyword match** — overlap between a canonical skills dictionary extracted from both
  texts (with alias normalization, e.g. `ReactJS → React`, `Postgres → PostgreSQL`).
- **ATS signals** — heuristic checks for structural sections (contact info, skills,
  experience, education, projects), resume length, measurable achievements, and JD keyword
  coverage. This is an **ATS-style analysis**, not a simulation of any specific company's
  actual applicant tracking system.

## Project structure

```text
jobfit-ai/
  backend/
    app/
      main.py          # FastAPI app, /api/analyze endpoint
      analyzer.py       # scoring, similarity, ATS checks, recommendations
      pdf_parser.py      # PyMuPDF text extraction
      skills.py          # skills dictionary + alias normalization
      schemas.py         # Pydantic response models
    requirements.txt
    .env.example
  frontend/
    app/
      page.tsx            # main single-page UI
      layout.tsx
      globals.css
    components/
      UploadForm.tsx       # PDF upload + JD textarea
      Results.tsx           # score dashboard
    lib/
      api.ts                # backend API client
      types.ts
    package.json
    .env.example
  render.yaml               # Render blueprint for the backend
  .gitignore
```

## Local development

### Backend (FastAPI)

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # adjust ALLOWED_ORIGINS if needed
uvicorn app.main:app --reload --port 8000
```

The first request (or app startup) downloads the `all-MiniLM-L6-v2` model (~90 MB) from
Hugging Face and caches it locally — this only happens once.

Backend runs at `http://localhost:8000`. Interactive API docs at `http://localhost:8000/docs`.

### Frontend (Next.js)

```bash
cd frontend
npm install
cp .env.example .env.local      # NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev
```

Frontend runs at `http://localhost:3000`.

## Deployment

### Backend → Render

**Option A — Blueprint (recommended):** push this repo to GitHub, then in Render choose
"New +" → "Blueprint" and point it at the repo. `render.yaml` at the project root configures
everything automatically.

**Option B — Manual web service:**
1. New + → Web Service → connect your GitHub repo.
2. **Root Directory:** `backend`
3. **Build Command:** `pip install -r requirements.txt`
4. **Start Command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. **Environment Variables:** add `ALLOWED_ORIGINS` set to your Vercel frontend URL once
   deployed (e.g. `https://jobfit-ai.vercel.app`). Use `*` initially if you want to test
   before the frontend is deployed.

> Free Render instances spin down after inactivity — the first request after idle can take
> 30-60 seconds while the instance wakes up and the model loads.

### Frontend → Vercel

1. Import the repo in Vercel.
2. **Root Directory:** `frontend`
3. Framework preset: Next.js (auto-detected).
4. **Environment Variable:** `NEXT_PUBLIC_API_URL` = your Render backend URL
   (e.g. `https://jobfit-ai-backend.onrender.com`, no trailing slash).
5. Deploy.

After both are live, update the backend's `ALLOWED_ORIGINS` env var on Render to your final
Vercel URL and redeploy the backend so CORS allows requests from it.

## API

### `POST /api/analyze`

**Request:** `multipart/form-data`
- `resume` — PDF file (max 5 MB)
- `job_description` — string (max 20,000 characters)

**Response:** `200 OK`

```json
{
  "overall_score": 78,
  "semantic_similarity": 82,
  "keyword_match": 74,
  "ats_score": 80,
  "matched_skills": ["Python", "SQL", "FastAPI"],
  "missing_skills": ["Docker", "AWS"],
  "ats_issues": ["Missing measurable achievements (numbers, %, impact)"],
  "recommendations": [
    "Add or highlight experience with: Docker, AWS",
    "Quantify achievements with numbers, percentages, or measurable outcomes"
  ],
  "recruiter_summary": "This resume shows a strong match for the job description, scoring 78/100 overall. ..."
}
```

**Error responses:** `400` for invalid/empty PDFs, oversized files, or empty job
descriptions, with a `detail` message.

## Notes & limitations

- Scanned/image-only PDF resumes won't extract text (no OCR is included) — the API returns
  a `400` in that case.
- The skills dictionary is intentionally maintainable rather than exhaustive; extend
  `backend/app/skills.py` (`SKILLS_CANONICAL` and `_ALIASES`) to broaden coverage.
- All matching happens in-memory on each request; nothing is persisted or logged beyond
  the process lifetime.