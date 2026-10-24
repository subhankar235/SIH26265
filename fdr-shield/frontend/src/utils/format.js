// Formatters

export function formatINR(amount) {
  // Intl.NumberFormat en-IN; crore/lakh short form helper
  return new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',maximumFractionDigits:0}).format(Number(amount||0));
}

export function formatDate(iso) {
  // dd MMM yyyy via date-fns
  return iso?new Intl.DateTimeFormat('en-IN',{dateStyle:'medium'}).format(new Date(iso)):'—';
}
