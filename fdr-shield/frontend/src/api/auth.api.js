import { client } from './client';

export const login = (email, password) => client.post('/auth/login', { email, password }).then((r) => r.data);
export const verifyMfa = (code) => client.post('/auth/mfa/verify', { code }).then((r) => r.data);
export const setupMfa = () => client.post('/auth/mfa/setup').then((r) => r.data);
export const getMe = () => client.get('/auth/me').then((r) => r.data);
export const getCsrf = () => client.get('/auth/csrf').then((r) => r.data);
export const logout = () => client.post('/auth/logout');
export const changePassword = (data) => client.post('/auth/change-password', data);
export const registerInstitution = (data) => client.post('/auth/register/institution', data);
export const registerOfficial = (data) => client.post('/auth/register/official', data);
export const setupInitialSuperAdmin = (data) => client.post('/auth/register/super-admin', data).then((r) => r.data);
export const verifyEmail = (token) => client.post('/auth/verify-email', { token });
export const acceptInvite = (data) => client.post('/auth/accept-invite', data);
export const forgotPassword = (email) => client.post('/auth/forgot-password', { email });
export const resetPassword = (data) => client.post('/auth/reset-password', data);
