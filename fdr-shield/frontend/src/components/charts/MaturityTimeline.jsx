import{ResponsiveContainer,LineChart,CartesianGrid,XAxis,YAxis,Tooltip,Line}from'recharts';
/**
 * MaturityTimeline
 * Props: data
 */
export default function MaturityTimeline({ data }) {
  // Recharts BarChart: FDR count/value maturing per month
  return <div className="h-72 rounded-xl border bg-white p-4"><ResponsiveContainer width="100%" height="100%"><LineChart data={data||[]}><CartesianGrid strokeDasharray="3 3"/><XAxis dataKey="label"/><YAxis allowDecimals={false}/><Tooltip/><Line type="monotone" dataKey="value" stroke="#0891b2" strokeWidth={3}/></LineChart></ResponsiveContainer></div>;
}
