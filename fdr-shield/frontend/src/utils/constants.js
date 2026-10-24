// Constants

export function getStatusMeta(status) {
  // Return label+color for each FDRStatus
  const label=String(status||'unknown').replaceAll('_',' ');const color=status==='verified'?'text-green-700':status==='mismatch'?'text-red-700':'text-slate-600';return{label,color};
}

export function getBadgeMeta(badge) {
  // Return emoji+label+tailwind class: bank_verified=green, self_declared=yellow, mismatch=red
  return({bank_verified:{emoji:'🟢',label:'Bank verified',className:'badge-green'},self_declared:{emoji:'🟡',label:'Self declared',className:'badge-yellow'},mismatch:{emoji:'🔴',label:'Mismatch',className:'badge-red'}})[badge]||{emoji:'🟡',label:'Self declared',className:'badge-yellow'};
}
