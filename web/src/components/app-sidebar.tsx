"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/components/providers/auth-provider";
import { ThemeToggle } from "@/components/theme-toggle";
import { cn } from "@/lib/utils";
import { useIsMobile } from "@/hooks/use-mobile";
import {
  Cat,
  LayoutDashboard,
  List,
  BarChart3,
  FileText,
  Settings,
  Users,
  Globe,
  Brain,
  Key,
  Play,
  LogOut,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Badge } from "@/components/ui/badge";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  createContext,
  useContext,
  useState,
  useEffect,
  type ReactNode,
} from "react";

// ── Collapse context (shared between sidebar and layout) ──

interface SidebarState {
  collapsed: boolean;
  setCollapsed: (v: boolean) => void;
  toggle: () => void;
}

const SidebarContext = createContext<SidebarState>({
  collapsed: false,
  setCollapsed: () => {},
  toggle: () => {},
});

export function useSidebar() {
  return useContext(SidebarContext);
}

export function SidebarProvider({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(() => {
    if (typeof window === "undefined") return false;
    return localStorage.getItem("sidebar-collapsed") === "true";
  });

  useEffect(() => {
    localStorage.setItem("sidebar-collapsed", String(collapsed));
  }, [collapsed]);

  return (
    <SidebarContext.Provider
      value={{ collapsed, setCollapsed, toggle: () => setCollapsed((c) => !c) }}
    >
      {children}
    </SidebarContext.Provider>
  );
}

// ── Nav data ──

interface NavItem {
  title: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
}

const userNav: NavItem[] = [
  { title: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
  { title: "Watchlist", href: "/watchlist", icon: List },
  { title: "Signals", href: "/signals", icon: BarChart3 },
  { title: "Reports", href: "/reports", icon: FileText },
  { title: "Settings", href: "/settings", icon: Settings },
];

const adminNav: NavItem[] = [
  { title: "Users", href: "/admin/users", icon: Users },
  { title: "Global Symbols", href: "/admin/global-symbols", icon: Globe },
  { title: "Strategies", href: "/admin/strategies", icon: Brain },
  { title: "LLM Tokens", href: "/admin/llm-tokens", icon: Key },
  { title: "Pipeline", href: "/admin/pipeline", icon: Play },
];

// ── NavLink ──

function NavLink({
  item,
  pathname,
  collapsed,
  onClick,
}: {
  item: NavItem;
  pathname: string;
  collapsed?: boolean;
  onClick?: () => void;
}) {
  const active = pathname === item.href || pathname.startsWith(item.href + "/");
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Link
          href={item.href}
          onClick={onClick}
          className={cn(
            "group flex items-center rounded-lg text-sm font-medium transition-all duration-200",
            collapsed ? "justify-center px-2 py-2" : "gap-3 px-3 py-2",
            active
              ? "bg-foreground/[0.06] text-foreground shadow-sm"
              : "text-muted-foreground hover:bg-foreground/[0.04] hover:text-foreground",
          )}
        >
          <item.icon
            className={cn(
              "h-4 w-4 shrink-0 transition-colors",
              active
                ? "text-foreground"
                : "text-muted-foreground group-hover:text-foreground",
            )}
          />
          {!collapsed && <span className="truncate">{item.title}</span>}
        </Link>
      </TooltipTrigger>
      {collapsed && (
        <TooltipContent side="right" sideOffset={8}>
          {item.title}
        </TooltipContent>
      )}
    </Tooltip>
  );
}

// ── Sidebar content (used in both desktop and mobile sheet) ──

function SidebarContent({
  collapsed,
  onNavClick,
}: {
  collapsed?: boolean;
  onNavClick?: () => void;
}) {
  const { user, isAdmin, logout } = useAuth();
  const pathname = usePathname();
  const sidebar = useSidebar();

  return (
    <div className="flex h-full flex-col">
      {/* Logo */}
      <div
        className={cn(
          "flex h-14 items-center border-b border-sidebar-border",
          collapsed ? "justify-center px-2" : "gap-2.5 px-5",
        )}
      >
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-foreground">
          <Cat className="h-4.5 w-4.5 text-background" />
        </div>
        {!collapsed && (
          <span className="text-lg font-semibold tracking-tight">
            TraderCat
          </span>
        )}
      </div>

      {/* Nav */}
      <nav
        className={cn(
          "flex-1 space-y-1 overflow-y-auto pt-2 pb-3",
          collapsed ? "px-2" : "px-3",
        )}
      >
        {!collapsed && (
          <p className="mb-1.5 px-3 text-[11px] font-medium uppercase tracking-widest text-muted-foreground/70">
            Menu
          </p>
        )}
        {userNav.map((item) => (
          <NavLink
            key={item.href}
            item={item}
            pathname={pathname}
            collapsed={collapsed}
            onClick={onNavClick}
          />
        ))}

        {isAdmin && (
          <>
            <Separator className="my-3" />
            {!collapsed && (
              <p className="mb-1.5 px-3 text-[11px] font-medium uppercase tracking-widest text-muted-foreground/70">
                Administration
              </p>
            )}
            {adminNav.map((item) => (
              <NavLink
                key={item.href}
                item={item}
                pathname={pathname}
                collapsed={collapsed}
                onClick={onNavClick}
              />
            ))}
          </>
        )}
      </nav>

      {/* Footer */}
      <div
        className={cn(
          "border-t border-sidebar-border",
          collapsed ? "p-2" : "p-3",
        )}
      >
        {collapsed ? (
          <div className="flex flex-col items-center gap-2">
            <Tooltip>
              <TooltipTrigger asChild>
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-foreground/[0.08] text-xs font-semibold text-foreground">
                  {user?.username?.charAt(0).toUpperCase() ?? "?"}
                </div>
              </TooltipTrigger>
              <TooltipContent side="right" sideOffset={8}>
                {user?.username} ({user?.role})
              </TooltipContent>
            </Tooltip>
            <ThemeToggle className="h-8 w-8" />
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 text-muted-foreground hover:text-foreground"
                  onClick={() => {
                    onNavClick?.();
                    logout();
                  }}
                >
                  <LogOut className="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="right" sideOffset={8}>
                Sign out
              </TooltipContent>
            </Tooltip>
          </div>
        ) : (
          <>
            <div className="mb-2 flex items-center gap-2.5 px-1">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-foreground/[0.08] text-xs font-semibold text-foreground">
                {user?.username?.charAt(0).toUpperCase() ?? "?"}
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium leading-tight">
                  {user?.username}
                </p>
                <Badge
                  variant="outline"
                  className="mt-0.5 text-[10px] font-normal"
                >
                  {user?.role}
                </Badge>
              </div>
              <ThemeToggle className="h-8 w-8 shrink-0" />
            </div>
            <Button
              variant="ghost"
              size="sm"
              className="w-full justify-start gap-2 text-muted-foreground hover:text-foreground"
              onClick={() => {
                onNavClick?.();
                logout();
              }}
            >
              <LogOut className="h-4 w-4" />
              Sign out
            </Button>
          </>
        )}
      </div>

      {/* Collapse toggle (desktop only, not shown in mobile sheet) */}
      {!onNavClick && (
        <div className="border-t border-sidebar-border p-2">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                className={cn(
                  "h-8 text-muted-foreground hover:text-foreground",
                  collapsed ? "w-8" : "w-full",
                )}
                onClick={sidebar.toggle}
                aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              >
                {collapsed ? (
                  <PanelLeftOpen className="h-4 w-4" />
                ) : (
                  <PanelLeftClose className="h-4 w-4" />
                )}
              </Button>
            </TooltipTrigger>
            {collapsed && (
              <TooltipContent side="right" sideOffset={8}>
                Expand sidebar
              </TooltipContent>
            )}
          </Tooltip>
        </div>
      )}
    </div>
  );
}

/** Mobile top bar with hamburger trigger */
export function MobileHeader() {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();

  // Close sheet on route change
  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b bg-background px-4 md:hidden">
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            className="h-9 w-9"
            aria-label="Open menu"
          >
            <Menu className="h-5 w-5" />
          </Button>
        </SheetTrigger>
        <SheetContent side="left" className="w-64 p-0 [&>button]:hidden">
          <SheetHeader className="sr-only">
            <SheetTitle>Navigation</SheetTitle>
          </SheetHeader>
          <TooltipProvider delayDuration={0}>
            <SidebarContent onNavClick={() => setOpen(false)} />
          </TooltipProvider>
        </SheetContent>
      </Sheet>
      <div className="flex items-center gap-2">
        <Cat className="h-5 w-5 text-foreground" />
        <span className="text-base font-semibold">TraderCat</span>
      </div>
    </header>
  );
}

/** Desktop sidebar — hidden on mobile */
export function AppSidebar() {
  const isMobile = useIsMobile();
  const { collapsed } = useSidebar();

  if (isMobile) return null;

  return (
    <TooltipProvider delayDuration={0}>
      <aside
        className={cn(
          "hidden h-screen shrink-0 flex-col border-r border-sidebar-border bg-sidebar transition-[width] duration-200 ease-in-out md:flex",
          collapsed ? "w-[52px]" : "w-60",
        )}
      >
        <SidebarContent collapsed={collapsed} />
      </aside>
    </TooltipProvider>
  );
}

