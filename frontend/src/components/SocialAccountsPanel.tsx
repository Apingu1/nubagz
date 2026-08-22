import { getIdentityToken, useLinkAccount, usePrivy } from '@privy-io/react-auth'
import { CheckCircle2, Link2, ShieldCheck } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'
import type { SocialAccount } from '../types'
import { privyConfigured } from '../context/WalletProvider'

function providerLabel(provider:string){return provider==='X'?'X':'Google'}
function providerMark(provider:string){return provider==='X'?'𝕏':'G'}

function ConnectedSocialAccounts(){
  const {ready,authenticated}=usePrivy();const [accounts,setAccounts]=useState<SocialAccount[]>([]);const [message,setMessage]=useState('');const [busy,setBusy]=useState('')
  const load=()=>api<SocialAccount[]>('/auth/social-accounts').then(setAccounts).catch(()=>setAccounts([]))
  useEffect(()=>{void load()},[])
  const sync=async()=>{try{const token=await getIdentityToken();if(!token)throw new Error('Privy identity tokens must be enabled before social accounts can be synced.');await api('/auth/social-accounts/sync',{method:'POST',body:JSON.stringify({identity_token:token})});await load();setMessage('Connected account verified and saved.')}catch(e:any){setMessage(e?.message||'Could not sync the connected account.')}finally{setBusy('')}}
  const {linkGoogle,linkTwitter}=useLinkAccount({onSuccess:()=>{void sync()},onError:(error)=>{setMessage(typeof error==='string'?error:'Could not link that account.');setBusy('')}})
  const byProvider=useMemo(()=>new Map(accounts.map(a=>[a.provider,a])),[accounts])
  const connect=(provider:'GOOGLE'|'X')=>{if(!ready||!authenticated){setMessage('Privy is still connecting your NuBagz identity. Try again in a moment.');return}setMessage('');setBusy(provider);if(provider==='GOOGLE')void linkGoogle();else void linkTwitter()}
  return <section className="panel social-accounts-panel"><div className="panel-head"><div><span>CONNECTED ACCOUNTS</span><h2>Your social identity</h2></div><ShieldCheck/></div><p>Link X once and NuBagz can use the verified X account for supported automatic Bag Work checks. Google remains available as a convenient login/account-recovery option.</p><div className="social-account-list social-account-list-two">{(['X','GOOGLE'] as const).map(provider=>{const row=byProvider.get(provider);return <div className={`social-account-row ${row?'connected':''}`} key={provider}><span className="social-account-mark">{providerMark(provider)}</span><div><strong>{providerLabel(provider)}</strong><small>{row?(row.username?`@${row.username.replace(/^@/,'')}`:row.email||row.display_name||'Connected'):(provider==='X'?'Connect for X Bag Work verification':'Available for login and account linking')}</small></div>{row?<span className="connected-pill"><CheckCircle2/> Connected</span>:<button type="button" className="mini-action" disabled={Boolean(busy)} onClick={()=>connect(provider)}><Link2/>{busy===provider?'Connecting…':'Connect'}</button>}</div>})}</div>{message&&<div className="form-note">{message}</div>}<div className="social-identity-note"><ShieldCheck/><span>For X Bag Work, NuBagz verifies the provider-issued X user ID. A typed username is never accepted as proof.</span></div></section>
}

export default function SocialAccountsPanel(){
  if(!privyConfigured)return null
  return <ConnectedSocialAccounts/>
}
