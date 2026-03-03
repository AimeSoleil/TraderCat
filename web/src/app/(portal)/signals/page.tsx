"use client";

import { useQuery, keepPreviousData } from "@tanstack/react-query";
import {
  flexRender,
  getCoreRowModel,
  getExpandedRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
  type ExpandedState,
  type Row,
} from "@tanstack/react-table";
import { useSearchParams, useRouter } from "next/navigation";
import { PageHeader } from "@/components/page-header";
import { DatePicker } from "@/components/date-picker";
import { signalsApi } from "@/lib/api-client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ChevronDown, ChevronRight, Download, Loader2 } from "lucide-react";
import { Fragment, useState, useEffect, useCallback } from "react";
import { toast } from "sonner";
import type { SignalResponse } from "@/lib/types";

/** Debounce hook — delays value updates by `delay` ms */
function useDebouncedValue<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(id);
  }, [value, delay]);
  return debounced;
}

const signalColor: Record<string, string> = {
  buy: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300",
  sell: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300",
  hold: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300",
  rebalance: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300",
};

const columns: ColumnDef<SignalResponse>[] = [
  {
    id: "expander",
    header: () => null,
    cell: ({ row }) => {
      const hasData = 
        (row.original.ohlcv && Object.keys(row.original.ohlcv).length > 0) ||
        (row.original.indicators && Object.keys(row.original.indicators).length > 0);
      if (!hasData) {
        return <span className="inline-block w-4" />;
      }
      return (
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6"
          onClick={(e) => {
            e.stopPropagation();
            row.toggleExpanded();
          }}
        >
          {row.getIsExpanded() ? (
            <ChevronDown className="h-4 w-4" />
          ) : (
            <ChevronRight className="h-4 w-4" />
          )}
        </Button>
      );
    },
    enableSorting: false,
  },
  { accessorKey: "run_date", header: "Date" },
  {
    accessorKey: "symbol",
    header: "Symbol",
    cell: ({ getValue }) => (
      <span className="font-medium">{getValue<string>()}</span>
    ),
  },
  { accessorKey: "strategy", header: "Strategy" },
  {
    accessorKey: "signal",
    header: "Signal",
    cell: ({ getValue }) => {
      const v = getValue<string>();
      return (
        <Badge variant="secondary" className={signalColor[v] ?? ""}>
          {v.toUpperCase()}
        </Badge>
      );
    },
  },
  {
    accessorKey: "confidence",
    header: "Confidence",
    cell: ({ getValue }) => {
      const pct = getValue<number>() * 100;
      return (
        <div className="flex items-center gap-2">
          <div className="h-2 w-16 rounded-full bg-muted">
            <div
              className="h-2 rounded-full bg-primary"
              style={{ width: `${pct}%` }}
            />
          </div>
          <span className="text-xs tabular-nums">{pct.toFixed(0)}%</span>
        </div>
      );
    },
  },
  { accessorKey: "scope", header: "Scope" },
  {
    accessorKey: "reason",
    header: "Reason",
    cell: ({ getValue }) => (
      <span className="line-clamp-2 max-w-xs text-xs text-muted-foreground">
        {getValue<string>() ?? "—"}
      </span>
    ),
  },
];

