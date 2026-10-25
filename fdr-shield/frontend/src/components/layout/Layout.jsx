import Sidebar from './Sidebar';import Topbar from './Topbar';import{useLocation}from'react-router-dom';import{ToastHost}from'../common/PageStates';
/**
 * Layout
 * Props: children
 */
export default function Layout({ children }) {
  // Sidebar + Topbar shell; sidebar links depend on role
  const location=useLocation();if(['/login','/mfa','/institution/login','/official/login','/admin/login','/institution/register','/verify-email','/accept-invite','/forgot-password','/reset-password','/account/change-password','/unauthorized'].includes(location.pathname))return <>{children}<ToastHost/></>;return <div className="min-h-screen bg-slate-50 md:flex"><Sidebar/><main className="min-w-0 flex-1"><Topbar/><div className="mx-auto max-w-[1600px] p-4 sm:p-6 lg:p-8">{children}</div></main><ToastHost/></div>;
}
