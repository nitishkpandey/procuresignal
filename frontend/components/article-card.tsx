import Link from "next/link";

import { Card } from "@/components/ui/card";
import { SignalBadge } from "@/components/signal-badge";
import type { FeedArticle } from "@/lib/types";

export function ArticleCard({ article }: { article: FeedArticle }) {
  return (
    <Card className="transition hover:border-slate-400">
      <Link href={`/articles/${article.id}`} className="block">
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <span className="uppercase tracking-wide">{article.category}</span>
          <span>·</span>
          <span>{article.source_name}</span>
        </div>
        <h3 className="mt-1 font-semibold text-slate-900">{article.title}</h3>
        <p className="mt-1 line-clamp-2 text-sm text-slate-600">{article.summary}</p>
        <div className="mt-2 flex flex-wrap gap-1">
          {article.signal_tags.map((tag) => (
            <SignalBadge key={tag} signal={tag} priority={tag === article.priority_signal} />
          ))}
        </div>
      </Link>
    </Card>
  );
}
