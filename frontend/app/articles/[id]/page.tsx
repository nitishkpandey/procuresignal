import { ArticleDetailView } from "@/components/article-detail-view";

export default function ArticlePage({ params }: { params: { id: string } }) {
  return <ArticleDetailView id={Number(params.id)} />;
}
