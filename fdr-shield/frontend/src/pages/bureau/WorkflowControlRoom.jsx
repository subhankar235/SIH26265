import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { client } from '../../api/client';

export default function WorkflowControlRoom(){
  const query=useQuery({queryKey:['official-workflows'],queryFn:()=>client.get('/workflows').then(r=>r.data),refetchInterval:8000});
  return <section><p className="text-sm font-semibold uppercase tracking-wide text-indigo-700">AICTE Official</p><h1 className="mb-2 mt-1 text-3xl font-bold">Workflow control room</h1><p className="mb-6 text-slate-600">Persisted case workflow states, pending human decisions and recoverable failures.</p>
    {query.isLoading?<p>Loading workflows…</p>:query.isError?<p role="alert" className="text-red-700">Could not load workflows.</p>:!query.data.length?<p className="rounded-xl border bg-white p-8 text-slate-600">No workflow instances yet. New FDR submissions create workflow instances.</p>:<div className="overflow-x-auto rounded-xl border bg-white"><table className="w-full min-w-[760px] text-left text-sm"><thead className="bg-slate-50"><tr>{['FDR id','Lifecycle','Execution','Authorization','Current node','Updated','Details'].map(x=><th key={x} className="p-3">{x}</th>)}</tr></thead><tbody>{query.data.map(row=><tr className="border-t" key={row.id}><td className="p-3">{row.fdr_id}</td><td className="p-3">{row.lifecycle_state}</td><td className="p-3">{row.execution_state}</td><td className="p-3">{row.authorization_state}</td><td className="p-3">{row.current_node||'—'}</td><td className="p-3">{row.updated_at?new Date(row.updated_at).toLocaleString():'—'}</td><td className="p-3"><Link className="text-indigo-800 underline" to={`/official/workflows/${row.id}`}>Inspect</Link></td></tr>)}</tbody></table></div>}
  </section>;
}
