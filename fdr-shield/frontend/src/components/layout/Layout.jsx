import Sidebar from './Sidebar';import Topbar from './Topbar';import{useLocation}from'react-router-dom';
/**
 * Layout
 * Props: children
 */
export default function Layout({ children }) {
  // Sidebar + Topbar shell; sidebar links depend on role
  const location=useLocation();if(location.pathname==='/login'||location.pathname==='/mfa')return children;return <div className="min-h-screen bg-slate-50 md:flex"><Sidebar/><main className="min-w-0 flex-1"><Topbar/><div className="mx-auto max-w-[1600px] p-4 sm:p-6 lg:p-8">{children}</div></main></div>;
}
