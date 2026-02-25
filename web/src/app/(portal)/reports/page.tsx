"use client";

import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "@/components/page-header";
import { reportsApi } from "@/lib/api-client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { MarkdownRenderer } from "@/components/markdown-renderer";
import { useState } from "react";
import Link from "next/link";
import type { GlobalReportResponse } from "@/lib/types";

/* ── Reusable report card for card-grid tabs ── */

function ReportCard({
  runDate,
  reportType,
  identity,
  model,
  href,
}: {
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

/* ── Reusable card grid (loading / empty / list) ── */

function ReportCardGrid({
  isLoading,
  reports,
  hrefPrefix,
}: {
  isLoading: boolean;
  reports: { id: string; run_date: string; report_type: string; identity_used: string | null; model_used: string | null }[] | undefined;
  hrefPrefix: string;
}) {
  if (isLoading) {
    return (
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {[1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-24" />
        ))}
      </div>
    );
  }
  if (!reports?.length) {
    return <p className="text-sm text-muted-foreground">No reports found.</p>;
  }
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {reports.map((r) => (
        <ReportCard
          key={r.id}
          runDate={r.run_date}
          reportType={r.report_type}
          identity={r.identity_used}
          model={r.model_used}
          href={`${hrefPrefix}/${r.id}`}
        />
      ))}
    </div>
  );
}

/* ── Symbols table with click-to-open modal ── */

function SymbolsTab({
  isLoading,
  reports,
}: {
  isLoading: boolean;
  reports: GlobalReportResponse[] | undefined;
}) {
  const [selected, setSelected] = useState<GlobalReportResponse | null>(null);

  if (isLoading) {
    return (
      <div className="space-y-2">
        {[1, 2, 3, 4].map((i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    );
  }

  if (!reports?.length) {
    return (
      <p className="text-sm text-muted-foreground">
        No symbol execution plans found.
      </p>
    );
  }

  return (
    <>
      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-28">Symbol</TableHead>
              <TableHead className="w-32">Date</TableHead>
              <TableHead>Model</TableHead>
              <TableHead>Persona</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {reports.map((r) => (
              <TableRow
                key={r.id}
                className="cursor-pointer transition-colors hover:bg-muted/60"
                onClick={() => setSelected(r)}
              >
                <TableCell className="font-medium">{r.symbol ?? "—"}</TableCell>
                <TableCell>{r.run_date}</TableCell>
                <TableCell className="text-muted-foreground text-xs">
                  {r.model_used ?? "—"}
                </TableCell>
                <TableCell className="text-muted-foreground text-xs">
                  {r.identity_used ?? "—"}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {/* ── Symbol detail modal ── */}
      <Dialog open={!!selected} onOpenChange={(open) => !open && setSelected(null)}>
        <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
          {selected && (
            <>
              <DialogHeader>
                <DialogTitle className="flex items-center gap-2">
                  <span>{selected.symbol ?? "Execution Plan"}</span>
                  <Badge variant="outline" className="text-xs font-normal">
                    {selected.run_date}
                  </Badge>
                  {selected.model_used && (
                    <Badge variant="secondary" className="text-xs font-normal">
                      {selected.model_used}
                    </Badge>
                  )}
                </DialogTitle>
              </DialogHeader>
              <MarkdownRenderer content={selected.content_md} />
            </>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}

/* ── Main page ── */

export default function ReportsPage() {
  const [tab, setTab] = useState("my");
  const [runDate, setRunDate] = useState("");

  const dateParam = runDate || undefined;

  // My (user) reports
  const userReports = useQuery({
    queryKey: ["reports", "user", runDate],
    queryFn: () => reportsApi.listUser({ run_date: dateParam, limit: 200 }),
  });

  // Macro reports (global, report_type = macro_summary)
  const macroReports = useQuery({
    queryKey: ["reports", "macro", runDate],
    queryFn: () =>
      reportsApi.listGlobal({ run_date: dateParam, report_type: "macro_summary", limit: 200 }),
  });

  // Portfolio reports (global, report_type = portfolio_summary)
  const portfolioReports = useQuery({
    queryKey: ["reports", "portfolio", runDate],
    queryFn: () =>
      reportsApi.listGlobal({ run_date: dateParam, report_type: "portfolio_summary", limit: 200 }),
  });

  // Symbol execution plans (global, report_type = symbol_execution_plan)
  const symbolReports = useQuery({
    queryKey: ["reports", "symbols", runDate],
    queryFn: () =>
      reportsApi.listGlobal({ run_date: dateParam, report_type: "symbol_execution_plan", limit: 500 }),
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
          <TabsTrigger value="my">
            My Report ({userReports.data?.total ?? "…"})
          </TabsTrigger>
          <TabsTrigger value="macro">
            Macro Report ({macroReports.data?.total ?? "…"})
          </TabsTrigger>
          <TabsTrigger value="portfolio">
            Portfolio ({portfolioReports.data?.total ?? "…"})
          </TabsTrigger>
          <TabsTrigger value="symbols">
            Symbols ({symbolReports.data?.total ?? "…"})
          </TabsTrigger>
        </TabsList>

        {/* ── My Report ── */}
        <TabsContent value="my" className="mt-4">
          <ReportCardGrid
            isLoading={userReports.isLoading}
            reports={userReports.data?.reports}
            hrefPrefix="/reports"
          />
        </TabsContent>

        {/* ── Macro Report ── */}
        <TabsContent value="macro" className="mt-4">
          <ReportCardGrid
            isLoading={macroReports.isLoading}
            reports={macroReports.data?.reports}
            hrefPrefix="/reports/global"
          />
        </TabsContent>

        {/* ── Portfolio ── */}
        <TabsContent value="portfolio" className="mt-4">
          <ReportCardGrid
            isLoading={portfolioReports.isLoading}
            reports={portfolioReports.data?.reports}
            hrefPrefix="/reports/global"
          />
        </TabsContent>

        {/* ── Symbols (table + modal) ── */}
        <TabsContent value="symbols" className="mt-4">
          <SymbolsTab
            isLoading={symbolReports.isLoading}
            reports={symbolReports.data?.reports}
          />
        </TabsContent>
      </Tabs>
    </>
  );
}
