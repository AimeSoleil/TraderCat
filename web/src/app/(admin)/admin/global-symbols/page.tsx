"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PageHeader } from "@/components/page-header";
import { DataTable } from "@/components/data-table";
import { adminGlobalSymbolsApi } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { Download, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import type { GlobalSymbolResponse } from "@/lib/types";

const columns: ColumnDef<GlobalSymbolResponse>[] = [
  { accessorKey: "symbol", header: "Symbol" },
  {
    accessorKey: "symbol_type",
    header: "Type",
    cell: ({ getValue }) => (
      <Badge variant="outline">{getValue<string>()}</Badge>
    ),
  },
  { accessorKey: "description", header: "Description" },
  {
    accessorKey: "added_at",
    header: "Added",
    cell: ({ getValue }) =>
      new Date(getValue<string>()).toLocaleDateString(),
  },
];

export default function AdminGlobalSymbolsPage() {
  const qc = useQueryClient();
  const [typeFilter, setTypeFilter] = useState<string>("all");
  const [addOpen, setAddOpen] = useState(false);
  const [addType, setAddType] = useState<"macro" | "sector">("macro");
  const [batchText, setBatchText] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const { data, isLoading } = useQuery({
    queryKey: ["admin", "global-symbols", typeFilter],
    queryFn: () =>
      adminGlobalSymbolsApi.list(
        typeFilter !== "all" ? (typeFilter as "macro" | "sector") : undefined,
      ),
  });

  const addMut = useMutation({
    mutationFn: () => {
      const symbols = batchText
        .split("\n")
        .map((l) => l.trim())
        .filter(Boolean)
        .map((l) => {
          const [sym, ...rest] = l.split(",");
          return {
            symbol: sym.trim().toUpperCase(),
            symbol_type: addType,
            description: rest.join(",").trim() || undefined,
          };
        });
      return adminGlobalSymbolsApi.batchAdd(symbols);
    },
    onSuccess: () => {
      toast.success("Symbols added");
      qc.invalidateQueries({ queryKey: ["admin", "global-symbols"] });
      setBatchText("");
      setAddOpen(false);
    },
    onError: () => toast.error("Failed to add symbols"),
  });

  const removeMut = useMutation({
    mutationFn: (sym: string) => adminGlobalSymbolsApi.batchRemove([sym]),
    onSuccess: () => {
      toast.success("Symbol removed");
      qc.invalidateQueries({ queryKey: ["admin", "global-symbols"] });
    },
    onError: () => toast.error("Failed to remove"),
  });

  const batchRemoveMut = useMutation({
    mutationFn: () => adminGlobalSymbolsApi.batchRemove(Array.from(selected)),
    onSuccess: () => {
      toast.success(`Removed ${selected.size} symbols`);
      qc.invalidateQueries({ queryKey: ["admin", "global-symbols"] });
      setSelected(new Set());
    },
    onError: () => toast.error("Batch remove failed"),
  });

  const toggleSelect = (sym: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(sym)) next.delete(sym);
      else next.add(sym);
      return next;
    });
  };

  const toggleSelectAll = () => {
    const allSymbols = (data?.items ?? []).map((i) => i.symbol);
    if (selected.size === allSymbols.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(allSymbols));
    }
  };

  const columnsWithActions: ColumnDef<GlobalSymbolResponse>[] = [
    {
      id: "select",
      header: () => (
        <Checkbox
          checked={
            (data?.items?.length ?? 0) > 0 && selected.size === (data?.items?.length ?? 0)
          }
          onCheckedChange={toggleSelectAll}
          aria-label="Select all"
        />
      ),
      cell: ({ row }) => (
        <Checkbox
          checked={selected.has(row.original.symbol)}
          onCheckedChange={() => toggleSelect(row.original.symbol)}
          aria-label={`Select ${row.original.symbol}`}
        />
      ),
      enableSorting: false,
    },
    ...columns,
    {
      id: "actions",
      cell: ({ row }) => (
        <Button
          variant="ghost"
          size="icon"
          onClick={() => removeMut.mutate(row.original.symbol)}
        >
          <Trash2 className="h-4 w-4 text-destructive" />
        </Button>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title="Global Symbols"
        description="Manage macro & sector symbols for global analysis"
        actions={
          <div className="flex gap-2">
            {selected.size > 0 && (
              <Button
                variant="destructive"
                size="sm"
                onClick={() => batchRemoveMut.mutate()}
              >
                <Trash2 className="mr-2 h-4 w-4" />
                Remove {selected.size}
              </Button>
            )}

            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                const filterType = typeFilter !== "all" ? (typeFilter as "macro" | "sector") : undefined;
                adminGlobalSymbolsApi.exportCsv(filterType).catch(() => toast.error("Export failed"));
              }}
            >
              <Download className="mr-2 h-4 w-4" />
              Export CSV
            </Button>

            <Dialog open={addOpen} onOpenChange={setAddOpen}>
              <DialogTrigger asChild>
                <Button size="sm">
                  <Plus className="mr-2 h-4 w-4" />
                  Add Symbols
                </Button>
              </DialogTrigger>
              <DialogContent className="max-h-[85vh] flex flex-col">
                <DialogHeader>
                  <DialogTitle>Batch Add Global Symbols</DialogTitle>
                </DialogHeader>
                <div className="flex items-center gap-2">
                  <span className="text-sm text-muted-foreground">Type:</span>
                  {(["macro", "sector"] as const).map((t) => (
                    <Button
                      key={t}
                      variant={addType === t ? "default" : "outline"}
                      size="sm"
                      onClick={() => setAddType(t)}
                      className="capitalize"
                    >
                      {t}
                    </Button>
                  ))}
                </div>
                <p className="text-sm text-muted-foreground">
                  One per line. Optional description after comma.
                </p>
                <ScrollArea className="flex-1 min-h-0">
                  <Textarea
                    rows={12}
                    className="min-h-[200px] max-h-[50vh] resize-y"
                    value={batchText}
                    onChange={(e) => setBatchText(e.target.value)}
                    placeholder={"SPY, S&P 500\nQQQ, Nasdaq 100\nDIA"}
                  />
                </ScrollArea>
                <Button
                  onClick={() => addMut.mutate()}
                  disabled={!batchText.trim()}
                >
                  Add
                </Button>
              </DialogContent>
            </Dialog>
          </div>
        }
      />

      <div className="mb-4 flex items-center gap-2">
        {(["all", "macro", "sector"] as const).map((t) => (
          <Button
            key={t}
            variant={typeFilter === t ? "default" : "outline"}
            size="sm"
            onClick={() => setTypeFilter(t)}
            className="capitalize"
          >
            {t === "all" ? "All Types" : t}
          </Button>
        ))}
      </div>

      <DataTable
        columns={columnsWithActions}
        data={data?.items ?? []}
        searchKey="symbol"
        searchPlaceholder="Search global symbols…"
      />
    </>
  );
}
