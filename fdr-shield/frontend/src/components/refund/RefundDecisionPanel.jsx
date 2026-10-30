import { useState } from 'react';

export default function RefundDecisionPanel({ refund, onDecide, busy = false }) {
  const [remarks, setRemarks] = useState('');
  return <div className="mt-4 space-y-3 border-t pt-4"><label className="block text-xs font-medium text-slate-600">Decision remarks<textarea value={remarks} onChange={e => setRemarks(e.target.value)} required rows={2} className="mt-1 w-full rounded-lg border p-2 text-sm focus:border-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-100" placeholder="Record the reason for this decision"/></label><div className="flex justify-end gap-2"><button disabled={busy || !remarks.trim()} onClick={() => onDecide?.(refund.id, 'rejected', remarks)} className="rounded-lg border border-red-200 px-3 py-2 text-sm font-semibold text-red-800 hover:bg-red-50">Reject</button><button disabled={busy || !remarks.trim()} onClick={() => onDecide?.(refund.id, 'approved', remarks)} className="rounded-lg bg-indigo-950 px-3 py-2 text-sm font-semibold text-white hover:bg-indigo-900">Approve release</button></div></div>;
}