/** Pretty-print a details value */
function DetailValue({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span className="text-muted-foreground">—</span>;
  if (typeof value === "boolean") return <Badge variant="outline">{value ? "true" : "false"}</Badge>;
  if (typeof value === "number") return <span className="tabular-nums">{value}</span>;
  if (typeof value === "string") return <span>{value}</span>;
  if (Array.isArray(value)) {
    return (
      <div className="flex flex-wrap gap-1">
        {value.map((item, i) => (
          <Badge key={i} variant="outline" className="text-xs font-normal">
            {String(item)}
          </Badge>
        ))}
      </div>
    );
  }
  // Nested object — render as indented JSON
  return (
    <pre className="max-h-40 overflow-auto rounded bg-muted p-2 text-xs">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

/** Expanded row panel showing OHLCV + Indicators in separate sections */
function DetailsPanel({ row }: { row: Row<SignalResponse> }) {
  const { ohlcv, indicators } = row.original;
  const hasOhlcv = ohlcv && Object.keys(ohlcv).length > 0;
  const hasIndicators = indicators && Object.keys(indicators).length > 0;
  if (!hasOhlcv && !hasIndicators) return null;

  return (
    <TableRow className="bg-muted/40 hover:bg-muted/40">
      <TableCell colSpan={columns.length} className="p-0">
        <div className="px-10 py-3 space-y-4">
          {hasOhlcv && (
            <div>
              <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                OHLCV
              </p>
              <div className="grid gap-x-8 gap-y-2 sm:grid-cols-3 lg:grid-cols-5">
                {Object.entries(ohlcv).map(([key, value]) => (
                  <div key={key} className="min-w-0">
                    <p className="text-[11px] font-medium text-muted-foreground">
                      {key.replace(/_/g, " ")}
                    </p>
                    <div className="mt-0.5 text-sm break-words">
                      <DetailValue value={value} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
          {hasIndicators && (
            <div>
              <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Technical Indicators
              </p>
              <div className="grid gap-x-8 gap-y-2 sm:grid-cols-2 lg:grid-cols-3">
                {Object.entries(indicators).map(([key, value]) => (
                  <div key={key} className="min-w-0">
                    <p className="text-[11px] font-medium text-muted-foreground">
                      {key.replace(/_/g, " ")}
                    </p>
                    <div className="mt-0.5 text-sm break-words">
                      <DetailValue value={value} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </TableCell>
    </TableRow>
  );
}

/** Return local today as YYYY-MM-DD */
function todayStr() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function SignalsPage() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const [runDate, setRunDate] = useState(() => searchParams.get("date") || todayStr());
  const [symbolFilter, setSymbolFilter] = useState("");
  const [signalFilter, setSignalFilter] = useState<string>("all");
  const [sorting, setSorting] = useState<SortingState>([]);
  const [expanded, setExpanded] = useState<ExpandedState>({});

  const handleDateChange = useCallback((date: string) => {
    setRunDate(date);
    const params = new URLSearchParams(searchParams.toString());
    params.set("date", date);
    router.replace(`?${params.toString()}`, { scroll: false });
  }, [searchParams, router]);

  // Debounce symbol input so we don't fire on every keystroke
  const debouncedSymbol = useDebouncedValue(symbolFilter, 350);

  const signalParam =
    signalFilter && signalFilter !== "all"
      ? (signalFilter as "buy" | "sell" | "hold" | "rebalance")
      : undefined;

  const { data, isFetching } = useQuery({
    queryKey: ["signals", runDate, debouncedSymbol, signalFilter],
    queryFn: () =>
      signalsApi.query({
        run_date: runDate || undefined,
        symbol: debouncedSymbol.toUpperCase() || undefined,
        signal: signalParam,
        limit: 500,
      }),
    placeholderData: keepPreviousData,
  });

  const table = useReactTable({
    data: data?.signals ?? [],
    columns,
    state: { sorting, expanded },
    onSortingChange: setSorting,
    onExpandedChange: setExpanded,
    getRowCanExpand: (row) => {
      const hasOhlcv = !!row.original.ohlcv && Object.keys(row.original.ohlcv).length > 0;
      const hasIndicators = !!row.original.indicators && Object.keys(row.original.indicators).length > 0;
      return hasOhlcv || hasIndicators;
    },
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    getExpandedRowModel: getExpandedRowModel(),
    initialState: { pagination: { pageSize: 20 } },
  });

  return (
    <>
      <PageHeader
        title="Signals"
        description={`${data?.total ?? 0} signal(s)`}
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              signalsApi
                .exportCsv({
                  run_date: runDate || undefined,
                  symbol: debouncedSymbol.toUpperCase() || undefined,
                  signal: signalParam,
                })
                .catch(() => toast.error("Export failed"));
            }}
          >
            <Download className="mr-2 h-4 w-4" />
            Export CSV
          </Button>
        }
      />

      <div className="mb-4 flex flex-wrap gap-3">
        <DatePicker
          value={runDate}
          onChange={handleDateChange}
          placeholder="Select date"
        />
        <Input
          placeholder="Symbol"
          value={symbolFilter}
          onChange={(e) => setSymbolFilter(e.target.value)}
          className="w-32"
        />
        <Select value={signalFilter} onValueChange={setSignalFilter}>
          <SelectTrigger className="w-32">
            <SelectValue placeholder="Signal" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All</SelectItem>
            <SelectItem value="buy">Buy</SelectItem>
            <SelectItem value="sell">Sell</SelectItem>
            <SelectItem value="hold">Hold</SelectItem>
            <SelectItem value="rebalance">Rebalance</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-4">
        <div className="relative overflow-x-auto rounded-md border">
          {isFetching && (
            <div className="absolute inset-0 z-10 flex items-center justify-center bg-background/60 backdrop-blur-[1px]">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          )}
          <Table>
            <TableHeader>
              {table.getHeaderGroups().map((hg) => (
                <TableRow key={hg.id}>
                  {hg.headers.map((header) => (
                    <TableHead key={header.id}>
                      {header.isPlaceholder
                        ? null
                        : flexRender(
                            header.column.columnDef.header,
                            header.getContext(),
                          )}
                    </TableHead>
                  ))}
                </TableRow>
              ))}
            </TableHeader>
            <TableBody>
              {table.getRowModel().rows.length ? (
                table.getRowModel().rows.map((row) => (
                  <Fragment key={row.id}>
                    <TableRow
                      className={row.getIsExpanded() ? "border-b-0" : undefined}
                      onClick={() => {
                        if (row.getCanExpand()) row.toggleExpanded();
                      }}
                      style={{
                        cursor: row.getCanExpand() ? "pointer" : "default",
                      }}
                    >
                      {row.getVisibleCells().map((cell) => (
                        <TableCell key={cell.id}>
                          {flexRender(
                            cell.column.columnDef.cell,
                            cell.getContext(),
                          )}
                        </TableCell>
                      ))}
                    </TableRow>
                    {row.getIsExpanded() && <DetailsPanel row={row} />}
                  </Fragment>
                ))
              ) : (
                <TableRow>
                  <TableCell
                    colSpan={columns.length}
                    className="h-24 text-center"
                  >
                    No results.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
        <div className="flex items-center justify-between">
          <p className="text-sm text-muted-foreground">
            {table.getFilteredRowModel().rows.length} row(s)
          </p>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => table.previousPage()}
              disabled={!table.getCanPreviousPage()}
            >
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => table.nextPage()}
              disabled={!table.getCanNextPage()}
            >
              Next
            </Button>
          </div>
        </div>
      </div>
    </>
  );
}
