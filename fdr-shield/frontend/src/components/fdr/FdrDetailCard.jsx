/**
 * FdrDetailCard
 * Props: fdr
 */
export default function FdrDetailCard({ fdr }) {
  // Key FDR details + timeline of status changes
  return <article className="rounded-xl border bg-white p-5"><h2 className="text-xl font-bold">{fdr.fdr_number}</h2><dl className="mt-4 grid grid-cols-2 gap-3 text-sm"><dt className="text-slate-500">Bank</dt><dd>{fdr.bank_name} · {fdr.branch}</dd><dt className="text-slate-500">Amount</dt><dd>₹{Number(fdr.amount).toLocaleString('en-IN')}</dd><dt className="text-slate-500">Maturity</dt><dd>{fdr.maturity_date}</dd><dt className="text-slate-500">Status</dt><dd>{fdr.status}</dd></dl></article>;
}
