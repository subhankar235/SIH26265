import { useEffect, useMemo, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import { client } from '../../api/client';
import ConfirmDialog from '../../components/common/ConfirmDialog';
import { ErrorState, LoadingState, LiveStatus, DataOriginBadge, useToast } from '../../components/common/PageStates';

export default function WorkflowExecution() {
  const { id } = useParams();
  const [selected, setSelected] = useState(null);
  const [reason, setReason] = useState('');
  const [sseActive, setSseActive] = useState(false);
  const [pendingAction, setPendingAction] = useState(null);
  const qc = useQueryClient();
  const toast = useToast();

  useEffect(() => {
    const api = import.meta.env.VITE_API_URL || '/api/v1';
    const stream = new EventSource(`${api}/workflows/${id}/stream`, { withCredentials: true });
    const refresh = () => qc.invalidateQueries({ queryKey: ['workflow', id] });

    stream.onopen = () => {
      setSseActive(true);
      refresh();
    };

    stream.onmessage = refresh;

    const eventTypes = [
      'node.started', 'node.succeeded', 'node.failed', 'state.changed',
      'exception.created', 'approval.recorded', 'command.progress',
      'FDR_SUBMITTED', 'WORKFLOW_ROUTED', 'NODE_STARTED', 'NODE_SUCCEEDED', 'NODE_FAILED',
      'WORKFLOW_PAUSED', 'WORKFLOW_RESUMED', 'CORRECTION_RECEIVED', 'CORRECTION_SLA_EXPIRED',
      'OFFICIAL_FDR_DECISION', 'OFFICIAL_REVIEW_STARTED', 'VERIFICATION_RESULT', 'WORKFLOW_REPLAY_REQUESTED',
      'WORKFLOW_NODE_RETRY_REQUESTED', 'MANUAL_REPROCESS_REQUESTED', 'EXCEPTION_CLAIMED', 'EXCEPTION_RESOLVED',
      'OFFICIAL_ESCALATED_EXCEPTION', 'RELEASE_APPROVED', 'RELEASE_REJECTED', 'WORKER_LEASE_EXPIRED',
    ];

    eventTypes.forEach((type) => stream.addEventListener(type, refresh));

    stream.onerror = () => {
      // Phase 8.5: Fallback to polling every 3 seconds if SSE blocked
      setSseActive(false);
    };

    return () => stream.close();
  }, [id, qc]);

  // Phase 8.5: Fallback polling: polls every 3s if SSE blocked; slows to 15s when SSE is active
  const query = useQuery({
    queryKey: ['workflow', id],
    queryFn: () => client.get(`/workflows/${id}`).then((r) => r.data),
    refetchInterval: sseActive ? 15000 : 3000,
  });

  const workflow = query.data;
  const nodes = workflow?.nodes || [];
  const chosen = useMemo(() => nodes.find((n) => n.id === selected) || nodes[nodes.length - 1], [nodes, selected]);
  const [compareA,setCompareA]=useState(''),[compareB,setCompareB]=useState('');
  const nodeDetails=useQuery({queryKey:['workflow-execution-detail',chosen?.id],queryFn:()=>client.get(`/workflows/executions/${chosen.id}`).then(r=>r.data),enabled:Boolean(chosen?.id)});
  const comparison=useMutation({mutationFn:()=>client.get(`/workflows/${id}/compare`,{params:{a:Number(compareA),b:Number(compareB)}}).then(r=>r.data)});

  const retry = useMutation({
    mutationFn: (node) =>
      client.post(`/workflows/executions/${node.id}/retry`, {
        reason: reason || 'Official requested a retry after inspecting the failed node.',
        idempotency_key: crypto.randomUUID(),
        acknowledge_side_effects: false,
      }),
    onSuccess: () => { toast('Failed workflow node retry queued.'); qc.invalidateQueries({ queryKey: ['workflow', id] }); },
    onError: () => qc.invalidateQueries({ queryKey: ['workflow', id] }),
  });

  const replay = useMutation({
    mutationFn: (checkpoint) =>
      client.post(`/workflows/${id}/replay`, {
        checkpoint_id: checkpoint.id,
        reason: reason || 'Official requested checkpoint replay after inspection.',
        idempotency_key: crypto.randomUUID(),
        acknowledge_side_effects: false,
      }),
    onSuccess: () => { toast('Workflow replay queued.'); qc.invalidateQueries({ queryKey: ['workflow', id] }); },
    onError: () => qc.invalidateQueries({ queryKey: ['workflow', id] }),
  });

  const pause = useMutation({
    mutationFn: () =>
      client.post(`/workflows/${id}/pause`, {
        reason: reason || 'Official paused for inspection.',
        idempotency_key: crypto.randomUUID(),
      }),
    onSuccess: () => { toast('Workflow pause requested.'); qc.invalidateQueries({ queryKey: ['workflow', id] }); },
    onError: () => qc.invalidateQueries({ queryKey: ['workflow', id] }),
  });

  const resume = useMutation({
    mutationFn: () =>
      client.post(`/workflows/${id}/resume`, {
        reason: reason || 'Official resumed after inspection.',
        idempotency_key: crypto.randomUUID(),
      }),
    onSuccess: () => { toast('Workflow resume requested.'); qc.invalidateQueries({ queryKey: ['workflow', id] }); },
    onError: () => qc.invalidateQueries({ queryKey: ['workflow', id] }),
  });

  if (query.isLoading) return <LoadingState label="Loading workflow"/>;
  if (query.isError) return <ErrorState error={query.error} onRetry={()=>query.refetch()} label="Could not load workflow"/>;

  return (
    <section>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold uppercase tracking-wide text-indigo-700">
            AICTE Official · Workflow {workflow.id}
          </p>
          <h1 className="mb-2 mt-1 text-3xl font-bold">FDR #{workflow.fdr_id}</h1>
          {workflow.is_synthetic&&<DataOriginBadge isSynthetic/>}
        </div>
        <span
          className={`rounded-full px-3 py-1 text-xs font-semibold ${
            sseActive ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800'
          }`}
        >
          {sseActive ? 'Live updates · SSE' : 'Polling fallback · 3s'}
        </span>
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-3 text-sm text-slate-600"><LiveStatus active={sseActive}/><p>
        Version {workflow.workflow_version} · execution {workflow.execution_version} · {workflow.lifecycle_state} /{' '}
        {workflow.execution_state} / authorization {workflow.authorization_state}
      </p></div>

      <div className="mb-5 flex flex-wrap gap-2">
        {nodes.map((node, index) => (
          <button
            key={node.id}
            onClick={() => setSelected(node.id)}
            className={`rounded-full border px-4 py-2 text-sm ${
              chosen?.id === node.id ? 'border-indigo-700 bg-indigo-50 font-semibold' : 'bg-white'
            }`}
          >
            <span className="mr-2 text-slate-500">{index + 1}</span>
            {node.node_key} · {node.status} #{node.attempt}
          </button>
        ))}
      </div>

      <div className="grid gap-5 xl:grid-cols-[1fr_380px]">
        <div className="space-y-5">
          <article className="rounded-xl border bg-white p-5">
            <h2 className="font-semibold text-slate-900">Workflow graph & execution timeline</h2>
            <ol aria-label="Workflow node graph" className="mt-4 flex flex-wrap items-center gap-2">{nodes.map((node,index)=><li key={`graph-${node.id}`} className="flex items-center gap-2"><button onClick={()=>setSelected(node.id)} className={`rounded-lg border px-3 py-2 text-xs font-semibold ${chosen?.id===node.id?'border-indigo-700 bg-indigo-50':'bg-white'}`} aria-label={`Inspect ${node.node_key} node, ${node.status}`}>{node.node_key}<span className="block">{node.status}</span></button>{index<nodes.length-1&&<span aria-hidden="true">→</span>}</li>)}</ol>
            <ol className="mt-3 space-y-3">
              {workflow.events.map((event) => (
                <li key={event.id} className="border-l-2 border-indigo-200 pl-3">
                  <p className="font-medium text-slate-900">{event.event_type}</p>
                  <p className="text-xs text-slate-500">{new Date(event.received_at).toLocaleString()}</p>
                </li>
              ))}
            </ol>
          </article>

          <article className="rounded-xl border bg-white p-5">
            <h2 className="font-semibold text-slate-900">Pure-node checkpoints</h2>
            <p className="mt-1 text-xs text-slate-500">
              Only checkpoints whose node has no side effect are replayed without additional acknowledgement.
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {workflow.checkpoints
                .filter((cp) => nodes.find((node) => node.id === cp.node_execution_id)?.node_key === 'extract_document')
                .map((cp) => (
                  <button
                    key={cp.id}
                    onClick={() => setPendingAction({title:'Replay extraction checkpoint',message:`Replay checkpoint #${cp.id}. This schedules a workflow run from preserved extraction output.`,run:()=>replay.mutate(cp)})}
                    className="rounded border px-3 py-2 text-sm hover:bg-slate-50"
                  >
                    Replay extraction checkpoint #{cp.id}
                  </button>
                ))}
            </div>
          </article>
        </div>

        <aside className="h-fit rounded-xl border bg-white p-5">
          <h2 className="font-semibold text-slate-900">Node inspection</h2>
          {chosen ? (
            <>
              <p className="mt-2 text-sm">
                {chosen.node_key} · attempt {chosen.attempt} · <span className="font-semibold">{chosen.status}</span>
              </p>
              <p className="mt-1 text-xs text-slate-500">
                 Duration: {chosen.duration_ms ?? '—'} ms · workflow {workflow.workflow_version} · rule version {nodeDetails.data?.rule_version||'not recorded'}
              </p>
              <label className="mt-4 block text-sm font-medium">
                Operator reason
                <textarea
                  className="mt-1 w-full rounded border p-2 text-sm"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="Required for recovery actions"
                />
              </label>
              <details className="mt-4">
                <summary className="cursor-pointer font-medium text-slate-800">Input reference</summary>
                <pre className="mt-2 max-h-48 overflow-auto rounded bg-slate-50 p-2 text-xs">
                  {JSON.stringify(chosen.input_ref, null, 2)}
                </pre>
              </details>
              <details className="mt-3">
                <summary className="cursor-pointer font-medium text-slate-800">Output / error</summary>
                <pre className="mt-2 max-h-48 overflow-auto rounded bg-slate-50 p-2 text-xs">
                  {JSON.stringify(
                    {
                      output: chosen.output_ref,
                      error_class: chosen.error_class,
                      error_code: chosen.error_code,
                      error_message: chosen.error_message,
                    },
                    null,
                    2
                  )}
                </pre>
              </details>
              {nodeDetails.data?.diagnostics&&<details className="mt-3"><summary className="cursor-pointer font-medium text-slate-800">Node diagnostics</summary><pre className="mt-2 max-h-48 overflow-auto rounded bg-slate-50 p-2 text-xs">{JSON.stringify(nodeDetails.data.diagnostics,null,2)}</pre></details>}
              {chosen.status === 'failed' && (
                <button
                  onClick={() => setPendingAction({title:'Retry failed workflow node',message:`Retry ${chosen.node_key} attempt ${chosen.attempt}. It may call adapters and enqueue new workflow/outbox effects.`,run:()=>retry.mutate(chosen)})}
                  disabled={reason.trim().length < 4 || retry.isPending}
                  className="mt-4 w-full rounded bg-indigo-950 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"
                >
                  {retry.isPending ? 'Retrying…' : 'Retry failed node'}
                </button>
              )}
            </>
          ) : (
            <p className="mt-3 text-sm text-slate-500">No persisted node attempts yet.</p>
          )}

          <div className="mt-4 flex gap-2">
            {workflow.execution_state === 'paused' ? (
              <button
                onClick={() => setPendingAction({title:'Resume workflow',message:'Resume processing from the persisted workflow position. Worker and notification side effects may occur.',run:()=>resume.mutate()})}
                disabled={reason.trim().length < 4 || resume.isPending}
                className="w-full rounded border border-indigo-700 bg-indigo-50 px-3 py-2 text-sm font-semibold text-indigo-900 disabled:opacity-50"
              >
                {resume.isPending ? 'Resuming…' : 'Resume workflow'}
              </button>
            ) : (
              <button
                onClick={() => setPendingAction({title:'Pause workflow',message:'Request pause at the next workflow boundary. In-flight node work may finish first.',run:()=>pause.mutate()})}
                disabled={reason.trim().length < 4 || pause.isPending}
                className="w-full rounded border px-3 py-2 text-sm font-semibold disabled:opacity-50"
              >
                {pause.isPending ? 'Pausing…' : 'Pause when idle'}
              </button>
            )}
          </div>

          {nodes.length>1&&<section className="mt-4 border-t pt-4"><h3 className="font-semibold">Compare executions</h3><div className="mt-2 grid grid-cols-2 gap-2"><label className="text-xs">Execution A<select value={compareA} onChange={e=>setCompareA(e.target.value)} className="mt-1 w-full rounded border p-2"><option value="">Select</option>{nodes.map(n=><option key={n.id} value={n.id}>{n.node_key} #{n.attempt}</option>)}</select></label><label className="text-xs">Execution B<select value={compareB} onChange={e=>setCompareB(e.target.value)} className="mt-1 w-full rounded border p-2"><option value="">Select</option>{nodes.map(n=><option key={n.id} value={n.id}>{n.node_key} #{n.attempt}</option>)}</select></label></div><button disabled={!compareA||!compareB||comparison.isPending} onClick={()=>comparison.mutate()} className="mt-2 rounded border px-3 py-2 text-sm disabled:opacity-50">Compare</button>{comparison.data&&<pre className="mt-2 max-h-48 overflow-auto rounded bg-slate-50 p-2 text-xs">{JSON.stringify(comparison.data,null,2)}</pre>}{comparison.isError&&<p role="alert" className="text-sm text-red-800">Comparison failed. Request ID: {comparison.error?.response?.headers?.['x-request-id']||'not supplied'}</p>}</section>}

          {(retry.isError || replay.isError || pause.isError || resume.isError) && (
            <p role="alert" className="mt-3 text-sm text-red-700">
              Action rejected or case changed; reload and inspect before retrying. Request ID: {retry.error?.response?.headers?.['x-request-id']||replay.error?.response?.headers?.['x-request-id']||pause.error?.response?.headers?.['x-request-id']||resume.error?.response?.headers?.['x-request-id']||'not supplied'}
            </p>
          )}
        </aside>
      </div>
      <ConfirmDialog open={Boolean(pendingAction)} title={pendingAction?.title} message={pendingAction?.message} onCancel={()=>setPendingAction(null)} onConfirm={()=>{const run=pendingAction?.run;setPendingAction(null);run?.();}}/>
    </section>
  );
}
