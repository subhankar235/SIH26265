import { Link, useLocation } from 'react-router-dom';
import { ArrowUpRight, Check, ShieldCheck, Zap } from 'lucide-react';
import { useAuthStore } from '../../store/authStore';

const shortcuts = {
  institution: [
    ['/institution/fdrs/new', 'Submit an FDR'],
    ['/institution/fdrs', 'My FDRs'],
    ['/institution/renewals', 'Renewals'],
  ],
  aicte_official: [
    ['/official/queue', 'Scrutiny queue'],
    ['/official/discrepancies', 'Discrepancies'],
    ['/official/approvals', 'Approvals'],
  ],
  admin: [
    ['/admin/users', 'User accounts'],
    ['/admin/rules', 'Automation rules'],
    ['/admin/health', 'System health'],
  ],
};

const viewLabels = {
  dashboard: 'Overview',
  queue: 'Scrutiny queue',
  discrepancies: 'Discrepancies',
  approvals: 'Approvals',
  fdrs: 'FDR records',
  renewals: 'Renewals',
  releases: 'Releases',
  users: 'User accounts',
  rules: 'Automation rules',
  health: 'System health',
};

export default function WorkspaceInspector() {
  const { user } = useAuthStore();
  const { pathname } = useLocation();
  const role = user?.role || 'institution';
  const options = shortcuts[role] || shortcuts.aicte_official;
  const pathEnd = pathname.split('/').filter(Boolean).at(-1) || 'dashboard';
  const currentView = viewLabels[pathEnd] || pathEnd.replaceAll('-', ' ').replace(/\b\w/g, letter => letter.toUpperCase());
  const roleLabel = role === 'admin' ? 'Super Admin' : role === 'institution' ? 'Institution' : 'AICTE Official';

  return <aside aria-label="Workspace details" className="workspace-inspector w-full shrink-0 overflow-hidden rounded-2xl border border-[#D8E1EA] bg-white xl:sticky xl:top-[88px] xl:w-[280px] 2xl:w-[310px]">
    <div className="border-b border-[#D8E1EA] px-5 py-5">
      <p className="text-xs font-semibold text-[#64748B]">Selected workspace</p>
      <h2 className="mt-1 text-lg font-bold tracking-tight text-[#273544]">{roleLabel} portal</h2>
    </div>

    <div className="border-b border-[#D8E1EA] px-5 py-4">
      <p className="text-xs font-semibold text-[#64748B]">Current view</p>
      <p className="mt-1 font-semibold text-[#273544]">{currentView}</p>
      <div className="mt-4 flex items-center justify-between gap-3 text-sm">
        <span className="text-[#526173]">Access</span>
        <span className="inline-flex items-center gap-1.5 rounded-full bg-[#EAF3FF] px-2.5 py-1 text-xs font-semibold text-[#2563EB]"><ShieldCheck size={13}/> Role-based</span>
      </div>
      <div className="mt-3 flex items-center justify-between gap-3 text-sm">
        <span className="text-[#526173]">Session</span>
        <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-emerald-700"><Check size={14}/> Active</span>
      </div>
    </div>

    <div className="px-5 py-4">
      <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-[.1em] text-[#64748B]"><Zap size={14} className="text-[#3182F6]"/> Quick actions</div>
      <nav aria-label="Quick actions" className="mt-3 space-y-1.5">
        {options.map(([href, label]) => <Link key={href} to={href} className="flex min-h-10 items-center justify-between gap-2 rounded-lg px-3 py-2 text-sm font-medium text-[#273544] transition-colors hover:bg-[#F1F5FA] hover:text-[#2563EB] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#3182F6]">
          {label}<ArrowUpRight size={15} className="shrink-0 text-[#64748B]"/>
        </Link>)}
      </nav>
    </div>

    <div className="mx-4 mb-4 rounded-xl border border-[#D8E1EA] bg-[#F5F8FC] p-3">
      <p className="text-xs font-semibold text-[#64748B]">Signed in as</p>
      <p className="mt-1 truncate text-sm font-semibold text-[#273544]" title={user?.email}>{user?.email || 'Account'}</p>
    </div>
  </aside>;
}
