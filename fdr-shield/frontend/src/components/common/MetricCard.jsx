import { Landmark, CalendarClock, ScanSearch, TriangleAlert, ArrowUpRight } from 'lucide-react';
const iconMap = { 'Active FDR value': Landmark, 'Maturing in 30 days': CalendarClock, 'Pending verification': ScanSearch, 'Flagged discrepancies': TriangleAlert };

export default function MetricCard({ title, value, icon: Icon, tone = 'indigo', subtitle }) {
  Icon ||= iconMap[title] || ArrowUpRight;
  const toneClass = tone === 'amber' ? 'bg-amber-50 text-amber-800' : tone === 'red' ? 'bg-red-50 text-red-800' : 'bg-indigo-50 text-indigo-800';
  return <article className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm transition-shadow hover:shadow-md"><div className="flex items-start justify-between gap-3"><div><p className="text-sm font-medium text-slate-500">{title}</p><p className="mt-3 text-2xl font-bold tabular-nums tracking-tight text-slate-950">{value ?? '—'}</p></div><span className={`grid size-10 place-items-center rounded-xl ${toneClass}`}><Icon size={19}/></span></div><p className="mt-3 text-xs text-slate-500">{subtitle || 'Current portfolio snapshot'}</p></article>;
}
