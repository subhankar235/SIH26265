import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useInfiniteQuery,useQuery } from '@tanstack/react-query';
import { client } from '../../api/client';
import { EmptyState,ErrorState,LoadingState,LiveStatus,DataOriginBadge } from '../../components/common/PageStates';
import StatusPill from '../../components/common/StatusPill';

async function loadWorkflowPage({pageParam,state}){
 const params={page_size:100};
 if(pageParam)params.before_id=pageParam;
 if(state!=='all')params.execution_state=state;
 const response=await client.get('/workflows/control-room',{params});
 return response.data;
}

export default function WorkflowControlRoom(){
 const[state,setState]=useState('all');
 const summary=useQuery({queryKey:['official-workflow-summary'],queryFn:async()=>(
  await client.get('/workflows/control-room/summary')
 ).data,refetchInterval:5000});
 const workflows=useInfiniteQuery({
  queryKey:['official-workflows',state],
  queryFn:({pageParam})=>loadWorkflowPage({pageParam,state}),
  initialPageParam:null,
  getNextPageParam:lastPage=>lastPage.has_more?lastPage.next_before_id:undefined,
 });
 const rows=workflows.data?.pages.flatMap(page=>page.items)||[];
 const counts=summary.data?.execution_state_counts||{};
 const refresh=()=>Promise.all([summary.refetch(),workflows.refetch()]);
 const isLoading=summary.isLoading||workflows.isLoading;
 const error=summary.error||workflows.error;
 return <section><div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-sm font-semibold uppercase tracking-wide text-indigo-700">AICTE Official</p><h1 className="mt-1 text-3xl font-bold">Workflow control room</h1><p className="mt-1 text-slate-600">Monitor running, failed, waiting, and human-gated work.</p></div><div className="flex items-center gap-3"><LiveStatus active={false}/><button type="button" className="rounded border px-3 py-2 text-sm" onClick={refresh} disabled={summary.isFetching||workflows.isFetching}>Refresh records</button></div></div>{isLoading?<LoadingState label="Loading workflow control room"/>:error?<ErrorState error={error} onRetry={refresh} label="Could not load workflow instances"/>:<><div className="my-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-7">{[['FDR records','total_fdrs'],['Total workflows','total_workflows'],['Running','running'],['Failed','failed'],['Blocked','blocked'],['Waiting for human','waiting_human'],['Paused','paused']].map(([label,key])=><article key={key} className="rounded-xl border bg-white p-4"><p className="text-xs uppercase text-slate-600">{label}</p><p className="mt-2 text-2xl font-bold">{summary.data?.[key]??counts[key]??0}</p></article>)}</div>{summary.data?.fdrs_without_workflow>0&&<div role="status" className="mb-4 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950"><strong>{summary.data.fdrs_without_workflow} FDR record(s) have no workflow instance.</strong> Back up the database, verify the backend DATABASE_URL, then run <code>python -m scripts.backfill_workflows</code> from the backend environment.</div>}<label className="mb-4 block max-w-xs text-sm">Filter execution state<select value={state} onChange={e=>setState(e.target.value)} className="mt-1 w-full rounded border p-2"><option value="all">All states</option>{Object.keys(counts).map(s=><option key={s} value={s}>{s}</option>)}</select></label>{!rows.length?<EmptyState title="No workflow instances match">New FDR submissions create workflow instances. Change the state filter to inspect other cases.</EmptyState>:<div className="overflow-x-auto rounded-xl border bg-white"><table className="w-full min-w-[820px] text-left text-sm"><thead className="bg-slate-50"><tr>{['Case','Lifecycle','Execution','Authorization','Current node','Updated','Details'].map(x=><th key={x} className="p-3">{x}</th>)}</tr></thead><tbody>{rows.map(row=><tr className="border-t" key={row.id}><td className="p-3">FDR #{row.fdr_id}{row.is_synthetic?<div className="mt-1"><DataOriginBadge isSynthetic/></div>:row.is_synthetic===null&&<span className="block text-xs">Origin unclassified</span>}</td><td className="p-3"><StatusPill status={row.lifecycle_state}/></td><td className="p-3"><StatusPill status={row.execution_state}/></td><td className="p-3">{row.authorization_state}</td><td className="p-3">{row.current_node||'—'}</td><td className="p-3">{row.updated_at?new Date(row.updated_at).toLocaleString():'—'}</td><td className="p-3"><Link className="font-semibold text-indigo-900 underline" to={`/official/workflows/${row.id}`}>Inspect workflow</Link></td></tr>)}</tbody></table>{workflows.hasNextPage&&<div className="border-t p-3 text-center"><button type="button" className="rounded border px-4 py-2 text-sm font-semibold" onClick={()=>workflows.fetchNextPage()} disabled={workflows.isFetchingNextPage}>{workflows.isFetchingNextPage?'Loading…':'Load more workflows'}</button></div>}</div>}</>}</section>;
}
