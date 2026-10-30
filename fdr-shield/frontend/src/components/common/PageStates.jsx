import { useEffect, useState } from 'react';
import { AlertCircle, CheckCircle2, Inbox, RefreshCw } from 'lucide-react';

export function LoadingState({ label = 'Loading' }) {
  return <div role="status" aria-live="polite" className="space-y-3 rounded-xl border border-[#D8E1EA] bg-white p-5 shadow-sm"><span className="sr-only">{label}…</span><div className="h-4 w-1/3 animate-pulse rounded bg-[#E7EDF4]" /><div className="h-10 animate-pulse rounded bg-[#F5F8FC]" /><div className="h-10 animate-pulse rounded bg-[#F5F8FC]" /></div>;
}

export function ErrorState({ error, onRetry, label = 'Could not load this information.' }) {
  const requestId = error?.response?.headers?.['x-request-id'] || error?.response?.data?.request_id;
  return <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-5 text-rose-950"><div className="flex items-center gap-2 font-semibold"><AlertCircle size={18} aria-hidden="true" />{label}</div>{requestId && <p className="mt-1 text-sm">Request ID: <code>{requestId}</code></p>}{onRetry && <button type="button" onClick={onRetry} className="mt-3 inline-flex items-center gap-2 rounded-lg border border-rose-300 bg-white px-3 py-2 text-sm font-semibold focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#3182F6]"><RefreshCw size={15} aria-hidden="true"/>Retry</button>}</div>;
}

export function EmptyState({ title = 'Nothing here yet', children, action }) {
  return <div className="rounded-xl border border-dashed border-[#D8E1EA] bg-white p-8 text-center"><Inbox className="mx-auto text-[#64748B]" aria-hidden="true"/><h2 className="mt-2 font-semibold text-[#273544]">{title}</h2>{children && <p className="mx-auto mt-1 max-w-xl text-sm text-slate-600">{children}</p>}{action && <div className="mt-4">{action}</div>}</div>;
}

export function LiveStatus({ active }) {
  return <span role="status" className="inline-flex items-center gap-1.5 rounded-full border border-[#D8E1EA] bg-white px-2.5 py-1 text-xs font-semibold text-[#64748B]">{active ? <CheckCircle2 size={14} className="text-emerald-600" aria-hidden="true"/> : <RefreshCw size={14} className="text-[#3182F6]" aria-hidden="true"/>}{active ? 'Live updates' : 'Polling updates'}</span>;
}

export function DataOriginBadge({ isSynthetic }) {
  if (!isSynthetic) return null;
  return <span className="inline-flex items-center rounded-full border border-amber-300 bg-amber-50 px-2 py-1 text-[11px] font-bold uppercase tracking-wide text-amber-900">Synthetic demo data</span>;
}

export function useToast() {
  return (message, tone = 'success') => window.dispatchEvent(new CustomEvent('app-toast', { detail: { message, tone } }));
}

export function ToastHost() {
  const [toast, setToast] = useState(null);
  useEffect(() => { const show = event => { setToast(event.detail); window.setTimeout(() => setToast(null), 3500); }; window.addEventListener('app-toast', show); return () => window.removeEventListener('app-toast', show); }, []);
  if (!toast) return null;
  return <div role="status" aria-live="polite" className={`fixed bottom-4 right-4 z-50 max-w-sm rounded-xl border p-4 shadow-lg ${toast.tone === 'error' ? 'border-rose-300 bg-rose-50 text-rose-950' : 'border-emerald-300 bg-emerald-50 text-emerald-950'}`}>{toast.message}</div>;
}
