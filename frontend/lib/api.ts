import { AnalyzeResult } from "./types";
import { createSupabaseBrowserClient } from "./supabase-browser";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function analyzeResume(
  resumeFile: File,
  jobDescription: string
): Promise<AnalyzeResult> {
  const formData = new FormData();
  formData.append("resume", resumeFile);
  formData.append("job_description", jobDescription);

  const supabase = createSupabaseBrowserClient();
  const { data } = await supabase.auth.getSession();
  const accessToken = data.session?.access_token;
  if (!accessToken) {
    throw new Error("Sign in to analyze your resume.");
  }

  const response = await fetch(`${API_URL}/api/analyze`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${accessToken}`,
    },
    body: formData,
  });

  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    try {
      const errorBody = await response.json();
      if (errorBody?.detail) message = errorBody.detail;
    } catch {
      // ignore JSON parse failure, use default message
    }
    throw new Error(message);
  }

  return response.json();
}