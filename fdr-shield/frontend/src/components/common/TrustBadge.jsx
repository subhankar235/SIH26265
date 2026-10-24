const labels = { bank_verified: ['Bank verified', 'badge-green', 'bg-green-700'], self_declared: ['Pending', 'badge-yellow', 'bg-amber-600'], mismatch: ['Mismatch', 'badge-red', 'bg-red-700'] };
export default function TrustBadge({ badge }) {
  const [label, style, dot] = labels[badge] || [badge || 'Pending', 'badge-yellow', 'bg-amber-600'];
  return <span className={style}><span aria-hidden="true" className={`size-1.5 rounded-full ${dot}`} />{label}</span>;
}
