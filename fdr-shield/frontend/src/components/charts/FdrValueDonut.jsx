import{ResponsiveContainer,PieChart,Pie,Cell,Tooltip}from'recharts';
/**
 * FdrValueDonut
 * Props: data
 */
export default function FdrValueDonut({ data }) {
  // Recharts PieChart donut of value by status/bank
  return <div className="h-72 rounded-xl border bg-white p-4"><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={data||[]} dataKey="value" nameKey="label" innerRadius={58} outerRadius={95} label>{(data||[]).map((x,i)=><Cell key={x.label} fill={['#0891b2','#16a34a','#eab308','#dc2626'][i%4]}/>)}</Pie><Tooltip/></PieChart></ResponsiveContainer></div>;
}
