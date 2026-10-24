import { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ShieldCheck } from 'lucide-react';
import { verifyMfa } from '../../api/auth.api';
import { useAuthStore } from '../../store/authStore';

export default function MfaVerify() {
  const [digits, setDigits] = useState(Array(6).fill('')), [error, setError] = useState('');
  const refs = useRef([]), navigate = useNavigate(), setUser = useAuthStore((s) => s.setUser);
  const update = (index, value) => { const digit = value.replace(/\D/g, '').slice(-1), next = [...digits]; next[index] = digit; setDigits(next); if (digit && index < 5) refs.current[index + 1]?.focus(); };
  async function submit(event) {
    event.preventDefault(); setError('');
    try {
      const { user } = await verifyMfa(digits.join(''));
      sessionStorage.removeItem('fdr-portal'); setUser(user);
      navigate(user.role === 'institution' ? '/institution' : user.role === 'admin' ? '/admin' : '/official', { replace: true });
    } catch { setError('The code is invalid or expired.'); }
  }
  return <main className="grid min-h-screen place-items-center bg-slate-50 p-5"><form onSubmit={submit} className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-8 shadow-sm"><span className="mb-5 grid size-11 place-items-center rounded-xl bg-indigo-50 text-indigo-900"><ShieldCheck/></span><h1 className="text-2xl font-bold">Two-factor verification</h1><p className="mt-2 text-sm text-slate-600">Enter the current six-digit code from your authenticator app.</p><div className="my-7 flex justify-between gap-2" role="group" aria-label="Six digit authenticator code">{digits.map((digit, i) => <input key={i} ref={el => refs.current[i] = el} aria-label={`Digit ${i + 1}`} inputMode="numeric" autoComplete={i === 0 ? 'one-time-code' : 'off'} value={digit} onChange={e => update(i, e.target.value)} onKeyDown={e => { if (e.key === 'Backspace' && !digits[i] && i > 0) refs.current[i - 1]?.focus(); }} className="h-12 w-11 rounded-lg border border-slate-300 text-center text-xl font-semibold focus:border-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-100" />)}</div>{error&&<p role="alert" className="mb-4 text-sm text-red-700">{error}</p>}<button disabled={digits.some(x => !x)} className="w-full rounded-lg bg-indigo-950 p-3 font-semibold text-white hover:bg-indigo-900">Verify identity</button></form></main>;
}
