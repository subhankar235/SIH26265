import { create } from 'zustand';
const saved=JSON.parse(localStorage.getItem('fdr-session')||'null');
export const useAuthStore=create((set)=>({token:saved?.token||null,user:saved?.user||null,setSession:(token,user)=>{localStorage.setItem('fdr-session',JSON.stringify({token,user}));set({token,user})},logout:()=>{localStorage.removeItem('fdr-session');set({token:null,user:null})}}));
