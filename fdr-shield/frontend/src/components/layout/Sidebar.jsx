import { useMemo, useState } from 'react';
import { NavLink } from 'react-router-dom';
import { useAuthStore } from '../../store/authStore';
import { useUiStore } from '../../store/uiStore';
import { Activity, AlertTriangle, Bell, BrainCircuit, Building2, ClipboardCheck, Files, GitBranch, LayoutDashboard, MessageSquareText, PanelLeftClose, PanelLeftOpen, Search, ScrollText, Settings, ShieldCheck, Upload, Wallet, X } from 'lucide-react';

const institutionLinks = [
  ['', 'Overview', LayoutDashboard], ['/fdrs/new', 'Submit FDR', Upload], ['/fdrs', 'My FDRs', Files], ['/renewals', 'Renewals', Activity], ['/releases', 'Releases', Wallet], ['/notifications', 'Notifications', Bell], ['/command', 'Command Center', MessageSquareText],
];
const bureauLinks = [
  ['', 'Overview', LayoutDashboard], ['/queue', 'Scrutiny queue', ShieldCheck], ['/registrations', 'Institution applications', ClipboardCheck], ['/discrepancies', 'Discrepancies', AlertTriangle], ['/approvals', 'Approvals', ClipboardCheck], ['/control-room', 'Control room', GitBranch], ['/exceptions', 'Exception inbox', AlertTriangle], ['/command', 'Command Center', MessageSquareText], ['/institutions', 'Institutions', Building2], ['/audit', 'Audit logs', ScrollText],
];
const adminLinks = [
  ['', 'Overview', LayoutDashboard], ['/users', 'User accounts', ShieldCheck], ['/roles', 'Role assignments', Settings], ['/registrations', 'Institution applications', Building2], ['/official-registrations', 'Official applications', ClipboardCheck], ['/institutions', 'Institutions', Building2], ['/rules', 'Automation rules', Settings], ['/ml', 'ML governance', BrainCircuit], ['/alerts', 'Alerts', Bell], ['/notifications', 'Delivery monitor', Activity], ['/jobs', 'Failed jobs', AlertTriangle], ['/health', 'System health', Activity], ['/ops-agent', 'Operations agent', MessageSquareText], ['/command', 'Command Center', MessageSquareText], ['/audit', 'Audit logs', ScrollText],
];

const categoryPlans = {
  institution: [['Triggers', [0, 1, 2]], ['Actions', [3, 4, 5]], ['Logic', [6]], ['Webhooks', []], ['Events', []]],
  aicte_official: [['Triggers', [0, 1, 2]], ['Actions', [3, 4]], ['Logic', [5, 7]], ['Webhooks', [6]], ['Events', [8, 9]]],
  admin: [['Triggers', [0, 3, 4]], ['Actions', [1, 5, 8]], ['Logic', [2, 6, 7]], ['Webhooks', [9, 11, 13]], ['Events', [10, 12, 14]]],
};

const tileTones = ['bg-[#EAF3FF] text-[#3182F6]', 'bg-[#E3F5EC] text-[#16845A]', 'bg-[#FFF4D6] text-[#A56B00]', 'bg-[#EAF3FF] text-[#3182F6]', 'bg-[#E3F5EC] text-[#16845A]'];
const railShortcuts = {
  institution: [['', 'Overview', LayoutDashboard], ['/fdrs/new', 'Submit FDR', Upload], ['/fdrs', 'My FDRs', Files], ['/renewals', 'Renewals', Activity], ['/command', 'Command Center', MessageSquareText]],
  aicte_official: [['', 'Overview', LayoutDashboard], ['/queue', 'Scrutiny queue', ShieldCheck], ['/discrepancies', 'Discrepancies', AlertTriangle], ['/approvals', 'Approvals', ClipboardCheck]],
  admin: [['', 'Overview', LayoutDashboard], ['/users', 'User accounts', ShieldCheck], ['/rules', 'Automation rules', Settings], ['/health', 'System health', Activity]],
};

