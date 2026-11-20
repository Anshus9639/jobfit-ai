import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "JobFit AI — Resume to Job Match Analyzer",
  description: "Find your fit. Know your worth.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-[#080808] text-neutral-100 antialiased">{children}</body>
    </html>
  );
}