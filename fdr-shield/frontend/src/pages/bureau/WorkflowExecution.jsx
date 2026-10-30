import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { client } from '../../api/client';
import ConfirmDialog from '../../components/common/ConfirmDialog';
import { ErrorState, LoadingState, LiveStatus, DataOriginBadge, useToast } from '../../components/common/PageStates';
import WorkflowCanvas from '../../components/workflow/WorkflowCanvas';

export default function WorkflowExecution({ Canvas = WorkflowCanvas }) {
  const { id } = useParams();
  const [selectedNodeKey,setSelectedNodeKey]=useState(null);
  const [componentSearch,setComponentSearch]=useState('');
  const [reason,setReason]=useState('');
  const [sseActive,setSseActive]=useState(false);
  const [pendingAction,setPendingAction]=useState(null);
  const qc=useQueryClient();
  const toast=useToast();

  useEffect(()=>{setSelectedNodeKey(null);setReason('');},[id]);

  const query=useQuery({
    queryKey:['workflow',id],
    queryFn:()=>client.get(`/workflows/${id}`).then(r=>r.data),
    refetchInterval:sseActive?15000:3000,
  });
  const workflow=query.data;
  const nodes=workflow?.nodes||[];
  const definition=workflow?.definition||{nodes:[],outcomes:[],edges:[],editable:false};
  const latestByKey=useMemo(()=>{
    const latest=new Map();
    for(const node of nodes){const old=latest.get(node.node_key);if(!old||node.id>old.id)latest.set(node.node_key,node);}
    return latest;
  },[nodes]);
  const activeNodeKey=selectedNodeKey||workflow?.current_node||nodes[nodes.length-1]?.node_key||null;
  const chosen=activeNodeKey?latestByKey.get(activeNodeKey)||null:null;
  const selectedDefinition=definition.nodes.find(node=>node.key===activeNodeKey);
  const selectedOutcome=definition.outcomes?.find(outcome=>outcome.id===activeNodeKey);
  const checkpoints=workflow?.checkpoints||[];

  useEffect(()=>{
    if(!workflow?.id)return;
    if(typeof EventSource==='undefined'){setSseActive(false);return;}
    const api=import.meta.env.VITE_API_URL||'/api/v1';
    const stream=new EventSource(`${api}/workflows/${id}/stream`,{withCredentials:true});
    const refresh=()=>qc.invalidateQueries({queryKey:['workflow',id]});
    stream.onopen=()=>{setSseActive(true);refresh();};
    stream.onmessage=refresh;
    const eventTypes=['node.started','node.succeeded','node.failed','state.changed','exception.created',
      'approval.recorded','FDR_SUBMITTED','WORKFLOW_ROUTED','NODE_STARTED','NODE_SUCCEEDED','NODE_FAILED',
      'WORKFLOW_PAUSED','WORKFLOW_RESUMED','CORRECTION_RECEIVED','CORRECTION_SLA_EXPIRED',
      'OFFICIAL_FDR_DECISION','OFFICIAL_REVIEW_STARTED','VERIFICATION_RESULT','WORKFLOW_REPLAY_REQUESTED',
      'WORKFLOW_NODE_RETRY_REQUESTED','MANUAL_REPROCESS_REQUESTED','EXCEPTION_CLAIMED','EXCEPTION_RESOLVED',
      'OFFICIAL_ESCALATED_EXCEPTION','RELEASE_APPROVED','RELEASE_REJECTED','WORKER_LEASE_EXPIRED'];
    eventTypes.forEach(type=>stream.addEventListener(type,refresh));
    stream.onerror=()=>setSseActive(false);
    return()=>stream.close();
  },[id,qc,workflow?.id]);

  const nodeDetails=useQuery({
    queryKey:['workflow-execution-detail',chosen?.id],
    queryFn:()=>client.get(`/workflows/executions/${chosen.id}`).then(r=>r.data),
    enabled:Boolean(chosen?.id),
  });
  const retry=useMutation({
    mutationFn:node=>client.post(`/workflows/executions/${node.id}/retry`,{
      reason:reason.trim(),idempotency_key:crypto.randomUUID(),acknowledge_side_effects:false,
    }),
    onSuccess:()=>{toast('Retry was recorded and queued.');qc.invalidateQueries({queryKey:['workflow',id]});},
    onError:()=>qc.invalidateQueries({queryKey:['workflow',id]}),
  });
  const replay=useMutation({
    mutationFn:checkpoint=>client.post(`/workflows/${id}/replay`,{
      checkpoint_id:checkpoint.id,reason:reason.trim(),idempotency_key:crypto.randomUUID(),
      acknowledge_side_effects:false,
    }),
    onSuccess:()=>{toast('Extraction checkpoint replay was recorded and queued.');qc.invalidateQueries({queryKey:['workflow',id]});},
    onError:()=>qc.invalidateQueries({queryKey:['workflow',id]}),
  });
  const pause=useMutation({
    mutationFn:()=>client.post(`/workflows/${id}/pause`,{reason:reason.trim(),idempotency_key:crypto.randomUUID()}),
    onSuccess:()=>{toast('Pause request recorded.');qc.invalidateQueries({queryKey:['workflow',id]});},
    onError:()=>qc.invalidateQueries({queryKey:['workflow',id]}),
  });
  const resume=useMutation({
    mutationFn:()=>client.post(`/workflows/${id}/resume`,{reason:reason.trim(),idempotency_key:crypto.randomUUID()}),
    onSuccess:()=>{toast('Resume request recorded.');qc.invalidateQueries({queryKey:['workflow',id]});},
    onError:()=>qc.invalidateQueries({queryKey:['workflow',id]}),
  });
  const comparison=useMutation({
    mutationFn:({a,b})=>client.get(`/workflows/${id}/compare`,{params:{a,b}}).then(r=>r.data),
  });
  const [compareA,setCompareA]=useState(''),[compareB,setCompareB]=useState('');

  if(query.isLoading)return <LoadingState label="Loading persisted workflow execution"/>;
  if(query.isError)return <ErrorState error={query.error} onRetry={()=>query.refetch()} label="Could not load persisted workflow execution"/>;

  const latestForSelected=activeNodeKey?latestByKey.get(activeNodeKey):null;
  const extractionCheckpoints=checkpoints.filter(cp=>
    nodes.find(node=>node.id===cp.node_execution_id)?.node_key==='extract_document');
  const visibleDefinitionNodes=definition.nodes.filter(node=>
    `${node.key} ${node.label} ${node.side_effect_class}`.toLowerCase().includes(componentSearch.trim().toLowerCase()));
  const canPause=!['paused','completed','failed','blocked','cancelled'].includes(workflow.execution_state)&&!workflow.worker_busy;
  const canResume=workflow.execution_state==='paused';
  const actionError=retry.error||replay.error||pause.error||resume.error;

  return <section className="space-y-4">
    <header className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border bg-white p-4">
      <div className="flex min-w-0 items-center gap-3">
        <Link className="rounded border px-3 py-2 text-sm" to="/official/control-room">← Control Room</Link>
        <div className="min-w-0"><p className="text-xs font-semibold uppercase tracking-wide text-indigo-700">AICTE · fixed backend workflow</p>
          <h1 className="truncate text-xl font-bold">FDR #{workflow.fdr_id} · execution {workflow.execution_version}</h1>
          <p className="text-xs text-slate-600">Definition {definition.version||workflow.workflow_version} · lifecycle {workflow.lifecycle_state} · execution {workflow.execution_state} · authorization {workflow.authorization_state}</p>
          {workflow.is_synthetic&&<DataOriginBadge isSynthetic/>}
        </div>
      </div>
      <div className="flex items-center gap-2">
        <LiveStatus active={sseActive}/>
        <button type="button" disabled title="This workflow graph is fixed by the backend; arbitrary definition editing is not supported." className="rounded border px-3 py-2 text-sm opacity-50">Save Draft</button>
        <button type="button" disabled title="Publishing arbitrary workflow definitions is not supported; backend transitions remain authoritative." className="rounded bg-indigo-950 px-3 py-2 text-sm font-semibold text-white opacity-50">Publish</button>
      </div>
    </header>

    <div className="grid min-h-[700px] gap-3 xl:grid-cols-[230px_minmax(500px,1fr)_330px]">
      <aside className="space-y-4 rounded-2xl border bg-slate-950 p-4 text-slate-100">
        <div><h2 className="font-semibold">Workflow components</h2><p className="mt-1 text-xs text-slate-400">Backend-registered executor stages for this workflow version.</p></div>
        <label className="block text-xs font-semibold text-slate-300">Search components
          <input value={componentSearch} onChange={event=>setComponentSearch(event.target.value)}
            className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white"
            placeholder="Search workflow stages"/>
        </label>
        <section><h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-400">Trigger</h3>
          <button type="button" onClick={()=>setSelectedNodeKey(null)} className="w-full rounded-lg border border-slate-700 bg-slate-900 p-3 text-left text-sm">
            <span className="block font-semibold">FDR submission received</span><span className="mt-1 block text-xs text-slate-400">Starts a persisted execution; trigger is not an executor node.</span>
          </button>
        </section>
        <section><h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-400">Processing nodes</h3>
          <div className="space-y-2">{visibleDefinitionNodes.map(node=>{
            const attempt=latestByKey.get(node.key);
            return <button type="button" key={node.key} onClick={()=>setSelectedNodeKey(node.key)}
              className={`w-full rounded-lg border p-3 text-left ${activeNodeKey===node.key?'border-blue-400 bg-blue-950':'border-slate-700 bg-slate-900 hover:border-slate-500'}`}>
              <span className="block text-sm font-semibold">{node.label}</span>
              <span className="mt-1 block text-xs capitalize text-slate-400">{attempt?.status||'not started'} · {node.side_effect_class}</span>
            </button>;
          })}</div>
        </section>
        <section><h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-400">Routing outcomes</h3>
          <div className="space-y-2">{definition.outcomes.map(outcome=><button type="button" key={outcome.id}
            onClick={()=>setSelectedNodeKey(outcome.id)} className={`w-full rounded-lg border p-3 text-left text-sm ${activeNodeKey===outcome.id?'border-blue-400 bg-blue-950':'border-slate-700 bg-slate-900'}`}>
            <span className="block font-semibold">{outcome.label}</span><span className="mt-1 block text-xs text-slate-400">Business lifecycle state · not an executable node</span>
          </button>)}</div>
        </section>
        <div className="rounded-lg border border-amber-900 bg-amber-950/40 p-3 text-xs text-amber-100">The LLM does not create workflow nodes, transitions, or approval decisions.</div>
      </aside>

      <main className="min-w-0 space-y-3 rounded-2xl border bg-slate-900 p-3">
        <div className="flex flex-wrap items-center justify-between gap-3 px-1 text-sm text-slate-300">
          <div><strong className="text-white">Execution graph</strong><span className="ml-2">Live state from persisted node attempts</span></div>
          <span className="text-xs">{nodes.length} node attempt(s) · {workflow.events.length} event(s)</span>
        </div>
        <Canvas definition={definition} executions={nodes} workflow={workflow}
          selectedNodeKey={activeNodeKey} onSelectNode={(key)=>setSelectedNodeKey(key)}/>
        <section className="rounded-xl border border-slate-700 bg-slate-950 p-4 text-slate-100">
          <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="font-semibold">Persisted execution timeline</h2><span className="text-xs text-slate-400">Newest events shown last</span></div>
          {!workflow.events.length?<p className="mt-3 text-sm text-slate-400">No workflow events have been recorded yet.</p>:
            <ol className="mt-3 max-h-52 space-y-2 overflow-auto">{workflow.events.slice(-30).map(event=><li key={event.id} className="flex flex-wrap justify-between gap-2 border-l-2 border-indigo-500 pl-3 text-sm">
              <span>{event.event_type}</span><time className="text-xs text-slate-400">{new Date(event.received_at).toLocaleString()}</time>
            </li>)}</ol>}
        </section>
      </main>

      <aside className="h-fit space-y-4 rounded-2xl border bg-white p-4">
        <div><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Selected block</p>
          <h2 className="mt-1 font-semibold">{selectedOutcome?.label||selectedDefinition?.label||'Select a workflow node'}</h2>
          {selectedDefinition&&<p className="mt-1 text-xs text-slate-500">{selectedDefinition.key} · {selectedDefinition.side_effect_class}</p>}
        </div>
        {selectedOutcome?<div className="rounded-lg bg-slate-50 p-3 text-sm"><p>Business outcome: <strong>{selectedOutcome.state}</strong></p><p className="mt-1 text-xs text-slate-500">This state is produced by route_case; it is not a separate worker node.</p></div>:
          selectedDefinition?<div className="space-y-3">
            <div className="grid grid-cols-2 gap-2 text-xs"><div className="rounded bg-slate-50 p-2"><span className="text-slate-500">Max attempts</span><strong className="block">{selectedDefinition.max_attempts}</strong></div><div className="rounded bg-slate-50 p-2"><span className="text-slate-500">Timeout</span><strong className="block">{selectedDefinition.timeout_seconds}s</strong></div></div>
            {latestForSelected?<>
              <div className="rounded-lg border p-3 text-sm"><strong className="capitalize">{latestForSelected.status}</strong><span className="ml-2 text-xs text-slate-500">attempt #{latestForSelected.attempt}</span>
                <p className="mt-1 text-xs text-slate-500">Started: {latestForSelected.started_at?new Date(latestForSelected.started_at).toLocaleString():'—'}</p>
                <p className="text-xs text-slate-500">Finished: {latestForSelected.finished_at?new Date(latestForSelected.finished_at).toLocaleString():'—'} · Duration: {latestForSelected.duration_ms??'—'} ms</p>
              </div>
              <details><summary className="cursor-pointer text-sm font-medium">Input reference</summary><pre className="mt-2 max-h-36 overflow-auto rounded bg-slate-50 p-2 text-xs">{JSON.stringify(latestForSelected.input_ref,null,2)}</pre></details>
              <details open={latestForSelected.status==='failed'}><summary className="cursor-pointer text-sm font-medium">Output / error</summary><pre className="mt-2 max-h-44 overflow-auto whitespace-pre-wrap rounded bg-slate-50 p-2 text-xs">{JSON.stringify({output:latestForSelected.output_ref,error_class:latestForSelected.error_class,error_code:latestForSelected.error_code,error_message:latestForSelected.error_message},null,2)}</pre></details>
              {nodeDetails.data?.diagnostics&&<details><summary className="cursor-pointer text-sm font-medium">Diagnostics</summary><pre className="mt-2 max-h-36 overflow-auto rounded bg-slate-50 p-2 text-xs">{JSON.stringify(nodeDetails.data.diagnostics,null,2)}</pre></details>}
              {latestForSelected.status==='failed'&&<button onClick={()=>setPendingAction({title:'Retry failed node',message:`Retry ${latestForSelected.node_key} attempt ${latestForSelected.attempt}; the backend will validate retry eligibility and side effects.`,run:()=>retry.mutate(latestForSelected)})} disabled={reason.trim().length<4||retry.isPending} className="w-full rounded bg-indigo-950 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50">{retry.isPending?'Queueing retry…':'Retry failed node'}</button>}
            </>:<p className="rounded-lg bg-slate-50 p-3 text-sm text-slate-600">No execution attempt has been recorded for this node.</p>}
            {selectedDefinition.key==='extract_document'&&extractionCheckpoints.length>0&&<div className="space-y-2 border-t pt-3"><h3 className="text-sm font-semibold">Pure extraction checkpoints</h3>{extractionCheckpoints.map(checkpoint=><button key={checkpoint.id} onClick={()=>setPendingAction({title:'Replay extraction checkpoint',message:`Replay persisted extraction checkpoint #${checkpoint.id}. The backend will validate the checkpoint and enqueue execution.`,run:()=>replay.mutate(checkpoint)})} disabled={reason.trim().length<4||replay.isPending} className="w-full rounded border px-3 py-2 text-left text-xs disabled:opacity-50">Replay checkpoint #{checkpoint.id}</button>)}</div>}
          </div>:<p className="text-sm text-slate-500">Select a processing node or routing outcome from the graph.</p>}

        <label className="block text-sm font-medium">Operator reason<textarea value={reason} onChange={event=>setReason(event.target.value)} minLength={4} maxLength={1000} className="mt-1 w-full rounded border p-2 text-sm" placeholder="Required for recovery actions"/></label>
        {canResume?<button onClick={()=>setPendingAction({title:'Resume workflow',message:'Resume from the persisted execution state; the worker queue may process follow-up nodes.',run:()=>resume.mutate()})} disabled={reason.trim().length<4||resume.isPending} className="w-full rounded border border-indigo-700 bg-indigo-50 px-3 py-2 text-sm font-semibold text-indigo-900 disabled:opacity-50">{resume.isPending?'Resuming…':'Resume execution'}</button>:
          <button onClick={()=>setPendingAction({title:'Pause workflow',message:'This will pause a workflow that is currently idle. If a worker is processing a node, wait for that node to finish before pausing.',run:()=>pause.mutate()})} disabled={!canPause||reason.trim().length<4||pause.isPending} className="w-full rounded border px-3 py-2 text-sm font-semibold disabled:opacity-50">{pause.isPending?'Pausing…':workflow.worker_busy?'Node is processing':'Pause idle workflow'}</button>}
        <section className="border-t pt-3"><h3 className="text-sm font-semibold">Compare node attempts</h3><div className="mt-2 grid grid-cols-2 gap-2"><label className="text-xs">Attempt A<select value={compareA} onChange={e=>setCompareA(e.target.value)} className="mt-1 w-full rounded border p-2"><option value="">Select</option>{nodes.map(node=><option key={node.id} value={node.id}>{node.node_key} #{node.attempt}</option>)}</select></label><label className="text-xs">Attempt B<select value={compareB} onChange={e=>setCompareB(e.target.value)} className="mt-1 w-full rounded border p-2"><option value="">Select</option>{nodes.map(node=><option key={node.id} value={node.id}>{node.node_key} #{node.attempt}</option>)}</select></label></div><button disabled={!compareA||!compareB||comparison.isPending} onClick={()=>comparison.mutate({a:Number(compareA),b:Number(compareB)})} className="mt-2 rounded border px-3 py-2 text-sm disabled:opacity-50">Compare</button>{comparison.data&&<pre className="mt-2 max-h-36 overflow-auto rounded bg-slate-50 p-2 text-xs">{JSON.stringify(comparison.data,null,2)}</pre>}</section>
        {(actionError||comparison.error)&&<ErrorState error={actionError||comparison.error} label="Workflow operation was rejected or failed"/>}
      </aside>
    </div>

    <ConfirmDialog open={Boolean(pendingAction)} title={pendingAction?.title} message={pendingAction?.message} onCancel={()=>setPendingAction(null)} onConfirm={()=>{const run=pendingAction?.run;setPendingAction(null);run?.();}}/>
  </section>;
}
