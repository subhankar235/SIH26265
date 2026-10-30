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
    <p className="eyebrow">AICTE Bureau</p>
    <h1 className="mb-6 mt-1 text-3xl font-bold tracking-tight text-[#273544]">Security deposit overview</h1>
    {dashboard.isLoading ? <p>Loading portfolio…</p> : <>
      <p className="mb-4 rounded-xl border border-[#D8E1EA] bg-white px-4 py-3 text-sm leading-6 text-[#526173]">Aggregate portfolio metrics and charts include explicitly real-origin records only. Synthetic demo and legacy-unclassified cases remain visible in the case table with origin labels and are excluded from those totals.</p>
      <div className="grid items-stretch gap-4 sm:grid-cols-2 2xl:grid-cols-4"><MetricCard title="Active real-record FDR value" value={formatINR(m.total_active_value)} /><MetricCard title="Maturing in 30 days · real" value={m.expiring_30d} /><MetricCard title="Pending verification · real" value={m.pending_verifications} /><MetricCard title="Flagged discrepancies · real" value={m.discrepancies_flagged} /></div>
      <div className="mt-6 grid gap-5 lg:grid-cols-2">
        <div className="surface-card h-80 p-5"><h2 className="font-semibold text-[#273544]">Trust status</h2><ResponsiveContainer width="100%" height="90%"><PieChart><Pie data={data.status_breakdown || []} dataKey="value" nameKey="label" outerRadius={95} label>{(data.status_breakdown || []).map((x, i) => <Cell key={x.label} fill={['#3182F6', '#22a06b', '#f0b429', '#d64545'][i % 4]} />)}</Pie><Tooltip /></PieChart></ResponsiveContainer></div>
        <div className="surface-card h-80 p-5"><h2 className="font-semibold text-[#273544]">Value by bank</h2><ResponsiveContainer width="100%" height="90%"><BarChart data={data.value_by_bank || []}><CartesianGrid strokeDasharray="3 3" stroke="#E7EDF4" /><XAxis dataKey="label" tick={{ fill: '#64748B', fontSize: 12 }} /><YAxis tick={{ fill: '#64748B', fontSize: 12 }} /><Tooltip formatter={value => formatINR(value)} /><Bar dataKey="value" fill="#3182F6" radius={[6, 6, 0, 0]} /></BarChart></ResponsiveContainer></div>
      </div>
      <div className="mt-6"><h2 className="mb-3 font-semibold">Maturities by month</h2><MaturityTimeline data={data.maturity_timeline || []} /></div>
      <div className="mt-6"><TrustMatrixTable rows={rows} filters={filters} onFilterChange={setFilters} onRowClick={row => navigate(`/official/scrutiny/${row.id}`)} /></div>
    </>}
  </section>;
}
