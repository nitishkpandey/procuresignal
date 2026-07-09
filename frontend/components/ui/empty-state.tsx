import type { ReactNode } from "react";

export function EmptyState({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children?: ReactNode;
}) {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 bg-white/70 p-8 text-center">
      <p className="font-medium text-slate-800">{title}</p>
      {hint ? <p className="mx-auto mt-1 max-w-md text-sm text-slate-500">{hint}</p> : null}
      {children ? <div className="mt-4 flex justify-center">{children}</div> : null}
    </div>
  );
}
