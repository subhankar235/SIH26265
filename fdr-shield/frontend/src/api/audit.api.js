import{client}from'./client';export const listAuditLogs=params=>client.get('/audit',{params}).then(r=>r.data);
