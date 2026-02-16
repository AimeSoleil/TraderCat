"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PageHeader } from "@/components/page-header";
import { DataTable } from "@/components/data-table";
import { usersApi } from "@/lib/api-client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { Copy, MoreHorizontal, Plus, Trash2, UserCheck, UserX } from "lucide-react";
import { useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import type { UserResponse } from "@/lib/types";
import Link from "next/link";

export default function AdminUsersPage() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [newKeyDialog, setNewKeyDialog] = useState<string | null>(null);
  const [form, setForm] = useState({
    username: "",
    email: "",
    role: "user" as "admin" | "user",
    max_symbols: 50,
  });

  const { data, isLoading } = useQuery({
    queryKey: ["admin", "users"],
    queryFn: () => usersApi.list(),
  });

  const createMut = useMutation({
    mutationFn: () =>
      usersApi.create({
        username: form.username,
        email: form.email,
        role: form.role,
        max_symbols: form.max_symbols,
      }),
    onSuccess: (res) => {
      toast.success(`User "${form.username}" created`);
      qc.invalidateQueries({ queryKey: ["admin", "users"] });
      setOpen(false);
      setForm({ username: "", email: "", role: "user", max_symbols: 50 });
      if (res.api_key) {
        setNewKeyDialog(res.api_key);
      }
    },
    onError: () => toast.error("Failed to create user"),
  });

  const toggleActiveMut = useMutation({
    mutationFn: ({ id, is_active }: { id: string; is_active: boolean }) =>
      usersApi.update(id, { is_active }),
    onSuccess: () => {
      toast.success("User updated");
      qc.invalidateQueries({ queryKey: ["admin", "users"] });
    },
    onError: () => toast.error("Failed to update user"),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => usersApi.remove(id),
    onSuccess: () => {
      toast.success("User deleted");
      qc.invalidateQueries({ queryKey: ["admin", "users"] });
    },
    onError: () => toast.error("Failed to delete user"),
  });

  const columns: ColumnDef<UserResponse>[] = [
    {
      accessorKey: "username",
      header: "Username",
      cell: ({ row }) => (
        <Link
          href={`/admin/users/${row.original.id}`}
          className="font-medium text-primary hover:underline"
        >
          {row.original.username}
        </Link>
      ),
    },
    { accessorKey: "email", header: "Email" },
    {
      accessorKey: "role",
      header: "Role",
      cell: ({ getValue }) => (
        <Badge
          variant={getValue<string>() === "admin" ? "default" : "secondary"}
        >
          {getValue<string>()}
        </Badge>
      ),
    },
    {
      accessorKey: "is_active",
      header: "Active",
      cell: ({ getValue }) => (
        <Badge variant={getValue<boolean>() ? "default" : "destructive"}>
          {getValue<boolean>() ? "Yes" : "No"}
        </Badge>
      ),
    },
    { accessorKey: "max_symbols", header: "Max Symbols" },
    {
      accessorKey: "created_at",
      header: "Created",
      cell: ({ getValue }) =>
        new Date(getValue<string>()).toLocaleDateString(),
    },
    {
      id: "actions",
      cell: ({ row }) => {
        const u = row.original;
        return (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="h-8 w-8">
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem asChild>
                <Link href={`/admin/users/${u.id}`}>View Details</Link>
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() =>
                  toggleActiveMut.mutate({
                    id: u.id,
                    is_active: !u.is_active,
                  })
                }
              >
                {u.is_active ? (
                  <>
                    <UserX className="mr-2 h-4 w-4" />
                    Deactivate
                  </>
                ) : (
                  <>
                    <UserCheck className="mr-2 h-4 w-4" />
                    Activate
                  </>
                )}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                className="text-destructive"
                onClick={() => {
                  if (
                    confirm(
                      `Delete "${u.username}"? This cannot be undone.`
                    )
                  ) {
                    deleteMut.mutate(u.id);
                  }
                }}
              >
                <Trash2 className="mr-2 h-4 w-4" />
                Delete
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        );
      },
    },
  ];

  return (
    <>
      <PageHeader
        title="Users"
        description="Manage portal users and API keys"
        actions={
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button size="sm">
                <Plus className="mr-2 h-4 w-4" />
                New User
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Create User</DialogTitle>
              </DialogHeader>
              <div className="space-y-3">
                <div>
                  <Label>Username</Label>
                  <Input
                    value={form.username}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, username: e.target.value }))
                    }
                  />
                </div>
                <div>
                  <Label>Email</Label>
                  <Input
                    type="email"
                    value={form.email}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, email: e.target.value }))
                    }
                  />
                </div>
                <div>
                  <Label>Role</Label>
                  <Select
                    value={form.role}
                    onValueChange={(v) =>
                      setForm((f) => ({ ...f, role: v as "admin" | "user" }))
                    }
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="user">User</SelectItem>
                      <SelectItem value="admin">Admin</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label>Max Symbols</Label>
                  <Input
                    type="number"
                    value={form.max_symbols}
                    onChange={(e) =>
                      setForm((f) => ({
                        ...f,
                        max_symbols: Number(e.target.value),
                      }))
                    }
                  />
                </div>
                <Button
                  onClick={() => createMut.mutate()}
                  disabled={!form.username || !form.email}
                  className="w-full"
                >
                  Create
                </Button>
              </div>
            </DialogContent>
          </Dialog>
        }
      />

      <DataTable
        columns={columns}
        data={data ?? []}
        searchKey="username"
        searchPlaceholder="Search users…"
      />

      {/* New key reveal dialog (shown after user creation) */}
      <Dialog
        open={!!newKeyDialog}
        onOpenChange={(o) => {
          if (!o) setNewKeyDialog(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>API Key Created</DialogTitle>
            <DialogDescription>
              Copy the key below. It will not be shown again.
            </DialogDescription>
          </DialogHeader>
          <div className="rounded-md border bg-muted p-3">
            <code className="break-all text-sm">{newKeyDialog}</code>
          </div>
          <Button
            onClick={() => {
              navigator.clipboard.writeText(newKeyDialog ?? "");
              toast.success("Copied to clipboard");
            }}
          >
            <Copy className="mr-2 h-4 w-4" />
            Copy Key
          </Button>
        </DialogContent>
      </Dialog>
    </>
  );
}
