"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PageHeader } from "@/components/page-header";
import { DataTable } from "@/components/data-table";
import { adminLlmTokensApi } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import type { LlmTokenResponse } from "@/lib/types";

const columns: ColumnDef<LlmTokenResponse>[] = [
  { accessorKey: "provider_name", header: "Provider" },
  {
    accessorKey: "token_preview",
    header: "Token",
  },
  { accessorKey: "description", header: "Description" },
  {
    accessorKey: "is_active",
    header: "Active",
    cell: ({ getValue }) => (
      <Badge variant={getValue<boolean>() ? "default" : "secondary"}>
        {getValue<boolean>() ? "Yes" : "No"}
      </Badge>
    ),
  },
  {
    accessorKey: "created_at",
    header: "Created",
    cell: ({ getValue }) =>
      new Date(getValue<string>()).toLocaleDateString(),
  },
];

export default function AdminLlmTokensPage() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    provider_name: "",
    token: "",
    description: "",
    is_active: true,
  });

  const { data, isLoading } = useQuery({
    queryKey: ["admin", "llm-tokens"],
    queryFn: () => adminLlmTokensApi.list(),
  });

  const addMut = useMutation({
    mutationFn: () =>
      adminLlmTokensApi.add({
        provider_name: form.provider_name,
        token: form.token,
        description: form.description || undefined,
        is_active: form.is_active,
      }),
    onSuccess: () => {
      toast.success("Token added");
      qc.invalidateQueries({ queryKey: ["admin", "llm-tokens"] });
      setOpen(false);
      setForm({ provider_name: "", token: "", description: "", is_active: true });
    },
    onError: () => toast.error("Failed to add token"),
  });

  const toggleMut = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) =>
      adminLlmTokensApi.update(id, { is_active: active }),
    onSuccess: () => {
      toast.success("Token updated");
      qc.invalidateQueries({ queryKey: ["admin", "llm-tokens"] });
    },
    onError: () => toast.error("Update failed"),
  });

  const removeMut = useMutation({
    mutationFn: (id: string) => adminLlmTokensApi.remove(id),
    onSuccess: () => {
      toast.success("Token removed");
      qc.invalidateQueries({ queryKey: ["admin", "llm-tokens"] });
    },
    onError: () => toast.error("Remove failed"),
  });

  const columnsWithActions: ColumnDef<LlmTokenResponse>[] = [
    ...columns,
    {
      id: "actions",
      cell: ({ row }) => (
        <div className="flex items-center gap-1">
          <Switch
            checked={row.original.is_active}
            onCheckedChange={(v) =>
              toggleMut.mutate({ id: row.original.id, active: v })
            }
          />
          <Button
            variant="ghost"
            size="icon"
            onClick={() => removeMut.mutate(row.original.id)}
          >
            <Trash2 className="h-4 w-4 text-destructive" />
          </Button>
        </div>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title="LLM Tokens"
        description="Manage API tokens for AI providers"
        actions={
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button size="sm">
                <Plus className="mr-2 h-4 w-4" />
                Add Token
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Add LLM Token</DialogTitle>
              </DialogHeader>
              <div className="space-y-3">
                <div>
                  <Label>Provider</Label>
                  <Input
                    value={form.provider_name}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, provider_name: e.target.value }))
                    }
                    placeholder="github-models / openai / anthropic"
                  />
                </div>
                <div>
                  <Label>Token</Label>
                  <Input
                    type="password"
                    value={form.token}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, token: e.target.value }))
                    }
                    placeholder="sk-…"
                  />
                </div>
                <div>
                  <Label>Description (optional)</Label>
                  <Input
                    value={form.description}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, description: e.target.value }))
                    }
                  />
                </div>
                <div className="flex items-center justify-between">
                  <Label>Active</Label>
                  <Switch
                    checked={form.is_active}
                    onCheckedChange={(v) =>
                      setForm((f) => ({ ...f, is_active: v }))
                    }
                  />
                </div>
                <Button
                  onClick={() => addMut.mutate()}
                  disabled={!form.provider_name || !form.token}
                  className="w-full"
                >
                  Add Token
                </Button>
              </div>
            </DialogContent>
          </Dialog>
        }
      />

      <DataTable
        columns={columnsWithActions}
        data={data?.items ?? []}
        searchKey="provider_name"
        searchPlaceholder="Search tokens…"
      />
    </>
  );
}
