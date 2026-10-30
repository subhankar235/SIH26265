import { useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { Eye, EyeOff } from 'lucide-react';
import BrandHeader from '../../components/layout/BrandHeader';
import { useAuthStore } from '../../store/authStore';
import { acceptInvite, changePassword, forgotPassword, registerInstitution, registerOfficial, resetPassword, verifyEmail } from '../../api/auth.api';

function AuthPanel({ title, children }) {
  return <main className="min-h-screen bg-slate-50"><BrandHeader rightSlot={<Link to="/login" className="rounded-lg px-3 py-2 text-sm font-semibold text-[#273544] hover:bg-[#F1F5FA]">Sign in</Link>}/><div className="grid min-h-[calc(100vh-68px)] place-items-center p-5"><section className="w-full max-w-xl rounded-2xl border bg-white p-7 shadow-sm"><h1 className="text-2xl font-bold">{title}</h1>{children}</section></div></main>;
}

function PasswordField({ name, minLength, maxLength, autoComplete = 'new-password', inputClassName = 'mt-1 w-full rounded-lg border p-3' }) {
  const [visible, setVisible] = useState(false);
  return <span className="relative mt-1 block">
    <input name={name} type={visible ? 'text' : 'password'} autoComplete={autoComplete}
      minLength={minLength} maxLength={maxLength} required className={`${inputClassName} pr-12`}/>
    <button type="button" aria-label={visible ? 'Hide password' : 'Show password'}
      aria-pressed={visible} onClick={() => setVisible(value => !value)}
      className="absolute inset-y-0 right-0 grid w-12 place-items-center rounded-r-lg text-slate-600 hover:bg-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-700">
      {visible ? <EyeOff size={18} aria-hidden="true"/> : <Eye size={18} aria-hidden="true"/>}
    </button>
  </span>;
}

export function OfficialRegister() {
  const [message, setMessage] = useState(''), [error, setError] = useState('');
  async function submit(event) {
    event.preventDefault(); setError('');
    const data = Object.fromEntries(new FormData(event.currentTarget).entries());
    try {
      await registerOfficial(data);
      setMessage('Your application has been submitted and is awaiting Super Admin approval. You can sign in after it is approved.');
    } catch (err) {
      setError(err.response?.data?.error?.message || err.response?.data?.detail || 'Could not submit the application. Check the fields and try again.');
    }
  }
  return <AuthPanel title="AICTE Official application"><p className="mt-2 text-sm text-slate-600">Submit your application for Super Admin approval. You can sign in after it is approved.</p>{message ? <p className="mt-5 rounded-lg bg-green-50 p-4 text-green-900" role="status">{message}</p> : <form onSubmit={submit} className="mt-5 space-y-3"><label className="block text-sm">Full name<input name="full_name" autoComplete="name" minLength="2" maxLength="255" required className="mt-1 w-full rounded-lg border p-3"/></label><label className="block text-sm">Official email<input name="email" type="email" autoComplete="email" required className="mt-1 w-full rounded-lg border p-3"/></label><label className="block text-sm">Password (12+ characters)<PasswordField name="password" minLength="12" maxLength="128" inputClassName="w-full rounded-lg border p-3"/></label>{error&&<p role="alert" className="text-sm text-red-700">{error}</p>}<button className="w-full rounded-lg bg-indigo-950 p-3 font-semibold text-white">Submit application</button></form>}<p className="mt-5 text-sm"><Link className="text-indigo-800 underline" to="/login">Back to shared login</Link></p></AuthPanel>;
}

export function InstitutionRegister() {
  const [message, setMessage] = useState(''), [error, setError] = useState('');
  async function submit(e) {
    e.preventDefault(); setError(''); const form = new FormData(e.currentTarget); const body = Object.fromEntries(form.entries());
    try { await registerInstitution(body); setMessage('Your registration has been submitted and is awaiting AICTE Official or Super Admin approval. You can sign in after it is approved.'); }
    catch (x) { setError(x.response?.data?.detail || 'Could not submit registration. Check the fields and try again.'); }
  }
  return <AuthPanel title="Institution registration"><p className="mt-2 text-sm text-slate-600">Submit your institution registration for AICTE Official or Super Admin approval. You can sign in after it is approved.</p>{message ? <p className="mt-5 rounded-lg bg-green-50 p-4 text-green-900" role="status">{message}</p> : <form className="mt-5 grid gap-3 sm:grid-cols-2" onSubmit={submit}>{[['institution_name','Institution name'],['aicte_institution_id','AICTE institution ID'],['contact_name','Contact person'],['email','Email'],['phone','Phone'],['state','State'],['address','Address'],['password','Password (12+ characters)']].map(([name,label])=><label key={name} className="text-sm">{label}{name==='password' ? <PasswordField name={name} minLength="12" inputClassName="w-full rounded-lg border p-2.5"/> : <input className="mt-1 w-full rounded-lg border p-2.5" required={name!=='address'} type={name==='email'?'email':'text'} name={name}/>}</label>)}{error&&<p role="alert" className="sm:col-span-2 text-red-700">{error}</p>}<button className="rounded-lg bg-indigo-950 p-3 font-semibold text-white sm:col-span-2">Submit registration</button></form>}<p className="mt-5 text-sm"><Link className="text-indigo-800 underline" to="/login">Back to shared login</Link></p></AuthPanel>;
}

export function VerifyEmailPage() {
  const [params] = useSearchParams(), [message, setMessage] = useState('Verifying…'), [error, setError] = useState('');
  useEffect(() => { const token = params.get('token'); if (!token) { setMessage(''); setError('Verification link is missing.'); return; } verifyEmail(token).then(() => setMessage('Email verified. Your application is awaiting the appropriate approval.')).catch(() => { setMessage(''); setError('This verification link is invalid or expired.'); }); }, [params]);
  return <AuthPanel title="Email verification"><p role={error?'alert':'status'} className="mt-4">{error || message}</p><Link className="mt-4 inline-block text-indigo-800 underline" to="/login">Continue to shared login</Link></AuthPanel>;
}

export function AcceptInvitePage() {
  const [params] = useSearchParams(), [error, setError] = useState(''), [done, setDone] = useState(false);
  async function submit(e) { e.preventDefault(); setError(''); const password = new FormData(e.currentTarget).get('password'); try { await acceptInvite({ token: params.get('token'), password }); setDone(true); } catch (x) { setError(x.response?.data?.detail || 'Invitation is invalid or expired.'); } }
  return <AuthPanel title="Accept invitation">{done?<p role="status" className="mt-4">Account activated. <Link className="text-indigo-800 underline" to="/login">Sign in</Link></p>:<form className="mt-5 space-y-4" onSubmit={submit}><label className="block text-sm">New password (12+ characters)<input className="mt-1 w-full rounded-lg border p-3" name="password" type="password" minLength="12" required/></label>{error&&<p role="alert" className="text-red-700">{error}</p>}<button className="rounded-lg bg-indigo-950 p-3 text-white">Set password</button></form>}</AuthPanel>;
}

export function ForgotPasswordPage() {
  const [done, setDone] = useState(false), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  async function submit(e) { e.preventDefault(); if(busy)return; setBusy(true); setError(''); const email = new FormData(e.currentTarget).get('email'); try { await forgotPassword(email); setDone(true); } catch (x) { setError(x.response?.status===429?'Too many requests. Try again later.':'Could not submit the request right now. Please try again.'); } finally {setBusy(false);} }
  return <AuthPanel title="Reset password">{done?<p role="status" className="mt-4">If the account is eligible, a reset link will be sent.</p>:<form className="mt-5 space-y-4" onSubmit={submit}><label className="block text-sm">Email<input className="mt-1 w-full rounded-lg border p-3" name="email" type="email" autoComplete="email" required/></label>{error&&<p role="alert" className="text-red-700">{error}</p>}<button disabled={busy} className="rounded-lg bg-indigo-950 p-3 text-white disabled:opacity-60">{busy?'Sending…':'Send reset link'}</button></form>}</AuthPanel>;
}

export function ResetPasswordPage() {
  const [params] = useSearchParams(), [done, setDone] = useState(false), [error, setError] = useState('');
  async function submit(e) { e.preventDefault(); const password = new FormData(e.currentTarget).get('password'); try { await resetPassword({ token: params.get('token'), new_password: password }); setDone(true); } catch (x) { setError(x.response?.data?.detail || 'This reset link is invalid or expired.'); } }
  return <AuthPanel title="Choose a new password">{done?<p role="status" className="mt-4">Password changed. <Link className="text-indigo-800 underline" to="/login">Sign in</Link></p>:<form className="mt-5 space-y-4" onSubmit={submit}><label className="block text-sm">New password (12+ characters)<input className="mt-1 w-full rounded-lg border p-3" name="password" type="password" minLength="12" required/></label>{error&&<p role="alert" className="text-red-700">{error}</p>}<button className="rounded-lg bg-indigo-950 p-3 text-white">Change password</button></form>}</AuthPanel>;
}

export function ChangePasswordPage() {
  const [error, setError] = useState(''), [done, setDone] = useState(false), clearSession = useAuthStore((s) => s.clearSession), navigate = useNavigate();
  async function submit(e) { e.preventDefault(); const fields = Object.fromEntries(new FormData(e.currentTarget).entries()); try { await changePassword(fields); clearSession(); setDone(true); } catch (x) { setError(x.response?.data?.detail || 'Password could not be changed.'); } }
  if (done) return <AuthPanel title="Password changed"><p className="mt-4">Please sign in again with your new password.</p><button onClick={() => navigate('/login')} className="mt-4 rounded bg-indigo-950 px-4 py-2 text-white">Continue</button></AuthPanel>;
  return <AuthPanel title="Change password"><form className="mt-5 space-y-4" onSubmit={submit}><label className="block text-sm">Current password<input className="mt-1 w-full rounded-lg border p-3" name="current_password" type="password" required/></label><label className="block text-sm">New password (12+ characters)<input className="mt-1 w-full rounded-lg border p-3" name="new_password" type="password" minLength="12" required/></label>{error&&<p role="alert" className="text-red-700">{error}</p>}<button className="rounded-lg bg-indigo-950 p-3 text-white">Change password</button></form></AuthPanel>;
}
