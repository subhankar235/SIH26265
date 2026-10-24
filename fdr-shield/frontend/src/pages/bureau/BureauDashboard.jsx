import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { client } from '../../api/client';
import MetricCard from '../../components/common/MetricCard';
import MaturityTimeline from '../../components/charts/MaturityTimeline';
import TrustMatrixTable from '../../components/fdr/TrustMatrixTable';
import { formatINR } from '../../utils/format';
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid } from 'recharts';

export default function BureauDashboard() {
  const [filters, setFilters] = useState({});
  const navigate = useNavigate();
  const dashboard = useQuery({ queryKey: ['bureau-dashboard'], queryFn: () => client.get('/dashboard/bureau').then(r => r.data), staleTime: 60_000 });
  const fdrs = useQuery({ queryKey: ['fdrs', filters], queryFn: () => client.get('/fdrs', { params: filters }).then(r => r.data) });
  const rows = useMemo(() => Array.isArray(fdrs.data) ? fdrs.data : fdrs.data?.items || [], [fdrs.data]);
  const data = dashboard.data || {}, m = data.metrics || {};
  return <section>
    <p className="text-sm font-semibold uppercase tracking-wide text-cyan-700">AICTE Bureau</p>
    <h1 className="mb-6 mt-1 text-3xl font-bold">Security deposit overview</h1>
    {dashboard.isLoading ? <p>Loading portfolio…</p> : <>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"><MetricCard title="Active FDR value" value={formatINR(m.total_active_value)} /><MetricCard title="Maturing in 30 days" value={m.expiring_30d} /><MetricCard title="Pending verification" value={m.pending_verifications} /><MetricCard title="Flagged discrepancies" value={m.discrepancies_flagged} /></div>
      <div className="mt-6 grid gap-5 lg:grid-cols-2">
        <div className="h-80 rounded-xl border bg-white p-5"><h2 className="font-semibold">Trust status</h2><ResponsiveContainer width="100%" height="90%"><PieChart><Pie data={data.status_breakdown || []} dataKey="value" nameKey="label" outerRadius={95} label>{(data.status_breakdown || []).map((x, i) => <Cell key={x.label} fill={['#16a34a', '#eab308', '#dc2626', '#64748b'][i % 4]} />)}</Pie><Tooltip /></PieChart></ResponsiveContainer></div>
        <div className="h-80 rounded-xl border bg-white p-5"><h2 className="font-semibold">Value by bank</h2><ResponsiveContainer width="100%" height="90%"><BarChart data={data.value_by_bank || []}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="label" /><YAxis /><Tooltip formatter={value => formatINR(value)} /><Bar dataKey="value" fill="#0891b2" radius={[6, 6, 0, 0]} /></BarChart></ResponsiveContainer></div>
      </div>
      <div className="mt-6"><h2 className="mb-3 font-semibold">Maturities by month</h2><MaturityTimeline data={data.maturity_timeline || []} /></div>
      <div className="mt-6"><TrustMatrixTable rows={rows} filters={filters} onFilterChange={setFilters} onRowClick={row => navigate(`/official/scrutiny/${row.id}`)} /></div>
    </>}
  </section>;
}
