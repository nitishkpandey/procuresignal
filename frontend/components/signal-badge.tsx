import { Badge } from "@/components/ui/badge";
import { humanize } from "@/lib/labels";

export function SignalBadge({ signal, priority = false }: { signal: string; priority?: boolean }) {
  const tone = priority
    ? "bg-red-100 text-red-800"
    : "bg-slate-100 text-slate-700";
  return <Badge className={tone}>{humanize(signal)}</Badge>;
}
