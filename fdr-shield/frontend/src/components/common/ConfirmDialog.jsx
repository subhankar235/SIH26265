/**
 * ConfirmDialog
 * Props: open, title, message, onConfirm, onCancel
 */
export default function ConfirmDialog({ open, title, message, onConfirm, onCancel }) {
  // Modal confirmation
  if(!open)return null;return <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 p-4"><div role="dialog" aria-modal="true" className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl"><h2 className="text-lg font-bold">{title||'Confirm action'}</h2><p className="my-4 text-sm text-slate-600">{message}</p><div className="flex justify-end gap-2"><button onClick={onCancel} className="rounded-lg border px-4 py-2">Cancel</button><button onClick={onConfirm} className="rounded-lg bg-slate-900 px-4 py-2 text-white">Confirm</button></div></div></div>;
}
