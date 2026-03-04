"use client"

import { useSyncExternalStore } from "react"
import { useTheme } from "next-themes"
import { LogOut, Moon, Sun } from "lucide-react"

import { useAuth } from "@/components/providers/auth-provider"
import { Badge } from "@/components/ui/badge"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { cn } from "@/lib/utils"

export function UserMenu({ className }: { className?: string }) {
  const { user, logout } = useAuth()
  const { resolvedTheme, setTheme } = useTheme()
  const mounted = useSyncExternalStore(
    () => () => {},
    () => true,
    () => false,
  )

  if (!user) return null

  const initial = user.username?.charAt(0).toUpperCase() ?? "?"
  const isDark = mounted && resolvedTheme === "dark"

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          className={cn(
            "inline-flex h-8 w-8 items-center justify-center rounded-full bg-foreground/8 text-xs font-semibold text-foreground transition-colors hover:bg-foreground/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            className,
          )}
        >
          {initial}
        </button>
      </DropdownMenuTrigger>

      <DropdownMenuContent className="w-52" align="end" sideOffset={8}>
        <DropdownMenuLabel className="flex flex-col gap-1 font-normal">
          <span className="text-sm font-medium">{user.username}</span>
          <Badge variant="outline" className="w-fit text-[10px] font-normal text-muted-foreground">
            {user.role}
          </Badge>
        </DropdownMenuLabel>

        <DropdownMenuSeparator />

        <DropdownMenuItem
          className="flex items-center gap-2"
          onSelect={(e) => {
            e.preventDefault()
            setTheme(isDark ? "light" : "dark")
          }}
        >
          {isDark ? (
            <Moon className="h-4 w-4" />
          ) : (
            <Sun className="h-4 w-4" />
          )}
          <span>Dark mode</span>
          <span className="ml-auto text-[10px] text-muted-foreground">
            {isDark ? "On" : "Off"}
          </span>
        </DropdownMenuItem>

        <DropdownMenuSeparator />

        <DropdownMenuItem
          className="flex items-center gap-2 text-destructive focus:text-destructive"
          onSelect={() => logout()}
        >
          <LogOut className="h-4 w-4" />
          <span>Sign out</span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
