import{ResponsiveContainer,BarChart,CartesianGrid,XAxis,YAxis,Tooltip,Bar}from'recharts';
/**
 * BankBarChart
 * Props: data
 */
export default function BankBarChart({ data }) {
  // Horizontal bars: amount per bank
  return <div className="h-72 rounded-xl border border-[#D8E1EA] bg-white p-4 shadow-sm"><ResponsiveContainer width="100%" height="100%"><BarChart data={data||[]}><CartesianGrid strokeDasharray="3 3" stroke="#E7EDF4"/><XAxis dataKey="label" tick={{fill:'#64748B',fontSize:12}}/><YAxis tick={{fill:'#64748B',fontSize:12}}/><Tooltip/><Bar dataKey="value" fill="#3182F6" radius={[5,5,0,0]}/></BarChart></ResponsiveContainer></div>;
}
