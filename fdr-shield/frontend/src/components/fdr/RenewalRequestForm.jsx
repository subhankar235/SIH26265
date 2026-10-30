/**
 * RenewalRequestForm
 * Props: fdr, onSubmit
 */
export default function RenewalRequestForm({ fdr, onSubmit }) {
  // New FDR number, maturity, amount, upload new scan
  return <form onSubmit={e=>{e.preventDefault();onSubmit?.({new_fdr_number:e.target.new_fdr_number.value,new_maturity_date:e.target.new_maturity_date.value,amount:Number(e.target.amount.value)})}} className="grid gap-3 rounded-xl border bg-white p-4"><h3 className="font-semibold">Renew {fdr.fdr_number}</h3><input name="new_fdr_number" required placeholder="Replacement FDR number" className="rounded-lg border p-3"/><input name="new_maturity_date" type="date" required className="rounded-lg border p-3"/><input name="amount" type="number" min="1" required placeholder="Amount" className="rounded-lg border p-3"/><button className="rounded-lg bg-slate-900 p-3 text-white">Request renewal</button></form>;
}
