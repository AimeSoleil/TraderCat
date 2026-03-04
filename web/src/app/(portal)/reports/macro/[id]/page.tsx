"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import { reportsApi } from "@/lib/api-client";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ArrowLeft } from "lucide-react";
import { MarkdownRenderer } from "@/components/markdown-renderer";

export default function MacroRegimeDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();

  const { data, isLoading } = useQuery({
    queryKey: ["report", "macro", id],
    queryFn: () => reportsApi.getMacro(id),
    enabled: !!id,
  });

  if (isLoading) return <Skeleton className="h-96" />;
  if (!data) return <p>Macro regime report not found.</p>;

  // Strip leading ```json { ... } ``` block so only the narrative markdown renders.
  const contentWithoutJson = data.content_md.replace(
    /```(?:json)?\s*\{[\s\S]*?\}\s*```\s*/,
    "",
  );

  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        className="mb-4"
        onClick={() => router.back()}
      >
        <ArrowLeft className="mr-2 h-4 w-4" />
        Back
      </Button>

      <PageHeader
        title={data.regime_label ?? "Macro Regime Context"}
        description={`Run date: ${data.run_date}${data.regime_score != null ? ` · Score: ${data.regime_score.toFixed(1)}` : ""}`}
        actions={
          <div className="flex gap-2">
            {data.identity_used && (
              <Badge variant="outline">{data.identity_used}</Badge>
            )}
            {data.model_used && (
              <Badge variant="secondary">{data.model_used}</Badge>
            )}
          </div>
        }
      />

      <MarkdownRenderer content={contentWithoutJson} />
    </>
  );
}
