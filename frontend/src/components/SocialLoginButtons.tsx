import { getIdentityToken, useLoginWithOAuth } from '@privy-io/react-auth'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { privyConfigured } from '../context/WalletProvider'

const REFERRAL_KEY='nubagz_social_referral'

type Provider='google'|'twitter'|'tiktok'

function PrivySocialButtons({mode,referral,onError}:{mode:'login'|'register';referral?:string;onError:(message:string)=>void}){
  const {socialLogin}=useAuth();const nav=useNavigate();const [active,setActive]=useState<Provider|null>(null)
  const {state,initOAuth}=useLoginWithOAuth({
    onComplete:()=>{void (async()=>{
      try{
        const identityToken=await getIdentityToken()
        if(!identityToken) throw new Error('Privy identity tokens are not enabled for this NuBagz application.')
        const pendingReferral=sessionStorage.getItem(REFERRAL_KEY)||undefined
        await socialLogin(identityToken,pendingReferral)
        sessionStorage.removeItem(REFERRAL_KEY)
        nav('/app')
      }catch(e:any){onError(e?.message||'Social login could not be completed');setActive(null)}
    })()},
    onError:(error)=>{onError(error?.message||'Social login failed');setActive(null)},
  })
  const start=(provider:Provider)=>{onError('');setActive(provider);if(mode==='register'&&referral?.trim())sessionStorage.setItem(REFERRAL_KEY,referral.trim());else sessionStorage.removeItem(REFERRAL_KEY);void initOAuth({provider})}
  const busy=state.status==='loading'
  return <div className="social-auth"><div className="social-auth-label"><span>or continue with</span></div><div className="social-auth-grid">
    <button type="button" className="social-auth-btn" disabled={busy} onClick={()=>start('google')}><span className="provider-mark google">G</span>{active==='google'&&busy?'Connecting…':'Google'}</button>
    <button type="button" className="social-auth-btn" disabled={busy} onClick={()=>start('twitter')}><span className="provider-mark x">𝕏</span>{active==='twitter'&&busy?'Connecting…':'X'}</button>
    <button type="button" className="social-auth-btn" disabled={busy} onClick={()=>start('tiktok')}><span className="provider-mark tiktok">♪</span>{active==='tiktok'&&busy?'Connecting…':'TikTok'}</button>
  </div><small className="social-auth-note">One NuBagz account can link your social identities and wallet setup.</small></div>
}

export default function SocialLoginButtons(props:{mode:'login'|'register';referral?:string;onError:(message:string)=>void}){
  if(!privyConfigured)return null
  return <PrivySocialButtons {...props}/>
}
