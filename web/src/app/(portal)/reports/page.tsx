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
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { MarkdownRenderer } from "@/components/markdown-renderer";
import { useIsMobile } from "@/hooks/use-mobile";
import { useState } from "react";
import Link from "next/link";
import type {
  MacroRegimeContextResponse,
  SymbolExecutionPlanResponse,
} from "@/lib/types";

/* ── Briefing card for My Briefing tab ── */

function BriefingCard({
  runDate,
  identity,
  model,
  href,
}: {
  runDate: string;
  identity: string | null;
  model: string | null;
  href: string;
}) {
  return (
    <Link href={href}>
      <Card className="cursor-pointer transition-colors hover:bg-muted/50">
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm font-medium">Briefing</CardTitle>
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

/* ── Macro regime card for Macro tab ── */

function MacroCard({
  report,
  href,
}: {
  report: MacroRegimeContextResponse;
  href: string;
}) {
  return (
    <Link href={href}>
      <Card className="cursor-pointer transition-colors hover:bg-muted/50">
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm font-medium">
              {report.regime_label ?? "Macro Regime"}
            </CardTitle>
            <Badge variant="outline" className="text-xs">
              {report.run_date}
            </Badge>
          </div>
        </CardHeader>
        <CardContent>
          <div className="flex gap-2 text-xs text-muted-foreground">
            {report.regime_score != null && (
              <span>Score: {report.regime_score.toFixed(1)}</span>
            )}
            {report.model_used && <span>Model: {report.model_used}</span>}
          </div>
        </CardContent>
      </Card>
    </Link>
  );
}

/* ── Skeleton grid helper ── */

function SkeletonGrid({ count = 3 }: { count?: number }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: count }, (_, i) => (
        <Skeleton key={i} className="h-24" />
      ))}
    </div>
  );
}

/* ── Execution plans table with click-to-open modal ── */

