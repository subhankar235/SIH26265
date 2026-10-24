import axios from 'axios';
export const client=axios.create({baseURL:import.meta.env.VITE_API_URL||'/api/v1'});
client.interceptors.request.use(c=>{const s=JSON.parse(localStorage.getItem('fdr-session')||'null');if(s?.token)c.headers.Authorization=`Bearer ${s.token}`;return c});
