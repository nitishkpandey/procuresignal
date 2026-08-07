import { ArticleDetailView } from "@/components/article-detail-view";

// Next 15 made route params asynchronous, and Next 16's generated route contract
// enforces it. Declaring them synchronously type-checks under Turbopack, which does
// not generate these types, and fails under webpack — so it passed CI while being
// wrong.
export default async function ArticlePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ArticleDetailView id={Number(id)} />;
}
