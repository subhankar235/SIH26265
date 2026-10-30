import { useState } from 'react';
import { FileUp } from 'lucide-react';

export default function FileDropzone({ onFile, accept = 'application/pdf,image/jpeg,image/png', name = 'file', required = false, maxSize = 10 * 1024 * 1024 }) {
  const [file, setFile] = useState(null), [error, setError] = useState('');
  function choose(event) {
    const candidate = event.target.files?.[0];
    if (!candidate) return;
    if (candidate.size > maxSize) { event.target.value = ''; setFile(null); setError('Maximum file size is 10 MB.'); onFile?.(null); return; }
    const accepted = accept.split(',').map(x => x.trim());
    if (accepted.length && !accepted.includes(candidate.type)) { event.target.value = ''; setFile(null); setError('Choose a PDF, JPEG, or PNG.'); onFile?.(null); return; }
    setFile(candidate); setError(''); onFile?.(candidate);
  }
  return <div><label className="block cursor-pointer rounded-xl border-2 border-dashed border-slate-300 p-6 text-center transition-colors hover:border-indigo-500 focus-within:border-indigo-600"><input name={name} type="file" accept={accept} required={required} onChange={choose} className="sr-only"/><span className="mx-auto mb-2 grid size-10 place-items-center rounded-full bg-indigo-50 text-indigo-800"><FileUp size={19}/></span><span className="block font-medium">{file?.name || 'Choose a PDF or image scan'}</span><span className="mt-1 block text-xs text-slate-500">PDF, JPEG, or PNG · Maximum 10 MB</span></label>{error&&<p role="alert" className="mt-2 text-sm text-red-700">{error}</p>}</div>;
}
