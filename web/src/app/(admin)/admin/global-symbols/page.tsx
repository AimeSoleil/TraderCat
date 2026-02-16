"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PageHeader } from "@/components/page-header";
import { DataTable } from "@/components/data-table";
import { adminGlobalSymbolsApi } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { Plus, Trash2 } from "lucide-react";
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

  const columnsWithActions: ColumnDef<GlobalSymbolResponse>[] = [
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
          <Dialog open={addOpen} onOpenChange={setAddOpen}>
            <DialogTrigger asChild>
              <Button size="sm">
                <Plus className="mr-2 h-4 w-4" />
                Add Symbols
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Batch Add Global Symbols</DialogTitle>
              </DialogHeader>
              <Select
                value={addType}
                onValueChange={(v) => setAddType(v as "macro" | "sector")}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="macro">Macro</SelectItem>
                  <SelectItem value="sector">Sector</SelectItem>
                </SelectContent>
              </Select>
              <p className="text-sm text-muted-foreground">
                One per line. Optional description after comma.
              </p>
              <Textarea
                rows={8}
                value={batchText}
                onChange={(e) => setBatchText(e.target.value)}
                placeholder={"SPY, S&P 500\nQQQ, Nasdaq 100\nDIA"}
              />
              <Button
                onClick={() => addMut.mutate()}
                disabled={!batchText.trim()}
              >
                Add
              </Button>
            </DialogContent>
          </Dialog>
        }
      />

      <div className="mb-4">
        <Select value={typeFilter} onValueChange={setTypeFilter}>
          <SelectTrigger className="w-36">
            <SelectValue placeholder="Type" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All</SelectItem>
            <SelectItem value="macro">Macro</SelectItem>
            <SelectItem value="sector">Sector</SelectItem>
          </SelectContent>
        </Select>
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
