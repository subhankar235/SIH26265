import{ResponsiveContainer,BarChart,CartesianGrid,XAxis,YAxis,Tooltip,Bar}from'recharts';
/**
 * BankBarChart
 * Props: data
 */
export default function BankBarChart({ data }) {
  // Horizontal bars: amount per bank
  return <div className="h-72 rounded-xl border bg-white p-4"><ResponsiveContainer width="100%" height="100%"><BarChart data={data||[]}><CartesianGrid strokeDasharray="3 3"/><XAxis dataKey="label"/><YAxis/><Tooltip/><Bar dataKey="value" fill="#0891b2"/></BarChart></ResponsiveContainer></div>;
}
