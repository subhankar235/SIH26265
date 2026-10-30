import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Activity, AlertTriangle, ArrowRight, BadgeCheck, Building2, CalendarDays, CircleHelp, FileSearch, GitCompareArrows, ListChecks, ScanSearch, ShieldCheck } from 'lucide-react';
import { client } from '../../api/client';
import { EmptyState, ErrorState, LoadingState } from '../../components/common/PageStates';

const capabilityInfo = {
  document_analysis: {
    title: 'Intelligent Document Analysis', icon: FileSearch, action: 'Explore Verification', to: '/bureau/scrutiny',
    description: 'Extract supported fields from submitted FDR documents so officials can compare the document with the institution declaration.',
  },
  discrepancy_detection: {
    title: 'Discrepancy Detection', icon: GitCompareArrows, action: 'Review Discrepancies', to: '/bureau/discrepancies',
    description: 'Compare declared, extracted, and available verification values; review recorded mismatches with their source values.',
  },
  anomaly_detection: {
    title: 'Anomaly Detection', icon: ScanSearch, action: 'Not yet available', to: null,
    description: 'A validated anomaly-detection capability is not deployed. Deterministic validation and scrutiny rules continue to identify cases requiring review.',
  },
  scrutiny_assistance: {
    title: 'Intelligent Scrutiny Assistance', icon: ListChecks, action: 'Open Scrutiny Queue', to: '/bureau/scrutiny',
    description: 'Existing workflow-state, case-age, and deadline rules provide advisory review priorities and help officials focus attention.',
  },
};

const statusLabel = status => ({
  available: 'Available in the FDR workflow',
  partially_available: 'Partially available',
  unavailable: 'Not yet available',
  unknown: 'Status checked during case processing',
}[status] || 'Status unavailable');

const findingType = field => ({
  amount: 'Amount mismatch', maturity_date: 'Maturity-date discrepancy',
  bank: 'Bank-detail discrepancy', bank_name: 'Bank-detail discrepancy',
  fdr_number: 'FDR-reference discrepancy', holder: 'Holder-detail discrepancy', holder_name: 'Holder-detail discrepancy',
}[field] || 'Document-field discrepancy');

