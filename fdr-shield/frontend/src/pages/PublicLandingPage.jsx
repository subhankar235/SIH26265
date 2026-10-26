import { Link } from 'react-router-dom';
import { Landmark, ShieldCheck } from 'lucide-react';

export default function PublicLandingPage() {
  return <main className="min-h-screen bg-slate-50 text-slate-950">
    <header className="mx-auto flex max-w-7xl items-center justify-between px-5 py-5 sm:px-8">
      <Link to="/" className="flex items-center gap-3 rounded-lg focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-700" aria-label="FDR-Shield home">
        <span className="grid size-10 place-items-center rounded-xl bg-navy-900 text-white"><Landmark aria-hidden="true" size={19}/></span>
        <span className="text-lg font-bold">FDR<span className="text-indigo-700">Shield</span></span>
      </Link>
      <nav aria-label="Public navigation" className="flex items-center gap-4 text-sm">
        <Link to="/login" className="rounded-lg bg-indigo-950 px-4 py-2.5 font-semibold text-white hover:bg-indigo-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-700">Sign in / choose portal</Link>
      </nav>
    </header>
    <section className="mx-auto grid min-h-[calc(100vh-80px)] max-w-7xl items-center gap-10 px-5 py-10 lg:grid-cols-[1.1fr_.9fr] lg:px-8">
      <div>
        <p className="inline-flex items-center gap-2 rounded-full border border-indigo-200 bg-white px-3 py-1.5 text-xs font-semibold text-indigo-900"><ShieldCheck size={15} aria-hidden="true"/>AICTE secure registry</p>
        <h1 className="mt-5 max-w-2xl text-4xl font-bold leading-tight tracking-tight sm:text-5xl">A clearer view of every security deposit.</h1>
        <p className="mt-5 max-w-2xl text-base leading-7 text-slate-600">Verify fixed deposit receipts, track maturity, and review decisions in one accountable workspace for institutions and AICTE officials.</p>
        <div className="mt-8 flex flex-wrap gap-3"><Link to="/login" className="rounded-lg bg-indigo-950 px-5 py-3 font-semibold text-white hover:bg-indigo-900">Choose your portal</Link></div>
      </div>
      <aside className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8"><h2 className="text-lg font-semibold">Three secure workspaces</h2><ul className="mt-5 space-y-4 text-sm leading-6 text-slate-600"><li><b className="text-slate-900">Institutions:</b> submit FDRs, follow verification, and manage renewals and releases.</li><li><b className="text-slate-900">AICTE Officials:</b> review applications, scrutinize records, and manage authorized decisions.</li><li><b className="text-slate-900">Super Admin:</b> approve users and oversee portal operations.</li></ul><p className="mt-6 border-t pt-4 text-xs text-slate-500">Demonstration portal. Bank verification uses the included mock gateway.</p></aside>
    </section>
  </main>;
}
