# JobFit AI

An AI/NLP resume-to-job-description match analyzer. Upload a PDF resume and paste a job
description — JobFit AI extracts skills, computes semantic similarity, checks basic ATS
signals, and returns a match score along with a full breakdown of *why* you got that score.

No database. No authentication. No paid APIs. No external LLM calls — all NLP runs locally
using `sentence-transformers` (all-MiniLM-L6-v2) and scikit-learn.

## Features

- **Overall Match score** — a single 0-100 score blending semantic similarity, keyword
  match, and ATS signals.
- **Why did I get this score?** — a plain-language breakdown of strengths and gaps,
  generated from your actual analysis results (not hardcoded).
- **Score Breakdown** — the three underlying signals shown separately, each as a percentage.
- **Job Intelligence** — the job description analyzed on its own: detected role, technical
  skills, key responsibilities, requirements, experience level, and top keywords.
- **Matched / Missing Skills** — canonical skill overlap between resume and JD, with alias
  normalization (e.g. `ReactJS → React`, `Postgres → PostgreSQL`).
- **Resume X-Ray** — an ATS-style scan of your resume's structure: contact info, sections
  present, action verbs, measurable achievements, and generic/weak phrasing — each flagged
  as detected (✓), needs attention (⚠), or missing (✕).
- **Improve Your Resume** — flags weak or generic bullet points and suggests stronger
  wording. Suggestions only ever reuse language already in your resume — no invented
  achievements, numbers, or technologies. Where a rewrite isn't safe to generate, you get a
  recommendation instead.
- **ATS Issues & Recommendations** — the original heuristic checks and actionable next steps.

## How the score works

```
overall_score = 40% semantic similarity + 40% keyword/skill match + 20% ATS signals
```

- **Semantic similarity** — cosine similarity between sentence-transformer embeddings of
  the full resume and job description text.
- **Keyword match** — overlap between a canonical skills dictionary extracted from both
  texts.
- **ATS signals** — heuristic checks for structural sections (contact info, skills,
  experience, education, projects), resume length, measurable achievements, and JD keyword
  coverage. This is an **ATS-style analysis**, not a simulation of any specific company's
  actual applicant tracking system, and none of the features here predict whether you'll be
  shortlisted or hired.

## Project structure

```text
jobfit-ai/
  backend/
    app/
      main.py               # FastAPI app, /api/analyze endpoint
      analyzer.py            # scoring, similarity, ATS checks, score explanation,
                              # resume x-ray, job intelligence, rewrite suggestions
      pdf_parser.py           # PyMuPDF text extraction
      skills.py               # skills dictionary + alias normalization
      schemas.py              # Pydantic response models
    requirements.txt
    .env.example
  frontend/
    app/
      page.tsx                 # main single-page UI
      layout.tsx
      globals.css
    components/
      UploadForm.tsx            # PDF upload + JD textarea
      Results.tsx                # assembles the full results dashboard
      WhyThisScore.tsx           # expandable strengths/gaps section
      JobIntelligence.tsx        # role, skills, responsibilities, requirements
      ResumeXRay.tsx              # detected/warning/missing resume signals
      ImproveResume.tsx           # weak-statement rewrite suggestions
    lib/
      api.ts                     # backend API client
      types.ts
    package.json
    .env.example
  render.yaml                    # Render blueprint for the backend
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
   deployed (e.g. `https://your-project.vercel.app`). Use `*` initially if you want to test
   before the frontend is deployed.

> Free Render instances spin down after inactivity — the first request after idle can take
> 30-60 seconds while the instance wakes up and the model loads.

### Frontend → Vercel

1. Import the repo in Vercel.
2. **Root Directory:** `frontend`
3. Framework preset: Next.js (auto-detected).
4. **Environment Variable:** `NEXT_PUBLIC_API_URL` = your Render backend URL
   (e.g. `https://jobfit-ai-backend-xxxx.onrender.com`, no trailing slash).
5. Deploy.

