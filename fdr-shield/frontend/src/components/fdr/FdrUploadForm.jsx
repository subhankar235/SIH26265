import { useState } from 'react';
import FileDropzone from '../common/FileDropzone';
/**
 * FdrUploadForm
 * Props: onSubmit
 */
export default function FdrUploadForm({ onSubmit, busy=false, error }) {
  // Form fields + FileDropzone; after upload show 'OCR in progress' then auto-fill preview via useVerificationReport
  const[validation,setValidation]=useState('');return <form onSubmit={e=>{e.preventDefault();const form=e.currentTarget,d=new FormData(form),file=d.get('file'),allowed=['application/pdf','image/jpeg','image/png'];if(file.size>10*1024*1024){setValidation('Maximum file size is 10 MB.');return}if(!allowed.includes(file.type)){setValidation('Choose a PDF, JPEG, or PNG.');return}setValidation('');onSubmit?.(d)}} className="grid gap-3 rounded-xl border bg-white p-5 sm:grid-cols-2">{[['fdr_number','FDR number'],['bank_name','Bank'],['branch','Branch'],['amount','Amount'],['issue_date','Issue date'],['maturity_date','Maturity date'],['holder','Holder']].map(([name,label])=><label key={name} className="text-sm">{label}<input name={name} type={name.includes('date')?'date':name==='amount'?'number':'text'} step={name==='amount'?'0.01':undefined} required className="mt-1 w-full rounded-lg border p-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-700"/></label>)}<div className="sm:col-span-2"><p className="mb-1 text-sm">Receipt scan</p><FileDropzone name="file" required /></div>{(error||validation)&&<p role="alert" className="text-sm text-red-700 sm:col-span-2">{validation||error}</p>}<button disabled={busy} className="rounded-lg bg-indigo-900 p-3 font-semibold text-white transition-colors hover:bg-indigo-800 disabled:opacity-60 sm:col-span-2">{busy?'Uploading…':'Submit FDR'}</button></form>;
}
