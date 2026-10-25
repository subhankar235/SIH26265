import { useEffect, useMemo, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import { client } from '../../api/client';

export default function WorkflowExecution(){
  const {id}=useParams(),[selected,setSelected]=useState(null),[reason,setReason]=useState(''),qc=useQueryClient();
  useEffect(()=>{
    const api=import.meta.env.VITE_API_URL||'/api/v1';
    const stream=new EventSource(`${api}/workflows/${id}/stream`,{withCredentials:true});
    const refresh=()=>qc.invalidateQueries({queryKey:['workflow',id]});
    stream.onmessage=refresh;stream.onopen=refresh;
    const eventTypes=['FDR_SUBMITTED','WORKFLOW_ROUTED','NODE_STARTED','NODE_SUCCEEDED','NODE_FAILED',
      'WORKFLOW_PAUSED','WORKFLOW_RESUMED','CORRECTION_RECEIVED','CORRECTION_SLA_EXPIRED',
      'OFFICIAL_FDR_DECISION','OFFICIAL_REVIEW_STARTED','VERIFICATION_RESULT','WORKFLOW_REPLAY_REQUESTED',
      'WORKFLOW_NODE_RETRY_REQUESTED','MANUAL_REPROCESS_REQUESTED','EXCEPTION_CLAIMED','EXCEPTION_RESOLVED',
      'OFFICIAL_ESCALATED_EXCEPTION','RELEASE_APPROVED','RELEASE_REJECTED','WORKER_LEASE_EXPIRED'];
    eventTypes.forEach(type=>stream.addEventListener(type,refresh));
    return()=>stream.close();
  },[id,qc]);
  const query=useQuery({queryKey:['workflow',id],queryFn:()=>client.get(`/workflows/${id}`).then(r=>r.data),refetchInterval:5000});
  const workflow=query.data;const nodes=workflow?.nodes||[];
  const chosen=useMemo(()=>nodes.find(n=>n.id===selected)||nodes[nodes.length-1], [nodes,selected]);
  const retry=useMutation({mutationFn:node=>client.post(`/workflows/executions/${node.id}/retry`,{
    reason:reason||'Official requested a retry after inspecting the failed node.',idempotency_key:crypto.randomUUID(),acknowledge_side_effects:false}),
    onSuccess:()=>qc.invalidateQueries({queryKey:['workflow',id]})});
  const replay=useMutation({mutationFn:checkpoint=>client.post(`/workflows/${id}/replay`,{
    checkpoint_id:checkpoint.id,reason:reason||'Official requested checkpoint replay after inspection.',
    idempotency_key:crypto.randomUUID(),acknowledge_side_effects:false}),
    onSuccess:()=>qc.invalidateQueries({queryKey:['workflow',id]})});
  const pause=useMutation({mutationFn:()=>client.post(`/workflows/${id}/pause`,{reason:reason||'Official paused for inspection.',idempotency_key:crypto.randomUUID()}),onSuccess:()=>qc.invalidateQueries({queryKey:['workflow',id]})});
  const resume=useMutation({mutationFn:()=>client.post(`/workflows/${id}/resume`,{reason:reason||'Official resumed after inspection.',idempotency_key:crypto.randomUUID()}),onSuccess:()=>qc.invalidateQueries({queryKey:['workflow',id]})});
  if(query.isLoading)return <p>Loading workflow…</p>;if(query.isError)return <p role="alert" className="text-red-700">Could not load workflow.</p>;
  return <section><p className="text-sm font-semibold uppercase tracking-wide text-indigo-700">AICTE Official · Workflow {workflow.id}</p><h1 className="mb-2 mt-1 text-3xl font-bold">FDR #{workflow.fdr_id}</h1><p className="mb-4 text-sm text-slate-600">Version {workflow.workflow_version} · execution {workflow.execution_version} · {workflow.lifecycle_state} / {workflow.execution_state} / authorization {workflow.authorization_state}</p>
    <div className="mb-5 flex flex-wrap gap-2">{nodes.map((node,index)=><button key={node.id} onClick={()=>setSelected(node.id)} className={`rounded-full border px-4 py-2 text-sm ${chosen?.id===node.id?'border-indigo-700 bg-indigo-50':'bg-white'}`}><span className="mr-2 text-slate-500">{index+1}</span>{node.node_key} · {node.status} #{node.attempt}</button>)}</div>
    <div className="grid gap-5 xl:grid-cols-[1fr_380px]"><div className="space-y-5"><article className="rounded-xl border bg-white p-5"><h2 className="font-semibold">Execution timeline</h2><ol className="mt-3 space-y-3">{workflow.events.map(event=><li key={event.id} className="border-l-2 border-indigo-200 pl-3"><p className="font-medium">{event.event_type}</p><p className="text-xs text-slate-500">{new Date(event.received_at).toLocaleString()}</p></li>)}</ol></article><article className="rounded-xl border bg-white p-5"><h2 className="font-semibold">Pure-node checkpoints</h2><p className="mt-1 text-xs text-slate-500">Only checkpoints whose node has no side effect are replayed without additional acknowledgement.</p><div className="mt-3 flex flex-wrap gap-2">{workflow.checkpoints.filter(cp=>nodes.find(node=>node.id===cp.node_execution_id)?.node_key==='extract_document').map(cp=><button key={cp.id} onClick={()=>replay.mutate(cp)} className="rounded border px-3 py-2 text-sm">Replay extraction checkpoint #{cp.id}</button>)}</div></article></div>
      <aside className="h-fit rounded-xl border bg-white p-5"><h2 className="font-semibold">Node inspection</h2>{chosen?<><p className="mt-2 text-sm">{chosen.node_key} · attempt {chosen.attempt} · {chosen.status}</p><p className="mt-1 text-xs text-slate-500">Duration: {chosen.duration_ms??'—'} ms · workflow {workflow.workflow_version}</p><label className="mt-4 block text-sm">Operator reason<textarea className="mt-1 w-full rounded border p-2" value={reason} onChange={e=>setReason(e.target.value)} placeholder="Required for recovery actions"/></label><details className="mt-4"><summary className="cursor-pointer font-medium">Input reference</summary><pre className="mt-2 overflow-auto rounded bg-slate-50 p-2 text-xs">{JSON.stringify(chosen.input_ref,null,2)}</pre></details><details className="mt-3"><summary className="cursor-pointer font-medium">Output / error</summary><pre className="mt-2 overflow-auto rounded bg-slate-50 p-2 text-xs">{JSON.stringify({output:chosen.output_ref,error_class:chosen.error_class,error_code:chosen.error_code,error_message:chosen.error_message},null,2)}</pre></details>{chosen.status==='failed'&&<button onClick={()=>retry.mutate(chosen)} disabled={reason.trim().length<4||retry.isPending} className="mt-4 rounded bg-indigo-950 px-3 py-2 text-sm text-white disabled:opacity-50">Retry failed node</button>}</>:<p className="mt-3 text-sm text-slate-500">No persisted node attempts yet.</p>}<div className="mt-4 flex gap-2">{workflow.execution_state==='paused'?<button onClick={()=>resume.mutate()} disabled={reason.trim().length<4} className="rounded border px-3 py-2">Resume</button>:<button onClick={()=>pause.mutate()} disabled={reason.trim().length<4||pause.isPending} className="rounded border px-3 py-2">Pause when idle</button>}</div>{(retry.isError||replay.isError||pause.isError||resume.isError)&&<p role="alert" className="mt-3 text-sm text-red-700">Action rejected or case changed; reload workflow state and inspect the current node.</p>}</aside></div>
  </section>;
}
