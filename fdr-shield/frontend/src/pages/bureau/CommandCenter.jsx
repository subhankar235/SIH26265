import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { client } from '../../api/client';
import { useAuthStore } from '../../store/authStore';

function getConversationId(userId){
  const key=`fdr-command-conversation:${userId||'session'}`;
  let value=sessionStorage.getItem(key);
  if(!value){value=crypto.randomUUID();sessionStorage.setItem(key,value);}
  return value;
}

export default function CommandCenter({ adminMode = false, portalLabel }) {
  const [text, setText] = useState('');
  const [active, setActive] = useState(null);
  const [chatMessages, setChatMessages] = useState([]);
  const [progress, setProgress] = useState(null);
  const [sseActive, setSseActive] = useState(false);
  const qc = useQueryClient();
  const userId=useAuthStore(state=>state.user?.id);
  const [conversationId]=useState(()=>getConversationId(userId));

  const history = useQuery({
    queryKey: ['command-history',conversationId],
    queryFn: () => client.get('/commands',{params:{conversation_id:conversationId,page:1,size:100}}).then((r) => r.data),
    refetchInterval: 5000,
  });

  useEffect(()=>{
    if(!history.data)return;
    setChatMessages([...history.data].reverse().map(item=>({
      question:item.raw_command,
      reply:item.mode==='chat'?item.assistant_reply:(item.result_summary||`Request status: ${item.status}.`),
      interpreter:item.interpreter,
      mode:item.mode,
      commandId:item.id,
    })));
  },[history.data]);

  const interpret = useMutation({
    mutationFn: (body) => client.post('/commands/interpret', body),
    onSuccess: ({ data }, variables) => {
      if (data.mode === 'chat') {
        setChatMessages((messages) => {
          const pendingIndex=messages.findLastIndex(message=>message.mode==='pending'&&message.question===variables.text);
          const reply={question:variables.text,reply:data.reply,interpreter:data.interpreter,
            mode:'chat',commandId:data.message_id};
          if(pendingIndex<0)return [...messages,reply];
          const next=[...messages];next[pendingIndex]=reply;return next;
        });
        qc.invalidateQueries({queryKey:['command-history',conversationId]});
        setActive(null);
        setProgress(null);
        return;
      }
      setActive(data);
      setProgress(data.command_id ? { command_id: data.command_id, status: data.status,
        queued: Boolean(data.queued), result_summary: data.result_summary } : null);
      qc.invalidateQueries({ queryKey: ['command-history',conversationId] });
    },
    onError:(_error,variables)=>setChatMessages(messages=>messages.map(message=>
      message.mode==='pending'&&message.question===variables.text
        ? {...message,mode:'failed',reply:'The request could not be processed. Check the error above and retry.'}
        : message)),
  });

  const confirm = useMutation({
    mutationFn: () => client.post(`/commands/${active.command_id}/confirm`, { plan_hash: active.plan_hash }),
    onSuccess: ({ data }) => {
      setProgress(data);
      qc.invalidateQueries({ queryKey: ['command-history',conversationId] });
    },
  });

  const cancel = useMutation({
    mutationFn: () => client.post(`/commands/${progress?.command_id || active?.command_id}/cancel`, {
      reason: 'Cancelled by the authenticated user.',
    }),
    onSuccess: ({ data }) => {
      setProgress((prev) => ({ ...prev, status: data.status }));
      qc.invalidateQueries({ queryKey: ['command-history',conversationId] });
    },
  });

  // Background SSE progress streaming with polling fallback (Phase 8.5 & 9.4)
  useEffect(() => {
    const id = progress?.command_id;
    if (!id || !progress?.queued) return;

    let stream;
    let pollTimer;
    const api = import.meta.env.VITE_API_URL || '/api/v1';

    try {
      stream = new EventSource(`${api}/commands/${id}/stream`, { withCredentials: true });

      stream.onopen = () => {
        setSseActive(true);
      };

      stream.addEventListener('command.progress', (event) => {
        try {
          const state = JSON.parse(event.data);
          setProgress((current) => ({ ...current, ...state, command_id: id, queued: true }));
          if (['succeeded', 'failed', 'cancelled'].includes(state.status)) {
            stream.close();
            setSseActive(false);
          }
        } catch {
          // ignore parse error
        }
      });

      stream.onerror = () => {
        // Fallback: poll every 3 seconds if SSE blocked or disconnected (Phase 8.5)
        setSseActive(false);
        if (!pollTimer) {
          pollTimer = setInterval(() => {
            client.get(`/commands/${id}`).then((r) => {
              setProgress((current) => ({ ...current, ...r.data, command_id: id, queued: true }));
              if (['succeeded', 'failed', 'cancelled'].includes(r.data.status)) {
                clearInterval(pollTimer);
              }
            }).catch(() => {});
          }, 3000);
        }
      };
    } catch {
      setSseActive(false);
    }

    return () => {
      if (stream) stream.close();
      if (pollTimer) clearInterval(pollTimer);
    };
  }, [progress?.command_id, progress?.queued]);

  function submit(e) {
    e.preventDefault();
    const request=text.trim();
    if(!request)return;
    setChatMessages(messages=>[...messages,{question:request,reply:'',mode:'pending'}]);
    setText('');
    interpret.mutate({text:request,idempotency_key:crypto.randomUUID(),conversation_id:conversationId});
  }

  // Parse Step 9.4 plan contract: [{step, tool, resolved_targets, effect_summary, requires_confirmation}]
  const planSteps = Array.isArray(active?.plan) ? active.plan : (active?.plan?.steps || (active?.plan ? [active.plan] : []));
  const firstStep = planSteps[0] || {};
  const targets = firstStep.resolved_targets || active?.plan?.resolved_targets || [];
  const effectSummary = firstStep.effect_summary || active?.plan?.effect_summary;
  const toolName = firstStep.tool || active?.plan?.tool || active?.plan?.intent;

  return (
    <section>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold uppercase tracking-wide text-indigo-700">
            {portalLabel || (adminMode ? 'Super Admin · Read-only command subset' : 'AICTE Official · Natural-Language Command Center')}
          </p>
          <h1 className="mb-2 mt-1 text-3xl font-bold">Command Center</h1>
        </div>
        {progress?.queued && (
          <span className={`rounded-full px-3 py-1 text-xs font-semibold ${sseActive ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800'}`}>
            {sseActive ? '● SSE Live Stream' : '○ Polling Fallback (3s)'}
          </span>
        )}
      </div>

      <p className="mb-5 max-w-3xl text-slate-600">
        Ask in your own words about authorized FDR details, verification observations, discrepancies, or workflow status.
        Answers use records you are authorized to see; the assistant cannot certify that an FDR is genuine.
        Supported changes use allowlisted tools and require confirmation where appropriate.
      </p>

      <form onSubmit={submit} className="rounded-xl border bg-white p-5">
        <label className="block text-sm font-semibold">
          Ask a question or describe an FDR task
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            className="mt-2 min-h-24 w-full rounded-lg border p-3"
            placeholder="What are the recorded details and unresolved discrepancies for FDR-1024?"
            minLength={1}
            maxLength={2000}
            required
          />
        </label>
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            disabled={interpret.isPending}
            className="rounded-lg bg-indigo-950 px-4 py-2 font-semibold text-white disabled:opacity-50"
          >
            {interpret.isPending ? 'Thinking…' : 'Send'}
          </button>
        </div>
        {interpret.isError && (
          <p role="alert" className="mt-3 text-sm text-red-700">
            {interpret.error?.response?.data?.error?.message ||
              interpret.error?.response?.data?.detail ||
              'Command is unsupported or no authorized target was found.'}
          </p>
        )}
      </form>

      {chatMessages.length > 0 && (
        <section className="mt-5 space-y-3" aria-label="Assistant conversation" aria-live="polite">
          {chatMessages.map((message, index) => (
            <article key={`${index}-${message.question}`} className="rounded-xl border bg-white p-4">
              <p className="text-sm font-semibold text-slate-700">You: {message.question}</p>
              <p className="mt-2 whitespace-pre-wrap text-sm text-slate-900">Assistant: {message.reply||'Working…'}</p>
              {message.interpreter === 'deterministic-chat-fallback' && (
                <p className="mt-2 text-xs text-amber-800">LLM unavailable; showing local guidance.</p>
              )}
            </article>
          ))}
        </section>
      )}

      {active && (
        <article className="mt-5 rounded-xl border border-indigo-200 bg-white p-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-lg font-semibold">Execution plan · Tool: {toolName}</h2>
            <span className="rounded bg-indigo-50 px-2 py-1 text-xs font-mono text-indigo-900">
              Plan hash: {active.plan_hash?.slice(0, 16)}…
            </span>
          </div>
          <p className="mt-1 text-sm text-slate-700">{effectSummary}</p>
          {active.interpreter&&<p className="mt-1 text-xs text-slate-500">Plan source: {active.interpreter==='llm-structured'?'configured LLM':'deterministic offline fallback'}</p>}

          <h3 className="mt-4 font-medium text-slate-900">
            Server-resolved targets ({targets.length})
          </h3>
          {targets.length === 0 ? (
            <p className="mt-2 text-xs italic text-slate-500">No targets matched the criteria.</p>
          ) : (
            <ul className="mt-2 list-disc space-y-1 pl-5 text-sm">
              {targets.map((target, index) => (
                <li key={`${target.fdr_id || target.workflow_id || target.notification_id || index}`}>
                  <strong>{target.fdr_number || `FDR #${target.fdr_id || '—'}`}</strong>
                  {target.maturity_date ? ` · matures ${target.maturity_date}` : ''}
                  {target.lifecycle_state ? ` · ${target.lifecycle_state}` : ''}
                  {target.error ? ` · error: ${target.error}` : ''}
                </li>
              ))}
            </ul>
          )}

          {active.warnings?.length > 0 && (
            <div className="mt-3 rounded bg-amber-50 p-3 text-xs text-amber-900">
              {active.warnings.map((w, idx) => (
                <p key={idx}>⚠️ {w}</p>
              ))}
            </div>
          )}

          <div className="mt-4 rounded-lg bg-slate-50 p-3 text-xs text-slate-600">
            ℹ️ Target case states and workflow versions will be re-verified at confirmation.
            Any state drift triggers re-planning.
          </div>

          {active.requires_confirmation ? (
            <button
              onClick={() => confirm.mutate()}
              disabled={confirm.isPending}
              className="mt-4 rounded-lg bg-indigo-950 px-4 py-2 font-semibold text-white disabled:opacity-50"
            >
              {confirm.isPending ? 'Confirming…' : 'Confirm and execute'}
            </button>
          ) : (
            <p className={`mt-4 rounded p-3 text-sm ${active.status==='succeeded'?'bg-green-50 text-green-900':active.status==='failed'?'bg-red-50 text-red-900':'bg-blue-50 text-blue-900'}`}>
              {active.status==='succeeded'?'✓ Read-only query completed using authorized portal data.':
                active.status==='failed'?'The query failed; no successful result was produced.':
                  'Read-only query queued; results will appear when execution finishes.'}
            </p>
          )}

          {confirm.isError && (
            <p role="alert" className="mt-3 text-sm text-red-700">
              {confirm.error?.response?.data?.error?.message ||
                'Plan became stale or was rejected. Rebuild the plan before retrying.'}
            </p>
          )}
        </article>
      )}

      {progress && (
        <article className="mt-5 rounded-xl border bg-white p-5" aria-live="polite">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="font-semibold text-slate-900">
                Command #{progress.command_id} · <span className="uppercase text-indigo-700">{progress.status}</span>
              </h2>
              <p className="mt-1 text-xs text-slate-500">
                Execution runs as a background job; cancelling stops execution before the next step;
                completed steps are not rolled back automatically.
              </p>
            </div>
            {['planned', 'confirmed', 'running'].includes(progress.status) && (
              <button
                onClick={() => cancel.mutate()}
                disabled={cancel.isPending}
                className="rounded border border-red-300 px-3 py-1 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50"
              >
                {cancel.isPending ? 'Stopping…' : 'Cancel command'}
              </button>
            )}
          </div>

          {progress.steps?.map((step, index) => (
            <p className="mt-3 text-sm" key={index}>
              Step {step.step || index + 1} ({step.tool}):{' '}
              <span className={`font-semibold ${step.status === 'succeeded' ? 'text-green-700' : 'text-slate-700'}`}>
                {step.status}
              </span>
            </p>
          ))}

          {progress.result_summary && (
            (() => {
              const answerStep = progress.steps?.find((step) => step.result?.answer);
              if (!answerStep) {
                return (
                  <pre className="mt-3 whitespace-pre-wrap rounded bg-slate-50 p-3 text-xs font-mono text-slate-800">
                    {progress.result_summary}
                  </pre>
                );
              }
              return (
                <div className="mt-3 rounded-lg bg-slate-50 p-4">
                  <p className="whitespace-pre-wrap text-sm text-slate-900">{answerStep.result.answer}</p>
                  <p className="mt-2 text-xs text-slate-500">
                    {answerStep.result.answer_source === 'llm-grounded'
                      ? 'LLM answer grounded in authorized database results'
                      : 'Structured database answer; LLM unavailable or not configured'}
                  </p>
                  <details className="mt-3">
                    <summary className="cursor-pointer text-xs font-semibold text-indigo-900">
                      Show structured database result
                    </summary>
                    <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap rounded bg-white p-3 text-xs font-mono text-slate-800">
                      {JSON.stringify(answerStep.result.data, null, 2)}
                    </pre>
                  </details>
                </div>
              );
            })()
          )}

          {cancel.isError && (
            <p role="alert" className="mt-3 text-sm text-red-700">
              {cancel.error?.response?.data?.error?.message ||
                'Command execution could not be cancelled.'}
            </p>
          )}
        </article>
      )}

      <h2 className="mb-3 mt-8 text-xl font-semibold">Recent commands</h2>
      {history.isLoading ? (
        <p>Loading command history…</p>
      ) : history.isError ? (
        <p role="alert" className="text-red-700">Could not load command history.</p>
      ) : !history.data.length ? (
        <p className="text-sm text-slate-500">No commands yet.</p>
      ) : (
        <div className="space-y-2">
          {history.data.map((item) => (
            <button
              key={item.id}
              onClick={() =>
                client
                  .get(`/commands/${item.id}`)
                  .then((r) =>
                    setProgress({
                      ...r.data,
                      command_id: item.id,
                      queued: ['confirmed', 'running'].includes(r.data.status),
                    })
                  )
              }
              className="flex w-full flex-wrap justify-between gap-2 rounded-lg border bg-white p-3 text-left text-sm hover:border-indigo-400"
            >
              <span className="font-medium text-slate-900">{item.raw_command}</span>
              <span className="text-xs uppercase text-slate-500">{item.status}</span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}
