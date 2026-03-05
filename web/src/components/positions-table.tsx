"use client";

import { useState } from "react";
import type { DashboardPositionItem } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  TrendingUp,
  TrendingDown,
  Minus,
  ChevronDown,
  AlertTriangle,
} from "lucide-react";
import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ */
/*  Config maps                                                        */
/* ------------------------------------------------------------------ */

const directionMeta: Record<
  string,
  { label: string; cls: string; icon: typeof TrendingUp }
> = {
  LONG: { label: "Long", cls: "text-emerald-600", icon: TrendingUp },
  SHORT: { label: "Short", cls: "text-red-500", icon: TrendingDown },
  NEUTRAL: { label: "Neutral", cls: "text-amber-500", icon: Minus },
};

const qualityBadge: Record<string, string> = {
  "A+": "bg-emerald-500/15 text-emerald-700 border-emerald-500/25",
  A: "bg-emerald-500/10 text-emerald-600 border-emerald-500/20",
  "B+": "bg-blue-500/15 text-blue-600 border-blue-500/25",
  B: "bg-blue-500/10 text-blue-500 border-blue-500/20",
  C: "bg-amber-500/10 text-amber-600 border-amber-500/20",
  REJECT: "bg-red-500/10 text-red-600 border-red-500/20",
};

const verdictBadge: Record<string, string> = {
  buy: "bg-emerald-500/15 text-emerald-700 border-emerald-500/25",
  sell: "bg-red-500/15 text-red-600 border-red-500/25",
  watchlist: "bg-amber-500/10 text-amber-600 border-amber-500/20",
  hold: "bg-slate-500/10 text-slate-500 border-slate-500/20",
  reject: "bg-red-500/10 text-red-500 border-red-500/20",
};

/* ------------------------------------------------------------------ */
/*  Expanded detail panel                                              */
/* ------------------------------------------------------------------ */

