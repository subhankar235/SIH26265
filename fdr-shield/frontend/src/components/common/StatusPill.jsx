import { AlertCircle, CheckCircle2, Clock3 } from 'lucide-react';

export default function StatusPill({ status }) {
  const label = String(status || 'unknown').replaceAll('_', ' ');
  const success = ['verified', 'released', 'accepted', 'completed', 'release_approved'].includes(status);
  const danger = ['mismatch', 'expired', 'failed', 'rejected', 'release_rejected'].includes(status);
  const Icon = success ? CheckCircle2 : danger ? AlertCircle : Clock3;
  const color = success ? 'bg-emerald-50 text-emerald-700' : danger ? 'bg-rose-50 text-rose-700' : 'bg-[#f5f5fa] text-[#526173]';
  return <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold capitalize ${color}`}><Icon size={13} aria-hidden="true"/>{label}</span>;
}
