import { useAuthStore } from '../../store/authStore';
import { useUiStore } from '../../store/uiStore';
import { Sun, Moon, LogOut, Shield } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { logout as logoutRequest } from '../../api/auth.api';

export default function Topbar({ user, onLogout }) {
  const auth = useAuthStore();
  const { darkMode, toggleDarkMode } = useUiStore();
  const navigate = useNavigate();
  user = user || auth.user;
  onLogout = onLogout || (async () => { try { await logoutRequest(); } finally { auth.clearSession(); navigate('/login',{replace:true}); } });
  return <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-slate-200 bg-white/95 px-4 backdrop-blur sm:px-6">
    <div><p className="text-sm font-semibold text-slate-900">Security Deposit Registry</p><p className="hidden text-[11px] text-slate-500 sm:block">AICTE · FDR management</p></div>
    <div className="flex items-center gap-2 sm:gap-3"><button onClick={toggleDarkMode} aria-label={darkMode?'Switch to light theme':'Switch to dark theme'} className="rounded-lg p-2 text-slate-600 hover:bg-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-700">{darkMode?<Sun size={18}/>:<Moon size={18}/>}</button><span className="hidden max-w-48 truncate text-xs text-slate-600 sm:inline">{user?.email}</span><span className="inline-flex items-center gap-1.5 rounded-full bg-indigo-50 px-2.5 py-1.5 text-xs font-semibold capitalize text-indigo-900"><Shield size={13}/>{user?.role?.replaceAll('_',' ')}</span><button onClick={onLogout} className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 py-2 text-xs font-semibold text-slate-700 transition-colors hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-700"><LogOut size={14}/><span className="hidden sm:inline">Sign out</span></button></div>
  </header>;
}
