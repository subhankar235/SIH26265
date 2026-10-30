// Countdown hook

export function useMaturityCountdown(maturityDate) {
  // Return {days, level:'ok'|'warn'|'critical'} updating daily; warn<=90, critical<=30
  const days=Math.ceil((new Date(maturityDate).setHours(0,0,0,0)-new Date().setHours(0,0,0,0))/86400000);return{days,level:days<=30?'critical':days<=90?'warn':'ok'};
}
