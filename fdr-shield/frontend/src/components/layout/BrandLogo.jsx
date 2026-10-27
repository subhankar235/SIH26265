import BrandWordmark from './BrandWordmark';

export default function BrandLogo({ inverse = false, markClassName = '' }) {
  return <span className="inline-flex min-w-0 items-center gap-2.5">
    <img src="/brand/nidhitrack-mark.svg" alt="" aria-hidden="true" className={`brand-logo-mark h-10 w-10 shrink-0 object-contain ${markClassName}`}/>
    <span className="flex min-w-0 flex-col leading-none">
      <BrandWordmark inverse={inverse} className="text-[17px] sm:text-[20px]"/>
      <span className={`mt-1.5 whitespace-nowrap text-[8px] font-semibold uppercase tracking-[.15em] sm:text-[9px] ${inverse ? 'text-white/75' : 'text-[#6B8488]'}`}>AICTE FDR Management Portal</span>
    </span>
  </span>;
}
