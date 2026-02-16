import { AuthGuard } from "@/components/auth-guard";
import { AppSidebar, MobileHeader, SidebarProvider } from "@/components/app-sidebar";

export default function PortalLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <AuthGuard>
      <SidebarProvider>
        <div className="flex h-screen overflow-hidden">
          <AppSidebar />
          <div className="flex flex-1 flex-col overflow-hidden">
            <MobileHeader />
            <main className="flex-1 overflow-y-auto bg-muted/30 p-4 md:p-6 lg:p-8">
              {children}
            </main>
          </div>
        </div>
      </SidebarProvider>
    </AuthGuard>
  );
}
