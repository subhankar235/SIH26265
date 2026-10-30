import { useEffect } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, BadgeCheck, Building2, ChartNoAxesCombined, Check, ClipboardCheck, Download, FileCheck2, FolderOpen, Github, Linkedin, LockKeyhole, Mail, Printer, ScanSearch } from 'lucide-react';
import BrandHeader from '../components/layout/BrandHeader';
import BrandWordmark from '../components/layout/BrandWordmark';

const features = [
  { icon: FileCheck2, title: 'One trusted record', text: 'Keep receipt details, supporting files, verification, and decisions connected to each FDR.' },
  { icon: ScanSearch, title: 'Clear verification', text: 'Review extracted details and bank checks together so discrepancies are easy to resolve.' },
  { icon: ClipboardCheck, title: 'A complete lifecycle', text: 'Follow maturity, renewal, and release actions with a traceable history at every step.' },
];

const developers = [
  ['Aditi Rao', 'aditi.rao@example.com'],
  ['Arjun Mehta', 'arjun.mehta@example.com'],
  ['Neha Kulkarni', 'neha.kulkarni@example.com'],
  ['Rohan Iyer', 'rohan.iyer@example.com'],
  ['Sana Khan', 'sana.khan@example.com'],
  ['Vivek Das', 'vivek.das@example.com'],
].map(([name, email]) => {
  const query = encodeURIComponent(name);
  return {
    name,
    email,
    github: `https://github.com/search?q=${query}&type=users`,
    linkedin: `https://www.linkedin.com/search/results/people/?keywords=${query}`,
  };
});

function useScrollReveal() {
  useEffect(() => {
    const items = [...document.querySelectorAll('[data-reveal]')];
    if (!('IntersectionObserver' in window)) {
      items.forEach(item => item.classList.add('is-visible'));
      return;
    }
    const observer = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12, rootMargin: '0px 0px -36px 0px' });
    items.forEach(item => observer.observe(item));
    return () => observer.disconnect();
  }, []);
}

