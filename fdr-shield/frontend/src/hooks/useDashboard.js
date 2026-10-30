// Dashboard hooks

export function useBureauDashboard() {
  // useQuery with refetchInterval 60s
  return useQuery({queryKey:['bureau-dashboard'],queryFn:getBureauDashboard,refetchInterval:60000});
}

export function useInstitutionDashboard() {
  // useQuery
  return useQuery({queryKey:['institution-dashboard'],queryFn:getInstitutionDashboard,refetchInterval:60000});
}
import{useQuery}from'@tanstack/react-query';import{getBureauDashboard,getInstitutionDashboard}from'../api/dashboard.api';
