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
import { toast } from "sonner";
import { Plus, Trash2, Upload } from "lucide-react";
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

  const columnsWithActions: ColumnDef<WatchlistItemResponse>[] = [
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
                Remove {selected.size}
              </Button>
            )}

            <Dialog open={batchOpen} onOpenChange={setBatchOpen}>
              <DialogTrigger asChild>
                <Button variant="outline" size="sm">
                  <Upload className="mr-2 h-4 w-4" />
                  Batch Import
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Batch Import Symbols</DialogTitle>
                </DialogHeader>
                <p className="text-sm text-muted-foreground">
                  One symbol per line. Optional description after comma:
                  <br />
                  <code className="text-xs">AAPL, Apple Inc</code>
                </p>
                <Textarea
                  rows={8}
                  value={batchText}
                  onChange={(e) => setBatchText(e.target.value)}
                  placeholder={"AAPL, Apple Inc\nMSFT, Microsoft\nTSLA"}
                />
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
