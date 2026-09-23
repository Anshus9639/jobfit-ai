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
    <form onSubmit={handleSubmit} className="card space-y-6">
      <div>
        <label className="block text-sm font-semibold text-slate-700 mb-2">
          Resume (PDF)
        </label>
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragActive(true);
          }}
          onDragLeave={() => setDragActive(false)}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          className={`flex flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-10 text-center cursor-pointer transition-colors ${
            dragActive
              ? "border-brand-500 bg-brand-50"
              : "border-slate-300 hover:border-brand-400 hover:bg-slate-50"
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
            <div>
              <p className="font-medium text-slate-800">{resumeFile.name}</p>
              <p className="text-sm text-slate-500 mt-1">
                {(resumeFile.size / 1024).toFixed(0)} KB — click or drop to replace
              </p>
            </div>
          ) : (
            <div>
              <p className="font-medium text-slate-700">
                Drag & drop your resume, or click to browse
              </p>
              <p className="text-sm text-slate-500 mt-1">PDF only, up to 5 MB</p>
            </div>
          )}
        </div>
      </div>

      <div>
        <label
          htmlFor="job-description"
          className="block text-sm font-semibold text-slate-700 mb-2"
        >
          Job Description
        </label>
        <textarea
          id="job-description"
          value={jobDescription}
          onChange={(e) => setJobDescription(e.target.value)}
          rows={8}
          placeholder="Paste the full job description here..."
          className="w-full rounded-xl border border-slate-300 px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-transparent resize-y"
        />
      </div>

      {formError && (
        <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-2">
          {formError}
        </p>
      )}

      <button
        type="submit"
        disabled={loading}
        className="w-full rounded-xl bg-brand-600 hover:bg-brand-700 disabled:bg-slate-300 disabled:cursor-not-allowed text-white font-semibold py-3 transition-colors"
      >
        {loading ? "Analyzing..." : "Analyze Resume"}
      </button>
    </form>
  );
}