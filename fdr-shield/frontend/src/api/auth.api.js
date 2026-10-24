import{client}from'./client';
export const login=(email,password)=>client.post('/auth/login',{email,password}).then(r=>r.data);
export const verifyMfa=(tempToken,code)=>client.post('/auth/mfa/verify',{temp_token:tempToken,code}).then(r=>r.data);
export const setupMfa=()=>client.post('/auth/mfa/setup').then(r=>r.data);
export const getMe=()=>client.get('/auth/me').then(r=>r.data);
