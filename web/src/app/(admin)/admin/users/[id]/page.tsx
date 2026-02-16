"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import { usersApi } from "@/lib/api-client";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
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
import { Skeleton } from "@/components/ui/skeleton";
import { toast } from "sonner";
import { ArrowLeft, Copy, Key, Plus, Power, Trash2 } from "lucide-react";
import { useState } from "react";
import type { ApiKeyResponse, UserUpdate, UserWithKeys } from "@/lib/types";

export default function AdminUserDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const qc = useQueryClient();

  const [editOpen, setEditOpen] = useState(false);
  const [addKeyOpen, setAddKeyOpen] = useState(false);
  const [newKeyName, setNewKeyName] = useState("default");
  const [newKeyDialog, setNewKeyDialog] = useState<string | null>(null);

  const { data: user, isLoading } = useQuery({
    queryKey: ["admin", "users", id],
    queryFn: () => usersApi.get(id),
    enabled: !!id,
  });

  // ── Edit form state ──
  const [editForm, setEditForm] = useState<UserUpdate>({});

  const openEdit = () => {
    if (user) {
      setEditForm({
        email: user.email,
        role: user.role,
        is_active: user.is_active,
        max_symbols: user.max_symbols,
        preferred_persona: user.preferred_persona,
        preferred_lang: user.preferred_lang,
      });
    }
    setEditOpen(true);
  };

  // ── Mutations ──
  const updateMut = useMutation({
    mutationFn: () => usersApi.update(id, editForm),
    onSuccess: () => {
      toast.success("User updated");
      qc.invalidateQueries({ queryKey: ["admin", "users", id] });
      qc.invalidateQueries({ queryKey: ["admin", "users"] });
      setEditOpen(false);
    },
    onError: () => toast.error("Failed to update user"),
  });

  const deleteMut = useMutation({
    mutationFn: () => usersApi.remove(id),
    onSuccess: () => {
      toast.success("User deleted");
      router.push("/admin/users");
    },
    onError: () => toast.error("Failed to delete user"),
  });

  const addKeyMut = useMutation({
    mutationFn: () => usersApi.createApiKey(id, newKeyName),
    onSuccess: (res) => {
      setNewKeyDialog(res.api_key);
      qc.invalidateQueries({ queryKey: ["admin", "users", id] });
      setAddKeyOpen(false);
      setNewKeyName("default");
    },
    onError: () => toast.error("Failed to create API key"),
  });

  const toggleKeyMut = useMutation({
    mutationFn: (keyId: string) => usersApi.toggleApiKey(id, keyId),
    onSuccess: () => {
      toast.success("API key toggled");
      qc.invalidateQueries({ queryKey: ["admin", "users", id] });
    },
    onError: () => toast.error("Failed to toggle key"),
  });

  const removeKeyMut = useMutation({
    mutationFn: (keyId: string) => usersApi.removeApiKey(id, keyId),
    onSuccess: () => {
      toast.success("API key deleted");
      qc.invalidateQueries({ queryKey: ["admin", "users", id] });
    },
    onError: () => toast.error("Failed to delete key"),
  });

  if (isLoading) return <Skeleton className="h-96" />;
  if (!user) return <p>User not found.</p>;

  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        className="mb-4"
        onClick={() => router.push("/admin/users")}
      >
        <ArrowLeft className="mr-2 h-4 w-4" />
        Back to Users
      </Button>

      <PageHeader
        title={user.username}
        description={user.email}
        actions={
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={openEdit}>
              Edit
            </Button>
            <Button
              variant="destructive"
              size="sm"
              onClick={() => {
                if (
                  confirm(
                    `Delete "${user.username}"? This cannot be undone.`
                  )
                ) {
                  deleteMut.mutate();
                }
              }}
            >
              <Trash2 className="mr-2 h-4 w-4" />
              Delete
            </Button>
          </div>
        }
      />

      {/* Info cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <InfoCard label="Role">
          <Badge variant={user.role === "admin" ? "default" : "secondary"}>
            {user.role}
          </Badge>
        </InfoCard>
        <InfoCard label="Status">
          <Badge variant={user.is_active ? "default" : "destructive"}>
            {user.is_active ? "Active" : "Inactive"}
          </Badge>
        </InfoCard>
        <InfoCard label="Max Symbols">{user.max_symbols}</InfoCard>
        <InfoCard label="Created">
          {new Date(user.created_at).toLocaleDateString()}
        </InfoCard>
      </div>

      {/* API Keys section */}
      <div className="mt-6">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="flex items-center gap-2 text-base">
              <Key className="h-4 w-4" />
              API Keys ({user.api_keys.length})
            </CardTitle>
            <Dialog open={addKeyOpen} onOpenChange={setAddKeyOpen}>
              <DialogTrigger asChild>
                <Button size="sm" variant="outline">
                  <Plus className="mr-2 h-4 w-4" />
                  New Key
                </Button>
              </DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Generate API Key</DialogTitle>
                </DialogHeader>
                <div className="space-y-3">
                  <div>
                    <Label>Key Name</Label>
                    <Input
                      value={newKeyName}
                      onChange={(e) => setNewKeyName(e.target.value)}
                      placeholder="default"
                    />
                  </div>
                  <Button
                    onClick={() => addKeyMut.mutate()}
                    className="w-full"
                  >
                    Generate
                  </Button>
                </div>
              </DialogContent>
            </Dialog>
          </CardHeader>
          <CardContent className="space-y-3">
            {user.api_keys.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No API keys. Create one to allow this user to authenticate.
              </p>
            ) : (
              user.api_keys.map((k) => (
                <ApiKeyRow
                  key={k.id}
                  apiKey={k}
                  onToggle={() => toggleKeyMut.mutate(k.id)}
                  onRemove={() => {
                    if (confirm("Delete this API key?")) {
                      removeKeyMut.mutate(k.id);
                    }
                  }}
                />
              ))
            )}
          </CardContent>
        </Card>
      </div>

      {/* New key reveal dialog */}
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

      {/* Edit user dialog */}
      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit User</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label>Email</Label>
              <Input
                value={editForm.email ?? ""}
                onChange={(e) =>
                  setEditForm((f) => ({ ...f, email: e.target.value }))
                }
              />
            </div>
            <div>
              <Label>Role</Label>
              <Select
                value={editForm.role ?? "user"}
                onValueChange={(v) =>
                  setEditForm((f) => ({
                    ...f,
                    role: v as "admin" | "user",
                  }))
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
            <div className="flex items-center justify-between">
              <Label>Active</Label>
              <Switch
                checked={editForm.is_active ?? true}
                onCheckedChange={(v) =>
                  setEditForm((f) => ({ ...f, is_active: v }))
                }
              />
            </div>
            <div>
              <Label>Max Symbols</Label>
              <Input
                type="number"
                value={editForm.max_symbols ?? 50}
                onChange={(e) =>
                  setEditForm((f) => ({
                    ...f,
                    max_symbols: Number(e.target.value),
                  }))
                }
              />
            </div>
            <div>
              <Label>Preferred Persona</Label>
              <Input
                value={editForm.preferred_persona ?? ""}
                onChange={(e) =>
                  setEditForm((f) => ({
                    ...f,
                    preferred_persona: e.target.value || null,
                  }))
                }
                placeholder="e.g. wyckoff, livermore"
              />
            </div>
            <div>
              <Label>Preferred Language</Label>
              <Input
                value={editForm.preferred_lang ?? ""}
                onChange={(e) =>
                  setEditForm((f) => ({
                    ...f,
                    preferred_lang: e.target.value || null,
                  }))
                }
                placeholder="e.g. en, zh"
              />
            </div>
            <Button onClick={() => updateMut.mutate()} className="w-full">
              Save Changes
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}

