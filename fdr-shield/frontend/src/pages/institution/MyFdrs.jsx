import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { client } from '../../api/client';
import { EmptyState, ErrorState, LoadingState, LiveStatus, DataOriginBadge } from '../../components/common/PageStates';
import { formatINR, formatDate } from '../../utils/format';
import TrustBadge from '../../components/common/TrustBadge';
import StatusPill from '../../components/common/StatusPill';

export default function MyFdrs(){
 const[status,setStatus]=useState('');
 const q=useQuery({queryKey:['fdrs',status],queryFn:()=>client.get('/fdrs',{params:status?{status}:undefined}).then(r=>r.data),refetchInterval:10000});
 const rows=Array.isArray(q.data)?q.data:[];
 return <section><div className="mb-5 flex flex-wrap items-end justify-between gap-3"><div><h1 className="text-3xl font-bold">My FDRs</h1><p className="mt-1 text-slate-600">Track lifecycle, verification observations, and corrections.</p></div><div className="flex items-center gap-3"><LiveStatus active={false}/><Link to="/institution/fdrs/new" className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white">Add FDR</Link></div></div><label className="mb-4 block max-w-xs text-sm">Filter by status<select value={status} onChange={e=>setStatus(e.target.value)} className="mt-1 w-full rounded-lg border p-2"><option value="">All cases</option>{['submitted','under_scrutiny','verified','mismatch','release_requested','released','expired'].map(s=><option key={s} value={s}>{s.replaceAll('_',' ')}</option>)}</select></label>{q.isLoading?<LoadingState label="Loading FDR records"/>:q.isError?<ErrorState error={q.error} onRetry={()=>q.refetch()} label="Could not load FDR records"/>:!rows.length?<EmptyState title="No FDRs found" action={<Link to="/institution/fdrs/new" className="rounded-lg bg-indigo-950 px-4 py-2 text-white">Submit FDR</Link>}>Submit a deposit to begin tracking its lifecycle and verification status.</EmptyState>:<div className="overflow-x-auto rounded-xl border bg-white"><table className="w-full min-w-[860px] text-left text-sm"><thead className="bg-slate-50 text-slate-600"><tr>{['FDR number','Origin','Bank','Amount','Maturity','Lifecycle','Trust'].map(x=><th key={x} className="px-4 py-3">{x}</th>)}</tr></thead><tbody className="divide-y">{rows.map(x=><tr key={x.id} className="hover:bg-slate-50"><td className="px-4 py-3 font-semibold"><Link className="underline" to={`/institution/fdrs/${x.id}`}>{x.fdr_number}</Link></td><td className="px-4 py-3">{x.is_synthetic?<DataOriginBadge isSynthetic/>:x.is_synthetic===false?'Institution submission':'Origin unclassified'}</td><td className="px-4 py-3">{x.bank_name}</td><td className="px-4 py-3">{formatINR(x.amount)}</td><td className="px-4 py-3">{formatDate(x.maturity_date)}</td><td className="px-4 py-3"><StatusPill status={x.lifecycle_state||x.status}/></td><td className="px-4 py-3"><TrustBadge badge={x.trust_badge}/></td></tr>)}</tbody></table></div>}</section>;
}
