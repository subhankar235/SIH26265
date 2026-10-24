import{client}from'./client';
export const submitFdr=form=>client.post('/fdrs',form).then(r=>r.data);
export const listFdrs=params=>client.get('/fdrs',{params}).then(r=>r.data);
export const getFdr=id=>client.get(`/fdrs/${id}`).then(r=>r.data);
export const updateFdrStatus=(id,status,remarks)=>client.patch(`/fdrs/${id}/status`,{status,remarks}).then(r=>r.data);
export const requestRenewal=(id,body)=>client.post(`/fdrs/${id}/renewal`,body).then(r=>r.data);
export const getPresignedUrl=id=>client.get(`/fdrs/${id}/presigned-url`).then(r=>r.data);
