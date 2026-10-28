import { Landmark, CalendarClock, ScanSearch, TriangleAlert, ArrowUpRight } from 'lucide-react';

const iconMap = { 'Active FDR value': Landmark, 'Maturing in 30 days': CalendarClock, 'Pending verification': ScanSearch, 'Flagged discrepancies': TriangleAlert };

export default function MetricCard({ title, value, icon: Icon, tone = 'indigo', subtitle }) {
  Icon ||= iconMap[title] || ArrowUpRight;
  const toneClass = tone === 'amber' ? 'bg-amber-50 text-amber-700' : tone === 'red' ? 'bg-rose-50 text-rose-700' : 'bg-[#EAF3FF] text-[#3182F6]';
  return <article className="surface-card group flex min-h-[176px] flex-col justify-between p-5 transition-[border-color,box-shadow] duration-200 hover:border-[#C9DAF3] hover:shadow-sm sm:p-6"><div className="flex items-start justify-between gap-4"><div className="min-w-0 flex-1"><p className="text-sm font-medium leading-5 text-[#64748B]">{title}</p><p className="mt-4 break-words text-2xl font-bold tabular-nums tracking-tight text-[#273544]">{value ?? '—'}</p></div><span className={`grid size-10 shrink-0 place-items-center rounded-lg ${toneClass}`}><Icon size={19}/></span></div><p className="mt-4 text-xs leading-5 text-slate-500">{subtitle || 'Current portfolio snapshot'}</p></article>;
}
