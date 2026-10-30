// React Query hooks for FDRs

export function useFdrs(filters) {
  // useQuery(['fdrs',filters], listFdrs)
  return useQuery({queryKey:['fdrs',filters],queryFn:()=>listFdrs(filters)});
}

export function useFdr(id) {
  // useQuery(['fdr',id], getFdr)
  return useQuery({queryKey:['fdr',id],queryFn:()=>getFdr(id),enabled:Boolean(id)});
}

export function useSubmitFdr() {
  // useMutation(submitFdr) + invalidate ['fdrs']
  const qc=useQueryClient();return useMutation({mutationFn:submitFdr,onSuccess:()=>qc.invalidateQueries({queryKey:['fdrs']})});
}

export function useUpdateFdrStatus() {
  // useMutation(updateFdrStatus)
  const qc=useQueryClient();return useMutation({mutationFn:({id,status,remarks})=>updateFdrStatus(id,status,remarks),onSuccess:()=>qc.invalidateQueries({queryKey:['fdrs']})});
}
import{useQuery,useMutation,useQueryClient}from'@tanstack/react-query';import{listFdrs,getFdr,submitFdr,updateFdrStatus}from'../api/fdr.api';
