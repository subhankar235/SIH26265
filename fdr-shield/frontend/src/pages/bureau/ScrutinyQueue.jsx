import { useMemo,useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { client } from '../../api/client';
import { EmptyState,ErrorState,LoadingState,LiveStatus,DataOriginBadge } from '../../components/common/PageStates';
import { formatINR,formatDate } from '../../utils/format';
import TrustBadge from '../../components/common/TrustBadge';
import StatusPill from '../../components/common/StatusPill';

async function getAllFdrs() {
 const all=[];
 for(let page=1;;page+=1){
  const {data}=await client.get('/fdrs',{params:{page,size:100}});
  if(!Array.isArray(data))throw new Error('FDR list response was not an array.');
  all.push(...data);
  if(data.length<100)return all;
 }
}

export default function ScrutinyQueue(){
 const[filter,setFilter]=useState('all');const q=useQuery({queryKey:['bureau-fdrs'],queryFn:getAllFdrs,refetchInterval:5000});
 const advisory=useQuery({queryKey:['official-ml-recommendations'],queryFn:()=>client.get('/workflows/recommendations').then(r=>r.data),refetchInterval:10000});
 const queue=useMemo(()=>{const all=(Array.isArray(q.data)?q.data:[]).filter(x=>['submitted','extraction_pending','extracting','validation_pending','validation_failed','correction_required','awaiting_institution','under_scrutiny','under_review','mismatch','ready_for_scrutiny','awaiting_official_decision'].includes((x.lifecycle_state||x.status||'').toLowerCase()));return all.filter(x=>filter==='all'||(filter==='priority'&&x.trust_badge==='mismatch')||(filter==='due'&&x.maturity_date&&new Date(x.maturity_date)<=new Date(Date.now()+30*86400000))).sort((a,b)=>(a.maturity_date||'9999').localeCompare(b.maturity_date||'9999'))},[q.data,filter]);
 const recommendations=advisory.data?.recommendations||[];const byFdr=new Map(recommendations.map(r=>[r.fdr_id,r]));
 return <section><div className="flex flex-wrap items-center justify-between gap-3"><div><h1 className="text-3xl font-bold">Verification queue</h1><p className="mt-1 text-slate-600">Sorted by due date with deterministic priority suggestions for operator review.</p></div><LiveStatus active={false}/></div><label className="my-4 block max-w-xs text-sm">Queue filter<select value={filter} onChange={e=>setFilter(e.target.value)} className="mt-1 w-full rounded border p-2"><option value="all">All awaiting review</option><option value="priority">Priority discrepancies</option><option value="due">Due within 30 days</option></select></label>{advisory.isError&&<ErrorState error={advisory.error} onRetry={()=>advisory.refetch()} label="Priority suggestions unavailable; deterministic queue order remains active"/>}{q.isLoading?<LoadingState label="Loading scrutiny queue"/>:q.isError?<ErrorState error={q.error} onRetry={()=>q.refetch()} label="Could not load scrutiny queue"/>:!queue.length?<EmptyState title="Nothing is waiting for scrutiny">Submitted cases will appear here for officer review.</EmptyState>:<div className="space-y-3">{queue.map(x=>{const suggestion=byFdr.get(x.id);return <Link key={x.id} to={`/official/review/${x.id}`} aria-label={`Review ${x.fdr_number}, maturity ${formatDate(x.maturity_date)}`} className="flex flex-wrap items-center justify-between gap-4 rounded-xl border bg-white p-4 hover:border-cyan-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-700"><div><div className="flex flex-wrap items-center gap-2"><b>{x.fdr_number}</b>{x.is_synthetic&&<DataOriginBadge isSynthetic/>}</div><p className="mt-1 text-sm text-slate-600">{x.bank_name} · Maturity due {formatDate(x.maturity_date)}</p>{suggestion&&<p className="mt-1 text-xs font-semibold text-indigo-950">{suggestion.recommendation} · advisory only</p>}</div><div className="flex flex-wrap items-center gap-4"><span>{formatINR(x.amount)}</span><StatusPill status={x.lifecycle_state||x.status}/><TrustBadge badge={x.trust_badge}/></div></Link>})}</div>}</section>;
}
