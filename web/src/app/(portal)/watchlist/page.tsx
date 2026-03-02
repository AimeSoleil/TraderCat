"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PageHeader } from "@/components/page-header";
import { DataTable } from "@/components/data-table";
import { watchlistApi } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import { ScrollArea } from "@/components/ui/scroll-area";
import { toast } from "sonner";
import { Download, Plus, Trash2, Upload } from "lucide-react";
import { useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import type { WatchlistItemResponse } from "@/lib/types";

const columns: ColumnDef<WatchlistItemResponse>[] = [
  { accessorKey: "symbol", header: "Symbol" },
  { accessorKey: "description", header: "Description" },
  {
    accessorKey: "added_at",
    header: "Added",
    cell: ({ getValue }) =>
      new Date(getValue<string>()).toLocaleDateString(),
  },
];

export default function WatchlistPage() {
  const qc = useQueryClient();
  const [addOpen, setAddOpen] = useState(false);
  const [batchOpen, setBatchOpen] = useState(false);
  const [symbol, setSymbol] = useState("");
  const [desc, setDesc] = useState("");
  const [batchText, setBatchText] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const { data, isLoading } = useQuery({
    queryKey: ["watchlist"],
    queryFn: () => watchlistApi.list(),
  });

  const addMut = useMutation({
    mutationFn: () => watchlistApi.add({ symbol: symbol.toUpperCase(), description: desc || undefined }),
    onSuccess: () => {
      toast.success(`Added ${symbol.toUpperCase()}`);
      qc.invalidateQueries({ queryKey: ["watchlist"] });
      setSymbol("");
      setDesc("");
      setAddOpen(false);
    },
    onError: () => toast.error("Failed to add symbol"),
  });

  const batchMut = useMutation({
    mutationFn: () => {
      const items = batchText
        .split("\n")
        .map((l) => l.trim())
        .filter(Boolean)
        .map((l) => {
          const [sym, ...rest] = l.split(",");
          return { symbol: sym.trim().toUpperCase(), description: rest.join(",").trim() || undefined };
        });
      return watchlistApi.batchImport(items);
    },
    onSuccess: (res) => {
      toast.success(`Created ${res.created}, skipped ${res.skipped}`);
      qc.invalidateQueries({ queryKey: ["watchlist"] });
      setBatchText("");
      setBatchOpen(false);
    },
    onError: () => toast.error("Batch import failed"),
  });

  const removeMut = useMutation({
    mutationFn: (sym: string) => watchlistApi.remove(sym),
    onSuccess: (_, sym) => {
      toast.success(`Removed ${sym}`);
      qc.invalidateQueries({ queryKey: ["watchlist"] });
    },
    onError: () => toast.error("Failed to remove symbol"),
  });

  const batchRemoveMut = useMutation({
    mutationFn: () => watchlistApi.batchRemove(Array.from(selected)),
    onSuccess: (res) => {
      toast.success(`Removed ${res.removed} symbols`);
      qc.invalidateQueries({ queryKey: ["watchlist"] });
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

  const columnsWithActions: ColumnDef<WatchlistItemResponse>[] = [
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
        title="Watchlist"
        description={`${data?.total ?? 0} symbols`}
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
                watchlistApi.exportCsv().catch(() => toast.error("Export failed"));
              }}
            >
              <Download className="mr-2 h-4 w-4" />
              Export CSV
            </Button>

            <Dialog open={batchOpen} onOpenChange={setBatchOpen}>
              <DialogTrigger asChild>
                <Button variant="outline" size="sm">
                  <Upload className="mr-2 h-4 w-4" />
                  Batch Import
                </Button>
              </DialogTrigger>
              <DialogContent className="max-h-[85vh] flex flex-col">
                <DialogHeader>
                  <DialogTitle>Batch Import Symbols</DialogTitle>
                </DialogHeader>
                <p className="text-sm text-muted-foreground">
                  One symbol per line. Optional description after comma:
                  <br />
                  <code className="text-xs">AAPL, Apple Inc</code>
                </p>
                <ScrollArea className="flex-1 min-h-0">
                  <Textarea
                    rows={12}
                    className="min-h-[200px] max-h-[50vh] resize-y"
                    value={batchText}
                    onChange={(e) => setBatchText(e.target.value)}
                    placeholder={"AAPL, Apple Inc\nMSFT, Microsoft\nTSLA"}
                  />
                </ScrollArea>
                <Button onClick={() => batchMut.mutate()} disabled={!batchText.trim()}>
                  Import
                </Button>
              </DialogContent>
            </Dialog>

            <Dialog open={addOpen} onOpenChange={setAddOpen}>
              <DialogTrigger asChild>
                <Button size="sm">
                  <Plus className="mr-2 h-4 w-4" />
                  Add Symbol
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Add Symbol</DialogTitle>
                </DialogHeader>
                <div className="space-y-3">
                  <div>
                    <Label>Symbol</Label>
                    <Input
                      value={symbol}
                      onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                      placeholder="AAPL"
                    />
                  </div>
                  <div>
                    <Label>Description (optional)</Label>
                    <Input
                      value={desc}
                      onChange={(e) => setDesc(e.target.value)}
                      placeholder="Apple Inc"
                    />
                  </div>
                  <Button
                    onClick={() => addMut.mutate()}
                    disabled={!symbol.trim()}
                    className="w-full"
                  >
                    Add
                  </Button>
                </div>
              </DialogContent>
            </Dialog>
          </div>
        }
      />

      <DataTable
        columns={columnsWithActions}
        data={data?.items ?? []}
        searchKey="symbol"
        searchPlaceholder="Search symbols…"
      />
    </>
  );
}
