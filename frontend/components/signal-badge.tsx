import { Badge } from "@/components/ui/badge";
import { humanize } from "@/lib/labels";

export function SignalBadge({ signal, priority = false }: { signal: string; priority?: boolean }) {
  const tone = priority
    ? "border-red-200 bg-red-100 text-red-800"
    : "border-slate-200 bg-slate-100 text-slate-700";
  return <Badge className={tone}>{humanize(signal)}</Badge>;
}
