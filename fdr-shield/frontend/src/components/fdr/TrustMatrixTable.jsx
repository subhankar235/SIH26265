import { Filter } from 'lucide-react';
import TrustBadge from '../common/TrustBadge';
import StatusPill from '../common/StatusPill';
import { DataOriginBadge } from '../common/PageStates';
import MaturityCountdown from './MaturityCountdown';

export default function TrustMatrixTable({rows=[],filters={},onFilterChange=()=>{},onRowClick}){
  const change=event=>onFilterChange({...filters,[event.target.name]:event.target.value||undefined});
  return <section className="overflow-hidden rounded-xl border bg-white shadow-sm">
    <div className="flex flex-wrap items-end gap-3 border-b p-4"><div className="mr-auto flex items-center gap-2 font-semibold"><Filter size={16} aria-hidden="true"/>Trust matrix</div>
      <label className="text-xs font-medium text-slate-700">Status<select name="status" value={filters.status||''} onChange={change} className="mt-1 block rounded-lg border bg-white px-3 py-2 text-sm"><option value="">All statuses</option>{['submitted','under_scrutiny','verified','mismatch','expired','released'].map(x=><option key={x} value={x}>{x.replaceAll('_',' ')}</option>)}</select></label>
      <label className="text-xs font-medium text-slate-700">Trust badge<select name="badge" value={filters.badge||''} onChange={change} className="mt-1 block rounded-lg border bg-white px-3 py-2 text-sm"><option value="">All badges</option>{['bank_verified','self_declared','mismatch'].map(x=><option key={x} value={x}>{x.replaceAll('_',' ')}</option>)}</select></label>
      <label className="text-xs font-medium text-slate-700">Institution ID<input name="institution_id" type="number" min="1" value={filters.institution_id||''} onChange={change} placeholder="All" className="mt-1 block w-28 rounded-lg border px-3 py-2 text-sm"/></label>
    </div>
    <div className="overflow-x-auto"><table className="w-full min-w-[900px] text-left text-sm"><thead className="sticky top-0 bg-slate-50 text-xs uppercase tracking-wide text-slate-600"><tr>{['FDR','Institution','Bank','Amount','Maturity','Countdown','Status','Trust'].map(x=><th key={x} className="px-4 py-3">{x}</th>)}</tr></thead>
      <tbody className="divide-y">{rows.map(x=><tr key={x.id} onClick={()=>onRowClick?.(x)} className={onRowClick?'cursor-pointer transition-colors hover:bg-slate-50 focus-within:bg-slate-50':''}>
        <td className="px-4 py-3 font-semibold"><span>{x.fdr_number}</span>{x.is_synthetic?<div className="mt-1"><DataOriginBadge isSynthetic/></div>:x.is_synthetic===null&&<span className="mt-1 block text-[11px] font-normal text-slate-700">Origin unclassified</span>}</td>
        <td className="px-4 py-3">{x.institution_name||`Institution #${x.institution_id}`}</td><td className="px-4 py-3">{x.bank_name}</td>
        <td className="px-4 py-3 tabular-nums">₹{Number(x.amount||0).toLocaleString('en-IN')}</td><td className="px-4 py-3">{x.maturity_date||'—'}</td>
        <td className="px-4 py-3"><MaturityCountdown maturityDate={x.maturity_date}/></td><td className="px-4 py-3"><StatusPill status={x.lifecycle_state||x.status}/></td><td className="px-4 py-3"><TrustBadge badge={x.trust_badge}/></td>
      </tr>)}</tbody></table>{!rows.length&&<p className="p-8 text-center text-slate-700">No records match these filters.</p>}</div>
  </section>;
}