function PositionDetail({ p }: { p: DashboardPositionItem }) {
  const isRejected = p.verdict === "reject";

  return (
    <div className="grid gap-5 px-2 py-4 sm:grid-cols-2 lg:grid-cols-3">
      {/* ── Rejection ── */}
      {isRejected && p.rejection_reason && (
        <div className="col-span-full flex items-start gap-2 rounded-lg bg-red-500/5 px-4 py-3 text-sm text-red-600">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{p.rejection_reason}</span>
        </div>
      )}

      {/* ── Structure & Setup ── */}
      {(p.structure || p.setup_type) && (
        <div className="space-y-1.5">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Structure / Setup
          </h4>
          {p.structure && (
            <p className="text-sm font-medium leading-snug">{p.structure}</p>
          )}
          {p.setup_type && (
            <p className="text-sm text-muted-foreground">
              {p.setup_type}
              {p.confluence && (
                <span className="ml-2 rounded bg-muted px-1.5 py-0.5 text-xs font-medium">
                  {p.confluence}
                </span>
              )}
            </p>
          )}
        </div>
      )}

      {/* ── Contract Legs ── */}
      {p.legs && p.legs.length > 0 && (
        <div className="space-y-1.5">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Contract Legs
          </h4>
          <div className="space-y-1 rounded-lg bg-muted/40 px-3 py-2">
            {p.legs.map((leg, i) => {
              const action = String(leg.action ?? "");
              const type = String(leg.type ?? "");
              const strike = String(leg.strike ?? "");
              const exp = String(leg.exp ?? "");
              const delta = leg.delta != null ? String(leg.delta) : null;
              return (
                <div
                  key={i}
                  className="flex items-center gap-2 font-mono text-sm"
                >
                  <span
                    className={cn(
                      "w-9 font-semibold",
                      action.toUpperCase() === "BUY"
                        ? "text-emerald-600"
                        : "text-red-500",
                    )}
                  >
                    {action.toUpperCase()}
                  </span>
                  <span className="text-muted-foreground">
                    {type} {strike} {exp}
                  </span>
                  {delta && (
                    <span className="text-muted-foreground/60">
                      Δ~{delta}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ── Key Metrics ── */}
      {p.has_structured_data && !isRejected && (
        <div className="space-y-1.5">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Key Metrics
          </h4>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
            {p.entry_price && (
              <div>
                <dt className="text-muted-foreground">Entry</dt>
                <dd className="font-mono font-medium">{p.entry_price}</dd>
              </div>
            )}
            {p.stop_loss && (
              <div>
                <dt className="text-muted-foreground">Stop</dt>
                <dd className="font-mono font-medium text-red-500">
                  {p.stop_loss}
                </dd>
              </div>
            )}
            {p.profit_target && (
              <div>
                <dt className="text-muted-foreground">Target</dt>
                <dd className="font-mono font-medium text-emerald-600">
                  {p.profit_target}
                </dd>
              </div>
            )}
            {p.rr_estimate && (
              <div>
                <dt className="text-muted-foreground">R:R</dt>
                <dd className="font-mono font-medium">{p.rr_estimate}</dd>
              </div>
            )}
          </dl>
        </div>
      )}

      {/* ── Risk Management ── */}
      {p.has_structured_data &&
        !isRejected &&
        (p.max_loss || p.max_profit || p.allocation || p.time_stop) && (
          <div className="space-y-1.5">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Risk Management
            </h4>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
              {p.max_loss && (
                <div>
                  <dt className="text-muted-foreground">Max Loss</dt>
                  <dd className="font-mono font-medium text-red-500">
                    {p.max_loss}
                  </dd>
                </div>
              )}
              {p.max_profit && (
                <div>
                  <dt className="text-muted-foreground">Max Profit</dt>
                  <dd className="font-mono font-medium text-emerald-600">
                    {p.max_profit}
                  </dd>
                </div>
              )}
              {p.allocation && (
                <div>
                  <dt className="text-muted-foreground">Allocation</dt>
                  <dd className="font-mono font-medium">{p.allocation}</dd>
                </div>
              )}
              {p.time_stop && (
                <div>
                  <dt className="text-muted-foreground">DTE</dt>
                  <dd className="font-mono font-medium">{p.time_stop}</dd>
                </div>
              )}
            </dl>
          </div>
        )}

      {/* ── Thesis ── */}
      {p.thesis && !isRejected && (
        <div className="col-span-full space-y-1.5">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Thesis
          </h4>
          <p className="max-w-prose text-sm leading-relaxed text-muted-foreground">
            {p.thesis}
          </p>
        </div>
      )}

      {/* ── No structured data ── */}
      {!p.has_structured_data && !isRejected && (
        <p className="col-span-full text-sm italic text-muted-foreground/60">
          Structured data not available — view the full report for details.
        </p>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Table component                                                    */
/* ------------------------------------------------------------------ */

interface PositionsTableProps {
  positions: DashboardPositionItem[];
}

export function PositionsTable({ positions }: PositionsTableProps) {
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  function toggle(id: string) {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div className="rounded-xl border bg-card">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="w-10 text-center">#</TableHead>
            <TableHead>Symbol</TableHead>
            <TableHead>Direction</TableHead>
            <TableHead>Setup</TableHead>
            <TableHead className="text-center">Quality</TableHead>
            <TableHead className="text-center">R : R</TableHead>
            <TableHead className="text-center">Verdict</TableHead>
            <TableHead className="w-10" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {positions.map((p) => {
            const dir =
              directionMeta[p.direction?.toUpperCase() ?? ""] ??
              directionMeta.NEUTRAL;
            const DirIcon = dir.icon;
            const expanded = expandedIds.has(p.id);

            return (
              <PositionRow
                key={p.id}
                position={p}
                dir={dir}
                DirIcon={DirIcon}
                expanded={expanded}
                onToggle={() => toggle(p.id)}
              />
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Single position row (header + detail)                              */
/* ------------------------------------------------------------------ */

function PositionRow({
  position: p,
  dir,
  DirIcon,
  expanded,
  onToggle,
}: {
  position: DashboardPositionItem;
  dir: (typeof directionMeta)[string];
  DirIcon: typeof TrendingUp;
  expanded: boolean;
  onToggle: () => void;
}) {
  const qual =
    qualityBadge[p.setup_quality ?? ""] ??
    "bg-muted text-muted-foreground";
  const vBadge =
    verdictBadge[p.verdict ?? ""] ?? "bg-muted text-muted-foreground";

  return (
    <>
      {/* --- Main row --- */}
      <TableRow
        className="cursor-pointer select-none interactive-row"
        onClick={onToggle}
      >
        {/* Rank */}
        <TableCell className="text-center font-semibold text-muted-foreground">
          {p.rank}
        </TableCell>

        {/* Symbol */}
        <TableCell className="font-bold tracking-tight text-base">
          {p.symbol}
        </TableCell>

        {/* Direction */}
        <TableCell>
          <span className={cn("inline-flex items-center gap-1 font-medium", dir.cls)}>
            <DirIcon className="h-3.5 w-3.5" />
            {dir.label}
          </span>
        </TableCell>

        {/* Setup (truncated) */}
        <TableCell className="max-w-[200px] truncate text-muted-foreground">
          {p.setup_type ?? "—"}
        </TableCell>

        {/* Quality */}
        <TableCell className="text-center">
          {p.setup_quality ? (
            <Badge variant="outline" className={cn("px-2 py-0.5 text-xs", qual)}>
              {p.setup_quality}
            </Badge>
          ) : (
            <span className="text-muted-foreground">—</span>
          )}
        </TableCell>

        {/* R:R */}
        <TableCell className="text-center font-mono text-sm">
          {p.rr_estimate ?? "—"}
        </TableCell>

        {/* Verdict */}
        <TableCell className="text-center">
          <Badge
            variant="outline"
            className={cn("px-2.5 py-0.5 text-xs font-semibold uppercase", vBadge)}
          >
            {p.verdict ?? "—"}
          </Badge>
        </TableCell>

        {/* Chevron */}
        <TableCell className="text-center">
          <ChevronDown
            className={cn(
              "h-4 w-4 text-muted-foreground transition-transform duration-200",
              expanded && "rotate-180",
            )}
          />
        </TableCell>
      </TableRow>

      {/* --- Expanded detail row --- */}
      {expanded && (
        <tr>
          <td colSpan={8} className="border-b bg-muted/30 px-4">
            <PositionDetail p={p} />
          </td>
        </tr>
      )}
    </>
  );
}
