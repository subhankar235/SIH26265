export default function BrandWordmark({ inverse = false, className = '' }) {
  return <span className={`inline-flex whitespace-nowrap font-extrabold tracking-[.025em] ${className}`}>
    <span className={inverse ? 'text-white' : 'text-[#12395A]'}>NIDHI</span>
    <span className={inverse ? 'text-[#55B7B1]' : 'text-[#197F80]'}>TRACK</span>
  </span>;
}
