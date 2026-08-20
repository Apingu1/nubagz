import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import type { User } from '../types'
import { api } from '../lib/api'

type AuthContextType = { user:User|null; loading:boolean; login:(email:string,password:string)=>Promise<void>; register:(email:string,username:string,password:string,referral?:string)=>Promise<void>; logout:()=>void; refresh:()=>Promise<void> }
const AuthContext = createContext<AuthContextType | undefined>(undefined)
const INSTALL_KEY='nubagz_install_id'

function localInstallId(){
  let id=localStorage.getItem(INSTALL_KEY)
  if(!id){
    id=typeof crypto!=='undefined'&&'randomUUID' in crypto?crypto.randomUUID():`nubagz-${Date.now()}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`
    localStorage.setItem(INSTALL_KEY,id)
  }
  return id
}

export function AuthProvider({children}:{children:ReactNode}){
  const [user,setUser]=useState<User|null>(null); const [loading,setLoading]=useState(true)
  const refresh=async()=>{ try{ setUser(await api<User>('/auth/me')) } catch { localStorage.removeItem('nubagz_token'); setUser(null) } }
  useEffect(()=>{(async()=>{ if(localStorage.getItem('nubagz_token')) await refresh(); setLoading(false) })()},[])
  useEffect(()=>{if(!user)return;api('/risk/context',{method:'POST',body:JSON.stringify({install_id:localInstallId()})}).catch(()=>{})},[user?.id])
  const login=async(email:string,password:string)=>{ const r=await api<{access_token:string;user:User}>('/auth/login',{method:'POST',body:JSON.stringify({email,password})}); localStorage.setItem('nubagz_token',r.access_token); setUser(r.user) }
  const register=async(email:string,username:string,password:string,referral_code?:string)=>{ const r=await api<{access_token:string;user:User}>('/auth/register',{method:'POST',body:JSON.stringify({email,username,password,referral_code:referral_code||null})}); localStorage.setItem('nubagz_token',r.access_token); setUser(r.user) }
  const logout=()=>{localStorage.removeItem('nubagz_token');setUser(null)}
  const value=useMemo(()=>({user,loading,login,register,logout,refresh}),[user,loading])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
export function useAuth(){ const ctx=useContext(AuthContext); if(!ctx) throw new Error('AuthProvider missing'); return ctx }
