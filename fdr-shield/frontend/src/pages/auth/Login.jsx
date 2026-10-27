import { useState } from 'react';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { Landmark, ShieldCheck, LockKeyhole, Eye, EyeOff } from 'lucide-react';
import { login } from '../../api/auth.api';
import { useAuthStore } from '../../store/authStore';

const portalOptions = [
  { key: 'institution', title: 'Institution / College', description: 'Submit and manage institutional FDR records.', dashboard: '/institution', registration: '/institution/register', action: 'Register institution' },
  { key: 'official', title: 'AICTE Official', description: 'Review applications, FDRs, and authorized decisions.', dashboard: '/official', registration: '/official/register', action: 'Apply as AICTE Official' },
  { key: 'admin', title: 'Super Admin', description: 'Approve users and manage portal operations.', dashboard: '/admin', registration: '/super-admin/setup', action: 'First-time setup only' },
];

export default function Login() {
  const location = useLocation(), navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const selectedPortal = portalOptions.find(option => option.key === searchParams.get('portal'));
  const [busy, setBusy] = useState(false), [error, setError] = useState(location.search.includes('expired=1') ? 'Your session expired. Please sign in again.' : ''), [showPassword, setShowPassword] = useState(false);
  const setUser = useAuthStore((s) => s.setUser);
  function choosePortal(portal) {
    const query = new URLSearchParams({ portal });
    if (searchParams.get('expired') === '1') query.set('expired','1');
    navigate(`/login?${query.toString()}`, { state: location.state });
  }
  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError('');
    const form = new FormData(event.currentTarget);
    try {
      const data = await login(String(form.get('email')), String(form.get('password')));
      if (data.mfa_required) {
        navigate('/mfa');
        return;
      }
      setUser(data.user);
      const defaultPath = data.user.role === 'institution' ? '/institution' : data.user.role === 'admin' ? '/admin' : '/official';
      const statePath = location.state?.from
        ? `${location.state.from.pathname || ''}${location.state.from.search || ''}${location.state.from.hash || ''}` : '';
      const queryPath = searchParams.get('returnTo') || '';
      const requestedPath = statePath || queryPath;
      const rolePrefixes = data.user.role === 'institution' ? ['/institution']
        : data.user.role === 'admin' ? ['/admin'] : ['/official','/bureau'];
      const internalPath = requestedPath.startsWith('/') && !requestedPath.startsWith('//') &&
        rolePrefixes.some(prefix => requestedPath === prefix || requestedPath.startsWith(`${prefix}/`));
      const destination = internalPath ? requestedPath : defaultPath;
      navigate(destination, { replace: true });
    } catch (err) {
      const status = err.response?.status;
      if (status === 429) setError('Too many attempts. Try again later.');
      else if (status === 401) setError('Invalid email or password.');
      else if (!err.response) setError('Cannot reach the login service. Check that the backend is running.');
      else if (err.response.data?.error?.code === 'ACCOUNT_STATUS') setError(err.response.data.error.message);
      else setError(err.response.data?.error?.message || err.response.data?.detail || 'Login service is temporarily unavailable. Try again.');
    } finally { setBusy(false); }
  }
  if (!selectedPortal) return <main className="min-h-screen bg-slate-50">
    <header className="mx-auto flex max-w-6xl items-center gap-3 px-5 py-6"><span className="grid size-10 place-items-center rounded-xl bg-navy-900 text-white"><Landmark size={19}/></span><span className="text-lg font-bold">FDR<span className="text-indigo-700">Shield</span></span></header>
    <section className="mx-auto max-w-6xl px-5 pb-12 pt-5 sm:pt-10"><p className="text-sm font-semibold uppercase tracking-wide text-indigo-800">AICTE secure registry</p><h1 className="mt-2 text-3xl font-bold tracking-tight sm:text-4xl">Choose your portal</h1><p className="mt-2 max-w-2xl text-slate-600">Choose the account type you were assigned. The backend verifies your stored role and sends you to its authorized dashboard.</p>{error&&<p role="alert" aria-live="polite" className="mt-5 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">{error}</p>}<div className="mt-7 grid gap-4 md:grid-cols-3">{portalOptions.map(option=><article key={option.key} className="flex flex-col rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6"><h2 className="text-xl font-semibold">{option.title}</h2><p className="mt-2 min-h-12 text-sm leading-6 text-slate-600">{option.description}</p><button type="button" onClick={()=>choosePortal(option.key)} className="mt-5 rounded-lg bg-indigo-950 p-3 font-semibold text-white hover:bg-indigo-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-700">Continue to sign in</button><Link to={option.registration} className="mt-4 text-sm font-medium text-indigo-800 underline">{option.action}</Link>{option.key==='admin'&&<p className="mt-2 text-xs leading-5 text-slate-500">Only available before the first Super Admin is created and when backend setup is enabled.</p>}</article>)}</div></section>
  </main>;

  return <main className="grid min-h-screen bg-slate-50 lg:grid-cols-[minmax(320px,0.85fr)_1.15fr]">
    <aside className="hidden flex-col justify-between bg-navy-900 p-12 text-white lg:flex"><div className="flex items-center gap-3"><span className="grid size-11 place-items-center rounded-xl bg-white/10"><Landmark/></span><span className="text-xl font-bold">FDR-Shield</span></div><div className="max-w-md"><p className="mb-4 inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1 text-xs text-indigo-100"><ShieldCheck size={14}/> AICTE secure registry</p><h1 className="text-4xl font-semibold leading-tight">A clearer view of every security deposit.</h1><p className="mt-4 leading-7 text-indigo-100/80">Verify receipts, track maturity, and review decisions in one accountable workspace.</p></div><p className="text-xs text-indigo-100/60">FDR-Shield · Demonstration environment</p></aside>
      <section className="grid place-items-center p-5 sm:p-10"><div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-7 shadow-sm sm:p-9"><div className="mb-7 flex items-center gap-3 lg:hidden"><span className="grid size-10 place-items-center rounded-xl bg-navy-900 text-white"><Landmark size={19}/></span><span className="font-bold">FDR-Shield</span></div><p className="text-sm font-semibold text-indigo-800">{selectedPortal.title}</p><h2 className="mt-1 text-2xl font-bold tracking-tight">Sign in to FDR-Shield</h2><p className="mt-2 text-sm text-slate-500">{selectedPortal.description} Your role and access are verified by the server.</p>
      <form onSubmit={submit} className="mt-7 space-y-4">
        <label className="block text-sm font-medium text-slate-700">Email address
          <input name="email" type="email" autoComplete="username" autoCapitalize="none" required
            className="mt-1.5 w-full rounded-lg border border-slate-300 p-3 outline-none focus:border-indigo-700 focus:ring-2 focus:ring-indigo-100"/>
        </label>
        <label className="block text-sm font-medium text-slate-700">Password
          <span className="relative mt-1.5 block">
            <input name="password" type={showPassword ? 'text' : 'password'} autoComplete="current-password" required
              className="w-full rounded-lg border border-slate-300 p-3 pr-12 outline-none focus:border-indigo-700 focus:ring-2 focus:ring-indigo-100"/>
            <button type="button" aria-label={showPassword ? 'Hide password' : 'Show password'}
              aria-pressed={showPassword} onClick={() => setShowPassword(value => !value)}
              className="absolute inset-y-0 right-0 grid w-12 place-items-center rounded-r-lg text-slate-600 hover:bg-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-700">
              {showPassword ? <EyeOff size={18} aria-hidden="true"/> : <Eye size={18} aria-hidden="true"/>}
            </button>
          </span>
        </label>
        {error&&<p role="alert" aria-live="polite" className="text-sm text-red-700">{error}</p>}
        <button type="submit" disabled={busy} className="mt-2 flex w-full items-center justify-center gap-2 rounded-lg bg-indigo-950 p-3 font-semibold text-white hover:bg-indigo-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-800 disabled:cursor-wait disabled:opacity-60">
          <LockKeyhole size={16}/>{busy?'Signing in…':'Continue securely'}
        </button>
      </form>
      <div className="mt-5 flex flex-wrap justify-between gap-3 text-sm"><Link className="text-indigo-800 underline" to="/forgot-password">Forgot password?</Link><button type="button" onClick={()=>navigate('/login',{state:location.state})} className="text-indigo-800 underline">Choose another portal</button><Link className="text-indigo-800 underline" to={selectedPortal.registration}>{selectedPortal.action}</Link></div>
    </div></section>
  </main>;
}
