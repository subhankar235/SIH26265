import { useState } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { Landmark, ShieldCheck, LockKeyhole } from 'lucide-react';
import { login } from '../../api/auth.api';
import { useAuthStore } from '../../store/authStore';

const portalInfo = {
  institution: { title: 'Institution portal', subtitle: 'Manage your institution’s FDR records.', route: '/institution' },
  official: { title: 'AICTE Official portal', subtitle: 'Review submissions and manage case decisions.', route: '/official' },
  admin: { title: 'Admin portal', subtitle: 'Manage accounts and monitor operations.', route: '/admin' },
};

export default function Login() {
  const location = useLocation(), navigate = useNavigate();
  const portal = useParams().portal || (location.pathname.startsWith('/institution') ? 'institution' : location.pathname.startsWith('/official') ? 'official' : 'admin');
  const info = portalInfo[portal] || portalInfo.institution;
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const setUser = useAuthStore((s) => s.setUser);
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError('');
    const form = new FormData(event.currentTarget);
    try {
      const data = await login(portal, String(form.get('email')), String(form.get('password')));
      if (data.mfa_required) {
        sessionStorage.setItem('fdr-portal', portal);
        navigate('/mfa');
        return;
      }
      setUser(data.user);
      const defaultPath = data.user.role === 'institution' ? '/institution' : data.user.role === 'admin' ? '/admin' : '/official';
      navigate(location.state?.from?.pathname || defaultPath, { replace: true });
    } catch (err) {
      setError(err.response?.status === 429 ? 'Too many attempts. Try again later.' : 'Invalid email or password.');
    } finally { setBusy(false); }
  }
  return <main className="grid min-h-screen bg-slate-50 lg:grid-cols-[minmax(320px,0.85fr)_1.15fr]">
    <aside className="hidden flex-col justify-between bg-navy-900 p-12 text-white lg:flex"><div className="flex items-center gap-3"><span className="grid size-11 place-items-center rounded-xl bg-white/10"><Landmark/></span><span className="text-xl font-bold">FDR-Shield</span></div><div className="max-w-md"><p className="mb-4 inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1 text-xs text-indigo-100"><ShieldCheck size={14}/> AICTE secure registry</p><h1 className="text-4xl font-semibold leading-tight">A clearer view of every security deposit.</h1><p className="mt-4 leading-7 text-indigo-100/80">Verify receipts, track maturity, and review decisions in one accountable workspace.</p></div><p className="text-xs text-indigo-100/60">FDR-Shield · Demonstration environment</p></aside>
    <section className="grid place-items-center p-5 sm:p-10"><div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-7 shadow-sm sm:p-9"><div className="mb-7 flex items-center gap-3 lg:hidden"><span className="grid size-10 place-items-center rounded-xl bg-navy-900 text-white"><Landmark size={19}/></span><span className="font-bold">FDR-Shield</span></div><p className="text-sm font-semibold text-indigo-800">{info.title}</p><h2 className="mt-1 text-2xl font-bold tracking-tight">Sign in to your portal</h2><p className="mt-2 text-sm text-slate-500">{info.subtitle}</p>
      <form onSubmit={submit} className="mt-7 space-y-4"><label className="block text-sm font-medium text-slate-700">Email address<input name="email" type="email" autoComplete="username" required className="mt-1.5 w-full rounded-lg border border-slate-300 p-3 outline-none focus:border-indigo-700 focus:ring-2 focus:ring-indigo-100"/></label><label className="block text-sm font-medium text-slate-700">Password<input name="password" type="password" autoComplete="current-password" required className="mt-1.5 w-full rounded-lg border border-slate-300 p-3 outline-none focus:border-indigo-700 focus:ring-2 focus:ring-indigo-100"/></label>{error&&<p role="alert" aria-live="polite" className="text-sm text-red-700">{error}</p>}<button disabled={busy} className="mt-2 flex w-full items-center justify-center gap-2 rounded-lg bg-indigo-950 p-3 font-semibold text-white hover:bg-indigo-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-800"><LockKeyhole size={16}/>{busy?'Signing in…':'Continue securely'}</button></form>
      <div className="mt-5 flex justify-between text-sm"><Link className="text-indigo-800 underline" to="/forgot-password">Forgot password?</Link>{portal==='institution'&&<Link className="text-indigo-800 underline" to="/institution/register">Register institution</Link>}</div><p className="mt-5 text-center text-xs"><Link className="text-slate-500 underline" to="/login">Choose another portal</Link></p>
    </div></section>
  </main>;
}
