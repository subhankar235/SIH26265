import { useState } from 'react';
import { client } from '../../api/client';

const fields = [
  ['fdr_number', 'FDR number'], ['bank_name', 'Bank'], ['branch', 'Branch'],
  ['amount', 'Amount'], ['issue_date', 'Issue date'], ['maturity_date', 'Maturity date'], ['holder', 'Holder'],
];

export default function FdrUploadForm({ onSubmit, busy = false, error }) {
  const [file, setFile] = useState(null);
  const [values, setValues] = useState({});
  const [confidence, setConfidence] = useState({});
  const [provenance, setProvenance] = useState({});
  const [confirmed, setConfirmed] = useState({});
  const [extracting, setExtracting] = useState(false);
  const [validation, setValidation] = useState('');
  const [extractError, setExtractError] = useState('');
  const [extractNotice, setExtractNotice] = useState('');

  async function extract() {
    if (!file) return setValidation('Choose your FDR scan first.');
    const form = new FormData(); form.append('file', file);
    setExtracting(true); setExtractError(''); setExtractNotice(''); setValidation('');
    try {
      const { data } = await client.post('/fdrs/extract-preview', form);
      setValues(data.fields);
      setConfidence(data.confidence);
      if (!Object.values(data.fields || {}).some(value => value !== null && value !== '')) {
        setExtractNotice('OCR returned no readable fields. Check the scan is clear, or enter the details manually.');
      }
      setProvenance(Object.fromEntries(fields.map(([name]) => [name, data.fields[name] ? 'EXTRACTED' : 'DECLARED'])));
      setConfirmed({});
    } catch (e) {
      setExtractError(e.response?.data?.detail || 'Could not extract fields. You may enter them manually.');
      setExtractNotice('');
      setValues(Object.fromEntries(fields.map(([name]) => [name, ''])));
      setConfidence({});
      setProvenance(Object.fromEntries(fields.map(([name]) => [name, 'DECLARED'])));
      setConfirmed({});
    } finally { setExtracting(false); }
  }

  function submit(e) {
    e.preventDefault();
    if (!file) return setValidation('Choose your FDR scan.');
    if (!fields.every(([name]) => confirmed[name])) return setValidation('Review and confirm every field before submission.');
    const body = new FormData();
    fields.forEach(([name]) => body.append(name, values[name] ?? ''));
    body.append('file', file);
    body.append('confirmed_fields', JSON.stringify(fields.map(([name]) => name)));
    body.append('field_provenance', JSON.stringify(provenance));
    setValidation(''); onSubmit?.(body);
  }

  return <form onSubmit={submit} className="grid gap-3 rounded-xl border bg-white p-5 sm:grid-cols-2">
    <div className="sm:col-span-2">
      <label className="text-sm font-medium">FDR scan <input type="file" accept="application/pdf,image/jpeg,image/png" required
        onChange={e => {
          setFile(e.target.files?.[0] || null);
          setValues(Object.fromEntries(fields.map(([name]) => [name, ''])));
          setProvenance(Object.fromEntries(fields.map(([name]) => [name, 'DECLARED'])));
          setConfidence({}); setConfirmed({}); setExtractError(''); setExtractNotice('');
        }}
        className="mt-1 block w-full rounded-lg border p-3" /></label>
      <button type="button" disabled={!file || extracting || busy} onClick={extract}
        className="mt-2 rounded-lg border border-indigo-800 px-4 py-2 text-sm font-semibold text-indigo-900 disabled:opacity-50">
        {extracting ? 'Extracting…' : 'Extract and prefill fields'}
      </button>
      {extractError && <p role="status" className="mt-2 text-sm text-amber-800">{extractError}</p>}
      {extractNotice && <p role="status" className="mt-2 text-sm text-amber-800">{extractNotice}</p>}
    </div>
    {fields.map(([name, label]) => {
      const low = confidence[name] !== undefined && confidence[name] < 0.7;
      const missing = values[name] === null || values[name] === undefined || values[name] === '';
      return <div key={name} className={`rounded-lg p-2 ${low || missing ? 'bg-amber-50 ring-1 ring-amber-300' : ''}`}>
        <label className="text-sm">{label}
          <input name={name} type={name.includes('date') ? 'date' : name === 'amount' ? 'number' : 'text'}
            step={name === 'amount' ? '0.01' : undefined} required={name !== 'branch' && name !== 'holder'}
            value={values[name] ?? ''} onChange={e => {
              setValues(v => ({ ...v, [name]: e.target.value }));
              setProvenance(p => ({ ...p, [name]: 'DECLARED' })); setConfirmed(c => ({ ...c, [name]: false }));
            }} className="mt-1 w-full rounded-lg border p-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-700" />
        </label>
        <p className={`mt-1 text-xs ${low || missing ? 'font-semibold text-amber-900' : 'text-slate-600'}`}>
          {missing ? 'Not found in document — enter or confirm that this field is blank.' : `Confidence ${Math.round((confidence[name] ?? 0) * 100)}%`}
          {` · ${provenance[name] || 'DECLARED'}`}
        </p>
        <label className="mt-1 flex items-center gap-2 text-xs">
          <input type="checkbox" checked={Boolean(confirmed[name])}
            onChange={e => setConfirmed(c => ({ ...c, [name]: e.target.checked }))} />
          I reviewed and confirm this field
        </label>
      </div>;
    })}
    {(error || validation) && <div role="alert" className="text-sm text-red-800 sm:col-span-2">{validation || error?.response?.data?.detail || error?.message || error}{error?.response?.headers?.['x-request-id']&&<p>Request ID: <code>{error.response.headers['x-request-id']}</code></p>}</div>}
    <button disabled={busy || extracting || !fields.every(([name]) => confirmed[name])}
      className="rounded-lg bg-indigo-900 p-3 font-semibold text-white transition-colors hover:bg-indigo-800 disabled:opacity-60 sm:col-span-2">
      {busy ? 'Submitting…' : 'Submit confirmed FDR'}
    </button>
  </form>;
}
