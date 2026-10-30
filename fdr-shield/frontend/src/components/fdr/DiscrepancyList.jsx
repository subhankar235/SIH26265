/**
 * DiscrepancyList
 * Props: items, onResolve
 */
export default function DiscrepancyList({ items, onResolve }) {
  // List with severity chips and Resolve button
  return <div className="rounded-xl border bg-white p-4"><h2 className="mb-3 font-semibold">Discrepancies</h2>{!items?.length?<p className="text-sm text-slate-500">No discrepancies detected.</p>:<ul className="space-y-2">{items.map((x,i)=><li key={x.id||i} className="rounded-lg bg-red-50 p-3 text-sm"><div className="flex justify-between"><b className="capitalize">{x.field?.replaceAll('_',' ')}</b><span className={x.severity==='high'?'text-red-700':'text-amber-700'}>{x.severity}</span></div><p className="mt-1 text-slate-600">Declared: {x.declared_value||'—'} · Found: {x.extracted_value||'—'} ({x.source})</p>{onResolve&&!x.resolved&&<button onClick={()=>onResolve(x.id)} className="mt-2 rounded border border-red-300 px-2 py-1 text-xs font-medium text-red-800 hover:bg-white">Resolve discrepancy</button>}</li>)}</ul>}</div>;
}
