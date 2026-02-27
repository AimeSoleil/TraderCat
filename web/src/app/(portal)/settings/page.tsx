"use client";

import { useAuth } from "@/components/providers/auth-provider";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export default function SettingsPage() {
  const { user } = useAuth();

  if (!user) return null;

  return (
    <>
      <PageHeader title="Settings" description="Your account information" />

      <Card className="max-w-lg">
        <CardHeader>
          <CardTitle className="text-base">Profile</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Row label="Username" value={user.username} />
          <Row label="Email" value={user.email} />
          <Row
            label="Role"
            value={
              <Badge variant={user.role === "admin" ? "default" : "secondary"}>
                {user.role}
              </Badge>
            }
          />
        </CardContent>
      </Card>

      <p className="mt-4 text-sm text-muted-foreground">
        Contact your admin to update account settings or generate new access tokens.
      </p>
    </>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  );
}
