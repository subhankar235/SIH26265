import { useAuthStore } from '../../store/authStore';
import { useUiStore } from '../../store/uiStore';
import { Sun, Moon, LogOut, Shield, Circle, Menu } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { logout as logoutRequest } from '../../api/auth.api';
import BrandHeader from './BrandHeader';

export default function Topbar({ user, onLogout, sidebarOpen = true }) {
  const auth = useAuthStore();
  const { darkMode, toggleDarkMode, toggleMobileSidebar, mobileSidebarOpen } = useUiStore();
  const navigate = useNavigate();
  user = user || auth.user;
  onLogout = onLogout || (async () => { try { await logoutRequest(); } finally { auth.clearSession(); navigate('/login', { replace: true }); } });

  return <BrandHeader
    descriptor="AICTE · Deposit tracking"
    className={`md:fixed md:right-0 md:top-0 ${sidebarOpen ? 'md:left-[340px]' : 'md:left-[76px]'}`}
    leading={<button onClick={toggleMobileSidebar} aria-label={mobileSidebarOpen ? 'Close navigation' : 'Open navigation'} aria-expanded={mobileSidebarOpen} aria-controls="app-navigation" className="grid size-10 shrink-0 place-items-center rounded-lg text-slate-600 hover:bg-[#F1F5FA] hover:text-[#3182F6] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#3182F6] md:hidden"><Menu size={19}/></button>}
    rightSlot={<>
      <span className="hidden items-center gap-1.5 text-[11px] font-semibold text-emerald-700 lg:inline-flex"><Circle size={7} fill="currentColor" aria-hidden="true"/>System operational</span>
      <button onClick={toggleDarkMode} aria-label={darkMode ? 'Switch to light theme' : 'Switch to dark theme'} className="grid size-10 place-items-center rounded-lg text-slate-500 hover:bg-[#F1F5FA] hover:text-[#3182F6] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#3182F6]">{darkMode ? <Sun size={18}/> : <Moon size={18}/>}</button>
      <span className="hidden max-w-48 truncate text-xs text-slate-600 sm:inline">{user?.email}</span>
      <span className="inline-flex max-w-[24vw] items-center gap-1.5 truncate rounded-full bg-[#EAF3FF] px-2 py-1.5 text-xs font-semibold capitalize text-[#273544] max-[380px]:hidden"><Shield size={13} className="shrink-0"/><span className="truncate">{user?.role?.replaceAll('_', ' ')}</span></span>
      <button onClick={onLogout} className="inline-flex min-h-10 shrink-0 items-center gap-1.5 rounded-lg border border-[#D8E1EA] bg-white px-2.5 py-2 text-xs font-semibold text-slate-700 hover:border-[#C9DAF3] hover:bg-[#E8F2FF] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#3182F6]"><LogOut size={14}/><span className="hidden sm:inline">Sign out</span></button>
    </>}
  />;
}
