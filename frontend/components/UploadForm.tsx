"use client";

import { useRef, useState } from "react";

interface UploadFormProps {
  onSubmit: (resumeFile: File, jobDescription: string) => void;
  loading: boolean;
}

export default function UploadForm({ onSubmit, loading }: UploadFormProps) {
  const [resumeFile, setResumeFile] = useState<File | null>(null);
  const [jobDescription, setJobDescription] = useState("");
  const [dragActive, setDragActive] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  function handleFileChange(file: File | null) {
    if (!file) {
      setResumeFile(null);
      return;
    }
    if (file.type !== "application/pdf") {
      setFormError("Please upload a PDF file.");
      setResumeFile(null);
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      setFormError("File is too large. Maximum size is 5 MB.");
      setResumeFile(null);
      return;
    }
    setFormError(null);
    setResumeFile(file);
  }

  function handleDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragActive(false);
    const file = e.dataTransfer.files?.[0];
    handleFileChange(file ?? null);
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!resumeFile) {
      setFormError("Please upload your resume PDF.");
      return;
    }
    if (!jobDescription.trim()) {
      setFormError("Please paste a job description.");
      return;
    }
    setFormError(null);
    onSubmit(resumeFile, jobDescription.trim());
  }

  return (
    <form onSubmit={handleSubmit} className="grid gap-8 lg:grid-cols-[0.85fr_1.15fr]">
      <div className="min-w-0">
        <div className="mb-6">
          <p className="eyebrow">Resume</p>
          <p className="mt-2 text-sm text-neutral-500">PDF only · 5 MB maximum</p>
        </div>
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragActive(true);
          }}
          onDragLeave={() => setDragActive(false)}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") fileInputRef.current?.click();
          }}
          aria-label="Upload resume PDF"
          className={`flex min-h-72 cursor-pointer flex-col items-center justify-center rounded-2xl border border-dashed px-6 py-10 text-center outline-none transition duration-200 ${
            dragActive
              ? "border-neutral-300 bg-white/[0.06]"
              : "border-white/[0.13] bg-[#111111] hover:border-white/[0.24] hover:bg-[#141414]"
          }`}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept="application/pdf"
            className="hidden"
            onChange={(e) => handleFileChange(e.target.files?.[0] ?? null)}
          />
          {resumeFile ? (
            <div className="max-w-full">
              <div className="mx-auto mb-5 flex h-12 w-12 items-center justify-center rounded-xl border border-white/10 bg-white/[0.04]">
                <span className="text-xs font-semibold text-neutral-300">PDF</span>
              </div>
              <p className="max-w-full truncate text-sm font-medium text-neutral-100">{resumeFile.name}</p>
              <p className="mt-1.5 text-xs text-neutral-500">
                {(resumeFile.size / 1024).toFixed(0)} KB · Ready to analyze
              </p>
            </div>
          ) : (
            <div>
              <div className="mx-auto mb-5 flex h-12 w-12 items-center justify-center rounded-xl border border-white/10 bg-white/[0.04] text-xl text-neutral-300">
                +
              </div>
              <p className="text-sm font-medium text-neutral-200">Drop your resume here</p>
              <p className="mt-1.5 text-xs text-neutral-500">or click to browse</p>
            </div>
          )}
        </div>
      </div>

      <div className="min-w-0">
        <div className="mb-6">
          <p className="eyebrow">Job description</p>
          <p className="mt-2 text-sm text-neutral-500">Include the role, requirements and responsibilities</p>
        </div>
        <label
          htmlFor="job-description"
          className="sr-only"
        >
          Job Description
        </label>
        <textarea
          id="job-description"
          value={jobDescription}
          onChange={(e) => setJobDescription(e.target.value)}
          rows={11}
          placeholder="Paste the full job description here..."
          className="field min-h-72 resize-y"
        />
        {formError && (
          <p role="alert" className="mt-3 rounded-lg border border-neutral-600/50 bg-neutral-900 px-3 py-2.5 text-sm text-neutral-300">
            {formError}
          </p>
        )}
        <button type="submit" disabled={loading} className="primary-button mt-4 w-full">
          {loading ? (
            <span className="flex items-center gap-2">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-neutral-500" />
              Analyzing your fit
            </span>
          ) : (
            "Analyze my resume"
          )}
        </button>
      </div>
    </form>
  );
}