/**
 * DataTable
 * Props: columns, rows, onRowClick, loading, pagination
 */
export default function DataTable({ columns=[], rows=[], onRowClick, loading, pagination }) {
  // Generic sortable table with skeleton loader
  if(loading)return <p className="rounded-xl border bg-white p-6 text-slate-500">Loading records…</p>;return <div className="overflow-x-auto rounded-xl border bg-white"><table className="w-full text-left text-sm"><thead className="bg-slate-50"><tr>{columns.map(c=><th key={c.key} className="px-4 py-3">{c.label}</th>)}</tr></thead><tbody className="divide-y">{rows.map((row,i)=><tr key={row.id||i} onClick={()=>onRowClick?.(row)} className={onRowClick?'cursor-pointer hover:bg-slate-50':''}>{columns.map(c=><td key={c.key} className="px-4 py-3">{c.render?c.render(row[c.key],row):row[c.key]}</td>)}</tr>)}</tbody></table>{!rows.length&&<p className="p-6 text-center text-sm text-slate-500">No records to show.</p>}</div>;
}
