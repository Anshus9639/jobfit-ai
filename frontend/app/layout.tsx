import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "JobFit AI — Resume to Job Match Analyzer",
  description: "See how closely your resume matches the job.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen text-slate-900 antialiased">{children}</body>
    </html>
  );
}