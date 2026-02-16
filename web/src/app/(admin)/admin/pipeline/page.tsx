"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PageHeader } from "@/components/page-header";
import { adminPipelineApi } from "@/lib/api-client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "sonner";
import { Play, RefreshCw } from "lucide-react";
import { useState } from "react";

const statusColor: Record<string, string> = {
  pending: "bg-yellow-100 text-yellow-800",
  running: "bg-blue-100 text-blue-800",
  completed: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
};

export default function AdminPipelinePage() {
  const qc = useQueryClient();
  const [triggerDate, setTriggerDate] = useState("");
  const [statusDate, setStatusDate] = useState("");

  const statusQuery = useQuery({
    queryKey: ["admin", "pipeline-status", statusDate],
    queryFn: () => adminPipelineApi.status(statusDate || undefined),
    refetchInterval: 10_000, // poll every 10s
  });

  const triggerMut = useMutation({
    mutationFn: () =>
      adminPipelineApi.trigger(triggerDate || undefined),
    onSuccess: (res) => {
      toast.success(`Pipeline triggered for ${res.run_date}`);
      qc.invalidateQueries({ queryKey: ["admin", "pipeline-status"] });
    },
    onError: () => toast.error("Failed to trigger pipeline"),
  });

  const run = statusQuery.data;

  return (
    <>
      <PageHeader
        title="Pipeline"
        description="Trigger and monitor signal/report generation"
      />

      {/* Trigger section */}
      <Card className="mb-6">
        <CardHeader>
          <CardTitle className="text-base">Trigger Pipeline</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-3">
            <Input
              type="date"
              value={triggerDate}
              onChange={(e) => setTriggerDate(e.target.value)}
              className="w-40"
              placeholder="Today"
            />
            <Button
              onClick={() => triggerMut.mutate()}
              disabled={triggerMut.isPending}
            >
              <Play className="mr-2 h-4 w-4" />
              {triggerMut.isPending ? "Triggering…" : "Trigger"}
            </Button>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            Leave date empty to use today. Requires at least one active LLM
            token.
          </p>
        </CardContent>
      </Card>

      {/* Status section */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-base">Pipeline Status</CardTitle>
          <div className="flex items-center gap-2">
            <Input
              type="date"
              value={statusDate}
              onChange={(e) => setStatusDate(e.target.value)}
              className="w-40"
            />
            <Button
              variant="outline"
              size="icon"
              onClick={() =>
                qc.invalidateQueries({ queryKey: ["admin", "pipeline-status"] })
              }
            >
              <RefreshCw className="h-4 w-4" />
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {statusQuery.isLoading ? (
            <Skeleton className="h-32" />
          ) : run ? (
            <div className="space-y-4">
              <div className="flex items-center gap-3">
                <Badge
                  variant="secondary"
                  className={statusColor[run.status] ?? ""}
                >
                  {run.status.toUpperCase()}
                </Badge>
                <span className="text-sm text-muted-foreground">
                  {run.run_date}
                </span>
                {run.step && (
                  <span className="text-sm text-muted-foreground">
                    Step: {run.step}
                  </span>
                )}
              </div>

              <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                <Stat label="Symbols" value={`${run.processed_symbols} / ${run.total_symbols}`} />
                <Stat label="Reports" value={`${run.processed_reports} / ${run.total_reports}`} />
                <Stat label="Started" value={run.started_at ? new Date(run.started_at).toLocaleTimeString() : "—"} />
                <Stat label="Completed" value={run.completed_at ? new Date(run.completed_at).toLocaleTimeString() : "—"} />
              </div>

              {run.error_log && Object.keys(run.error_log).length > 0 && (
                <div>
                  <p className="mb-1 text-sm font-medium text-destructive">
                    Errors
                  </p>
                  <pre className="max-h-48 overflow-auto rounded bg-muted p-2 text-xs">
                    {JSON.stringify(run.error_log, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              No pipeline run found for the selected date.
            </p>
          )}
        </CardContent>
      </Card>
    </>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-sm font-medium">{value}</p>
    </div>
  );
}