**After both are live, this step is required, not optional:** update the backend's
`ALLOWED_ORIGINS` env var on Render to your exact Vercel URL (no trailing slash,
`https://`, exact match) and let it redeploy. Skipping this causes a browser CORS error —
`No 'Access-Control-Allow-Origin' header is present` — even though both services are
individually live and working. See **Troubleshooting** below.

### Redeploying after any code change

Both Render and Vercel redeploy automatically on every push to `main`:

```bash
git add .
git commit -m "describe the change"
git push
```

No manual redeploy step needed on either dashboard.

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
  "matched_skills": ["React", "Node.js", "MongoDB", "Git"],
  "missing_skills": ["Docker", "AWS", "PostgreSQL"],
  "ats_issues": ["Missing measurable achievements (numbers, %, impact)"],
  "recommendations": [
    "Add or highlight experience with: Docker, AWS, PostgreSQL",
    "Quantify achievements with numbers, percentages, or measurable outcomes"
  ],
  "recruiter_summary": "This resume shows a strong match for the job description, scoring 78/100 overall. ...",
  "score_explanation": {
    "strengths": ["Strong React alignment", "Good keyword coverage with the job description"],
    "gaps": ["Docker not detected in resume", "Limited cloud experience detected"],
    "explanation": "This score combines three signals: semantic similarity (82%, 40% weight) ..."
  },
  "resume_xray": [
    { "label": "Contact Information", "status": "detected", "note": null },
    { "label": "Measurable Achievements", "status": "warning", "note": "Add numbers, percentages, or measurable outcomes" }
  ],
  "job_intelligence": {
    "role": "Software Engineer",
    "technical_skills": ["React", "Node.js", "MongoDB", "AWS", "Docker"],
    "responsibilities": ["Design, build, and maintain scalable web applications using React and Node.js"],
    "requirements": ["1-3 years of experience with JavaScript/TypeScript"],
    "experience_level": "1-3 years",
    "important_keywords": ["React", "Node.js", "MongoDB"]
  },
  "improvement_suggestions": [
    {
      "original": "- Worked on a responsive single-page website using React and Tailwind CSS",
      "suggestion": "- Contributed to a responsive single-page website using React and Tailwind CSS",
      "why": "Replaces generic/passive phrasing with a more active, ownership-focused verb, using only your original wording.",
      "type": "rewrite"
    }
  ]
}
```

**Error responses:** `400` for invalid/empty PDFs, oversized files, or empty job
descriptions, with a `detail` message.

## Troubleshooting

**CORS error in the browser console** (`has been blocked by CORS policy: No
'Access-Control-Allow-Origin' header is present`), even though both Render and Vercel show
as live:

- Go to Render → your backend service → **Environment** tab
- Confirm `ALLOWED_ORIGINS` is set to your **exact** Vercel URL — `https://`, no trailing
  slash, exact domain
- Save, wait for the automatic redeploy to finish (**Live** status, check Logs for
  `Application startup complete.`)
- Hard-refresh the frontend (`Ctrl+Shift+R`) and retry

**`Module not found` on a component import** — the import path in `Results.tsx` (or
wherever the import lives) must match the actual filename exactly, including case. Check the
`components/` folder listing against the import statement.

**Unknown at rule `@tailwind` / `@apply` warnings in `globals.css`** — these are only VS
Code's built-in CSS linter not recognizing Tailwind syntax; they don't affect the build.
Install the "Tailwind CSS IntelliSense" extension to silence them, or ignore — `npm run dev`
and `npm run build` process these correctly regardless.

## Notes & limitations

- Scanned/image-only PDF resumes won't extract text (no OCR is included) — the API returns
  a `400` in that case.
- The skills dictionary is intentionally maintainable rather than exhaustive; extend
  `backend/app/skills.py` (`SKILLS_CANONICAL` and `_ALIASES`) to broaden coverage.
- Resume rewrite suggestions never invent achievements, numbers, technologies, or
  responsibilities — they either reword existing text using only your own wording, or
  return a recommendation instead of a rewrite when there isn't enough information to
  safely generate one.
- All matching happens in-memory on each request; nothing is persisted or logged beyond
  the process lifetime.