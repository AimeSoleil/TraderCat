"use client";

import { useState } from "react";
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
import {
  Cat,
  Eye,
  EyeOff,
  BarChart3,
  Zap,
  Brain,
  TrendingUp,
} from "lucide-react";
import { ThemeToggle } from "@/components/theme-toggle";

const highlights = [
  {
    icon: Brain,
    title: "AI-Powered Analysis",
    desc: "Multiple AI analysts evaluate every symbol with quantitative strategies.",
  },
  {
    icon: BarChart3,
    title: "Multi-Strategy Signals",
    desc: "Technical indicators, candlestick patterns, and quant models combined.",
  },
  {
    icon: Zap,
    title: "Automated Pipeline",
    desc: "Daily scheduled runs — fetch data, compute signals, generate reports.",
  },
  {
    icon: TrendingUp,
    title: "Actionable Reports",
    desc: "Per-symbol reports and portfolio summaries with confidence scores.",
  },
];

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
    <div className="flex min-h-screen bg-background">
      {/* ── Left / Top: Branding Panel ── */}
      <div className="relative hidden w-[480px] shrink-0 flex-col justify-between overflow-hidden bg-foreground p-10 text-background md:flex lg:w-[520px]">
        {/* Decorative gradient orbs */}
        <div className="pointer-events-none absolute -top-24 -left-24 h-72 w-72 rounded-full bg-background/[0.04] blur-3xl" />
        <div className="pointer-events-none absolute -bottom-32 -right-32 h-96 w-96 rounded-full bg-background/[0.03] blur-3xl" />

        {/* Logo & tagline */}
        <div className="relative">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-background">
              <Cat className="h-5 w-5 text-foreground" />
            </div>
            <span className="text-xl font-semibold tracking-tight">TraderCat</span>
          </div>
          <h1 className="mt-10 text-3xl font-bold leading-tight tracking-tight lg:text-4xl">
            Smarter signals.
            <br />
            <span className="text-background/60">Better decisions.</span>
          </h1>
          <p className="mt-4 max-w-sm text-sm leading-relaxed text-background/50">
            Combine multiple AI analysts with quantitative strategies to deliver
            actionable trading signals every market day.
          </p>
        </div>

        {/* Feature highlights */}
        <div className="relative space-y-5">
          {highlights.map((h) => (
            <div key={h.title} className="flex items-start gap-3">
              <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-background/[0.08]">
                <h.icon className="h-4 w-4 text-background/70" />
              </div>
              <div>
                <p className="text-sm font-medium text-background/90">{h.title}</p>
                <p className="text-xs leading-relaxed text-background/40">{h.desc}</p>
              </div>
            </div>
          ))}
        </div>

        {/* Footer */}
        <p className="relative text-xs text-background/30">
          &copy; {new Date().getFullYear()} TraderCat &mdash; AI-powered trading
          signal analysis
        </p>
      </div>

      {/* ── Right / Bottom: Login Form ── */}
      <div className="relative flex flex-1 flex-col items-center justify-center px-4 py-12">
        {/* Subtle radial bg */}
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_50%_-20%,var(--muted)_0%,transparent_50%)]" />

        {/* Theme toggle */}
        <div className="absolute right-4 top-4 sm:right-6 sm:top-6">
          <ThemeToggle />
        </div>

        {/* Mobile-only branding */}
        <div className="relative mb-8 flex flex-col items-center md:hidden">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-foreground">
            <Cat className="h-6 w-6 text-background" />
          </div>
          <h2 className="mt-4 text-xl font-bold tracking-tight">TraderCat</h2>
          <p className="mt-1 text-center text-sm text-muted-foreground">
            AI-powered trading signal analysis
          </p>
        </div>

        <Card className="relative w-full max-w-sm border-border/50 shadow-lg shadow-black/[0.03]">
          <CardHeader className="pb-4 text-center">
            <div className="mx-auto mb-3 hidden h-12 w-12 items-center justify-center rounded-xl bg-foreground md:flex">
              <Cat className="h-6 w-6 text-background" />
            </div>
            <CardTitle className="text-xl font-semibold">Welcome back</CardTitle>
            <CardDescription className="text-sm">
              Enter your personal access token to continue
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
    </div>
  );
}
