"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PageHeader } from "@/components/page-header";
import { adminStrategiesApi } from "@/lib/api-client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import { ChevronRight, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import type { StrategyResponse, StrategyWithPresets, StrategyPresetResponse } from "@/lib/types";

export default function AdminStrategiesPage() {
  const qc = useQueryClient();
  const [selected, setSelected] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["admin", "strategies"],
    queryFn: () => adminStrategiesApi.list(),
  });

  const detail = useQuery({
    queryKey: ["admin", "strategies", selected],
    queryFn: () => adminStrategiesApi.get(selected!),
    enabled: !!selected,
  });

  return (
    <>
      <PageHeader
        title="Strategies"
        description="Manage analysis strategies and presets"
      />

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Strategy list */}
        <div className="space-y-2 lg:col-span-1">
          {isLoading ? (
            <div className="space-y-2">
              {[1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-16" />
              ))}
            </div>
          ) : (
            data?.strategies.map((s) => (
              <StrategyCard
                key={s.id}
                strategy={s}
                active={selected === s.name}
                onClick={() => setSelected(s.name)}
              />
            ))
          )}
        </div>

        {/* Detail panel */}
        <div className="lg:col-span-2">
          {selected && detail.data ? (
            <StrategyDetail
              strategy={detail.data}
              onUpdate={() => {
                qc.invalidateQueries({ queryKey: ["admin", "strategies"] });
                qc.invalidateQueries({
                  queryKey: ["admin", "strategies", selected],
                });
              }}
            />
          ) : (
            <Card>
              <CardContent className="flex h-64 items-center justify-center text-muted-foreground">
                Select a strategy to view details
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}

function StrategyCard({
  strategy,
  active,
  onClick,
}: {
  strategy: StrategyResponse;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <Card
      className={`cursor-pointer transition-colors ${active ? "border-primary" : "hover:bg-muted/50"}`}
      onClick={onClick}
    >
      <CardContent className="flex items-center justify-between p-4">
        <div>
          <p className="font-medium">{strategy.name}</p>
          <p className="text-xs text-muted-foreground">
            {strategy.strategy_class}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant={strategy.is_active ? "default" : "secondary"}>
            {strategy.is_active ? "Active" : "Inactive"}
          </Badge>
          <ChevronRight className="h-4 w-4 text-muted-foreground" />
        </div>
      </CardContent>
    </Card>
  );
}

function StrategyDetail({
  strategy,
  onUpdate,
}: {
  strategy: StrategyWithPresets;
  onUpdate: () => void;
}) {
  const [addOpen, setAddOpen] = useState(false);
  const [presetName, setPresetName] = useState("");
  const [presetDesc, setPresetDesc] = useState("");
  const [presetParams, setPresetParams] = useState("{}");

  const activateMut = useMutation({
    mutationFn: (presetId: string | null) =>
      adminStrategiesApi.updateActivePreset(strategy.name, presetId),
    onSuccess: () => {
      toast.success("Active preset updated");
      onUpdate();
    },
    onError: () => toast.error("Failed to update"),
  });

  const addMut = useMutation({
    mutationFn: () =>
      adminStrategiesApi.addPreset(strategy.name, {
        name: presetName,
        description: presetDesc || undefined,
        parameters: JSON.parse(presetParams),
      }),
    onSuccess: () => {
      toast.success("Preset added");
      setAddOpen(false);
      setPresetName("");
      setPresetDesc("");
      setPresetParams("{}");
      onUpdate();
    },
    onError: () => toast.error("Failed to add preset"),
  });

  const removeMut = useMutation({
    mutationFn: (name: string) =>
      adminStrategiesApi.removePreset(strategy.name, name),
    onSuccess: () => {
      toast.success("Preset removed");
      onUpdate();
    },
    onError: () => toast.error("Failed to remove"),
  });

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between text-base">
            {strategy.name}
            <Badge variant={strategy.is_active ? "default" : "secondary"}>
              {strategy.is_active ? "Active" : "Inactive"}
            </Badge>
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <p>
            <span className="text-muted-foreground">Class:</span>{" "}
            {strategy.strategy_class}
          </p>
          <p>
            <span className="text-muted-foreground">Default preset:</span>{" "}
            {strategy.default_preset_name}
          </p>
          {strategy.description && (
            <p className="text-muted-foreground">{strategy.description}</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-base">
            Presets ({strategy.presets.length})
          </CardTitle>
          <Dialog open={addOpen} onOpenChange={setAddOpen}>
            <DialogTrigger asChild>
              <Button size="sm" variant="outline">
                <Plus className="mr-2 h-4 w-4" />
                Add Preset
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>New Preset</DialogTitle>
              </DialogHeader>
              <div className="space-y-3">
                <div>
                  <Label>Name</Label>
                  <Input
                    value={presetName}
                    onChange={(e) => setPresetName(e.target.value)}
                  />
                </div>
                <div>
                  <Label>Description</Label>
                  <Input
                    value={presetDesc}
                    onChange={(e) => setPresetDesc(e.target.value)}
                  />
                </div>
                <div>
                  <Label>Parameters (JSON)</Label>
                  <Textarea
                    rows={6}
                    value={presetParams}
                    onChange={(e) => setPresetParams(e.target.value)}
                    className="font-mono text-xs"
                  />
                </div>
                <Button
                  onClick={() => addMut.mutate()}
                  disabled={!presetName}
                  className="w-full"
                >
                  Add
                </Button>
              </div>
            </DialogContent>
          </Dialog>
        </CardHeader>
        <CardContent className="space-y-3">
          {strategy.presets.map((p) => (
            <PresetRow
              key={p.id}
              preset={p}
              isActive={p.id === strategy.active_preset_id}
              onActivate={() => activateMut.mutate(p.id)}
              onRemove={() => removeMut.mutate(p.name)}
            />
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

function PresetRow({
  preset,
  isActive,
  onActivate,
  onRemove,
}: {
  preset: StrategyPresetResponse;
  isActive: boolean;
  onActivate: () => void;
  onRemove: () => void;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="rounded-md border p-3">
      <div className="flex items-center justify-between">
        <div
          className="flex-1 cursor-pointer"
          onClick={() => setExpanded(!expanded)}
        >
          <div className="flex items-center gap-2">
            <p className="text-sm font-medium">{preset.name}</p>
            {isActive && <Badge className="text-[10px]">Active</Badge>}
          </div>
          {preset.description && (
            <p className="text-xs text-muted-foreground">
              {preset.description}
            </p>
          )}
        </div>
        <div className="flex items-center gap-1">
          {!isActive && (
            <Button variant="outline" size="sm" onClick={onActivate}>
              Activate
            </Button>
          )}
          <Button variant="ghost" size="icon" onClick={onRemove}>
            <Trash2 className="h-4 w-4 text-destructive" />
          </Button>
        </div>
      </div>
      {expanded && (
        <pre className="mt-2 max-h-48 overflow-auto rounded bg-muted p-2 text-xs">
          {JSON.stringify(preset.parameters, null, 2)}
        </pre>
      )}
    </div>
  );
}
