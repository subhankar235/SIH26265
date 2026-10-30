/**
 * RefundForm
 * Props: fdr, onSubmit
 */
export default function RefundForm({ fdr, onSubmit }) {
  // Reason + supporting docs upload
  return <form onSubmit={e=>{e.preventDefault();onSubmit?.({fdr_id:fdr.id,reason:e.target.reason.value})}} className="space-y-3 rounded-xl border bg-white p-4"><h3 className="font-semibold">Request release for {fdr.fdr_number}</h3><textarea name="reason" required placeholder="Reason and closure confirmation" className="w-full rounded-lg border p-3"/><button className="rounded-lg bg-slate-900 px-4 py-2 text-white">Submit refund request</button></form>;
}
