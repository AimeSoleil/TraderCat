"use client";

import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/components/providers/auth-provider";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { watchlistApi, signalsApi, reportsApi } from "@/lib/api-client";
import { BarChart3, FileText, List, TrendingUp } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";

export default function DashboardPage() {
  const { user, isAdmin } = useAuth();

  const watchlist = useQuery({
    queryKey: ["watchlist"],
    queryFn: () => watchlistApi.list(),
  });

  const signals = useQuery({
    queryKey: ["signals", "latest"],
    queryFn: () => signalsApi.query({ limit: 5 }),
  });

  const reports = useQuery({
    queryKey: ["reports", "briefings", "latest"],
    queryFn: () => reportsApi.listBriefings({ limit: 5 }),
  });

  const macroReports = useQuery({
    queryKey: ["reports", "macro", "latest"],
    queryFn: () => reportsApi.listMacro({ limit: 5 }),
  });

  const stats = [
    {
      title: "Watchlist Symbols",
      value: watchlist.data?.total ?? "—",
      icon: List,
    },
    {
      title: "Latest Signals",
      value: signals.data?.total ?? "—",
      icon: BarChart3,
    },
    {
      title: "Briefings",
      value: reports.data?.total ?? "—",
      icon: FileText,
    },
    {
      title: "Macro Reports",
      value: macroReports.data?.total ?? "—",
      icon: TrendingUp,
    },
  ];

  return (
    <>
      <PageHeader
        title={`Welcome, ${user?.username ?? ""}!`}
        description={isAdmin ? "Admin dashboard" : "Your trading dashboard"}
      />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {stats.map((s) => (
          <Card key={s.title}>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                {s.title}
              </CardTitle>
              <s.icon className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              {watchlist.isLoading ? (
                <Skeleton className="h-8 w-16" />
              ) : (
                <p className="text-2xl font-bold">{s.value}</p>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Recent signals preview */}
      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Recent Signals</CardTitle>
          </CardHeader>
          <CardContent>
            {signals.isLoading ? (
              <div className="space-y-2">
                {[1, 2, 3].map((i) => (
                  <Skeleton key={i} className="h-6 w-full" />
                ))}
              </div>
            ) : signals.data?.signals.length ? (
              <div className="space-y-2">
                {signals.data.signals.map((s) => (
                  <div
                    key={s.id}
                    className="flex items-center justify-between text-sm"
                  >
                    <span className="font-medium">{s.symbol}</span>
                    <span className="text-muted-foreground">{s.strategy}</span>
                    <span
                      className={
                        s.signal === "buy"
                          ? "text-green-600"
                          : s.signal === "sell"
                            ? "text-red-600"
                            : "text-muted-foreground"
                      }
                    >
                      {s.signal.toUpperCase()}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">No signals yet.</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Recent Reports</CardTitle>
          </CardHeader>
          <CardContent>
            {reports.isLoading ? (
              <div className="space-y-2">
                {[1, 2, 3].map((i) => (
                  <Skeleton key={i} className="h-6 w-full" />
                ))}
              </div>
            ) : reports.data?.reports.length ? (
              <div className="space-y-2">
                {reports.data.reports.map((r) => (
                  <div
                    key={r.id}
                    className="flex items-center justify-between text-sm"
                  >
                    <span className="font-medium">Briefing</span>
                    <span className="text-muted-foreground">{r.run_date}</span>
                    <span className="text-xs text-muted-foreground">
                      {r.identity_used ?? "—"}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">No reports yet.</p>
            )}
          </CardContent>
        </Card>
      </div>
    </>
  );
}
