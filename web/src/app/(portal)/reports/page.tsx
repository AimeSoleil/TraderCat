"use client";

import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "@/components/page-header";
import { reportsApi } from "@/lib/api-client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useState } from "react";
import Link from "next/link";

function ReportCard({
  id,
  runDate,
  reportType,
  identity,
  model,
  href,
}: {
  id: string;
  runDate: string;
  reportType: string;
  identity: string | null;
  model: string | null;
  href: string;
}) {
  return (
    <Link href={href}>
      <Card className="cursor-pointer transition-colors hover:bg-muted/50">
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm font-medium">{reportType}</CardTitle>
            <Badge variant="outline" className="text-xs">
              {runDate}
            </Badge>
          </div>
        </CardHeader>
        <CardContent>
          <div className="flex gap-2 text-xs text-muted-foreground">
            {identity && <span>Persona: {identity}</span>}
            {model && <span>Model: {model}</span>}
          </div>
        </CardContent>
      </Card>
    </Link>
  );
}

export default function ReportsPage() {
  const [tab, setTab] = useState("user");
  const [runDate, setRunDate] = useState("");

  const userReports = useQuery({
    queryKey: ["reports", "user", runDate],
    queryFn: () => reportsApi.listUser({ run_date: runDate || undefined, limit: 100 }),
  });

  const globalReports = useQuery({
    queryKey: ["reports", "global", runDate],
    queryFn: () => reportsApi.listGlobal({ run_date: runDate || undefined, limit: 100 }),
  });

  return (
    <>
      <PageHeader title="Reports" description="AI-generated analysis reports" />

      <div className="mb-4">
        <Input
          type="date"
          value={runDate}
          onChange={(e) => setRunDate(e.target.value)}
          className="w-40"
        />
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="user">
            My Reports ({userReports.data?.total ?? 0})
          </TabsTrigger>
          <TabsTrigger value="global">
            Global Reports ({globalReports.data?.total ?? 0})
          </TabsTrigger>
        </TabsList>

        <TabsContent value="user" className="mt-4">
          {userReports.isLoading ? (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {[1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-24" />
              ))}
            </div>
          ) : userReports.data?.reports.length ? (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {userReports.data.reports.map((r) => (
                <ReportCard
                  key={r.id}
                  id={r.id}
                  runDate={r.run_date}
                  reportType={r.report_type}
                  identity={r.identity_used}
                  model={r.model_used}
                  href={`/reports/${r.id}`}
                />
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No user reports.</p>
          )}
        </TabsContent>

        <TabsContent value="global" className="mt-4">
          {globalReports.isLoading ? (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {[1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-24" />
              ))}
            </div>
          ) : globalReports.data?.reports.length ? (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {globalReports.data.reports.map((r) => (
                <ReportCard
                  key={r.id}
                  id={r.id}
                  runDate={r.run_date}
                  reportType={r.report_type}
                  identity={r.identity_used}
                  model={r.model_used}
                  href={`/reports/global/${r.id}`}
                />
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              No global reports.
            </p>
          )}
        </TabsContent>
      </Tabs>
    </>
  );
}
