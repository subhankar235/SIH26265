import { NavLink } from 'react-router-dom';
import { useAuthStore } from '../../store/authStore';
import { useUiStore } from '../../store/uiStore';
import { Landmark, LayoutDashboard, Upload, Files, Wallet, ShieldCheck, AlertTriangle, Building2, ScrollText, PanelLeftClose, PanelLeftOpen, GitBranch, MessageSquareText, Bell, Settings, Activity, ClipboardCheck, BrainCircuit } from 'lucide-react';

const institutionLinks = [
  ['', 'Overview', LayoutDashboard], ['/fdrs/new', 'Submit FDR', Upload], ['/fdrs', 'My FDRs', Files], ['/renewals', 'Renewals', Activity], ['/releases', 'Releases', Wallet], ['/notifications', 'Notifications', Bell],
];
const bureauLinks = [
  ['', 'Overview', LayoutDashboard], ['/queue', 'Scrutiny queue', ShieldCheck], ['/registrations', 'Institution applications', ClipboardCheck], ['/discrepancies', 'Discrepancies', AlertTriangle], ['/approvals', 'Approvals', ClipboardCheck], ['/control-room', 'Control room', GitBranch], ['/exceptions', 'Exception inbox', AlertTriangle], ['/command', 'Command Center', MessageSquareText], ['/institutions', 'Institutions', Building2], ['/audit', 'Audit logs', ScrollText],
];
const adminLinks = [
  ['', 'Overview', LayoutDashboard], ['/users', 'User accounts', ShieldCheck], ['/roles', 'Role assignments', Settings], ['/registrations', 'Institution applications', Building2], ['/official-registrations', 'Official applications', ClipboardCheck], ['/institutions', 'Institutions', Building2], ['/rules', 'Automation rules', Settings], ['/ml', 'ML governance', BrainCircuit], ['/alerts', 'Alerts', Bell], ['/jobs', 'Failed jobs', AlertTriangle], ['/health', 'System health', Activity], ['/ops-agent', 'Operations agent', MessageSquareText], ['/audit', 'Audit logs', ScrollText],
];

export default function Sidebar() {
  const { user } = useAuthStore();
  const { sidebarOpen, toggleSidebar } = useUiStore();
  const institution = user?.role === 'institution', admin = user?.role === 'admin';
  const root = institution ? '/institution' : admin ? '/admin' : '/official';
  const links = institution ? institutionLinks : admin ? adminLinks : bureauLinks.map(([path,label,icon])=>[path==='/scrutiny'?'/queue':path,label,icon]);
  return <aside className={`shrink-0 border-r border-slate-200 bg-white transition-[width] duration-200 md:min-h-screen ${sidebarOpen ? 'md:w-64' : 'md:w-[76px]'}`}>
    <div className="flex h-16 items-center justify-between border-b px-4">
      <div className="flex items-center gap-2 overflow-hidden"> <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-navy-900 text-white"><Landmark size={19}/></span>{sidebarOpen&&<span className="whitespace-nowrap text-lg font-bold tracking-tight">FDR<span className="text-indigo-700">Shield</span></span>}</div>
      <button onClick={toggleSidebar} aria-label={sidebarOpen?'Collapse sidebar':'Expand sidebar'} className="hidden rounded-lg p-2 text-slate-500 hover:bg-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-700 md:block">{sidebarOpen?<PanelLeftClose size={17}/>:<PanelLeftOpen size={17}/>}</button>
    </div>
     <div className="px-3 py-5"><p className={`mb-2 px-3 text-[10px] font-bold uppercase tracking-[.16em] text-slate-400 ${!sidebarOpen&&'sr-only'}`}>{institution?'Institution portal':admin?'Super Admin portal':'AICTE Official workspace'}</p><nav aria-label="Main navigation" className="space-y-1">{links.map(([path,label,Icon])=><NavLink key={path} end={!path} to={`${root}${path}`} title={!sidebarOpen?label:undefined} className={({isActive})=>`flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-700 ${isActive?'bg-indigo-50 text-indigo-900':'text-slate-600 hover:bg-slate-50 hover:text-slate-950'}`}><Icon size={18} className="shrink-0"/><span className={!sidebarOpen?'md:sr-only':''}>{label}</span></NavLink>)}</nav></div>
    <div className={`mx-3 mt-auto hidden rounded-xl bg-slate-50 p-3 text-xs text-slate-500 md:block ${!sidebarOpen?'md:hidden':''}`}><div className="mb-1 flex items-center gap-2 font-semibold text-slate-700"><span className="size-2 rounded-full bg-green-600"/>Secure registry</div>Demo bank gateway active</div>
  </aside>;
}
