import { useState } from 'react';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { Building2, ChartNoAxesColumnIncreasing, ClipboardCheck, Eye, EyeOff, FolderOpen, LockKeyhole, ScanLine, Settings2, Share2 } from 'lucide-react';
import { login } from '../../api/auth.api';
import { useAuthStore } from '../../store/authStore';
import BrandWordmark from '../../components/layout/BrandWordmark';

const portalOptions = [
  { key: 'admin', title: 'Super Admin', description: 'Approve users and manage portal operations.', registration: '/super-admin/setup', action: 'First-time setup only', icon: Settings2, theme: 'border-[#D8E1EA] bg-[#EAF3FF]/75 text-[#12395A]' },
  { key: 'official', title: 'AICTE Official', description: 'Review applications, FDRs, and authorized decisions.', registration: '/official/register', action: 'Apply as AICTE Official', icon: ClipboardCheck, theme: 'border-[#B8E8D5] bg-[#DDF8EC]/80 text-[#126B5B]' },
  { key: 'institution', title: 'Institutional User', description: 'Submit and manage institutional FDR records.', registration: '/institution/register', action: 'Register institution', icon: Building2, theme: 'border-[#F1D7A1] bg-[#FFF7DF]/85 text-[#8A5418]' },
];

function LoginBackdrop() {
  return <>
    <div aria-hidden="true" className="login-dot-field absolute inset-0"/>
    <svg aria-hidden="true" className="pointer-events-none absolute inset-0 h-full w-full" viewBox="0 0 1024 576" preserveAspectRatio="none" fill="none">
      <path d="M-30 108H238C280 108 300 128 300 168V221" stroke="#3182F6" strokeOpacity=".2" strokeWidth="34"/><path d="M-30 108H238C280 108 300 128 300 168V221" stroke="#3182F6" strokeOpacity=".82" strokeWidth="2.5"/>
      <path d="M-30 306H178C218 306 240 320 264 352C285 380 302 390 339 390H550" stroke="#36B7AD" strokeOpacity=".21" strokeWidth="34"/><path d="M-30 306H178C218 306 240 320 264 352C285 380 302 390 339 390H550" stroke="#2CAFA5" strokeOpacity=".82" strokeWidth="2.5"/>
      <path d="M-30 476H214C260 476 282 453 282 412V376C282 333 310 306 354 306H550" stroke="#36B7AD" strokeOpacity=".21" strokeWidth="34"/><path d="M-30 476H214C260 476 282 453 282 412V376C282 333 310 306 354 306H550" stroke="#2CAFA5" strokeOpacity=".82" strokeWidth="2.5"/>
      <path d="M1048 126H1007C980 126 966 145 966 173V194C966 222 950 240 921 240H826" stroke="#EF725E" strokeOpacity=".2" strokeWidth="34"/><path d="M1048 126H1007C980 126 966 145 966 173V194C966 222 950 240 921 240H826" stroke="#E96B58" strokeOpacity=".84" strokeWidth="2.5"/>
      <path d="M826 280H898C940 280 962 300 962 340V410C962 444 986 460 1048 460" stroke="#E6A23A" strokeOpacity=".21" strokeWidth="34"/><path d="M826 280H898C940 280 962 300 962 340V410C962 444 986 460 1048 460" stroke="#D99A30" strokeOpacity=".84" strokeWidth="2.5"/>
    </svg>
  </>;
}

