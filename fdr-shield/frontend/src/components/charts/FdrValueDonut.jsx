import{ResponsiveContainer,PieChart,Pie,Cell,Tooltip}from'recharts';
/**
 * FdrValueDonut
 * Props: data
 */
export default function FdrValueDonut({ data }) {
  // Recharts PieChart donut of value by status/bank
  return <div className="h-72 rounded-xl border border-[#D8E1EA] bg-white p-4 shadow-sm"><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={data||[]} dataKey="value" nameKey="label" innerRadius={58} outerRadius={95} label>{(data||[]).map((x,i)=><Cell key={x.label} fill={['#3182F6','#22a06b','#f0b429','#d64545'][i%4]}/>)}</Pie><Tooltip/></PieChart></ResponsiveContainer></div>;
}
