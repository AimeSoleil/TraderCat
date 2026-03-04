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
        /* Empty state — no positions at all */
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed py-16 text-center">
          <Inbox className="mb-4 h-12 w-12 text-muted-foreground/30" />
          <h3 className="text-base font-semibold">No positions yet</h3>
          <p className="mt-1 max-w-sm text-sm text-muted-foreground">
            Run the pipeline to generate trading signals and execution plans for
            your watchlist symbols.
          </p>
          {isAdmin && (
            <Button asChild variant="outline" size="sm" className="mt-4">
              <Link href="/admin/pipeline">Go to Pipeline</Link>
            </Button>
          )}
        </div>
      ) : null}
    </>
  );
}
