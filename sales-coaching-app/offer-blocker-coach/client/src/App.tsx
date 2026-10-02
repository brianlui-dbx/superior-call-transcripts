import { createBrowserRouter, RouterProvider, NavLink, Outlet } from 'react-router';
import { useState } from 'react';
import { Badge, Button, Sheet, SheetContent, SheetHeader, SheetTitle, useIsMobile } from '@databricks/appkit-ui/react';
import { Menu } from 'lucide-react';
import { CoachingQueuePage } from './pages/queue/CoachingQueuePage';
import { CaseDetailPage } from './pages/queue/CaseDetailPage';
import { GeniePage } from './pages/genie/GeniePage';
import { TeamPage } from './pages/team/TeamPage';
import { useIdentity } from './lib/useIdentity';

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
    isActive ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted hover:text-foreground'
  }`;

const mobileNavLinkClass = ({ isActive }: { isActive: boolean }) =>
  `block px-3 py-2 rounded-md text-sm font-medium transition-colors ${
    isActive ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted hover:text-foreground'
  }`;

type NavLinkClassFn = (props: { isActive: boolean }) => string;

function NavLinks({
  className,
  linkClass,
  onClick,
}: {
  className?: string;
  linkClass: NavLinkClassFn;
  onClick?: () => void;
}) {
  return (
    <nav className={className}>
      <NavLink to="/" end className={linkClass} onClick={onClick}>
        Coaching queue
      </NavLink>
      <NavLink to="/genie" className={linkClass} onClick={onClick}>
        Ask Genie
      </NavLink>
      <NavLink to="/team" className={linkClass} onClick={onClick}>
        Team
      </NavLink>
    </nav>
  );
}

function Layout() {
  const isMobile = useIsMobile();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const identity = useIdentity();

  // Derived rather than synced in an effect: widening past the breakpoint
  // closes the sheet without a second render pass.
  const navSheetOpen = mobileNavOpen && isMobile;

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header className="flex items-center gap-4 border-b px-4 py-3 md:px-6">
        <h1 className="text-lg font-semibold text-foreground">Offer Blocker Coach</h1>
        {/* Desktop nav — hidden below md breakpoint */}
        <NavLinks className="hidden gap-1 md:flex" linkClass={navLinkClass} />
        <div className="ml-auto flex items-center gap-2">
          <Badge variant="secondary" className="hidden sm:inline-flex">
            {identity?.email ?? 'Signed in'}
          </Badge>
          {/* Mobile nav — visible below md breakpoint */}
          <div className="md:hidden">
            <Sheet open={navSheetOpen} onOpenChange={setMobileNavOpen}>
              <Button variant="ghost" size="icon" onClick={() => setMobileNavOpen(true)}>
                <Menu className="h-5 w-5" />
                <span className="sr-only">Open navigation</span>
              </Button>
              <SheetContent side="left">
                <SheetHeader>
                  <SheetTitle>Navigation</SheetTitle>
                </SheetHeader>
                <NavLinks
                  className="flex flex-col gap-1"
                  linkClass={mobileNavLinkClass}
                  onClick={() => setMobileNavOpen(false)}
                />
              </SheetContent>
            </Sheet>
          </div>
        </div>
      </header>

      <main className="flex-1 p-4 md:p-6">
        <Outlet />
      </main>
    </div>
  );
}

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: '/', element: <CoachingQueuePage /> },
      { path: '/cases/:id', element: <CaseDetailPage /> },
      { path: '/genie', element: <GeniePage /> },
      { path: '/team', element: <TeamPage /> },
    ],
  },
]);

export default function App() {
  return <RouterProvider router={router} />;
}
