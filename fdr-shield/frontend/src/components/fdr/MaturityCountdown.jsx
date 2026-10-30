import{useMaturityCountdown}from'../../hooks/useMaturityCountdown';
/**
 * MaturityCountdown
 * Props: maturityDate
 */
export default function MaturityCountdown({ maturityDate }) {
  // Uses useMaturityCountdown; color coded chip
  const{days,level}=useMaturityCountdown(maturityDate);const color=level==='critical'?'text-red-700 bg-red-50':level==='warn'?'text-amber-700 bg-amber-50':'text-green-700 bg-green-50';return <span className={`rounded-full px-3 py-1 text-xs font-semibold ${color}`}>{days<0?`${Math.abs(days)} days overdue`:`${days} days left`}</span>;
}
