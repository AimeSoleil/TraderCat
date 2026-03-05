import Link from "next/link";
import { Cat } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background px-4 text-center">
      <div className="mb-8 flex h-16 w-16 items-center justify-center rounded-2xl bg-foreground/[0.06]">
        <Cat className="h-8 w-8 text-muted-foreground" />
      </div>
      <p className="text-8xl font-bold tracking-tighter text-foreground/10">
        404
      </p>
      <h1 className="mt-4 text-xl font-semibold text-foreground">
        Page not found
      </h1>
      <p className="mt-2 max-w-sm text-sm text-muted-foreground">
        The page you&apos;re looking for doesn&apos;t exist or has been moved.
      </p>
      <Button asChild className="mt-8" size="sm">
        <Link href="/dashboard">Back to Dashboard</Link>
      </Button>
    </div>
  );
}
