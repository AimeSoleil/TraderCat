"use client";

import type { DashboardPositionItem } from "@/lib/types";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  TrendingUp,
  TrendingDown,
  Minus,
  AlertTriangle,
  Eye,
  Ban,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface PositionCardProps {
  position: DashboardPositionItem;
}

const directionConfig: Record<
  string,
  { label: string; color: string; icon: typeof TrendingUp }
> = {
  LONG: {
    label: "LONG",
    color: "bg-emerald-500/10 text-emerald-600 border-emerald-500/20",
    icon: TrendingUp,
  },
  SHORT: {
    label: "SHORT",
    color: "bg-red-500/10 text-red-600 border-red-500/20",
    icon: TrendingDown,
  },
  NEUTRAL: {
    label: "NEUTRAL",
    color: "bg-amber-500/10 text-amber-600 border-amber-500/20",
    icon: Minus,
  },
};

const qualityColors: Record<string, string> = {
  "A+": "bg-emerald-500/10 text-emerald-700 border-emerald-500/20",
  A: "bg-emerald-500/10 text-emerald-600 border-emerald-500/20",
  "B+": "bg-blue-500/10 text-blue-600 border-blue-500/20",
  B: "bg-blue-500/10 text-blue-500 border-blue-500/20",
  C: "bg-amber-500/10 text-amber-600 border-amber-500/20",
  REJECT: "bg-red-500/10 text-red-600 border-red-500/20",
};

const verdictConfig: Record<
  string,
  { label: string; color: string; icon: typeof TrendingUp }
> = {
  buy: {
    label: "BUY",
    color: "bg-emerald-500/10 text-emerald-600 border-emerald-500/20",
    icon: TrendingUp,
  },
  sell: {
    label: "SELL",
    color: "bg-red-500/10 text-red-600 border-red-500/20",
    icon: TrendingDown,
  },
  watchlist: {
    label: "WATCHLIST",
    color: "bg-amber-500/10 text-amber-600 border-amber-500/20",
    icon: Eye,
  },
  hold: {
    label: "HOLD",
    color: "bg-slate-500/10 text-slate-600 border-slate-500/20",
    icon: Minus,
  },
  reject: {
    label: "REJECT",
    color: "bg-red-500/10 text-red-600 border-red-500/20",
    icon: Ban,
  },
};

