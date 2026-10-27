import { AlertTriangle, CheckCircle2, FileText } from 'lucide-react';
import { formatINR, formatDate } from '../../utils/format';

const labels = { fdr_number:'FDR number', bank_name:'Bank', holder:'Holder', amount:'Amount', issue_date:'Issue date', maturity_date:'Maturity' };

export default function SplitViewer({ fileUrl, fdr, report }) {
  const declared = fdr?.declared_data || {}, ocr = report?.ocr || {}, bank = report?.bank || {};
  const mismatches = new Set((report?.discrepancies || []).map((item) => item.field));
  const val = (field, value) => {
    if (value == null || value === '') return '—';
    if (field === 'amount') return formatINR(value);
    if (field.endsWith('_date')) return formatDate(value);
    return String(value);
  };
  const rows = [
    ['fdr_number', declared.fdr_number, ocr.fdr_number, bank.found ? fdr?.fdr_number : null],
    ['bank_name', declared.bank_name, ocr.bank_name, bank.found ? fdr?.bank_name : null],
    ['holder', declared.holder ?? declared.holder_name, ocr.holder_name, bank.holder],
    ['amount', declared.amount, ocr.amount, bank.amount],
    ['issue_date', declared.issue_date, ocr.issue_date, null],
    ['maturity_date', declared.maturity_date, ocr.maturity_date, bank.maturity_date],
  ];
  const level = fdr?.verification_level || (bank.found ? 'mock_verified' : ocr.confidence ? 'extracted' : 'declared');
  const evidenceLabel = {
    declared: 'Institution-declared', extracted: 'Document-extracted; not proof of authenticity',
    mock_verified: 'Mock bank match; demo only', verified_external: 'Independently verified source',
    human_scrutinized: 'Human-scrutinized', ai_recommendation: 'AI recommendation only',
  }[level] || 'Evidence source not recorded';
  const bankMessage = bank.verification_message || (
    bank.found ? `Demo bank fixture matched (${bank.status}); not an independent bank confirmation.`
      : 'Bank verification was not confirmed. This does not establish whether the FDR is genuine.'
  );
  const formatStatus = String(ocr.document_format || 'not_checked').replace(/_/g, ' ');

  return <div className="grid min-h-[620px] grid-cols-1 overflow-hidden rounded-xl border bg-white lg:grid-cols-2" aria-label="FDR scrutiny evidence viewer">
    <section className="border-b p-4 lg:border-b-0 lg:border-r">
      <h2 className="mb-3 flex items-center gap-2 font-semibold"><FileText size={17}/>Original scan</h2>
      {fileUrl ? <iframe title="FDR scan" src={fileUrl} className="h-[72vh] min-h-[520px] w-full rounded-lg bg-slate-100"/> : <div className="grid h-[72vh] min-h-[520px] place-items-center rounded-lg bg-slate-50 text-sm text-slate-500">Secure scan is loading…</div>}
    </section>
    <section className="p-4">
      <h2 className="mb-2 font-semibold">Evidence comparison</h2>
      <p className="mb-3 rounded-lg bg-amber-50 p-3 text-xs text-amber-950"><strong>{evidenceLabel}.</strong> OCR consistency and a demo-bank match do not independently certify that an FDR is genuine.</p>
      <p className="mb-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-800">
        <strong>Generic FDR format screen: {formatStatus}.</strong>{' '}
        {ocr.format_reason || 'This OCR engine did not provide a format assessment.'}
        {' '}This checks document appearance only; it is not bank verification or proof of authenticity.
      </p>
      <div className="overflow-x-auto"><table className="w-full min-w-[540px] text-left text-sm">
        <thead className="sticky top-0 bg-slate-50 text-xs text-slate-500"><tr>{['Field','Institution-declared','Document extraction','Demo bank gateway'].map(x=><th key={x} className="px-3 py-3">{x}</th>)}</tr></thead>
        <tbody className="divide-y">{rows.map(([field,d,o,b])=>{const mismatch=mismatches.has(field);return <tr key={field} className={mismatch?'bg-red-50 text-red-900':''}><th scope="row" className="px-3 py-3 font-medium">{labels[field]}{mismatch&&<AlertTriangle aria-label="Mismatch" size={14} className="ml-1 inline text-red-700"/>}</th><td className="px-3 py-3 tabular-nums">{val(field,d)}</td><td className="px-3 py-3 tabular-nums">{val(field,o)}</td><td className="px-3 py-3 tabular-nums">{val(field,b)}</td></tr>})}</tbody>
      </table></div>
      <p className="mt-3 flex items-center gap-2 text-xs text-slate-600">{bank.found&&<CheckCircle2 size={14} className="text-amber-700"/>}{bankMessage}</p>
    </section>
  </div>;
}
