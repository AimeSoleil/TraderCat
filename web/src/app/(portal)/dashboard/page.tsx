"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/components/providers/auth-provider";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import { DatePicker } from "@/components/date-picker";
import { PositionCard } from "@/components/position-card";
import { dashboardApi, watchlistApi, signalsApi } from "@/lib/api-client";
import {
  BarChart3,
  FileText,
  List,
  Shield,
  ArrowRight,
  Inbox,
} from "lucide-react";

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

export default function DashboardPage() {
  const { user, isAdmin } = useAuth();
  const [selectedDate, setSelectedDate] = useState<string | null>(null);

  // Main dashboard data
  const dashboard = useQuery({
    queryKey: ["dashboard", "positions", selectedDate],
    queryFn: () =>
      dashboardApi.getPositions(selectedDate ? { run_date: selectedDate } : undefined),
  });

  // Side stats
  const watchlist = useQuery({
    queryKey: ["watchlist"],
    queryFn: () => watchlistApi.list(),
  });

  const signals = useQuery({
    queryKey: ["signals", "latest"],
    queryFn: () => signalsApi.query({ limit: 5 }),
  });

  const data = dashboard.data;
  const activePositions = data?.positions.filter((p) => p.verdict === "buy" || p.verdict === "sell") ?? [];
  const watchlistPositions = data?.positions.filter((p) => p.verdict === "watchlist") ?? [];
  const rejectedPositions = data?.positions.filter(
    (p) => p.verdict === "reject" || p.verdict === "hold",
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

      {/* Summary Stats Bar */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {/* Regime */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-medium text-muted-foreground">
              Market Regime
            </CardTitle>
            <Shield className="h-3.5 w-3.5 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {dashboard.isLoading ? (
              <Skeleton className="h-6 w-20" />
            ) : data?.regime_label ? (
              <div className="flex items-center gap-2">
                <Badge className={getRegimeColor(data.regime_label)}>
                  {data.regime_label}
                </Badge>
                {data.regime_score !== null && (
                  <span className="text-xs text-muted-foreground">
                    ({data.regime_score.toFixed(1)})
                  </span>
                )}
              </div>
            ) : (
              <span className="text-sm text-muted-foreground">—</span>
            )}
          </CardContent>
        </Card>

        {/* Active Trades */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-medium text-muted-foreground">
              Active Trades
            </CardTitle>
            <BarChart3 className="h-3.5 w-3.5 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {dashboard.isLoading ? (
              <Skeleton className="h-7 w-12" />
            ) : (
              <p className="text-2xl font-bold">{activePositions.length}</p>
            )}
          </CardContent>
        </Card>

        {/* Watchlist Symbols */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-medium text-muted-foreground">
              Watchlist
            </CardTitle>
            <List className="h-3.5 w-3.5 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {watchlist.isLoading ? (
              <Skeleton className="h-7 w-12" />
            ) : (
              <p className="text-2xl font-bold">{watchlist.data?.total ?? "—"}</p>
            )}
          </CardContent>
        </Card>

        {/* Latest Signals */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-medium text-muted-foreground">
              Signals Today
            </CardTitle>
            <BarChart3 className="h-3.5 w-3.5 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {signals.isLoading ? (
              <Skeleton className="h-7 w-12" />
            ) : (
              <p className="text-2xl font-bold">{signals.data?.total ?? "—"}</p>
            )}
          </CardContent>
        </Card>

        {/* Briefing Link */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-medium text-muted-foreground">
              Full Report
            </CardTitle>
            <FileText className="h-3.5 w-3.5 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {dashboard.isLoading ? (
              <Skeleton className="h-7 w-24" />
            ) : data?.briefing_id ? (
              <Button asChild variant="outline" size="sm" className="gap-1.5 text-xs">
                <Link href={`/reports/${data.briefing_id}`}>
                  View Briefing
                  <ArrowRight className="h-3 w-3" />
                </Link>
              </Button>
            ) : (
              <span className="text-sm text-muted-foreground">—</span>
            )}
          </CardContent>
        </Card>
      </div>

      <Separator className="my-6" />

      {/* Active Positions */}
      {dashboard.isLoading ? (
        <div className="space-y-4">
          <Skeleton className="h-5 w-40" />
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {[1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-64 w-full rounded-xl" />
            ))}
          </div>
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
              <Button asChild variant="ghost" size="sm" className="gap-1 text-xs">
                <Link href={`/reports/${data.briefing_id}`}>
                  View Full Report
                  <ArrowRight className="h-3 w-3" />
                </Link>
              </Button>
            )}
          </div>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {activePositions.map((p) => (
              <PositionCard key={p.id} position={p} />
            ))}
          </div>
        </section>
      ) : !data?.positions.length ? (
        /* Empty state */
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

      {/* Watchlist Positions */}
      {watchlistPositions.length > 0 && (
        <section className="mt-8">
          <h2 className="mb-4 text-lg font-semibold">
            Watchlist
            <span className="ml-2 text-sm font-normal text-muted-foreground">
              ({watchlistPositions.length})
            </span>
          </h2>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {watchlistPositions.map((p) => (
              <PositionCard key={p.id} position={p} />
            ))}
          </div>
        </section>
      )}

      {/* Rejected / Hold */}
      {rejectedPositions.length > 0 && (
        <section className="mt-8">
          <h2 className="mb-4 text-lg font-semibold text-muted-foreground">
            Rejected / Hold
            <span className="ml-2 text-sm font-normal">
              ({rejectedPositions.length})
            </span>
          </h2>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {rejectedPositions.map((p) => (
              <PositionCard key={p.id} position={p} />
            ))}
          </div>
        </section>
      )}
    </>
  );
}
