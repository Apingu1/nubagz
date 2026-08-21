import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { ArrowLeft, ArrowRight, CheckCircle2 } from 'lucide-react'
import { Logo } from '../components/Logo'
import { BagZMascot } from '../components/BagZMascot'
import { useAuth } from '../context/AuthContext'
import { api } from '../lib/api'

type ReferralStatus={valid:boolean;eligible:boolean;referrer?:string|null}

export default function Auth({mode}:{mode:'login'|'register'}){
 const {login,register}=useAuth(); const nav=useNavigate(); const [params]=useSearchParams(); const [form,setForm]=useState({email:'',username:'',password:'',referral:params.get('ref')||''}); const [error,setError]=useState(''); const [busy,setBusy]=useState(false);const [refStatus,setRefStatus]=useState<ReferralStatus|null>(null)
 const validateReferral=async(code:string)=>{const clean=code.trim();if(!clean){setRefStatus(null);return}try{setRefStatus(await api<ReferralStatus>(`/referrals/validate/${encodeURIComponent(clean)}`))}catch{setRefStatus(null)}}
 useEffect(()=>{if(mode==='register'&&form.referral)validateReferral(form.referral)},[])
 const submit=async(e:React.FormEvent)=>{e.preventDefault();setBusy(true);setError('');try{if(mode==='login'){await login(form.email,form.password);nav('/app')}else{await register(form.email,form.username,form.password,form.referral);nav('/wallet-setup')}}catch(e:any){setError(e.message||'Something went wrong')}finally{setBusy(false)}}
 return <div className="auth-page"><div className="auth-art"><Link to="/" className="back"><ArrowLeft/> Back</Link><Logo/><BagZMascot variant="hello" className="bag-z-auth-art"/><div className="auth-message"><span>WELCOME TO THE BAG ECONOMY</span><h1>{mode==='login'?'Your Bag is waiting.':'Start at £0. Go anywhere.'}</h1><p>Discover funded opportunities, build reputation and earn your way into crypto without putting your own money on the line.</p><div className="auth-points"><div><CheckCircle2/> No deposit to start</div><div><CheckCircle2/> Transparent funded rewards</div><div><CheckCircle2/> Your wallet, your choice</div></div></div></div>
 <div className="auth-form-wrap"><form className="auth-form" onSubmit={submit}><span className="form-kicker">{mode==='login'?'WELCOME BACK':'CREATE YOUR BAG'}</span><h2>{mode==='login'?'Log in to NuBagz':'Join NuBagz'}</h2><p>{mode==='login'?<>New here? <Link to="/register">Create your Bag</Link></>:<>Already baggin'? <Link to="/login">Log in</Link></>}</p>
 {mode==='register'&&<label>Username<input value={form.username} onChange={e=>setForm({...form,username:e.target.value})} placeholder="BagHunter" required/></label>}
 <label>Email<input type="email" value={form.email} onChange={e=>setForm({...form,email:e.target.value})} placeholder="you@example.com" required/></label>
 <label>Password<input type="password" minLength={8} value={form.password} onChange={e=>setForm({...form,password:e.target.value})} placeholder="8+ characters" required/></label>
 {mode==='register'&&<><label>Referral code <small>optional</small><input value={form.referral} onChange={e=>{setForm({...form,referral:e.target.value});setRefStatus(null)}} onBlur={e=>validateReferral(e.target.value)} placeholder="NUBAGZ0000"/></label>{refStatus?.valid&&refStatus.eligible&&<div className="form-note">Invite verified from <strong>{refStatus.referrer}</strong>. No reward is created by signup alone; referral rewards only settle from funded Bag completions.</div>}{refStatus&&(!refStatus.valid||!refStatus.eligible)&&<div className="form-error">This referral code is not currently eligible for attribution. You can remove it and continue without a referral.</div>}</>}
 {error&&<div className="form-error">{error}</div>}<button className="btn primary full big" disabled={busy}>{busy?'Loading…':mode==='login'?'Enter NuBagz':'Create my Bag'} <ArrowRight/></button>
 {mode==='login'&&<button type="button" className="demo-link" onClick={()=>setForm({...form,email:'demo@demo.nubagz.com',password:'Demo123!'})}>Use demo account</button>}
 </form></div></div>
}