function InfoCard({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-xs text-muted-foreground">{label}</p>
        <div className="mt-1 text-sm font-medium">{children}</div>
      </CardContent>
    </Card>
  );
}

function ApiKeyRow({
  apiKey,
  onToggle,
  onRemove,
}: {
  apiKey: ApiKeyResponse;
  onToggle: () => void;
  onRemove: () => void;
}) {
  return (
    <div className="flex items-center justify-between rounded-md border p-3">
      <div>
        <div className="flex items-center gap-2">
          <code className="text-sm">{apiKey.key_prefix}…</code>
          <Badge variant="outline" className="text-[10px]">
            {apiKey.name}
          </Badge>
          <Badge
            variant={apiKey.is_active ? "default" : "destructive"}
            className="text-[10px]"
          >
            {apiKey.is_active ? "Active" : "Inactive"}
          </Badge>
        </div>
        <p className="text-xs text-muted-foreground">
          Created: {new Date(apiKey.created_at).toLocaleDateString()}
          {apiKey.last_used_at &&
            ` · Last used: ${new Date(
              apiKey.last_used_at
            ).toLocaleDateString()}`}
        </p>
      </div>
      <div className="flex items-center gap-1">
        <Button
          variant="ghost"
          size="icon"
          title="Toggle active"
          onClick={onToggle}
        >
          <Power className="h-4 w-4" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          title="Delete key"
          onClick={onRemove}
        >
          <Trash2 className="h-4 w-4 text-destructive" />
        </Button>
      </div>
    </div>
  );
}
