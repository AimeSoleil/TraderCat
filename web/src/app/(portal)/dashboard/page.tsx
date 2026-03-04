"use client";

import { useCallback } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/components/providers/auth-provider";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import { DatePicker } from "@/components/date-picker";
import { PositionsTable } from "@/components/positions-table";
import { dashboardApi, watchlistApi } from "@/lib/api-client";
import {
  BarChart3,
  List,
  Shield,
  ArrowRight,
  Inbox,
  AlertTriangle,
  Loader2,
  Clock,
} from "lucide-react";

/* ------------------------------------------------------------------ */
/*  Regime colour helpers                                              */
/* ------------------------------------------------------------------ */

const regimeColors: Record<string, string> = {
  "DARK GREEN": "bg-emerald-600 text-white",
  GREEN: "bg-emerald-500 text-white",
  YELLOW: "bg-amber-400 text-amber-950",
  ORANGE: "bg-orange-500 text-white",
  RED: "bg-red-600 text-white",
};

function getRegimeColor(label: string | null | undefined): string {
  if (!label) return "bg-muted text-muted-foreground";
  const upper = label.toUpperCase();
  for (const [key, val] of Object.entries(regimeColors)) {
    if (upper.includes(key)) return val;
  }
  return "bg-muted text-muted-foreground";
}

/* ------------------------------------------------------------------ */
/*  Pipeline status banner — explains why data may be missing          */
/* ------------------------------------------------------------------ */

/** Map pipeline step codes to human-readable phase names */
function formatPipelineStep(step: string | null | undefined): string {
  if (!step) return "Unknown step";
  const map: Record<string, string> = {
    p1_signals: "Phase 1 — Signal Generation",
    p2_macro_regime: "Phase 2 — Macro Regime Analysis",
    p3_execution_plans: "Phase 3 — Execution Plans",
    p4_user_briefings: "Phase 4 — User Briefings",
    completed: "Completed",
  };
  return map[step] ?? step;
}