export default function Sidebar() {
  const { user } = useAuthStore();
  const { sidebarOpen, toggleSidebar, mobileSidebarOpen, closeMobileSidebar } = useUiStore();
  const [search, setSearch] = useState('');
  const [collapsed, setCollapsed] = useState({});
  const role = user?.role || 'institution';
  const institution = role === 'institution', admin = role === 'admin';
  const root = institution ? '/institution' : admin ? '/admin' : '/official';
  const links = institution ? institutionLinks : admin ? adminLinks : bureauLinks;
  const portalName = institution ? 'Institution portal' : admin ? 'Super Admin portal' : 'AICTE Official workspace';
  const visibleLinks = useMemo(() => links.map((item, index) => ({ item, index })).filter(({ item }) => item[1].toLowerCase().includes(search.trim().toLowerCase())), [links, search]);
  const groups = useMemo(() => search.trim()
    ? [['Search results', visibleLinks]]
    : (categoryPlans[role] || categoryPlans.aicte_official).map(([name, indices]) => [name, visibleLinks.filter(({ index }) => indices.includes(index))]).filter(([, entries]) => entries.length),
  [visibleLinks, search, role]);
  const railLinks = railShortcuts[role] || railShortcuts.aicte_official;
  const initials = (user?.full_name || user?.email || 'U').split(/[\s@.]+/).filter(Boolean).slice(0, 2).map(part => part[0]).join('').toUpperCase();

  return <aside id="app-navigation" aria-label="Application navigation" className={`${mobileSidebarOpen ? 'fixed inset-y-0 left-0 z-50 flex w-[min(22rem,92vw)] shadow-2xl' : 'hidden'} shrink-0 overflow-hidden border-r border-[#D8E1EA] bg-white text-[#526173] transition-[width,transform] duration-200 md:fixed md:inset-y-0 md:left-0 md:z-40 md:flex md:min-h-screen md:shadow-none ${sidebarOpen ? 'md:w-[340px]' : 'md:w-[76px]'}`}>
    <div className="flex w-[68px] shrink-0 flex-col items-center border-r border-[#D8E1EA] bg-[#F8FAFD] py-4">
      <div className="relative mb-5 grid size-10 place-items-center rounded-full bg-[#273544] text-xs font-bold text-white" title={user?.full_name || user?.email || 'Signed in user'}>{initials}<span className="absolute -right-0.5 -top-0.5 size-2.5 rounded-full border-2 border-white bg-[#22A06B]"/></div>
      <nav aria-label="Workspace shortcuts" className="flex w-full flex-1 flex-col items-center gap-2">
        {railLinks.map(([path, label, Icon]) => <NavLink key={path} end={!path} to={`${root}${path}`} onClick={closeMobileSidebar} title={label} aria-label={label} className={({ isActive }) => `grid size-10 place-items-center rounded-xl transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#3182F6] ${isActive ? 'bg-[#DCEBFF] text-[#2563EB]' : 'text-[#64748B] hover:bg-[#EAF3FF] hover:text-[#2563EB]'}`}><Icon size={19}/></NavLink>)}
      </nav>
      <button onClick={closeMobileSidebar} aria-label="Close navigation" className="mb-1 grid size-10 place-items-center rounded-lg text-[#64748B] hover:bg-[#EAF3FF] hover:text-[#2563EB] md:hidden"><X size={18}/></button>
      <button onClick={toggleSidebar} aria-label={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'} className="hidden size-10 place-items-center rounded-lg text-[#64748B] hover:bg-[#EAF3FF] hover:text-[#2563EB] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#3182F6] md:grid">{sidebarOpen ? <PanelLeftClose size={17}/> : <PanelLeftOpen size={17}/>}</button>
    </div>

    <div className={`${sidebarOpen ? 'flex min-w-0 flex-1 flex-col' : 'hidden'} md:flex md:w-[272px] md:shrink-0`}>
      <div className="flex h-[72px] items-center justify-between border-b border-[#E7EDF4] px-4"><div className="min-w-0"><p className="truncate text-[10px] font-bold uppercase tracking-[.13em] text-[#64748B]">{portalName}</p><p className="mt-1 text-sm font-semibold text-[#273544]">Workspace menu</p></div><button onClick={closeMobileSidebar} aria-label="Close navigation" className="grid size-9 place-items-center rounded-lg text-[#64748B] hover:bg-[#F1F5FA] md:hidden"><X size={17}/></button></div>
      <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-4 pt-3">
        <label className="relative mb-4 block"><Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[#64748B]"/><span className="sr-only">Search workspace pages</span><input value={search} onChange={event => setSearch(event.target.value)} placeholder="Search..." className="min-h-10 w-full rounded-lg border border-[#D8E1EA] bg-white pl-9 pr-3 text-sm outline-none placeholder:text-[#64748B] focus:border-[#3182F6] focus:ring-2 focus:ring-[#3182F6]/15"/></label>
        {!visibleLinks.length ? <p className="px-3 py-5 text-sm text-[#64748B]">No matching pages.</p> : groups.map(([group, entries]) => <section key={group} className="mb-3"><button type="button" aria-expanded={!collapsed[group]} onClick={() => setCollapsed(value => ({ ...value, [group]: !value[group] }))} className="flex min-h-8 w-full items-center justify-between px-1 text-left text-sm font-semibold text-[#273544] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#3182F6]"><span>{group}</span><span className={`text-[#64748B] transition-transform ${collapsed[group] ? '-rotate-90' : ''}`}>⌄</span></button>{!collapsed[group]&&<nav aria-label={group} className="sidebar-palette-grid mt-1">{entries.map(({ item: [path, label, Icon], index }) => <NavLink key={path} end={!path} to={`${root}${path}`} onClick={closeMobileSidebar} title={label} className={({ isActive }) => `sidebar-palette-tile group ${isActive ? 'sidebar-palette-tile-active' : ''}`}><span className={`sidebar-palette-icon ${tileTones[index % tileTones.length]}`}><Icon size={19}/></span><span className="line-clamp-2 text-center text-[10px] font-medium leading-tight text-[#273544] group-hover:text-[#2563EB]">{label}</span></NavLink>)}</nav>}</section>)}
      </div>
      <div className="mx-3 mb-4 rounded-xl border border-[#D8E1EA] bg-[#F5F8FC] p-3 text-xs text-[#526173]"><div className="mb-1 flex items-center gap-2 font-semibold text-[#273544]"><span className="size-2 rounded-full bg-emerald-500"/>Secure registry</div>Demo bank gateway active</div>
    </div>
  </aside>;
}
