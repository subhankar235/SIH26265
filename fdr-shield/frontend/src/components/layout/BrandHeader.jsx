import { Link } from 'react-router-dom';
import BrandLogo from './BrandLogo';

export default function BrandHeader({ rightSlot, leading, className = '', innerClassName = '' }) {
  return <header className={`brand-header sticky top-0 z-30 flex h-[68px] w-full shrink-0 items-center border-b px-4 sm:px-6 ${className}`}>
    <div className={`mx-auto flex w-full max-w-[1600px] min-w-0 items-center justify-between gap-3 ${innerClassName}`}>
      <div className="flex min-w-0 items-center gap-2 sm:gap-3">
        {leading}
        <Link to="/" aria-label="NidhiTrack home" className="flex min-w-0 items-center rounded-lg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#2563EB]">
          <BrandLogo/>
        </Link>
      </div>
      {rightSlot && <div className="flex shrink-0 items-center gap-2 sm:gap-4">{rightSlot}</div>}
    </div>
  </header>;
}
