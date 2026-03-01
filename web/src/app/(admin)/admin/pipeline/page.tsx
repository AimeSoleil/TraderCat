"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PageHeader } from "@/components/page-header";
import { adminPipelineApi } from "@/lib/api-client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import {
  Play,
  RefreshCw,
  StopCircle,
  Loader2,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { Fragment, useState } from "react";
import type { PipelineRunResponse } from "@/lib/types";

const STATUS_OPTIONS = [
  { value: "all", label: "All" },
  { value: "running", label: "Running" },
  { value: "pending", label: "Pending" },
  { value: "completed", label: "Completed" },
  { value: "failed", label: "Failed" },
] as const;

/* ── Status badge colour map ── */
const statusColor: Record<string, string> = {
  pending: "bg-yellow-100 text-yellow-800",
  running: "bg-blue-100 text-blue-800",
  completed: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
};

/* ── Inline cancel button with confirmation dialog ── */
function CancelButton({
  runDate,
  disabled,
}: {
  runDate: string;
  disabled?: boolean;
}) {
  const qc = useQueryClient();
  const cancelMut = useMutation({
    mutationFn: () => adminPipelineApi.cancel(runDate),
    onSuccess: (res) => {
      toast.success(res.message);
      qc.invalidateQueries({ queryKey: ["admin", "pipeline-runs"] });
    },
    onError: () =>
      toast.error("Failed to cancel pipeline — is it still running?"),
  });

  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button
          variant="destructive"
          size="sm"
          className="h-7 px-2 text-xs"
          disabled={disabled || cancelMut.isPending}
        >
          <StopCircle className="mr-1 h-3 w-3" />
          {cancelMut.isPending ? "…" : "Cancel"}
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Cancel pipeline?</AlertDialogTitle>
          <AlertDialogDescription>
            This will mark the running pipeline for{" "}
            <strong>{runDate}</strong> as failed so you can re-trigger it.
            In-flight LLM calls may still finish in the background but will be
            overwritten on the next run.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Keep running</AlertDialogCancel>
          <AlertDialogAction
            onClick={() => cancelMut.mutate()}
            className="bg-destructive text-white hover:bg-destructive/90"
          >
            Yes, cancel it
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

/* ── Expandable detail row ── */
function DetailRow({ run }: { run: PipelineRunResponse }) {
  return (
    <TableRow className="bg-muted/30 hover:bg-muted/30">
      <TableCell colSpan={7} className="p-4">
        <div className="grid grid-cols-2 gap-x-8 gap-y-2 text-sm sm:grid-cols-4">
          <Stat label="Total Symbols" value={String(run.total_symbols)} />
          <Stat label="Processed Symbols" value={String(run.processed_symbols)} />
          <Stat label="Total Reports" value={String(run.total_reports)} />
          <Stat label="Processed Reports" value={String(run.processed_reports)} />
          <Stat
            label="Started"
            value={
              run.started_at
                ? new Date(run.started_at).toLocaleString()
                : "—"
            }
          />
          <Stat
            label="Completed"
            value={
              run.completed_at
                ? new Date(run.completed_at).toLocaleString()
                : "—"
            }
          />
          <Stat label="Run ID" value={run.id.slice(0, 8) + "…"} />
          <Stat
            label="Created"
            value={new Date(run.created_at).toLocaleString()}
          />
        </div>
        {run.error_log && (
          <div className="mt-3">
            <p className="mb-1 text-xs font-medium text-destructive">Errors</p>
            <pre className="max-h-40 overflow-auto rounded bg-muted p-2 text-xs whitespace-pre-wrap">
              {typeof run.error_log === "string"
                ? run.error_log
                : JSON.stringify(run.error_log, null, 2)}
            </pre>
          </div>
        )}
      </TableCell>
    </TableRow>
  );
}

/* ── Main page ── */
/** Return local today as YYYY-MM-DD */
function todayStr() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function AdminPipelinePage() {
  const qc = useQueryClient();
  const [triggerDate, setTriggerDate] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [runDateFilter, setRunDateFilter] = useState(todayStr);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const runsQuery = useQuery({
    queryKey: ["admin", "pipeline-runs", statusFilter, runDateFilter],
    queryFn: () =>
      adminPipelineApi.list({
        limit: 50,
        status: statusFilter === "all" ? undefined : statusFilter,
        run_date: runDateFilter || undefined,
      }),
    refetchInterval: 10_000,
  });

  const triggerMut = useMutation({
    mutationFn: () => adminPipelineApi.trigger(triggerDate || undefined),
    onSuccess: (res) => {
      toast.success(`Pipeline triggered for ${res.run_date}`);
      qc.invalidateQueries({ queryKey: ["admin", "pipeline-runs"] });
    },
    onError: () => toast.error("Failed to trigger pipeline"),
  });

  const toggleExpand = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const runs = runsQuery.data?.runs ?? [];

  return (
    <>
      <PageHeader
        title="Pipeline"
        description="Trigger and monitor signal/report generation"
      />

      {/* ── Trigger ── */}
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
            Leave date empty to use today. Date must be a US market trading day
            (no weekends or holidays). Requires at least one active LLM token.
          </p>
        </CardContent>
      </Card>

      {/* ── Pipeline runs table ── */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-base">
            Pipeline Runs
            {runsQuery.data && (
              <span className="ml-2 text-xs font-normal text-muted-foreground">
                ({runsQuery.data.total} total)
              </span>
            )}
          </CardTitle>
          <div className="flex items-center gap-2">
            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="w-32 h-8 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {STATUS_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input
              type="date"
              value={runDateFilter}
              onChange={(e) => setRunDateFilter(e.target.value)}
              className="w-40 h-8 text-xs"
            />
            <Button
              variant="outline"
              size="icon"
              onClick={() =>
                qc.invalidateQueries({ queryKey: ["admin", "pipeline-runs"] })
              }
            >
              <RefreshCw className="h-4 w-4" />
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {runsQuery.isLoading ? (
            <div className="space-y-2">
              {[1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : runs.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No pipeline runs found.
            </p>
          ) : (
            <div className="rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-8" />
                    <TableHead className="w-28">Date</TableHead>
                    <TableHead className="w-28">Status</TableHead>
                    <TableHead>Step</TableHead>
                    <TableHead className="text-center">Symbols</TableHead>
                    <TableHead className="text-center">Reports</TableHead>
                    <TableHead className="w-24 text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {runs.map((run) => {
                    const isRunning = run.status === "running";
                    const isExpanded = expanded.has(run.id);
                    return (
                      <Fragment key={run.id}>
                        <TableRow
                          className="cursor-pointer transition-colors hover:bg-muted/50"
                          onClick={() => toggleExpand(run.id)}
                        >
                          <TableCell className="px-2">
                            {isExpanded ? (
                              <ChevronUp className="h-4 w-4 text-muted-foreground" />
                            ) : (
                              <ChevronDown className="h-4 w-4 text-muted-foreground" />
                            )}
                          </TableCell>
                          <TableCell className="font-medium">
                            {run.run_date}
                          </TableCell>
                          <TableCell>
                            <Badge
                              variant="secondary"
                              className={`text-xs ${statusColor[run.status] ?? ""}`}
                            >
                              {isRunning && (
                                <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                              )}
                              {run.status.toUpperCase()}
                            </Badge>
                          </TableCell>
                          <TableCell className="text-muted-foreground text-xs">
                            {run.step ?? "—"}
                          </TableCell>
                          <TableCell className="text-center text-xs">
                            {run.processed_symbols}/{run.total_symbols}
                          </TableCell>
                          <TableCell className="text-center text-xs">
                            {run.processed_reports}/{run.total_reports}
                          </TableCell>
                          <TableCell
                            className="text-right"
                            onClick={(e) => e.stopPropagation()}
                          >
                            {isRunning && (
                              <CancelButton runDate={run.run_date} />
                            )}
                          </TableCell>
                        </TableRow>
                        {isExpanded && (
                          <DetailRow key={`${run.id}-detail`} run={run} />
                        )}
                      </Fragment>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
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
