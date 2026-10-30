import{ResponsiveContainer,LineChart,CartesianGrid,XAxis,YAxis,Tooltip,Line}from'recharts';
/**
 * MaturityTimeline
 * Props: data
 */
export default function MaturityTimeline({ data }) {
  // Recharts BarChart: FDR count/value maturing per month
  return <div className="h-72 rounded-xl border border-[#D8E1EA] bg-white p-4 shadow-sm"><ResponsiveContainer width="100%" height="100%"><LineChart data={data||[]}><CartesianGrid strokeDasharray="3 3" stroke="#E7EDF4"/><XAxis dataKey="label" tick={{fill:'#64748B',fontSize:12}}/><YAxis allowDecimals={false} tick={{fill:'#64748B',fontSize:12}}/><Tooltip/><Line type="monotone" dataKey="value" stroke="#3182F6" strokeWidth={3}/></LineChart></ResponsiveContainer></div>;
}