function PipelineStatusBanner({
  status,
  step,
  error,
  isAdmin,
}: {
  status: string | null | undefined;
  step: string | null | undefined;
  error: string | null | undefined;
  isAdmin: boolean;
}) {
  // No pipeline run exists for this date
  if (!status) {
    return (
      <div className="flex flex-col items-center justify-center rounded-xl border border-dashed py-16 text-center">
        <Clock className="mb-4 h-12 w-12 text-muted-foreground/30" />
        <h3 className="text-base font-semibold">Pipeline has not run</h3>
        <p className="mt-1 max-w-sm text-sm text-muted-foreground">
          No pipeline run found for this date. An admin can trigger it manually.
        </p>
        {isAdmin && (
          <Button asChild variant="outline" size="sm" className="mt-4">
            <Link href="/admin/pipeline">Go to Pipeline</Link>
          </Button>
        )}
      </div>
    );
  }

  // Pipeline is currently running
  if (status === "running") {
    return (
      <div className="flex flex-col items-center justify-center rounded-xl border border-blue-200 bg-blue-50 py-12 text-center dark:border-blue-900 dark:bg-blue-950/30">
        <Loader2 className="mb-4 h-12 w-12 animate-spin text-blue-500" />
        <h3 className="text-base font-semibold">Pipeline is running</h3>
        <p className="mt-1 max-w-sm text-sm text-muted-foreground">
          Currently at: <span className="font-medium">{formatPipelineStep(step)}</span>.
          Positions will appear once execution plans are generated.
        </p>
      </div>
    );
  }

  // Pipeline is pending (queued but not started)
  if (status === "pending") {
    return (
      <div className="flex flex-col items-center justify-center rounded-xl border border-dashed py-16 text-center">
        <Clock className="mb-4 h-12 w-12 text-muted-foreground/30" />
        <h3 className="text-base font-semibold">Pipeline is pending</h3>
        <p className="mt-1 max-w-sm text-sm text-muted-foreground">
          The pipeline is queued and will start shortly.
        </p>
      </div>
    );
  }

  // Pipeline failed
  if (status === "failed") {
    // Determine a user-friendly reason from the step and error
    let reason = "An unexpected error occurred during analysis.";
    if (step === "p1_signals") {
      reason = "Signal generation failed — market data may be unavailable.";
    } else if (step === "p2_macro_regime") {
      reason = "Macro regime analysis failed — LLM service may be unreachable.";
    } else if (step === "p3_execution_plans") {
      reason = "Execution plan generation failed — LLM analysis did not complete.";
    } else if (step === "p4_user_briefings") {
      reason = "Briefing generation failed — execution plans were generated but the final summary could not be produced.";
    }
    // Check for common error patterns
    if (error) {
      if (error.toLowerCase().includes("timeout")) {
        reason += " (Timeout — the LLM took too long to respond)";
      } else if (error.toLowerCase().includes("token") || error.toLowerCase().includes("auth")) {
        reason += " (Authentication error — LLM API key may be invalid)";
      } else if (error.toLowerCase().includes("database") || error.toLowerCase().includes("sqlalchemy")) {
        reason += " (Database error — data could not be saved)";
      }
    }

    return (
      <div className="flex flex-col items-center justify-center rounded-xl border border-red-200 bg-red-50 py-12 text-center dark:border-red-900 dark:bg-red-950/30">
        <AlertTriangle className="mb-4 h-12 w-12 text-red-500" />
        <h3 className="text-base font-semibold text-red-700 dark:text-red-400">Pipeline Failed</h3>
        <p className="mt-1 max-w-md text-sm text-muted-foreground">{reason}</p>
        {error && (
          <details className="mt-3 max-w-lg text-left">
            <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">
              Technical details
            </summary>
            <pre className="mt-1 max-h-24 overflow-auto rounded bg-muted p-2 text-xs">
              {error}
            </pre>
          </details>
        )}
        {isAdmin && (
          <Button asChild variant="outline" size="sm" className="mt-4">
            <Link href="/admin/pipeline">Go to Pipeline</Link>
          </Button>
        )}
      </div>
    );
  }

  // Pipeline completed but no positions (LLM returned no actionable data)
  if (status === "completed") {
    return (
      <div className="flex flex-col items-center justify-center rounded-xl border border-dashed py-16 text-center">
        <Inbox className="mb-4 h-12 w-12 text-muted-foreground/30" />
        <h3 className="text-base font-semibold">No positions generated</h3>
        <p className="mt-1 max-w-sm text-sm text-muted-foreground">
          The pipeline completed successfully but no actionable positions were
          found for your watchlist. This may happen when the LLM analysis did
          not identify high-confidence setups, or all symbols were rejected by
          the gate audit.
        </p>
      </div>
    );
  }

  // Fallback
  return null;
}

/* ------------------------------------------------------------------ */
/*  Dashboard page                                                     */
/* ------------------------------------------------------------------ */