function PlanDetailContent({ plan }: { plan: SymbolExecutionPlanResponse }) {
  return (
    <div className="flex flex-col gap-5">
      {/* ── Header: symbol + metadata ── */}
      <div className="space-y-2">
        <div className="flex flex-wrap items-baseline gap-3">
          <span className="text-2xl font-bold tracking-tight">{plan.symbol}</span>
          {plan.verdict && (
            <Badge
              variant={plan.verdict === "go" ? "default" : "secondary"}
              className="text-sm px-2.5 py-0.5"
            >
              {plan.verdict.toUpperCase()}
            </Badge>
          )}
          {plan.setup_quality && (
            <span className="text-sm text-muted-foreground">
              Quality: <span className="font-medium text-foreground">{plan.setup_quality}</span>
            </span>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
          <span>{plan.run_date}</span>
          {plan.identity_used && <span>Persona: {plan.identity_used}</span>}
          {plan.model_used && <span>Model: {plan.model_used}</span>}
        </div>
      </div>

      {/* ── Divider ── */}
      <hr className="border-border" />

      {/* ── Body: markdown content ── */}
      <MarkdownRenderer content={plan.content_md} className="text-[0.95rem] leading-relaxed" />
    </div>
  );
}

function PlansTab({
  isLoading,
  plans,
}: {
  isLoading: boolean;
  plans: SymbolExecutionPlanResponse[] | undefined;
}) {
  const [selected, setSelected] = useState<SymbolExecutionPlanResponse | null>(null);
  const isMobile = useIsMobile();

  if (isLoading) {
    return (
      <div className="space-y-2">
        {[1, 2, 3, 4].map((i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    );
  }

  if (!plans?.length) {
    return (
      <p className="text-sm text-muted-foreground">
        No execution plans found.
      </p>
    );
  }

  /* ── Mobile: compact card list ── */
  const mobileList = (
    <div className="space-y-2 sm:hidden">
      {plans.map((p) => (
        <Card
          key={p.id}
          className="cursor-pointer transition-colors hover:bg-muted/50"
          onClick={() => setSelected(p)}
        >
          <CardContent className="flex items-center justify-between p-3">
            <span className="font-medium">{p.symbol}</span>
            <div className="flex items-center gap-2">
              {p.verdict && (
                <Badge
                  variant={p.verdict === "go" ? "default" : "secondary"}
                  className="text-xs"
                >
                  {p.verdict.toUpperCase()}
                </Badge>
              )}
              <Badge variant="outline" className="text-xs">{p.run_date}</Badge>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );

  /* ── Desktop: table ── */
  const desktopTable = (
    <div className="hidden sm:block rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-28">Symbol</TableHead>
            <TableHead className="w-24">Verdict</TableHead>
            <TableHead className="w-28">Quality</TableHead>
            <TableHead className="w-32">Date</TableHead>
            <TableHead>Model</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {plans.map((p) => (
            <TableRow
              key={p.id}
              className="cursor-pointer transition-colors hover:bg-muted/60"
              onClick={() => setSelected(p)}
            >
              <TableCell className="font-medium">{p.symbol}</TableCell>
              <TableCell>
                {p.verdict ? (
                  <Badge
                    variant={p.verdict === "go" ? "default" : "secondary"}
                    className="text-xs"
                  >
                    {p.verdict.toUpperCase()}
                  </Badge>
                ) : (
                  "—"
                )}
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">
                {p.setup_quality ?? "—"}
              </TableCell>
              <TableCell>{p.run_date}</TableCell>
              <TableCell className="text-muted-foreground text-xs">
                {p.model_used ?? "—"}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );

  return (
    <>
      {mobileList}
      {desktopTable}

      {/* ── Mobile: bottom sheet ── */}
      {isMobile ? (
        <Sheet open={!!selected} onOpenChange={(open) => !open && setSelected(null)}>
          <SheetContent aria-describedby={undefined} side="bottom" className="h-[90dvh] overflow-y-auto rounded-t-xl px-5 py-5 pb-8">
            <SheetHeader className="sr-only">
              <SheetTitle>{selected?.symbol ?? "Execution Plan"}</SheetTitle>
            </SheetHeader>
            {selected && <PlanDetailContent plan={selected} />}
          </SheetContent>
        </Sheet>
      ) : (
        /* ── Desktop: centered dialog ── */
        <Dialog open={!!selected} onOpenChange={(open) => !open && setSelected(null)}>
          <DialogContent aria-describedby={undefined} className="max-w-[108rem] w-[95vw] max-h-[90vh] overflow-y-auto px-8 py-6">
            {selected && (
              <>
                <DialogHeader className="sr-only">
                  <DialogTitle>{selected.symbol} Execution Plan</DialogTitle>
                </DialogHeader>
                <PlanDetailContent plan={selected} />
              </>
            )}
          </DialogContent>
        </Dialog>
      )}
    </>
  );
}

/* ── Main page ── */

/** Return local today as YYYY-MM-DD */
function todayStr() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function ReportsPage() {
  const [tab, setTab] = useState("my");
  const [runDate, setRunDate] = useState(todayStr);

  const dateParam = runDate || undefined;

  // My briefings (P4)
  const briefings = useQuery({
    queryKey: ["reports", "briefings", runDate],
    queryFn: () => reportsApi.listBriefings({ run_date: dateParam, limit: 200 }),
  });

  // Macro regime contexts (P2)
  const macroReports = useQuery({
    queryKey: ["reports", "macro", runDate],
    queryFn: () => reportsApi.listMacro({ run_date: dateParam, limit: 200 }),
  });

  // Symbol execution plans (P3)
  const plans = useQuery({
    queryKey: ["reports", "plans", runDate],
    queryFn: () => reportsApi.listPlans({ run_date: dateParam, limit: 500 }),
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
            My Briefing ({briefings.data?.total ?? "…"})
          </TabsTrigger>
          <TabsTrigger value="macro">
            Macro Regime ({macroReports.data?.total ?? "…"})
          </TabsTrigger>
          <TabsTrigger value="plans">
            Execution Plans ({plans.data?.total ?? "…"})
          </TabsTrigger>
        </TabsList>

        {/* ── My Briefing ── */}
        <TabsContent value="my" className="mt-4">
          {briefings.isLoading ? (
            <SkeletonGrid />
          ) : !briefings.data?.reports.length ? (
            <p className="text-sm text-muted-foreground">No briefings found.</p>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {briefings.data.reports.map((r) => (
                <BriefingCard
                  key={r.id}
                  runDate={r.run_date}
                  identity={r.identity_used}
                  model={r.model_used}
                  href={`/reports/${r.id}`}
                />
              ))}
            </div>
          )}
        </TabsContent>

        {/* ── Macro Regime ── */}
        <TabsContent value="macro" className="mt-4">
          {macroReports.isLoading ? (
            <SkeletonGrid />
          ) : !macroReports.data?.reports.length ? (
            <p className="text-sm text-muted-foreground">No macro reports found.</p>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {macroReports.data.reports.map((r) => (
                <MacroCard
                  key={r.id}
                  report={r}
                  href={`/reports/macro/${r.id}`}
                />
              ))}
            </div>
          )}
        </TabsContent>

        {/* ── Execution Plans (table + modal) ── */}
        <TabsContent value="plans" className="mt-4">
          <PlansTab
            isLoading={plans.isLoading}
            plans={plans.data?.reports}
          />
        </TabsContent>
      </Tabs>
    </>
  );
}
