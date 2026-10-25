import { useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useAuthStore } from '../../store/authStore';
import { acceptInvite, changePassword, forgotPassword, registerInstitution, resetPassword, verifyEmail } from '../../api/auth.api';

function AuthPanel({ title, children }) {
  return <main className="grid min-h-screen place-items-center bg-slate-50 p-5"><section className="w-full max-w-xl rounded-2xl border bg-white p-7 shadow-sm"><h1 className="text-2xl font-bold">{title}</h1>{children}</section></main>;
}

export function PortalChooser() {
  const choices = [['Institution / College', '/institution/login'], ['AICTE Official', '/official/login'], ['Admin', '/admin/login']];
  return <AuthPanel title="Choose your FDR-Shield portal"><p className="mt-2 text-sm text-slate-600">Sign in through the portal assigned to your account.</p><div className="mt-6 grid gap-3">{choices.map(([label, path]) => <Link className="rounded-xl border p-4 font-semibold text-indigo-950 hover:bg-indigo-50" key={path} to={path}>{label} →</Link>)}</div></AuthPanel>;
}

export function InstitutionRegister() {
  const [message, setMessage] = useState(''), [error, setError] = useState('');
  async function submit(e) {
    e.preventDefault(); setError(''); const form = new FormData(e.currentTarget); const body = Object.fromEntries(form.entries());
    try { await registerInstitution(body); setMessage('If the registration can be processed, an email verification link will be sent.'); }
    catch (x) { setError(x.response?.data?.detail || 'Could not submit registration. Check the fields and try again.'); }
  }
  return <AuthPanel title="Institution registration"><p className="mt-2 text-sm text-slate-600">Verify your email, then wait for Admin approval before signing in.</p>{message ? <p className="mt-5 rounded-lg bg-green-50 p-4 text-green-900" role="status">{message}</p> : <form className="mt-5 grid gap-3 sm:grid-cols-2" onSubmit={submit}>{[['institution_name','Institution name'],['aicte_institution_id','AICTE institution ID'],['contact_name','Contact person'],['email','Email'],['phone','Phone'],['state','State'],['address','Address'],['password','Password (12+ characters)']].map(([name,label])=><label key={name} className="text-sm">{label}<input className="mt-1 w-full rounded-lg border p-2.5" required={name!=='address'} type={name==='email'?'email':name==='password'?'password':'text'} name={name} minLength={name==='password'?12:undefined}/></label>)}{error&&<p role="alert" className="sm:col-span-2 text-red-700">{error}</p>}<button className="rounded-lg bg-indigo-950 p-3 font-semibold text-white sm:col-span-2">Submit registration</button></form>}<p className="mt-5 text-sm"><Link className="text-indigo-800 underline" to="/institution/login">Back to Institution login</Link></p></AuthPanel>;
}

export function VerifyEmailPage() {
  const [params] = useSearchParams(), [message, setMessage] = useState('Verifying…'), [error, setError] = useState('');
  useEffect(() => { const token = params.get('token'); if (!token) { setMessage(''); setError('Verification link is missing.'); return; } verifyEmail(token).then(() => setMessage('Email verified. Your registration is awaiting Admin approval.')).catch(() => { setMessage(''); setError('This verification link is invalid or expired.'); }); }, [params]);
  return <AuthPanel title="Email verification"><p role={error?'alert':'status'} className="mt-4">{error || message}</p><Link className="mt-4 inline-block text-indigo-800 underline" to="/institution/login">Continue to login</Link></AuthPanel>;
}

