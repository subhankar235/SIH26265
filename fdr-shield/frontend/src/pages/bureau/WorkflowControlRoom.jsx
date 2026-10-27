import { useMemo,useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { client } from '../../api/client';
import { EmptyState,ErrorState,LoadingState,LiveStatus,DataOriginBadge } from '../../components/common/PageStates';
import StatusPill from '../../components/common/StatusPill';

async function loadAllWorkflows(){
 const size=100,all=[];let page=1;
 while(true){
  const response=await client.get('/workflows',{params:{page,size}});
  const rows=Array.isArray(response.data)?response.data:[];
  all.push(...rows);
  if(rows.length<size) return all;
  page+=1;
 }
}

export default function WorkflowControlRoom(){
 const[state,setState]=useState('all');const query=useQuery({queryKey:['official-workflows'],queryFn:loadAllWorkflows,refetchInterval:5000});
 const rows=Array.isArray(query.data)?query.data:[];const shown=useMemo(()=>rows.filter(w=>state==='all'||w.execution_state===state),[rows,state]);
 const count=s=>rows.filter(w=>w.execution_state===s).length;
 return <section><div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-sm font-semibold uppercase tracking-wide text-indigo-700">AICTE Official</p><h1 className="mt-1 text-3xl font-bold">Workflow control room</h1><p className="mt-1 text-slate-600">Monitor running, failed, waiting, and human-gated work.</p></div><LiveStatus active={false}/></div>{query.isLoading?<LoadingState label="Loading workflow control room"/>:query.isError?<ErrorState error={query.error} onRetry={()=>query.refetch()} label="Could not load workflow instances"/>:<><div className="my-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">{['running','failed','blocked','waiting_human','paused'].map(s=><article key={s} className="rounded-xl border bg-white p-4"><p className="text-xs uppercase text-slate-600">{s.replaceAll('_',' ')}</p><p className="mt-2 text-2xl font-bold">{count(s)}</p></article>)}</div><label className="mb-4 block max-w-xs text-sm">Filter execution state<select value={state} onChange={e=>setState(e.target.value)} className="mt-1 w-full rounded border p-2"><option value="all">All states</option>{[...new Set(rows.map(w=>w.execution_state))].map(s=><option key={s} value={s}>{s}</option>)}</select></label>{!shown.length?<EmptyState title="No workflow instances match">New FDR submissions create workflow instances. Change the state filter to inspect other cases.</EmptyState>:<div className="overflow-x-auto rounded-xl border bg-white"><table className="w-full min-w-[820px] text-left text-sm"><thead className="bg-slate-50"><tr>{['Case','Lifecycle','Execution','Authorization','Current node','Updated','Details'].map(x=><th key={x} className="p-3">{x}</th>)}</tr></thead><tbody>{shown.map(row=><tr className="border-t" key={row.id}><td className="p-3">FDR #{row.fdr_id}{row.is_synthetic?<div className="mt-1"><DataOriginBadge isSynthetic/></div>:row.is_synthetic===null&&<span className="block text-xs">Origin unclassified</span>}</td><td className="p-3"><StatusPill status={row.lifecycle_state}/></td><td className="p-3"><StatusPill status={row.execution_state}/></td><td className="p-3">{row.authorization_state}</td><td className="p-3">{row.current_node||'—'}</td><td className="p-3">{row.updated_at?new Date(row.updated_at).toLocaleString():'—'}</td><td className="p-3"><Link className="font-semibold text-indigo-900 underline" to={`/official/workflows/${row.id}`}>Inspect workflow</Link></td></tr>)}</tbody></table></div>}</>}</section>;
}
