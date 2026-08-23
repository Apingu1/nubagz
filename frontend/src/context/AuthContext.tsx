import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import type { User } from '../types'
import { api } from '../lib/api'

type AuthSource='password'|'privy'|null
type AuthContextType = { user:User|null; loading:boolean; authSource:AuthSource; login:(email:string,password:string)=>Promise<void>; register:(email:string,username:string,password:string,referral?:string)=>Promise<void>; socialLogin:(identityToken:string,referral?:string)=>Promise<void>; logout:()=>void; refresh:()=>Promise<void> }
const AuthContext = createContext<AuthContextType | undefined>(undefined)
const INSTALL_KEY='nubagz_install_id'
const SOURCE_KEY='nubagz_auth_source'

function localInstallId(){
  let id=localStorage.getItem(INSTALL_KEY)
  if(!id){
    id=typeof crypto!=='undefined'&&'randomUUID' in crypto?crypto.randomUUID():`nubagz-${Date.now()}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`
    localStorage.setItem(INSTALL_KEY,id)
  }
  return id
}

function savedSource():AuthSource{
  const value=localStorage.getItem(SOURCE_KEY)
  return value==='privy'?'privy':value==='password'?'password':null
}

export function AuthProvider({children}:{children:ReactNode}){
  const [user,setUser]=useState<User|null>(null); const [loading,setLoading]=useState(true);const [authSource,setAuthSource]=useState<AuthSource>(()=>savedSource())
  const refresh=async()=>{ try{ setUser(await api<User>('/auth/me')) } catch { localStorage.removeItem('nubagz_token');localStorage.removeItem(SOURCE_KEY);setAuthSource(null);setUser(null) } }
  useEffect(()=>{(async()=>{ if(localStorage.getItem('nubagz_token')) await refresh(); setLoading(false) })()},[])
  useEffect(()=>{if(!user)return;api('/risk/context',{method:'POST',body:JSON.stringify({install_id:localInstallId()})}).catch(()=>{})},[user?.id])
  const storeSession=(r:{access_token:string;user:User},source:Exclude<AuthSource,null>)=>{localStorage.setItem('nubagz_token',r.access_token);localStorage.setItem(SOURCE_KEY,source);setAuthSource(source);setUser(r.user)}
  const login=async(email:string,password:string)=>{ const r=await api<{access_token:string;user:User}>('/auth/login',{method:'POST',body:JSON.stringify({email,password})});storeSession(r,'password') }
  const register=async(email:string,username:string,password:string,referral_code?:string)=>{ const r=await api<{access_token:string;user:User}>('/auth/register',{method:'POST',body:JSON.stringify({email,username,password,referral_code:referral_code||null})});storeSession(r,'password') }
  const socialLogin=async(identity_token:string,referral_code?:string)=>{const r=await api<{access_token:string;user:User}>('/auth/privy',{method:'POST',body:JSON.stringify({identity_token,referral_code:referral_code||null})});storeSession(r,'privy')}
  const logout=()=>{localStorage.removeItem('nubagz_token');localStorage.removeItem(SOURCE_KEY);setAuthSource(null);setUser(null)}
  const value=useMemo(()=>({user,loading,authSource,login,register,socialLogin,logout,refresh}),[user,loading,authSource])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
export function useAuth(){ const ctx=useContext(AuthContext); if(!ctx) throw new Error('AuthProvider missing'); return ctx }
