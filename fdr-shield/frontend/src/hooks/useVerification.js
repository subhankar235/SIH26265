// Verification hooks

export function useVerificationReport(fdrId) {
  // useQuery; poll every 3s while status is SUBMITTED (OCR running)
  return useQuery({queryKey:['verification',fdrId],queryFn:()=>getReport(fdrId),enabled:Boolean(fdrId),refetchInterval:q=>q.state.data?.ocr?false:3000});
}

export function useDiscrepancies(resolved) {
  // useQuery
  return useQuery({queryKey:['discrepancies',resolved],queryFn:()=>listDiscrepancies({resolved})});
}
import{useQuery}from'@tanstack/react-query';import{getReport,listDiscrepancies}from'../api/verification.api';
