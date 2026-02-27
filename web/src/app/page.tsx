import Link from "next/link";
import {
  Cat,
  BarChart3,
  Brain,
  Shield,
  Zap,
  ArrowRight,
  TrendingUp,
  LineChart,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/theme-toggle";

const features = [
  {
    icon: Brain,
    title: "AI-Powered Analysis",
    description:
      "Multiple AI personas — Wyckoff, Livermore, Simons — analyze every symbol from distinct perspectives.",
  },
  {
    icon: BarChart3,
    title: "Multi-Strategy Signals",
    description:
      "Combine technical indicators, candlestick patterns, and quantitative models into actionable buy/sell/hold signals.",
  },
  {
    icon: Zap,
    title: "Automated Pipeline",
    description:
      "Daily scheduled runs fetch market data, compute signals, and generate reports — fully hands-off.",
  },
  {
    icon: Shield,
    title: "Role-Based Access",
    description:
      "Admin controls for users, access tokens, LLM tokens, and strategies. User-scoped watchlists and reports.",
  },
  {
    icon: TrendingUp,
    title: "Comprehensive Reports",
    description:
      "Detailed markdown reports per symbol and portfolio-wide summaries with confidence scores.",
  },
  {
    icon: LineChart,
    title: "Real-Time Dashboard",
    description:
      "At-a-glance overview of watchlist, latest signals, and report activity — everything in one place.",
  },
];

export default function LandingPage() {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      {/* ── Header ── */}
      <header className="sticky top-0 z-50 border-b border-border/50 bg-background/80 backdrop-blur-lg">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4 sm:px-6">
          <Link href="/" className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-foreground">
              <Cat className="h-4.5 w-4.5 text-background" />
            </div>
            <span className="text-lg font-semibold tracking-tight">TraderCat</span>
          </Link>
          <div className="flex items-center gap-2">
            <ThemeToggle />
            <Button asChild size="sm" variant="ghost">
              <Link href="/login">Sign in</Link>
            </Button>
            <Button asChild size="sm" className="hidden sm:inline-flex">
              <Link href="/login">Get Started</Link>
            </Button>
          </div>
        </div>
      </header>

      {/* ── Hero ── */}
      <section className="relative overflow-hidden">
        {/* Subtle gradient orb */}
        <div className="pointer-events-none absolute -top-40 left-1/2 h-[500px] w-[800px] -translate-x-1/2 rounded-full bg-gradient-to-b from-foreground/[0.03] to-transparent blur-3xl" />

        <div className="mx-auto max-w-4xl px-4 pt-24 pb-20 text-center sm:px-6 sm:pt-32 sm:pb-28">
          <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-border/60 bg-muted/50 px-4 py-1.5 text-xs font-medium text-muted-foreground">
            <Zap className="h-3.5 w-3.5" />
            AI-powered trading signal analysis
          </div>
          <h1 className="text-4xl font-bold tracking-tight text-foreground sm:text-5xl lg:text-6xl">
            Smarter signals.
            <br />
            <span className="text-muted-foreground">Better decisions.</span>
          </h1>
          <p className="mx-auto mt-6 max-w-2xl text-base leading-relaxed text-muted-foreground sm:text-lg">
            TraderCat combines multiple AI analysts with quantitative strategies to
            deliver actionable trading signals every market day. Set your watchlist,
            let the pipeline run, and focus on what matters.
          </p>
          <div className="mt-10 flex flex-col items-center gap-3 sm:flex-row sm:justify-center">
            <Button asChild size="lg" className="gap-2">
              <Link href="/login">
                Get Started
                <ArrowRight className="h-4 w-4" />
              </Link>
            </Button>
            <Button asChild size="lg" variant="outline">
              <Link href="#features">Learn More</Link>
            </Button>
          </div>
        </div>
      </section>

      {/* ── Features ── */}
      <section id="features" className="border-t bg-muted/30 py-20 sm:py-28">
        <div className="mx-auto max-w-6xl px-4 sm:px-6">
          <div className="text-center">
            <p className="text-sm font-medium uppercase tracking-widest text-muted-foreground">
              Features
            </p>
            <h2 className="mt-3 text-2xl font-bold tracking-tight sm:text-3xl">
              Everything you need to trade smarter
            </h2>
          </div>

          <div className="mt-14 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {features.map((f) => (
              <div
                key={f.title}
                className="group rounded-xl border border-border/50 bg-card p-6 transition-all duration-300 hover:border-border hover:shadow-sm"
              >
                <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-lg bg-foreground/[0.06] transition-colors group-hover:bg-foreground/[0.1]">
                  <f.icon className="h-5 w-5 text-foreground/70" />
                </div>
                <h3 className="text-sm font-semibold text-foreground">{f.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                  {f.description}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── CTA ── */}
      <section className="border-t py-20 sm:py-28">
        <div className="mx-auto max-w-2xl px-4 text-center sm:px-6">
          <h2 className="text-2xl font-bold tracking-tight sm:text-3xl">
            Ready to get started?
          </h2>
          <p className="mt-4 text-base text-muted-foreground">
            Sign in with your personal access token to access your personalized trading dashboard,
            signals, and reports.
          </p>
          <Button asChild size="lg" className="mt-8 gap-2">
            <Link href="/login">
              Sign in to TraderCat
              <ArrowRight className="h-4 w-4" />
            </Link>
          </Button>
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className="border-t bg-muted/20 py-8">
        <div className="mx-auto flex max-w-6xl flex-col items-center gap-4 px-4 sm:flex-row sm:justify-between sm:px-6">
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Cat className="h-4 w-4" />
            <span>&copy; {new Date().getFullYear()} TraderCat</span>
          </div>
          <p className="text-xs text-muted-foreground/60">
            AI-powered trading signal analysis platform
          </p>
        </div>
      </footer>
    </div>
  );
}
