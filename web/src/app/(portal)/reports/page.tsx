"use client";

import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "@/components/page-header";
import { DatePicker } from "@/components/date-picker";
import { reportsApi } from "@/lib/api-client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
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
import { useState, useCallback } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import { FileText, Shield, Inbox } from "lucide-react";
import type {
  MacroRegimeContextResponse,
  SymbolExecutionPlanResponse,
} from "@/lib/types";

/* ── Regime color map (same as Dashboard) ── */

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

function getRegimeBorderColor(label: string | null | undefined): string {
  if (!label) return "border-muted-foreground/30";
  const upper = label.toUpperCase();
  if (upper.includes("DARK GREEN")) return "border-emerald-600";
  if (upper.includes("GREEN")) return "border-emerald-500";
  if (upper.includes("YELLOW")) return "border-amber-400";
  if (upper.includes("ORANGE")) return "border-orange-500";
  if (upper.includes("RED")) return "border-red-600";
  return "border-muted-foreground/30";
}

/* ── Empty state helper ── */

function EmptyState({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed py-12 text-center">
      <Inbox className="mb-3 h-10 w-10 text-muted-foreground/30" />
      <p className="text-sm font-medium">{title}</p>
      <p className="mt-1 text-xs text-muted-foreground">{description}</p>
    </div>
  );
}

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
      <Card className="cursor-pointer border-l-4 border-primary transition-colors hover:bg-muted/50">
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <FileText className="h-4 w-4 text-primary" />
              <CardTitle className="text-sm font-medium">Briefing</CardTitle>
            </div>
            <Badge variant="outline" className="text-xs font-semibold">
              {runDate}
            </Badge>
          </div>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col gap-1 text-xs text-muted-foreground">
            {identity && (
              <span>
                Persona: <span className="font-medium text-foreground">{identity}</span>
              </span>
            )}
            {model && (
              <span>
                Model: <span className="font-medium text-foreground">{model}</span>
              </span>
            )}
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
      <Card
        className={`cursor-pointer border-l-4 ${getRegimeBorderColor(report.regime_label)} transition-colors hover:bg-muted/50`}
      >
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Shield className="h-4 w-4 text-muted-foreground" />
              <CardTitle className="text-sm font-medium">
                {report.regime_label ?? "Macro Regime"}
              </CardTitle>
            </div>
            <Badge variant="outline" className="text-xs font-semibold">
              {report.run_date}
            </Badge>
          </div>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-center gap-3">
            {report.regime_label && (
              <Badge className={getRegimeColor(report.regime_label)}>
                {report.regime_label}
              </Badge>
            )}
            {report.regime_score != null && (
              <span className="text-xs text-muted-foreground">
                Score:{" "}
                <span className="font-semibold text-foreground">
                  {report.regime_score.toFixed(1)}
                </span>
              </span>
            )}
            {report.model_used && (
              <span className="text-xs text-muted-foreground">
                Model:{" "}
                <span className="font-medium text-foreground">
                  {report.model_used}
                </span>
              </span>
            )}
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
  // Strip the redundant title heading (e.g. "## AAPL — Analysis Report")
  // since the modal header already displays the symbol + metadata.
  const strippedContent = plan.content_md
    .replace(/^##?\s+.*(?:Analysis Report|—).*\n*/i, "")
    .trimStart();

  return (
    <div className="flex flex-col gap-3">
      {/* ── Header: symbol + metadata ── */}
      <div className="space-y-1">
        <div className="flex flex-wrap items-baseline gap-2">
          <span className="text-base font-bold tracking-tight">{plan.symbol}</span>
          {plan.verdict && (
            <Badge
              variant={plan.verdict === "buy" ? "default" : plan.verdict === "sell" ? "destructive" : "secondary"}
              className="text-xs px-1.5 py-px"
            >
              {plan.verdict.toUpperCase()}
            </Badge>
          )}
          {plan.setup_quality && (
            <span className="text-xs text-muted-foreground">
              Quality: <span className="font-medium text-foreground">{plan.setup_quality}</span>
            </span>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span>{plan.run_date}</span>
          {plan.identity_used && <span>Persona: {plan.identity_used}</span>}
          {plan.model_used && <span>Model: {plan.model_used}</span>}
        </div>
      </div>

      {/* ── Divider ── */}
      <hr className="border-border" />

      {/* ── Body: markdown content ── */}
      <MarkdownRenderer content={strippedContent} className="text-sm leading-relaxed" />
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
      <EmptyState
        title="No execution plans found"
        description="Try selecting a different date"
      />
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
                  variant={p.verdict === "buy" ? "default" : p.verdict === "sell" ? "destructive" : "secondary"}
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
    <div className="hidden sm:block overflow-x-auto rounded-md border">
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
                    variant={p.verdict === "buy" ? "default" : p.verdict === "sell" ? "destructive" : "secondary"}
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
          <DialogContent aria-describedby={undefined} className="max-w-4xl max-h-[90vh] overflow-y-auto px-10 py-8">
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
  const searchParams = useSearchParams();
  const router = useRouter();

  const [tab, setTab] = useState(() => searchParams.get("tab") || "my");
  const [runDate, setRunDate] = useState(() => searchParams.get("date") || todayStr());

  // Sync date + tab to URL so navigating back preserves selection
  const updateParam = useCallback(
    (key: string, value: string) => {
      const params = new URLSearchParams(searchParams.toString());
      params.set(key, value);
      router.replace(`?${params.toString()}`, { scroll: false });
    },
    [searchParams, router],
  );

  const handleDateChange = (value: string) => {
    setRunDate(value);
    updateParam("date", value);
  };

  const handleTabChange = (value: string) => {
    setTab(value);
    updateParam("tab", value);
  };

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
      <PageHeader
        title="Reports"
        description="AI-generated analysis reports"
        actions={
          <DatePicker
            value={runDate}
            onChange={handleDateChange}
            placeholder="Select date"
          />
        }
      />

      <Tabs value={tab} onValueChange={handleTabChange}>
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
            <EmptyState
              title="No briefings found"
              description="Try selecting a different date"
            />
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
            <EmptyState
              title="No macro reports found"
              description="Try selecting a different date"
            />
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