function CapabilityCard({ capability, data }) {
  const info = capabilityInfo[capability.id];
  if (!info) return null;
  const Icon = info.icon;
  const available = capability.status === 'available';
  const action = available && !info.to ? 'Open Scrutiny Queue' : info.action;
  const to = available && !info.to ? '/bureau/scrutiny' : info.to;
  return <article className="flex h-full flex-col rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
    <div className="flex items-start justify-between gap-3"><span className="grid size-11 shrink-0 place-items-center rounded-lg bg-blue-50 text-blue-800"><Icon size={22}/></span><span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${available ? 'border-emerald-200 bg-emerald-50 text-emerald-900' : capability.status === 'unavailable' ? 'border-slate-200 bg-slate-50 text-slate-600' : 'border-amber-200 bg-amber-50 text-amber-900'}`}>{statusLabel(capability.status)}</span></div>
    <h2 className="mt-4 text-lg font-bold text-slate-900">{info.title}</h2>
    <p className="mt-2 flex-1 text-sm leading-6 text-slate-600">{info.description}</p>
    {capability.message&&<p className="mt-3 text-xs leading-5 text-slate-500">{capability.message}</p>}
    {to ? <Link to={to} className="mt-5 inline-flex min-h-10 items-center justify-between rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-900 hover:border-blue-500 hover:bg-blue-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-700">{action}<ArrowRight size={16}/></Link>
      : <button type="button" disabled className="mt-5 min-h-10 cursor-not-allowed rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-left text-sm font-semibold text-slate-500">{action}</button>}
  </article>;
}

function WorkflowSteps() {
  const steps = [
    ['FDR submitted', 'The institution submits an FDR and supporting document.', Building2],
    ['Information extracted', 'Supported fields are extracted for case review.', FileSearch],
    ['Discrepancy checks', 'Declared values are compared with extracted and available verification data.', GitCompareArrows],
    ['Findings reviewed', 'An authorized official examines findings and their supporting records.', ShieldCheck],
    ['Official decision', 'The authorized official records the appropriate case decision.', BadgeCheck],
  ];
  return <div className="grid gap-3 md:grid-cols-5">{steps.map(([title, description, Icon], index) => <article key={title} className="relative rounded-lg border border-slate-200 bg-white p-4"><div className="flex items-center gap-2"><span className="grid size-8 shrink-0 place-items-center rounded-full bg-slate-100 text-sm font-bold text-slate-700">{index + 1}</span><Icon size={18} className="text-blue-800"/><h3 className="text-sm font-bold text-slate-900">{title}</h3></div><p className="mt-3 text-xs leading-5 text-slate-600">{description}</p>{index < steps.length - 1&&<span aria-hidden="true" className="absolute -right-2 top-7 z-10 hidden h-px w-4 bg-slate-300 md:block"/>}</article>)}</div>;
}

function FindingTable({ rows }) {
  return <div className="overflow-x-auto rounded-lg border border-slate-200"><table className="w-full min-w-[760px] text-left text-sm"><thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-600"><tr>{['Case reference','Institution','Finding type','Summary','Review status','Detected at','Action'].map(title=><th key={title} className="px-4 py-3 font-semibold">{title}</th>)}</tr></thead><tbody>{rows.map(row=><tr key={row.id} className="border-t border-slate-200 align-top"><td className="px-4 py-3 font-semibold text-slate-900">{row.fdr_number}</td><td className="px-4 py-3">{row.institution_name}</td><td className="px-4 py-3"><span className={`inline-flex rounded-full px-2 py-1 text-xs font-semibold ${row.severity==='high'?'bg-red-50 text-red-800':'bg-amber-50 text-amber-900'}`}>{findingType(row.field)}</span><p className="mt-1 text-xs text-slate-500">{row.severity} severity</p></td><td className="max-w-72 px-4 py-3 text-slate-700">Declared: {row.declared_value??'Not recorded'}<br/>Found: {row.extracted_value??'Not recorded'}<p className="mt-1 text-xs text-slate-500">Source: {row.source}</p></td><td className="px-4 py-3"><span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-1 text-xs font-semibold text-amber-900">{row.resolved?'Reviewed':'Pending review'}</span></td><td className="whitespace-nowrap px-4 py-3 text-slate-600">{row.detected_at ? <span className="inline-flex items-center gap-1"><CalendarDays size={14}/>{new Date(row.detected_at).toLocaleString()}</span> : 'Not recorded'}</td><td className="px-4 py-3"><Link to={`/bureau/scrutiny/${row.fdr_id}`} className="inline-flex items-center gap-1 whitespace-nowrap font-semibold text-blue-800 underline underline-offset-2">View case<ArrowRight size={14}/></Link></td></tr>)}</tbody></table></div>;
}

export default function MLGovernance() {
  const queryClient = useQueryClient();
  const [findingsPage, setFindingsPage] = useState(1);
  const capabilities = useQuery({ queryKey: ['ml-showcase-capabilities'], queryFn: () => client.get('/admin/intelligence/capabilities').then(r => r.data.capabilities) });
  const findings = useQuery({ queryKey: ['ml-showcase-findings', findingsPage], queryFn: () => client.get('/verification/discrepancies', { params: { real_only: true, resolved: false, page: findingsPage, size: 20 } }).then(r => r.data), refetchInterval: 30000 });
  const availableCount = useMemo(() => (capabilities.data||[]).filter(item => item.status === 'available').length, [capabilities.data]);
  const refresh = () => { queryClient.invalidateQueries({ queryKey: ['ml-showcase-capabilities'] }); queryClient.invalidateQueries({ queryKey: ['ml-showcase-findings'] }); };
  const byCapability = useMemo(() => new Map((capabilities.data||[]).map(item => [item.id, item])), [capabilities.data]);

  return <section className="space-y-7">
    <header className="flex flex-wrap items-start justify-between gap-4"><div><p className="text-sm font-semibold uppercase tracking-wide text-indigo-800">AICTE FDR Portal</p><h1 className="mt-1 text-3xl font-bold tracking-tight text-slate-950">ML Governance</h1><p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">Intelligent assistance for FDR verification, discrepancy detection, and regulatory scrutiny. Automated findings support authorized officials; final decisions remain with the responsible personnel.</p>{capabilities.data&&<p className="mt-3 inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700"><Activity size={14}/>{availableCount} of {capabilities.data.length} capabilities available</p>}</div><button type="button" onClick={refresh} disabled={capabilities.isFetching||findings.isFetching} className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-800 hover:bg-slate-50 disabled:opacity-60"><Activity size={16}/>{capabilities.isFetching||findings.isFetching?'Refreshing…':'Refresh'}</button></header>

    <section aria-labelledby="intelligence-overview-title"><div className="mb-4"><h2 id="intelligence-overview-title" className="text-xl font-bold text-slate-900">Intelligence overview</h2><p className="mt-1 text-sm text-slate-600">Operational capabilities available in existing FDR workflows.</p></div>
      {capabilities.isLoading?<LoadingState label="Checking available FDR capabilities"/>:capabilities.isError?<ErrorState error={capabilities.error} onRetry={() => capabilities.refetch()} label="Capability availability could not be checked"/>:<div className="grid gap-4 sm:grid-cols-2 2xl:grid-cols-4">{Object.keys(capabilityInfo).map(id=><CapabilityCard key={id} capability={byCapability.get(id)||{id,status:'unknown'}}/>)}</div>}
    </section>

    <section aria-labelledby="verification-workflow-title" className="rounded-xl border border-slate-200 bg-slate-50 p-5 sm:p-6"><div className="mb-4"><h2 id="verification-workflow-title" className="text-xl font-bold text-slate-900">How intelligent verification works</h2><p className="mt-1 text-sm text-slate-600">A general explanation of the FDR review process—not a live status for an individual case.</p></div><WorkflowSteps/></section>

    <section aria-labelledby="recent-findings-title" className="space-y-4"><div className="flex flex-wrap items-end justify-between gap-3"><div><h2 id="recent-findings-title" className="text-xl font-bold text-slate-900">Recent intelligent findings</h2><p className="mt-1 text-sm text-slate-600">Unresolved discrepancies from explicitly real-origin FDR cases. Older records may not have a recorded detection time.</p></div><Link to="/bureau/discrepancies" className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-800">Open discrepancy board<ArrowRight size={15}/></Link></div>
      {findings.isLoading?<LoadingState label="Loading recent case findings"/>:findings.isError?<ErrorState error={findings.error} onRetry={() => findings.refetch()} label="Recent findings could not be loaded"/>:!findings.data?.items?.length?<EmptyState title="No findings to review">Intelligent findings will appear here when eligible FDR cases have been analyzed. Open the scrutiny queue to review cases already awaiting official attention.</EmptyState>:<><FindingTable rows={findings.data.items}/><nav aria-label="Finding pages" className="flex items-center justify-between"><button type="button" disabled={findingsPage<=1||findings.isFetching} onClick={() => setFindingsPage(page => Math.max(1,page-1))} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold disabled:opacity-50">Previous</button><span className="text-sm text-slate-600">Page {findingsPage}</span><button type="button" disabled={!findings.data.has_more||findings.isFetching} onClick={() => setFindingsPage(page => page+1)} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold disabled:opacity-50">Next</button></nav></>}
      {!findings.isLoading&&!findings.isError&&<p className="flex items-start gap-2 text-xs leading-5 text-slate-500"><CircleHelp size={15} className="mt-0.5 shrink-0"/>A recorded discrepancy is a review finding, not a determination of fraud or authenticity. Supporting case information and official actions are available through the linked case review.</p>}
    </section>

    <section aria-label="Responsible review principles" className="grid gap-4 md:grid-cols-3"><article className="rounded-xl border border-slate-200 bg-white p-5"><h3 className="flex items-center gap-2 font-bold text-slate-900"><ShieldCheck size={18} className="text-blue-800"/>Evidence-led analysis</h3><p className="mt-2 text-sm leading-6 text-slate-600">Findings link to recorded document values and verification results wherever available.</p></article><article className="rounded-xl border border-slate-200 bg-white p-5"><h3 className="flex items-center gap-2 font-bold text-slate-900"><BadgeCheck size={18} className="text-blue-800"/>Human-supervised decisions</h3><p className="mt-2 text-sm leading-6 text-slate-600">Automated assistance does not independently approve or reject FDRs; authorized officials retain decision-making authority.</p></article><article className="rounded-xl border border-slate-200 bg-white p-5"><h3 className="flex items-center gap-2 font-bold text-slate-900"><AlertTriangle size={18} className="text-amber-700"/>Safe manual review</h3><p className="mt-2 text-sm leading-6 text-slate-600">When automated analysis is unavailable or unreliable, the established scrutiny workflow remains available.</p></article></section>
  </section>;
}
