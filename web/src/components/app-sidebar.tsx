"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/components/providers/auth-provider";
import { UserMenu } from "@/components/user-menu";
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
  Menu,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
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
            "group flex items-center rounded-md text-sm font-medium transition-all duration-150",
            collapsed ? "justify-center px-2 py-1.5" : "gap-3 px-3 py-1.5",
            active
              ? "bg-primary/8 text-foreground"
              : "text-muted-foreground hover:bg-foreground/4 hover:text-foreground",
          )}
        >
          <item.icon
            className={cn(
              "h-4 w-4 shrink-0 transition-colors",
              active
                ? "text-primary"
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
  const { isAdmin } = useAuth();
  const pathname = usePathname();

  return (
    <div className="flex h-full flex-col">
      {/* Logo */}
      <div
        className={cn(
          "flex h-12 items-center border-b border-sidebar-border",
          collapsed ? "justify-center px-2" : "gap-2.5 px-4",
        )}
      >
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-foreground">
          <Cat className="h-4 w-4 text-background" />
        </div>
        {!collapsed && (
          <span className="text-base font-semibold tracking-tight">
            TraderCat
          </span>
        )}
      </div>

      {/* Nav */}
      <nav
        className={cn(
          "flex-1 space-y-0.5 overflow-y-auto py-3",
          collapsed ? "px-1.5" : "px-2",
        )}
      >
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
            <Separator className="my-3!" />
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
    </div>
  );
}

/** Mobile top bar with hamburger trigger */
export function MobileHeader() {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const [lastPathname, setLastPathname] = useState(pathname);

  // Close sheet on route change (setState during render — React approved pattern)
  if (pathname !== lastPathname) {
    setLastPathname(pathname);
    setOpen(false);
  }

  return (
    <header className="flex h-12 shrink-0 items-center border-b bg-background px-3 md:hidden">
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            aria-label="Open menu"
          >
            <Menu className="h-5 w-5" />
          </Button>
        </SheetTrigger>
        <SheetContent side="left" className="w-60 p-0 [&>button]:hidden">
          <SheetHeader className="sr-only">
            <SheetTitle>Navigation</SheetTitle>
          </SheetHeader>
          <TooltipProvider delayDuration={0}>
            <SidebarContent onNavClick={() => setOpen(false)} />
          </TooltipProvider>
        </SheetContent>
      </Sheet>
      <div className="flex flex-1 items-center gap-2 pl-1">
        <Cat className="h-5 w-5 text-foreground" />
        <span className="text-base font-semibold">TraderCat</span>
      </div>
      <UserMenu />
    </header>
  );
}

/** Desktop sidebar — hidden on mobile */
export function AppSidebar() {
  const isMobile = useIsMobile();
  const { collapsed, toggle } = useSidebar();

  if (isMobile) return null;

  return (
    <TooltipProvider delayDuration={0}>
      <aside
        className={cn(
          "group/sidebar relative hidden h-screen shrink-0 flex-col border-r border-sidebar-border bg-sidebar transition-[width] duration-200 ease-in-out md:flex",
          collapsed ? "w-13" : "w-56",
        )}
      >
        <SidebarContent collapsed={collapsed} />

        {/* Collapse handle — circular button riding on the border line */}
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              onClick={toggle}
              aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              className="absolute top-6.5 -right-3 z-30 flex h-6 w-6 items-center justify-center rounded-full border border-border bg-background text-muted-foreground shadow-sm opacity-0 transition-all duration-150 hover:text-foreground hover:shadow-md active:scale-90 group-hover/sidebar:opacity-100"
            >
              {collapsed ? (
                <ChevronRight className="h-3.5 w-3.5" />
              ) : (
                <ChevronLeft className="h-3.5 w-3.5" />
              )}
            </button>
          </TooltipTrigger>
          <TooltipContent side="right" sideOffset={12}>
            {collapsed ? "Expand" : "Collapse"}
          </TooltipContent>
        </Tooltip>
      </aside>
    </TooltipProvider>
  );
}

