import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { ArrowLeft, ArrowRight, CheckCircle2 } from 'lucide-react'
import { Logo } from '../components/Logo'
import { useAuth } from '../context/AuthContext'

export default function Auth({mode}:{mode:'login'|'register'}){
 const {login,register}=useAuth(); const nav=useNavigate(); const [params]=useSearchParams(); const [form,setForm]=useState({email:'',username:'',password:'',referral:params.get('ref')||''}); const [error,setError]=useState(''); const [busy,setBusy]=useState(false)
 const submit=async(e:React.FormEvent)=>{e.preventDefault();setBusy(true);setError('');try{if(mode==='login') await login(form.email,form.password); else await register(form.email,form.username,form.password,form.referral);nav('/app')}catch(e:any){setError(e.message||'Something went wrong')}finally{setBusy(false)}}
 return <div className="auth-page"><div className="auth-art"><Link to="/" className="back"><ArrowLeft/> Back</Link><Logo/><div className="auth-message"><span>WELCOME TO THE BAG ECONOMY</span><h1>{mode==='login'?'Your Bag is waiting.':'Start at £0. Go anywhere.'}</h1><p>Discover funded opportunities, build reputation and earn your way into crypto without putting your own money on the line.</p><div className="auth-points"><div><CheckCircle2/> No deposit to start</div><div><CheckCircle2/> Transparent funded rewards</div><div><CheckCircle2/> One profile, growing BagScore</div></div></div></div>
 <div className="auth-form-wrap"><form className="auth-form" onSubmit={submit}><span className="form-kicker">{mode==='login'?'WELCOME BACK':'CREATE YOUR BAG'}</span><h2>{mode==='login'?'Log in to NuBagz':'Join NuBagz'}</h2><p>{mode==='login'?<>New here? <Link to="/register">Create your Bag</Link></>:<>Already baggin'? <Link to="/login">Log in</Link></>}</p>
 {mode==='register'&&<label>Username<input value={form.username} onChange={e=>setForm({...form,username:e.target.value})} placeholder="BagHunter" required/></label>}
 <label>Email<input type="email" value={form.email} onChange={e=>setForm({...form,email:e.target.value})} placeholder="you@example.com" required/></label>
 <label>Password<input type="password" minLength={8} value={form.password} onChange={e=>setForm({...form,password:e.target.value})} placeholder="8+ characters" required/></label>
 {mode==='register'&&<label>Referral code <small>optional</small><input value={form.referral} onChange={e=>setForm({...form,referral:e.target.value})} placeholder="NUBAGZ0000"/></label>}
 {error&&<div className="form-error">{error}</div>}<button className="btn primary full big" disabled={busy}>{busy?'Loading…':mode==='login'?'Enter NuBagz':'Create my Bag'} <ArrowRight/></button>
 {mode==='login'&&<button type="button" className="demo-link" onClick={()=>setForm({...form,email:'demo@demo.nubagz.com',password:'Demo123!'})}>Use demo account</button>}
 </form></div></div>
}
