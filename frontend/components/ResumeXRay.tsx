import { ResumeXRayItem, XRayStatus } from "@/lib/types";

interface ResumeXRayProps {
  items: ResumeXRayItem[];
}

const STATUS_STYLES: Record<XRayStatus, { icon: string; className: string }> = {
  detected: { icon: "✓", className: "text-emerald-600" },
  warning: { icon: "⚠", className: "text-amber-600" },
  missing: { icon: "✕", className: "text-red-500" },
};

export default function ResumeXRay({ items }: ResumeXRayProps) {
  return (
    <div className="card">
      <div className="mb-4">
        <h2 className="font-semibold text-slate-800">Resume X-Ray 🔍</h2>
        <p className="text-xs text-slate-400 mt-0.5">
          ATS-style analysis of what was detected in your resume — not a real ATS prediction.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-3">
        {items.map((item, i) => {
          const style = STATUS_STYLES[item.status] ?? STATUS_STYLES.warning;
          return (
            <div key={i} className="flex items-start gap-2.5">
              <span className={`font-semibold leading-5 ${style.className}`}>{style.icon}</span>
              <div>
                <p className="text-sm text-slate-700">{item.label}</p>
                {item.note && <p className="text-xs text-slate-400 mt-0.5">{item.note}</p>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}