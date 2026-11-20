import { ResumeXRayItem, XRayStatus } from "@/lib/types";

interface ResumeXRayProps {
  items: ResumeXRayItem[];
}

const STATUS_STYLES: Record<XRayStatus, { symbol: string; className: string }> = {
  detected: { symbol: "Present", className: "border-neutral-500/40 text-neutral-200" },
  warning: { symbol: "Review", className: "border-white/[0.12] text-neutral-400" },
  missing: { symbol: "Missing", className: "border-neutral-700 text-neutral-500" },
};

export default function ResumeXRay({ items }: ResumeXRayProps) {
  return (
    <div className="card">
      <div className="mb-4">
        <h2 className="font-medium text-neutral-100">Resume structure</h2>
        <p className="mt-1 text-xs text-neutral-500">
          ATS-style signals detected in your resume.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-3">
        {items.map((item, i) => {
          const style = STATUS_STYLES[item.status] ?? STATUS_STYLES.warning;
          return (
            <div key={i} className="flex items-start gap-2.5">
              <span className={`rounded border px-1.5 py-0.5 text-[9px] uppercase tracking-wider ${style.className}`}>{style.symbol}</span>
              <div>
                <p className="text-sm text-neutral-300">{item.label}</p>
                {item.note && <p className="mt-1 text-xs leading-5 text-neutral-600">{item.note}</p>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}