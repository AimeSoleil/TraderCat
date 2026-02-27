"use client";

import { useState } from "react";
import Link from "next/link";
import { useAuth } from "@/components/providers/auth-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { toast } from "sonner";
import { Cat, Eye, EyeOff, ArrowLeft } from "lucide-react";
import { ThemeToggle } from "@/components/theme-toggle";

export default function LoginPage() {
  const { login } = useAuth();
  const [token, setToken] = useState("");
  const [loading, setLoading] = useState(false);
  const [showKey, setShowKey] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token.trim()) return;
    setLoading(true);
    try {
      await login(token.trim());
      toast.success("Logged in successfully");
    } catch {
      toast.error("Invalid or inactive token");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center bg-background px-4">
      {/* Subtle background texture */}
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_50%_-20%,var(--muted)_0%,transparent_50%)]" />

      {/* Top nav */}
      <div className="absolute top-0 left-0 right-0 flex h-14 items-center justify-between px-4 sm:px-6">
        <Link
          href="/"
          className="flex items-center gap-2 text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" />
          Home
        </Link>
        <ThemeToggle />
      </div>

      <Card className="relative w-full max-w-sm border-border/50 shadow-lg shadow-black/[0.03]">
        <CardHeader className="pb-4 text-center">
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-foreground">
            <Cat className="h-6 w-6 text-background" />
          </div>
          <CardTitle className="text-xl font-semibold">Welcome back</CardTitle>
          <CardDescription className="text-sm">
            Enter your personal access token to access TraderCat
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="pat" className="text-sm font-medium">
                Personal Access Token
              </Label>
              <div className="relative">
                <Input
                  id="pat"
                  type={showKey ? "text" : "password"}
                  placeholder="tc_..."
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                  className="pr-10"
                  autoFocus
                  autoComplete="off"
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="absolute right-0 top-0 h-full w-10 text-muted-foreground hover:text-foreground"
                  onClick={() => setShowKey(!showKey)}
                  tabIndex={-1}
                  aria-label={showKey ? "Hide key" : "Show key"}
                >
                  {showKey ? (
                    <EyeOff className="h-4 w-4" />
                  ) : (
                    <Eye className="h-4 w-4" />
                  )}
                </Button>
              </div>
            </div>
            <Button
              type="submit"
              className="w-full"
              disabled={loading || !token.trim()}
            >
              {loading ? (
                <span className="flex items-center gap-2">
                  <span className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
                  Signing in…
                </span>
              ) : (
                "Sign in"
              )}
            </Button>
          </form>

          <p className="mt-6 text-center text-xs text-muted-foreground">
            Don&apos;t have a token? Contact your administrator.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