export default function DashboardPage() {
  const { user, isAdmin } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();

  // Sync selectedDate with the URL query param `date`
  const selectedDate = searchParams.get("date");

  const setSelectedDate = useCallback(
    (date: string) => {
      const params = new URLSearchParams(searchParams.toString());
      params.set("date", date);
      router.replace(`?${params.toString()}`);
    },
    [router, searchParams],
  );

  /* ---- Data fetching ---- */

  const dashboard = useQuery({
    queryKey: ["dashboard", "positions", selectedDate],
    queryFn: () =>
      dashboardApi.getPositions(
        selectedDate ? { run_date: selectedDate } : undefined,
      ),
  });

  const watchlist = useQuery({
    queryKey: ["watchlist"],
    queryFn: () => watchlistApi.list(),
  });

  const data = dashboard.data;

  /* Use the effective run date (URL param → API response) for links */
  const effectiveDate = selectedDate ?? data?.run_date ?? "";

  // Only active (buy / sell) positions are shown
  const activePositions =
    data?.positions.filter(
      (p) => p.verdict === "buy" || p.verdict === "sell",
    ) ?? [];

  return (
    <>
      {/* Header with date picker */}
      <PageHeader
        title={`Welcome, ${user?.username ?? ""}!`}
        description={
          data?.run_date
            ? `Portfolio positions for ${data.run_date}`
            : isAdmin
              ? "Admin dashboard"
              : "Your trading dashboard"
        }
        actions={
          <DatePicker
            value={data?.run_date ?? selectedDate}
            onChange={setSelectedDate}
            availableDates={data?.available_dates ?? []}
            placeholder="Select date"
          />
        }
      />

      {/* ---- Summary Stats (3 clickable cards) ---- */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {/* Market Regime */}
        <Card
          className="cursor-pointer transition-colors hover:bg-muted/50"
          onClick={() =>
            router.push(
              `/reports?tab=macro${effectiveDate ? `&date=${effectiveDate}` : ""}`,
            )
          }
        >
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-medium text-muted-foreground">
              Market Regime
            </CardTitle>
            <div className="flex items-center gap-1.5 text-muted-foreground">
              <Shield className="h-3.5 w-3.5" />
              <ArrowRight className="h-3 w-3" />
            </div>
          </CardHeader>
          <CardContent>
            {dashboard.isLoading ? (
              <Skeleton className="h-6 w-20" />
            ) : data?.regime_label ? (
              <div className="flex items-center gap-2">
                <Badge className={getRegimeColor(data.regime_label)}>
                  {data.regime_label}
                </Badge>
              </div>
            ) : (
              <span className="text-sm text-muted-foreground">—</span>
            )}
          </CardContent>
        </Card>

        {/* Signals Today */}
        <Card
          className="cursor-pointer transition-colors hover:bg-muted/50"
          onClick={() =>
            router.push(
              `/signals${effectiveDate ? `?date=${effectiveDate}` : ""}`,
            )
          }
        >
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-medium text-muted-foreground">
              Signals Today
            </CardTitle>
            <div className="flex items-center gap-1.5 text-muted-foreground">
              <BarChart3 className="h-3.5 w-3.5" />
              <ArrowRight className="h-3 w-3" />
            </div>
          </CardHeader>
          <CardContent>
            {dashboard.isLoading ? (
              <Skeleton className="h-7 w-12" />
            ) : (
              <p className="text-2xl font-bold">
                {data?.signal_count ?? "—"}
              </p>
            )}
          </CardContent>
        </Card>

        {/* Watchlist */}
        <Card
          className="cursor-pointer transition-colors hover:bg-muted/50"
          onClick={() => router.push("/watchlist")}
        >
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-medium text-muted-foreground">
              Watchlist
            </CardTitle>
            <div className="flex items-center gap-1.5 text-muted-foreground">
              <List className="h-3.5 w-3.5" />
              <ArrowRight className="h-3 w-3" />
            </div>
          </CardHeader>
          <CardContent>
            {watchlist.isLoading ? (
              <Skeleton className="h-7 w-12" />
            ) : (
              <p className="text-2xl font-bold">
                {watchlist.data?.total ?? "—"}
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      <Separator className="my-6" />

      {/* ---- Active Positions ---- */}
      {dashboard.isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-5 w-40" />
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-14 w-full rounded-xl" />
          ))}
        </div>
      ) : activePositions.length > 0 ? (
        <section>
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-semibold">
              Active Positions
              <span className="ml-2 text-sm font-normal text-muted-foreground">
                ({activePositions.length})
              </span>
            </h2>
            {data?.briefing_id && (
              <Button
                asChild
                variant="ghost"
                size="sm"
                className="gap-1 text-xs"
              >
                <Link href={`/reports/${data.briefing_id}`}>
                  View Full Report
                  <ArrowRight className="h-3 w-3" />
                </Link>
              </Button>
            )}
          </div>
          <PositionsTable positions={activePositions} />
        </section>
      ) : !data?.positions.length ? (
        /* Empty state — show pipeline status context */
        <PipelineStatusBanner
          status={data?.pipeline_status}
          step={data?.pipeline_step}
          error={data?.pipeline_error}
          isAdmin={!!isAdmin}
        />
      ) : null}
    </>
  );
}