export default function Login() {
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const selectedPortal = portalOptions.find(option => option.key === searchParams.get('portal'));
  const [pendingPortal, setPendingPortal] = useState(selectedPortal?.key || '');
  const activePortal = selectedPortal || portalOptions.find(option => option.key === pendingPortal) || portalOptions[1];
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(location.search.includes('expired=1') ? 'Your session expired. Please sign in again.' : '');
  const [showPassword, setShowPassword] = useState(false);
  const setUser = useAuthStore((s) => s.setUser);

  function choosePortal(portal) {
    setPendingPortal(portal);
    const query = new URLSearchParams({ portal });
    if (searchParams.get('expired') === '1') query.set('expired', '1');
    navigate(`/login?${query.toString()}`, { state: location.state });
  }

  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError('');
    const form = new FormData(event.currentTarget);
    try {
      const data = await login(String(form.get('email')), String(form.get('password')));
      if (data.mfa_required) { navigate('/mfa'); return; }
      setUser(data.user);
      const defaultPath = data.user.role === 'institution' ? '/institution' : data.user.role === 'admin' ? '/admin' : '/official';
      const requestedPath = location.state?.from?.pathname || '';
      const expectedPrefix = `${defaultPath}/`;
      const destination = requestedPath === defaultPath || requestedPath.startsWith(expectedPrefix) ? requestedPath : defaultPath;
      navigate(destination, { replace: true });
    } catch (err) {
      const status = err.response?.status;
      if (status === 429) setError('Too many attempts. Try again later.');
      else if (status === 401) setError('Invalid email or password. Check your details and try again.');
      else if (!err.response) setError('Cannot reach the login service. Check that the backend is running.');
      else if (err.response.data?.error?.code === 'ACCOUNT_STATUS') setError(err.response.data.error.message);
      else setError(err.response.data?.error?.message || err.response.data?.detail || 'Login service is temporarily unavailable. Try again.');
    } finally { setBusy(false); }
  }

  return <main className="login-viewport relative isolate flex min-h-dvh items-center justify-center overflow-hidden bg-[#F5F8FC] text-[#273544]">
    <div className="login-stage">
      <LoginBackdrop/>
      <span aria-hidden="true" className="login-float login-float-scan"><ScanLine/></span>
      <span aria-hidden="true" className="login-float login-float-folder"><FolderOpen/></span>
      <span aria-hidden="true" className="login-float login-float-share"><Share2/></span>
      <span aria-hidden="true" className="login-float login-float-chart"><ChartNoAxesColumnIncreasing/></span>
      <span aria-hidden="true" className="login-sparkle">✦</span>
      <aside className="login-brand-position absolute z-10">
        <Link to="/" aria-label="NidhiTrack home" className="login-brand group inline-flex w-fit items-center gap-4 rounded-lg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[#3182F6]">
          <img src="/brand/nidhitrack-mark.svg" alt="" aria-hidden="true" className="login-brand-mark h-20 w-20 shrink-0 object-contain xl:h-24 xl:w-24"/>
          <span className="login-brand-copy flex min-w-0 flex-col leading-none"><BrandWordmark/><span className="login-brand-subtitle mt-2 whitespace-nowrap font-medium uppercase tracking-[.12em] text-[#506A75]">AICTE FDR Management Portal</span></span>
        </Link>
      </aside>

    <section className="login-panel absolute z-10 flex items-center justify-center">
      <div className="login-card w-full rounded-2xl border border-[#D8E1EA] bg-white/95 shadow-[0_16px_48px_rgba(39,53,68,.10)]">
        <header className="mb-4">
          <div className="flex items-center justify-between gap-3"><h2 aria-label="Sign in to NidhiTrack" className="text-2xl font-bold tracking-tight text-[#273544]">Sign in</h2><p className="inline-flex items-center rounded-full bg-[#EAF3FF] px-2 py-0.5 text-xs font-bold uppercase tracking-[.1em] text-[#124C7A]">Secure access</p></div>
          <p className="mt-1.5 text-sm text-[#64748B]">Choose your role to continue to your workspace.</p>
        </header>
        <div className="mb-2 flex items-center gap-3"><span className="h-px flex-1 bg-[#D8E1EA]"/><h1 className="whitespace-nowrap text-sm font-semibold text-[#526173]">Select your role</h1><span className="h-px flex-1 bg-[#D8E1EA]"/></div>
        <div className="grid grid-cols-3 overflow-hidden rounded-xl border border-[#D8E1EA]">
          {portalOptions.map(({ key, title, icon: Icon, theme }) => {
            const active = (selectedPortal?.key || pendingPortal) === key;
            return <button key={key} type="button" aria-pressed={active} onClick={() => choosePortal(key)} className={`flex min-h-[76px] flex-col items-center justify-center gap-1 border-r border-[#D8E1EA] p-1.5 text-center text-[11px] font-semibold leading-tight transition-[color,background-color,border-color,box-shadow] last:border-r-0 hover:brightness-[.98] focus-visible:z-10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#3182F6] sm:min-h-[88px] sm:gap-1.5 sm:p-2 sm:text-sm ${active ? 'border-[#12395A] bg-[#12395A] text-white shadow-[0_4px_12px_rgba(18,57,90,.24)] ring-2 ring-[#3182F6]/30' : theme}`}>
              <span className={`grid size-8 place-items-center rounded-lg shadow-sm sm:size-10 ${active ? 'bg-white text-[#12395A]' : 'bg-white/80'}`}><Icon size={19}/></span>{title}
            </button>;
          })}
        </div>

        {error && <p role="alert" aria-live="polite" className="mt-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm leading-5 text-rose-900">{error}</p>}
        <form onSubmit={submit}>
          <label className="block text-xs font-semibold uppercase tracking-wide text-[#64748B]">Email address<input name="email" type="email" autoComplete="username" autoCapitalize="none" required placeholder="Email address" className="mt-1 min-h-10 w-full rounded-lg border border-[#D8E1EA] bg-white px-3.5 text-base normal-case tracking-normal outline-none transition focus:border-[#3182F6] focus:ring-4 focus:ring-[#3182F6]/10"/></label>
          <div>
            <div className="flex items-center justify-between gap-3"><label htmlFor="login-password" className="text-xs font-semibold uppercase tracking-wide text-[#64748B]">Password</label><Link className="text-sm font-semibold text-[#3182F6] hover:text-[#197F80]" to="/forgot-password">Forgot password?</Link></div>
            <span className="relative mt-1 block"><input id="login-password" name="password" type={showPassword ? 'text' : 'password'} autoComplete="current-password" required placeholder="Password" className="min-h-10 w-full rounded-lg border border-[#D8E1EA] bg-white px-3.5 pr-12 text-base outline-none transition focus:border-[#3182F6] focus:ring-4 focus:ring-[#3182F6]/10"/><button type="button" aria-label={showPassword ? 'Hide password' : 'Show password'} aria-pressed={showPassword} onClick={() => setShowPassword(value => !value)} className="absolute inset-y-0 right-0 grid w-12 place-items-center rounded-r-lg text-[#526173] hover:bg-[#F1F5FA] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#3182F6]">{showPassword ? <EyeOff size={18} aria-hidden="true"/> : <Eye size={18} aria-hidden="true"/>}</button></span>
          </div>
          <button type="submit" disabled={busy} className="flex min-h-10 w-full items-center justify-center gap-2 rounded-lg bg-gradient-to-r from-[#3182F6] to-[#25B98A] p-2.5 font-bold text-white shadow-sm transition hover:brightness-105 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#3182F6] disabled:cursor-wait disabled:opacity-60"><LockKeyhole size={16}/>{busy ? 'Signing in…' : 'Secure access'}</button>
        </form>
        <div className="mt-3 text-center"><Link className="text-sm font-semibold text-[#3182F6] underline decoration-[#C9DAF3] underline-offset-4 hover:text-[#197F80]" to={activePortal.registration}>{activePortal.action}</Link></div>
      </div>
    </section>
    </div>
  </main>;
}
