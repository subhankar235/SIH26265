/**
 * StatusPill
 * Props: status
 */
export default function StatusPill({ status }) {
  // Render FDR status pill
  const label=String(status||'unknown').replaceAll('_',' ');const color=status==='verified'||status==='released'?'bg-green-100 text-green-800':status==='mismatch'||status==='expired'?'bg-red-100 text-red-800':'bg-slate-100 text-slate-700';return <span className={`rounded-full px-2.5 py-1 text-xs font-semibold capitalize ${color}`}>{label}</span>;
}
