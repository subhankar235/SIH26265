import Sidebar from './Sidebar';
import Topbar from './Topbar';
import { useLocation } from 'react-router-dom';
import { ToastHost } from '../common/PageStates';
import { useUiStore } from '../../store/uiStore';
import WorkspaceInspector from './WorkspaceInspector';
/**
 * Layout
 * Props: children
 */
export default function Layout({ children }) {
  const { pathname } = useLocation();
  const sidebarOpen = useUiStore((state) => state.sidebarOpen);
  const mobileSidebarOpen = useUiStore((state) => state.mobileSidebarOpen);
  const closeMobileSidebar = useUiStore((state) => state.closeMobileSidebar);
  if (pathname === '/admin/ops-agent') return <>{children}<ToastHost/></>;
  // Authentication and public application pages are standalone: never render them
  // inside the authenticated dashboard chrome.
  const standaloneRoutes = new Set([
    '/', '/login', '/mfa',
    '/institution/login', '/official/login', '/admin/login',
    '/institution/register', '/official/register', '/super-admin/setup',
    '/verify-email', '/accept-invite', '/forgot-password', '/reset-password',
    '/account/change-password', '/unauthorized',
  ]);
  if (standaloneRoutes.has(pathname)) return <>{children}<ToastHost/></>;
  return <div className="app-shell surface-grid min-h-screen md:flex"><a href="#main-content" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-white focus:px-4 focus:py-3 focus:text-sm focus:font-semibold focus:text-[#273544]">Skip to content</a>{mobileSidebarOpen&&<button type="button" aria-label="Close navigation" onClick={closeMobileSidebar} className="fixed inset-0 z-40 bg-slate-950/40 md:hidden"/>}<Sidebar/><main id="main-content" className={`min-w-0 flex-1 ${sidebarOpen ? 'md:pl-[340px]' : 'md:pl-[76px]'}`}><Topbar sidebarOpen={sidebarOpen}/><div className="workspace-layout mx-auto flex w-full max-w-[1900px] min-w-0 flex-col items-stretch gap-5 px-4 pb-8 pt-[84px] sm:px-6 lg:gap-6 lg:px-8 xl:flex-row xl:items-start"><div className="workspace-canvas page-content min-w-0 flex-1 rounded-2xl border border-[#D8E1EA] p-4 sm:p-6 lg:p-7">{children}</div><WorkspaceInspector/></div></main><ToastHost/></div>;
}