export default function PublicLandingPage() {
  useScrollReveal();

  return <main className="min-h-screen bg-white text-[#273544]">
    <a href="#main-content" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-white focus:px-4 focus:py-3 focus:text-sm focus:font-semibold">Skip to content</a>
    <BrandHeader className="home-brand-header" innerClassName="home-header-inner" rightSlot={<nav aria-label="Public navigation" className="home-public-nav flex items-center gap-3 text-xs sm:gap-7"><a href="#lifecycle" className="hidden font-medium text-[#111827] hover:text-[#197F80] sm:inline">How it works</a><a href="#features" className="hidden font-medium text-[#111827] hover:text-[#197F80] sm:inline">Features</a><a href="#contact" className="hidden font-medium text-[#111827] hover:text-[#197F80] sm:inline">Contact Us</a><Link to="/login" className="inline-flex min-h-7 items-center justify-center rounded-md bg-gradient-to-r from-[#3182F6] to-[#25B98A] px-[27px] py-1.5 font-semibold text-white shadow-[0_3px_10px_rgba(49,130,246,.2)] transition-transform hover:-translate-y-0.5 hover:brightness-105 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#3182F6]">Sign in</Link></nav>} />

    <section id="main-content" className="home-hero relative isolate flex min-h-[calc(100svh-68px)] items-center justify-center overflow-hidden px-5 py-12 sm:px-8">
      <div aria-hidden="true" className="home-dot-field absolute inset-0"/>
      <svg aria-hidden="true" className="home-flow-lines pointer-events-none absolute inset-0 h-full w-full" viewBox="0 0 1024 576" preserveAspectRatio="none" fill="none">
        <path d="M-24 48H226C274 48 298 72 298 116V184" stroke="#5EB9E5" strokeOpacity=".19" strokeWidth="31"/><path d="M-24 48H226C274 48 298 72 298 116V184" stroke="#55A9DA" strokeOpacity=".82" strokeWidth="2.5"/>
        <path d="M-24 380H10C35 380 46 360 46 330V270C46 240 65 223 104 223H194" stroke="#55C4BE" strokeOpacity=".2" strokeWidth="31"/><path d="M-24 380H10C35 380 46 360 46 330V270C46 240 65 223 104 223H194" stroke="#48B8B3" strokeOpacity=".83" strokeWidth="2.5"/>
        <path d="M1048 55H1001C975 55 963 75 963 105V175C963 201 944 203 917 203H828" stroke="#F27A64" strokeOpacity=".2" strokeWidth="31"/><path d="M1048 55H1001C975 55 963 75 963 105V175C963 201 944 203 917 203H828" stroke="#EA715D" strokeOpacity=".84" strokeWidth="2.5"/>
        <path d="M828 240H916C950 240 964 261 964 297V405C964 428 985 440 1028 440H1048" stroke="#E8B64D" strokeOpacity=".22" strokeWidth="31"/><path d="M828 240H916C950 240 964 261 964 297V405C964 428 985 440 1028 440H1048" stroke="#DCA63A" strokeOpacity=".86" strokeWidth="2.5"/>
      </svg>
      <span aria-hidden="true" className="home-float home-float-folder"><FolderOpen/></span>
      <span aria-hidden="true" className="home-float home-float-printer"><Printer/></span>
      <span aria-hidden="true" className="home-float home-float-chart-top"><ChartNoAxesCombined/></span>
      <span aria-hidden="true" className="home-float home-float-chart-bottom"><ChartNoAxesCombined/></span>
      <span aria-hidden="true" className="home-sparkle">✦</span>
      <div className="relative z-10 mx-auto w-full max-w-4xl -translate-y-3 text-center">
        <p className="home-eyebrow animate-rise">AICTE · FDR lifecycle tracking</p>
        <h1 className="animate-rise-delay mt-3 font-display text-4xl font-bold leading-[1.04] tracking-tight text-[#111827] sm:text-5xl lg:text-[4.25rem] lg:leading-[.92]">Every deposit.<br className="hidden sm:block"/> Accounted for.</h1>
        <p className="mx-auto mt-5 max-w-2xl text-base leading-7 text-[#111827] sm:text-lg sm:leading-8">Move each security deposit from receipt to verification, review, and renewal with a clear, auditable record at every step.</p>
        <div className="mt-7 flex flex-wrap justify-center gap-3">
          <Link to="/login" className="inline-flex min-h-12 items-center gap-2 rounded-md bg-gradient-to-r from-[#3182F6] to-[#20B99D] px-6 py-3 font-medium text-white shadow-[0_4px_12px_rgba(49,130,246,.24)] transition-transform hover:-translate-y-0.5 hover:brightness-105 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#3182F6]">Choose your workspace <ArrowRight size={17}/></Link>
          <a href="https://github.com/subhankar235/SIH26265/releases" target="_blank" rel="noopener noreferrer" className="inline-flex min-h-12 items-center gap-2 rounded-md border border-[#BFCBD7] bg-white/35 px-6 py-3 font-medium text-[#111827] transition-colors hover:border-[#3182f6] hover:bg-white/75 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#3182F6]"><Download size={17}/> Download App APK</a>
          <a href="#features" className="inline-flex min-h-12 items-center rounded-md border border-[#BFCBD7] bg-white/35 px-6 py-3 font-medium text-[#111827] transition-colors hover:border-[#3182f6] hover:bg-white/75 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#3182F6]">Explore the features</a>
        </div>
        <div className="mt-5 flex flex-wrap justify-center gap-x-5 gap-y-3 text-sm text-[#111827]">
          <span className="group inline-flex items-center gap-2"><span className="home-trust-icon home-trust-violet"><BadgeCheck size={15}/></span><span className="hero-glow-violet">Auditable records</span></span>
          <span className="group inline-flex items-center gap-2"><span className="home-trust-icon home-trust-amber"><LockKeyhole size={15}/></span><span className="hero-glow-slate">Role-based access</span></span>
          <span className="group inline-flex items-center gap-2"><span className="home-trust-icon home-trust-green"><Building2 size={15}/></span><span className="hero-glow-muted">Institution-ready</span></span>
        </div>
      </div>
    </section>
    <section id="lifecycle" className="image-divider scroll-mt-[68px]" aria-labelledby="lifecycle-divider-heading">
      <div className="mx-auto flex min-h-[360px] max-w-7xl flex-col items-center justify-center px-5 py-16 text-center text-white sm:min-h-[420px] sm:px-8 sm:py-20">
        <p className="text-xs font-bold uppercase tracking-[.18em] text-[#DCEBFF]">From submission to maturity</p>
        <h2 id="lifecycle-divider-heading" className="mt-4 max-w-3xl text-3xl font-bold leading-tight tracking-tight sm:text-4xl lg:text-5xl">One clear record, through every step.</h2>
        <p className="mt-5 max-w-2xl text-sm leading-7 text-white/85 sm:text-base">Keep each receipt, review decision, and maturity action connected in a traceable deposit lifecycle.</p>
        <div aria-label="Deposit lifecycle" className="mt-8 flex flex-wrap items-center justify-center gap-2 rounded-full border border-white/25 bg-white/10 px-3 py-2 text-xs font-semibold text-white shadow-lg backdrop-blur-md sm:gap-3 sm:px-5 sm:py-3 sm:text-sm">
          {['Receipt', 'Verification', 'Decision', 'Maturity'].map((item, index) => <span key={item} className="inline-flex items-center gap-2 sm:gap-3"><span>{item}</span>{index < 3 && <span aria-hidden="true" className="text-[#DCEBFF]">→</span>}</span>)}
        </div>
      </div>
    </section>

    <section id="evidence" className="home-evidence relative isolate flex min-h-[calc(100svh-68px)] items-center justify-center overflow-hidden scroll-mt-[68px]" aria-label="Evidence in context">
      <div aria-hidden="true" className="home-dot-field absolute inset-0"/>
      <svg aria-hidden="true" className="home-flow-lines pointer-events-none absolute inset-0 h-full w-full" viewBox="0 0 1024 576" preserveAspectRatio="none" fill="none">
        <path d="M-24 48H226C274 48 298 72 298 116V184" stroke="#5EB9E5" strokeOpacity=".19" strokeWidth="31"/><path d="M-24 48H226C274 48 298 72 298 116V184" stroke="#55A9DA" strokeOpacity=".82" strokeWidth="2.5"/>
        <path d="M-24 380H10C35 380 46 360 46 330V270C46 240 65 223 104 223H194" stroke="#55C4BE" strokeOpacity=".2" strokeWidth="31"/><path d="M-24 380H10C35 380 46 360 46 330V270C46 240 65 223 104 223H194" stroke="#48B8B3" strokeOpacity=".83" strokeWidth="2.5"/>
        <path d="M1048 55H1001C975 55 963 75 963 105V175C963 201 944 203 917 203H828" stroke="#F27A64" strokeOpacity=".2" strokeWidth="31"/><path d="M1048 55H1001C975 55 963 75 963 105V175C963 201 944 203 917 203H828" stroke="#EA715D" strokeOpacity=".84" strokeWidth="2.5"/>
        <path d="M828 240H916C950 240 964 261 964 297V405C964 428 985 440 1028 440H1048" stroke="#E8B64D" strokeOpacity=".22" strokeWidth="31"/><path d="M828 240H916C950 240 964 261 964 297V405C964 428 985 440 1028 440H1048" stroke="#DCA63A" strokeOpacity=".86" strokeWidth="2.5"/>
        <path d="M365 232C402 232 418 252 418 282V335C418 363 440 378 475 378H535" stroke="#55C4BE" strokeOpacity=".2" strokeWidth="28"/><path d="M365 232C402 232 418 252 418 282V335C418 363 440 378 475 378H535" stroke="#48B8B3" strokeOpacity=".84" strokeWidth="2.5"/>
      </svg>
      <span aria-hidden="true" className="home-float home-evidence-folder"><FolderOpen/></span>
      <span aria-hidden="true" className="home-float home-evidence-printer"><Printer/></span>
      <span aria-hidden="true" className="home-float home-evidence-chart-top"><ChartNoAxesCombined/></span>
      <span aria-hidden="true" className="home-float home-evidence-chart-bottom"><ChartNoAxesCombined/></span>
      <span aria-hidden="true" className="home-sparkle">&#10022;</span>
      <div className="home-evidence-layout relative z-10 grid items-center">
        <figure className="home-evidence-figure">
          <div className="home-evidence-paper" aria-label="Sample HDFC fixed deposit receipt">
            <div className="home-receipt-page">
              <p className="home-receipt-heading">HDFC FIXED DEPOSIT RECEIPT</p>
              <p className="home-receipt-line">FDR Number: HDFC700002</p>
              <p className="home-receipt-line">Holder: Deliberately Different Institute</p>
              <p className="home-receipt-line">Amount (INR): 650000.0</p>
              <p className="home-receipt-line">Maturity Date: 2026-11-24</p>
            </div>
          </div>
          <figcaption className="home-evidence-caption">Demo sample scan</figcaption>
        </figure>
        <div className="home-evidence-copy">
          <p className="home-eyebrow">Evidence in context</p>
          <h2 className="home-evidence-title">See the receipt, checks, and next together.</h2>
          <p className="home-evidence-description"><BrandWordmark className="text-[.95em]"/> keeps the original document alongside the record details and review history, helping each person pick up the work with confidence.</p>
          <ul className="home-evidence-list">
            {['Receipt attached to its FDR record', 'Verification observations kept in view', 'Decisions and follow-up actions traceable'].map(item => <li key={item}><span aria-hidden="true"><Check size={13}/></span>{item}</li>)}
          </ul>
          <Link to="/login" className="home-evidence-link">Open your workspace <ArrowRight size={15}/></Link>
        </div>
      </div>
    </section>
    <section id="features" className="home-features relative isolate flex min-h-[calc(100svh-68px)] items-center justify-center overflow-hidden scroll-mt-[68px]" aria-labelledby="features-heading">
      <div aria-hidden="true" className="home-dot-field absolute inset-0"/>
      <svg aria-hidden="true" className="home-flow-lines pointer-events-none absolute inset-0 h-full w-full" viewBox="0 0 1024 576" preserveAspectRatio="none" fill="none">
        <path d="M-24 48H226C274 48 298 72 298 116V184" stroke="#5EB9E5" strokeOpacity=".19" strokeWidth="31"/><path d="M-24 48H226C274 48 298 72 298 116V184" stroke="#55A9DA" strokeOpacity=".82" strokeWidth="2.5"/>
        <path d="M-24 380H10C35 380 46 360 46 330V270C46 240 65 223 104 223H194" stroke="#55C4BE" strokeOpacity=".2" strokeWidth="31"/><path d="M-24 380H10C35 380 46 360 46 330V270C46 240 65 223 104 223H194" stroke="#48B8B3" strokeOpacity=".83" strokeWidth="2.5"/>
        <path d="M1048 55H1001C975 55 963 75 963 105V175C963 201 944 203 917 203H828" stroke="#F27A64" strokeOpacity=".2" strokeWidth="31"/><path d="M1048 55H1001C975 55 963 75 963 105V175C963 201 944 203 917 203H828" stroke="#EA715D" strokeOpacity=".84" strokeWidth="2.5"/>
        <path d="M828 240H916C950 240 964 261 964 297V405C964 428 985 440 1028 440H1048" stroke="#E8B64D" strokeOpacity=".22" strokeWidth="31"/><path d="M828 240H916C950 240 964 261 964 297V405C964 428 985 440 1028 440H1048" stroke="#DCA63A" strokeOpacity=".86" strokeWidth="2.5"/>
      </svg>
      <span aria-hidden="true" className="home-float home-feature-folder"><FolderOpen/></span>
      <span aria-hidden="true" className="home-float home-feature-printer"><Printer/></span>
      <span aria-hidden="true" className="home-float home-feature-chart-top"><ChartNoAxesCombined/></span>
      <span aria-hidden="true" className="home-float home-feature-chart-bottom"><ChartNoAxesCombined/></span>
      <span aria-hidden="true" className="home-sparkle">✦</span>
      <div className="home-features-content relative z-10">
        <div data-reveal className="home-features-heading text-center">
          <p className="home-eyebrow">A dependable record at every stage</p>
          <h2 id="features-heading" className="home-features-title">Clear records. Confident decisions.</h2>
          <p className="home-features-description">Bring the evidence and next steps for every security deposit into one accountable workspace.</p>
        </div>
        <div className="home-feature-grid">
          {features.map(({ icon: Icon, title, text }, index) => <article data-reveal key={title} style={{ '--reveal-delay': `${index * 90}ms` }} className="home-feature-card group">
            <span className="home-feature-icon"><Icon size={20}/></span>
            <h3>{title}</h3>
            <p>{index === 1 ? <>Review extracted details and bank<br className="home-feature-line-break"/>checks together so<br className="home-feature-line-break"/>discrepancies are easy to resolve.</> : text}</p>
          </article>)}
        </div>
      </div>
    </section>

    <footer id="contact" className="home-footer scroll-mt-[68px]" aria-label="NidhiTrack footer">
      <div className="home-footer-shell">
        <div className="home-footer-grid">
          <section className="home-footer-intro" aria-labelledby="footer-chat-heading">
            <div className="home-footer-intro-heading">
              <span className="home-footer-avatar" aria-hidden="true"><Mail size={20}/></span>
              <h2 id="footer-chat-heading">Let&apos;s Chat</h2>
            </div>
            <p>Bringing fixed-deposit receipts, verification, and decisions together in one clear, secure workspace.</p>
            <a href="#developer-contacts" className="home-footer-cta">Contact the team <ArrowRight size={14}/></a>
          </section>

          <nav className="home-footer-column" aria-label="Footer navigation">
            <h2>Portfolio</h2>
            <a href="#main-content">Overview</a>
            <a href="#features">Features</a>
            <a href="#lifecycle">How it works</a>
            <Link to="/login">Sign in</Link>
          </nav>

          <nav className="home-footer-column" aria-label="Social links">
            <h2>Social</h2>
            <a href="https://github.com/search?q=NidhiTrack&type=repositories" target="_blank" rel="noopener noreferrer"><Github size={15}/> GitHub</a>
            <a href="https://www.linkedin.com/search/results/companies/?keywords=NidhiTrack" target="_blank" rel="noopener noreferrer"><Linkedin size={15}/> LinkedIn</a>
            <a href="#developer-contacts"><Mail size={15}/> Developer contacts</a>
          </nav>

          <section id="developer-contacts" className="home-footer-contacts" aria-labelledby="contact-heading">
            <h2 id="contact-heading">Contacts</h2>
            <ul>
              {developers.map(({ name, email, github, linkedin }) => <li className="home-footer-person" key={email}>
                <div className="home-footer-person-details">
                  <span>{name}</span>
                  <a href={`mailto:${email}`}>{email}</a>
                </div>
                <div className="home-footer-person-links">
                  <a href={github} target="_blank" rel="noopener noreferrer" aria-label={`${name} on GitHub`} title={`${name} on GitHub`}><Github size={15}/></a>
                  <a href={linkedin} target="_blank" rel="noopener noreferrer" aria-label={`${name} on LinkedIn`} title={`${name} on LinkedIn`}><Linkedin size={15}/></a>
                </div>
              </li>)}
            </ul>
          </section>
        </div>
        <div className="home-footer-bottom">
          <span>&copy; 2026 NidhiTrack. All rights reserved.</span>
          <span>AICTE FDR Management Portal - Demonstration workspace</span>
        </div>
      </div>
    </footer>
  </main>;
}
