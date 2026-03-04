"use client"

import { cn } from "@/lib/utils"
import { ThemeToggle } from "@/components/theme-toggle"
import { UserMenu } from "@/components/user-menu"

export function TopBar({ className }: { className?: string }) {
  return (
    <header
      className={cn(
        "hidden md:flex h-12 border-b border-border bg-background/80 backdrop-blur-sm items-center justify-end px-4 sticky top-0 z-10",
        className,
      )}
    >
      <div className="flex items-center gap-2">
        <ThemeToggle className="h-8 w-8" />
        <UserMenu />
      </div>
    </header>
  )
}