export function PositionCard({ position: p }: PositionCardProps) {
  const dir = directionConfig[p.direction?.toUpperCase() ?? ""] ?? directionConfig.NEUTRAL;
  const qual = qualityColors[p.setup_quality ?? ""] ?? "bg-muted text-muted-foreground";
  const verd = verdictConfig[p.verdict ?? ""] ?? verdictConfig.hold;
  const isRejected = p.verdict === "reject";
  const isWatchlist = p.verdict === "watchlist";
  const DirIcon = dir.icon;

  return (
    <Card
      className={cn(
        "relative overflow-hidden transition-all duration-200",
        isRejected && "opacity-60",
        isWatchlist && "border-dashed",
      )}
    >
      {/* Rank indicator */}
      <div className="absolute left-0 top-0 flex h-6 w-6 items-center justify-center rounded-br-lg bg-muted text-[10px] font-bold text-muted-foreground">
        {p.rank}
      </div>

      <CardHeader className="pb-3 pl-9 pr-4 pt-3">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="text-lg font-bold tracking-tight">{p.symbol}</span>
            <Badge variant="outline" className={cn("text-[10px] px-1.5 py-0", dir.color)}>
              <DirIcon className="mr-0.5 h-3 w-3" />
              {dir.label}
            </Badge>
          </div>
          <div className="flex items-center gap-1.5">
            {p.setup_quality && (
              <Badge variant="outline" className={cn("text-[10px] px-1.5 py-0", qual)}>
                {p.setup_quality}
              </Badge>
            )}
            <Badge variant="outline" className={cn("text-[10px] px-1.5 py-0", verd.color)}>
              {verd.label}
            </Badge>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-3 px-4 pb-4 pt-0">
        {/* Rejection reason */}
        {isRejected && p.rejection_reason && (
          <div className="flex items-start gap-2 rounded-md bg-red-500/5 px-3 py-2 text-xs text-red-600">
            <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
            <span>{p.rejection_reason}</span>
          </div>
        )}

        {/* Structure + Setup type */}
        {(p.structure || p.setup_type) && (
          <div className="space-y-1">
            {p.structure && (
              <p className="text-sm font-medium">{p.structure}</p>
            )}
            {p.setup_type && (
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">{p.setup_type}</span>
                {p.confluence && (
                  <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
                    {p.confluence}
                  </Badge>
                )}
              </div>
            )}
          </div>
        )}

        {/* Legs */}
        {p.legs && p.legs.length > 0 && (
          <div className="rounded-md bg-muted/50 px-3 py-2">
            <p className="mb-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
              Contract Legs
            </p>
            <div className="space-y-0.5">
              {p.legs.map((leg, i) => {
                const action = String(leg.action ?? "");
                const type = String(leg.type ?? "");
                const strike = String(leg.strike ?? "");
                const exp = String(leg.exp ?? "");
                const delta = leg.delta != null ? String(leg.delta) : null;
                return (
                <div key={i} className="flex items-center gap-2 text-xs font-mono">
                  <span
                    className={cn(
                      "w-8 font-medium",
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
                      @{"\u0394"}~{delta}
                    </span>
                  )}
                </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Key metrics — Entry / Stop / Target / R:R */}
        {p.has_structured_data && !isRejected && (
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
            {p.entry_price && (
              <div>
                <span className="text-muted-foreground">Entry: </span>
                <span className="font-medium font-mono">{p.entry_price}</span>
              </div>
            )}
            {p.stop_loss && (
              <div>
                <span className="text-muted-foreground">Stop: </span>
                <span className="font-medium font-mono text-red-500">{p.stop_loss}</span>
              </div>
            )}
            {p.profit_target && (
              <div>
                <span className="text-muted-foreground">Target: </span>
                <span className="font-medium font-mono text-emerald-600">{p.profit_target}</span>
              </div>
            )}
            {p.rr_estimate && (
              <div>
                <span className="text-muted-foreground">R:R: </span>
                <span className="font-medium font-mono">{p.rr_estimate}</span>
              </div>
            )}
          </div>
        )}

        {/* Risk row — Max Loss / Max Profit / Allocation / DTE */}
        {p.has_structured_data && !isRejected && (p.max_loss || p.max_profit || p.allocation) && (
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 border-t pt-2 text-xs">
            {p.max_loss && (
              <div>
                <span className="text-muted-foreground">Max Loss: </span>
                <span className="font-medium font-mono text-red-500">{p.max_loss}</span>
              </div>
            )}
            {p.max_profit && (
              <div>
                <span className="text-muted-foreground">Max Profit: </span>
                <span className="font-medium font-mono text-emerald-600">{p.max_profit}</span>
              </div>
            )}
            {p.allocation && (
              <div>
                <span className="text-muted-foreground">Allocation: </span>
                <span className="font-medium font-mono">{p.allocation}</span>
              </div>
            )}
            {p.time_stop && (
              <div>
                <span className="text-muted-foreground">DTE: </span>
                <span className="font-medium font-mono">{p.time_stop}</span>
              </div>
            )}
          </div>
        )}

        {/* Thesis */}
        {p.thesis && !isRejected && (
          <p className="text-xs italic text-muted-foreground leading-relaxed line-clamp-2">
            {p.thesis}
          </p>
        )}

        {/* No structured data fallback */}
        {!p.has_structured_data && !isRejected && (
          <p className="text-xs text-muted-foreground/60 italic">
            Structured data not available — view full report for details.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
