/**
 * ConfirmDialog
 * Props: open, title, message, onConfirm, onCancel
 */
export default function ConfirmDialog({ open, title, message, onConfirm, onCancel }) {
  const confirmRef=useRef(null),cancelRef=useRef(null),previousFocus=useRef(null);
  useEffect(()=>{if(!open)return;previousFocus.current=document.activeElement;confirmRef.current?.focus();const key=e=>{if(e.key==='Escape')onCancel?.();if(e.key==='Tab'){const items=[cancelRef.current,confirmRef.current].filter(Boolean);if(items.length===1){e.preventDefault();items[0].focus()}else if(e.shiftKey&&document.activeElement===items[0]){e.preventDefault();items[1].focus()}else if(!e.shiftKey&&document.activeElement===items[1]){e.preventDefault();items[0].focus()}}};document.addEventListener('keydown',key);return()=>{document.removeEventListener('keydown',key);previousFocus.current?.focus?.()}},[open,onCancel]);
  if(!open)return null;return <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 p-4" onMouseDown={e=>e.target===e.currentTarget&&onCancel?.()}><div role="dialog" aria-modal="true" aria-labelledby="confirm-title" aria-describedby="confirm-message" className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl"><h2 id="confirm-title" className="text-lg font-bold">{title||'Confirm action'}</h2><p id="confirm-message" className="my-4 text-sm text-slate-600">{message}</p><div className="flex justify-end gap-2"><button ref={cancelRef} onClick={onCancel} className="rounded-lg border px-4 py-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-700">Cancel</button><button ref={confirmRef} onClick={onConfirm} className="rounded-lg bg-slate-900 px-4 py-2 text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-700">Confirm</button></div></div></div>;
}
import { useEffect, useRef } from 'react';
