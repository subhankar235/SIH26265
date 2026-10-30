import { useState } from 'react';
import { Link } from 'react-router-dom';
import BrandLogo from '../../components/layout/BrandLogo';
import { Eye, EyeOff, ShieldCheck } from 'lucide-react';
import { setupInitialSuperAdmin } from '../../api/auth.api';
import BrandHeader from '../../components/layout/BrandHeader';

export default function SuperAdminSetup() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [complete, setComplete] = useState(false);
  const [visible, setVisible] = useState({ password: false, confirm: false, secret: false });

  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    setError('');
    const form = event.currentTarget;
    const values = Object.fromEntries(new FormData(form).entries());
    if (values.password !== values.confirm_password) {
      setError('Password and confirmation do not match.');
      return;
    }
    setBusy(true);
    try {
      await setupInitialSuperAdmin({
        full_name: values.full_name.trim(),
        email: values.email.trim(),
        phone_number: values.phone_number.trim(),
        password: values.password,
        confirm_password: values.confirm_password,
        setup_secret: values.setup_secret,
      });
      form.reset();
      setComplete(true);
    } catch (requestError) {
      const status = requestError.response?.status;
      if (status === 403) setError('The setup secret is invalid.');
      else if (status === 409) setError('Initial Super Admin setup has already been completed, or the email cannot be used.');
      else if (status === 503) setError('Initial Super Admin setup is not enabled by the server.');
      else if (status === 422) setError('Check the submitted fields and password requirements.');
      else if (!requestError.response) setError('Cannot reach the setup service. Check that the backend is running.');
      else setError('Setup is temporarily unavailable. Please try again.');
    } finally {
      setBusy(false);
    }
  }

  const fieldClass = 'mt-1 w-full rounded-lg border border-slate-300 p-3 pr-12 outline-none transition focus:border-indigo-700 focus:ring-2 focus:ring-indigo-100';
  function secretField(name, label, visibilityKey, autoComplete) {
    const isVisible = visible[visibilityKey];
    return <label className="block text-sm font-medium text-slate-700" key={name}>{label}
      <span className="relative mt-1 block">
        <input className={fieldClass} name={name} type={isVisible ? 'text' : 'password'}
          autoComplete={autoComplete} required minLength={name === 'setup_secret' ? 1 : 12}
          maxLength={name === 'setup_secret' ? 512 : 128}/>
        <button type="button" aria-label={isVisible ? `Hide ${label.toLowerCase()}` : `Show ${label.toLowerCase()}`}
          aria-pressed={isVisible} onClick={() => setVisible(current => ({ ...current, [visibilityKey]: !current[visibilityKey] }))}
          className="absolute inset-y-0 right-0 grid w-12 place-items-center rounded-r-lg text-slate-600 hover:bg-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-700">
          {isVisible ? <EyeOff size={18} aria-hidden="true"/> : <Eye size={18} aria-hidden="true"/>}
        </button>
      </span>
    </label>;
  }

  return <main className="min-h-screen bg-slate-50"><BrandHeader rightSlot={<Link to="/login" className="rounded-lg px-3 py-2 text-sm font-semibold text-[#273544] hover:bg-[#F1F5FA]">Sign in</Link>}/><div className="grid min-h-[calc(100vh-68px)] place-items-center p-4 sm:p-8">
    <section className="w-full max-w-2xl overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-xl">
      <header className="bg-navy-900 p-6 text-white sm:p-8">
        <BrandLogo inverse markClassName="h-11 w-11"/>
        <p className="mt-6 inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1 text-xs text-indigo-100"><ShieldCheck size={14} aria-hidden="true"/>Controlled initial setup</p>
        <h1 className="mt-3 text-2xl font-bold sm:text-3xl">Create the first Super Admin</h1>
        <p className="mt-2 max-w-xl text-sm leading-6 text-indigo-100/90">This one-time setup is available only while no Super Admin account exists and requires a secret configured on the backend.</p>
      </header>

      <div className="p-6 sm:p-8">
        {complete ? <div className="space-y-4" role="status"><p className="rounded-lg border border-emerald-300 bg-emerald-50 p-4 text-emerald-950">Initial Super Admin created. Public setup is now permanently closed. Sign in using the Super Admin portal.</p><Link to="/admin/login" className="inline-flex rounded-lg bg-indigo-950 px-5 py-3 font-semibold text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-700">Go to Super Admin sign in</Link></div> : <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
          <label className="block text-sm font-medium text-slate-700">Full name<input className={fieldClass} name="full_name" autoComplete="name" required minLength="2" maxLength="255"/></label>
          <label className="block text-sm font-medium text-slate-700">Official email<input className={fieldClass} name="email" type="email" autoComplete="email" autoCapitalize="none" required maxLength="255"/></label>
          <label className="block text-sm font-medium text-slate-700 sm:col-span-2">Phone number<input className={fieldClass} name="phone_number" type="tel" autoComplete="tel" inputMode="tel" required minLength="7" maxLength="32" pattern="[+0-9() .-]+" title="Use digits, spaces, and optional + ( ) . - characters."/></label>
          {secretField('password','Password','password','new-password')}
          {secretField('confirm_password','Confirm password','confirm','new-password')}
          {secretField('setup_secret','Super Admin setup secret','secret','off')}
          {error && <p role="alert" aria-live="polite" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800 sm:col-span-2">{error}</p>}
          <button type="submit" disabled={busy} className="rounded-lg bg-indigo-950 p-3 font-semibold text-white transition hover:bg-indigo-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-700 disabled:cursor-wait disabled:opacity-60 sm:col-span-2">
            {busy ? 'Creating Super Admin…' : 'Create initial Super Admin'}
          </button>
          <p className="text-xs leading-5 text-slate-500 sm:col-span-2">The setup secret is submitted only to the backend for verification. It is not stored in the browser or returned in the response.</p>
        </form>}
      </div>
    </section>
  </div></main>;
}
