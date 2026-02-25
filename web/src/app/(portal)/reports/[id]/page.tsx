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

export default function UserReportDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();

  const { data, isLoading } = useQuery({
    queryKey: ["report", "user", id],
    queryFn: () => reportsApi.getUser(id),
    enabled: !!id,
  });

  if (isLoading) return <Skeleton className="h-96" />;
  if (!data) return <p>Report not found.</p>;

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
        title={data.report_type}
        description={`Run date: ${data.run_date}`}
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

      <MarkdownRenderer content={data.content_md} />
    </>
  );
}
