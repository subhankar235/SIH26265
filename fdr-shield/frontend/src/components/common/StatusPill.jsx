/**
 * StatusPill
 * Props: status
 */
export default function StatusPill({ status }) {
  // Render FDR status pill
  const label=String(status||'unknown').replaceAll('_',' ');const success=['verified','released','accepted','completed','release_approved'].includes(status),danger=['mismatch','expired','failed','rejected','release_rejected'].includes(status);const Icon=success?CheckCircle2:danger?AlertCircle:Clock3;const color=success?'bg-green-100 text-green-900':danger?'bg-red-100 text-red-900':'bg-slate-100 text-slate-800';return <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold capitalize ${color}`}><Icon size={13} aria-hidden="true"/>{label}</span>;
}
import { AlertCircle, CheckCircle2, Clock3 } from 'lucide-react';
