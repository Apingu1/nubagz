import { useEffect, useRef, useState } from 'react'

const SITE_KEY = import.meta.env.VITE_TURNSTILE_SITE_KEY || ''
const SCRIPT_ID = 'nubagz-turnstile-script'

type TurnstileApi={
  render:(container:HTMLElement,options:{sitekey:string;theme?:'dark'|'light'|'auto';callback:(token:string)=>void;'expired-callback':()=>void;'error-callback':()=>void})=>string
  remove:(widgetId:string)=>void
}

declare global {
  interface Window { turnstile?: TurnstileApi }
}

export function turnstileConfigured(){return Boolean(SITE_KEY)}

export default function HumanVerification({onToken}:{onToken:(token:string|null)=>void}){
  const container=useRef<HTMLDivElement>(null)
  const widgetId=useRef<string|null>(null)
  const [ready,setReady]=useState(Boolean(window.turnstile))
  const [failed,setFailed]=useState(false)

  useEffect(()=>{
    if(!SITE_KEY)return
    if(window.turnstile){setReady(true);return}
    let script=document.getElementById(SCRIPT_ID) as HTMLScriptElement|null
    const onLoad=()=>setReady(true)
    const onError=()=>setFailed(true)
    if(!script){
      script=document.createElement('script')
      script.id=SCRIPT_ID
      script.src='https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit'
      script.async=true
      script.defer=true
      document.head.appendChild(script)
    }
    script.addEventListener('load',onLoad)
    script.addEventListener('error',onError)
    return()=>{script?.removeEventListener('load',onLoad);script?.removeEventListener('error',onError)}
  },[])

  useEffect(()=>{
    if(!SITE_KEY||!ready||!container.current||!window.turnstile||widgetId.current)return
    widgetId.current=window.turnstile.render(container.current,{
      sitekey:SITE_KEY,
      theme:'dark',
      callback:(token)=>{setFailed(false);onToken(token)},
      'expired-callback':()=>onToken(null),
      'error-callback':()=>{setFailed(true);onToken(null)},
    })
    return()=>{
      if(widgetId.current&&window.turnstile){window.turnstile.remove(widgetId.current);widgetId.current=null}
    }
  },[ready,onToken])

  if(!SITE_KEY)return <div className="form-note">Human verification is not configured on this environment. Use the Retry-After period and try again.</div>
  return <div className="human-verification"><div className="form-note">Traffic protection was triggered. Complete the human check to retry this login or registration once.</div><div ref={container}/>{failed&&<div className="form-error">Human verification could not be completed. You can retry after the throttle window instead.</div>}</div>
}