export function AcceptInvitePage() {
  const [params] = useSearchParams(), [error, setError] = useState(''), [done, setDone] = useState(false);
  async function submit(e) { e.preventDefault(); setError(''); const password = new FormData(e.currentTarget).get('password'); try { await acceptInvite({ token: params.get('token'), password }); setDone(true); } catch (x) { setError(x.response?.data?.detail || 'Invitation is invalid or expired.'); } }
  return <AuthPanel title="Accept invitation">{done?<p role="status" className="mt-4">Account activated. <Link className="text-indigo-800 underline" to="/login">Sign in</Link></p>:<form className="mt-5 space-y-4" onSubmit={submit}><label className="block text-sm">New password (12+ characters)<input className="mt-1 w-full rounded-lg border p-3" name="password" type="password" minLength="12" required/></label>{error&&<p role="alert" className="text-red-700">{error}</p>}<button className="rounded-lg bg-indigo-950 p-3 text-white">Set password</button></form>}</AuthPanel>;
}

export function ForgotPasswordPage() {
  const [done, setDone] = useState(false), [error, setError] = useState('');
  async function submit(e) { e.preventDefault(); setError(''); const email = new FormData(e.currentTarget).get('email'); try { await forgotPassword(email); setDone(true); } catch (x) { setError(x.response?.data?.detail || 'Please try again later.'); } }
  return <AuthPanel title="Reset password">{done?<p role="status" className="mt-4">If the account is eligible, a reset link will be sent.</p>:<form className="mt-5 space-y-4" onSubmit={submit}><label className="block text-sm">Email<input className="mt-1 w-full rounded-lg border p-3" name="email" type="email" required/></label>{error&&<p role="alert" className="text-red-700">{error}</p>}<button className="rounded-lg bg-indigo-950 p-3 text-white">Send reset link</button></form>}</AuthPanel>;
}

export function ResetPasswordPage() {
  const [params] = useSearchParams(), [done, setDone] = useState(false), [error, setError] = useState('');
  async function submit(e) { e.preventDefault(); const password = new FormData(e.currentTarget).get('password'); try { await resetPassword({ token: params.get('token'), new_password: password }); setDone(true); } catch (x) { setError(x.response?.data?.detail || 'This reset link is invalid or expired.'); } }
  return <AuthPanel title="Choose a new password">{done?<p role="status" className="mt-4">Password changed. <Link className="text-indigo-800 underline" to="/login">Sign in</Link></p>:<form className="mt-5 space-y-4" onSubmit={submit}><label className="block text-sm">New password (12+ characters)<input className="mt-1 w-full rounded-lg border p-3" name="password" type="password" minLength="12" required/></label>{error&&<p role="alert" className="text-red-700">{error}</p>}<button className="rounded-lg bg-indigo-950 p-3 text-white">Change password</button></form>}</AuthPanel>;
}

export function ChangePasswordPage() {
  const [error, setError] = useState(''), [done, setDone] = useState(false), [loginPath, setLoginPath] = useState('/login'), user = useAuthStore((s) => s.user), clearSession = useAuthStore((s) => s.clearSession), navigate = useNavigate();
  async function submit(e) { e.preventDefault(); const fields = Object.fromEntries(new FormData(e.currentTarget).entries()); try { await changePassword(fields); setLoginPath(user?.role==='institution'?'/institution/login':user?.role==='admin'?'/admin/login':'/official/login'); clearSession(); setDone(true); } catch (x) { setError(x.response?.data?.detail || 'Password could not be changed.'); } }
  if (done) return <AuthPanel title="Password changed"><p className="mt-4">Please sign in again with your new password.</p><button onClick={() => navigate(loginPath)} className="mt-4 rounded bg-indigo-950 px-4 py-2 text-white">Continue</button></AuthPanel>;
  return <AuthPanel title="Change password"><form className="mt-5 space-y-4" onSubmit={submit}><label className="block text-sm">Current password<input className="mt-1 w-full rounded-lg border p-3" name="current_password" type="password" required/></label><label className="block text-sm">New password (12+ characters)<input className="mt-1 w-full rounded-lg border p-3" name="new_password" type="password" minLength="12" required/></label>{error&&<p role="alert" className="text-red-700">{error}</p>}<button className="rounded-lg bg-indigo-950 p-3 text-white">Change password</button></form></AuthPanel>;
}
