import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ArrowRight, Check, ExternalLink, LockKeyhole, ShieldCheck, Sparkles, Wallet, WalletCards } from 'lucide-react'
import { useConnectWallet, useCreateWallet, usePrivy } from '@privy-io/react-auth'
import { Logo } from '../components/Logo'
import { BagZMascot } from '../components/BagZMascot'
import { api } from '../lib/api'
import { privyConfigured } from '../context/WalletProvider'
import { useAuth } from '../context/AuthContext'

function walletErrorMessage(error: unknown, fallback: string) {
  if (typeof error === 'string' && error.trim()) return error
  if (error instanceof Error && error.message) return error.message
  if (error && typeof error === 'object' && 'error' in error) {
    const nested = (error as { error?: unknown }).error
    if (typeof nested === 'string' && nested.trim()) return nested
  }
  return fallback
}

function PayoutOnlySetup({onSaved}:{onSaved:()=>void}){
  const [address,setAddress]=useState(''); const [chain,setChain]=useState('Robinhood'); const [busy,setBusy]=useState(false); const [msg,setMsg]=useState('')
  const save=async()=>{setBusy(true);setMsg('');try{await api('/users/payout-addresses',{method:'POST',body:JSON.stringify({address,chain,label:'Security-first reward address',make_primary:true})});setMsg('Payout-only reward address saved. No wallet connection was made.');onSaved()}catch(e:any){setMsg(e.message||'Could not save payout address')}finally{setBusy(false)}}
  return <div className="payout-only-card"><div className="safety-title"><ShieldCheck/><div><strong>Security-first option</strong><span>No connection. No signature. No permissions.</span></div></div><p><strong>If connecting a valuable wallet to a new website makes you uncomfortable — rightly so — don’t.</strong> Simply add a deposit address for NuBagz rewards. We will never request access to that wallet.</p><label>Reward network<select value={chain} onChange={e=>setChain(e.target.value)}><option>Robinhood</option><option>Avalanche</option><option>Ethereum</option><option>Base</option><option>Arbitrum</option><option>Polygon</option><option>Solana</option></select></label><label>Deposit / payout address<input value={address} onChange={e=>setAddress(e.target.value.trim())} placeholder="Paste an address you control"/></label><div className="payout-warning"><LockKeyhole/>This address is stored as <b>payout-only / unverified</b>. NuBagz does not claim you control it, so double-check it before saving.</div><button className="btn primary full" disabled={busy||address.length<8} onClick={save}>{busy?'Saving…':'Use this for my rewards'} <ArrowRight/></button>{msg&&<div className="form-note">{msg}</div>}</div>
}

function PrivyWalletActions({onReady}:{onReady:()=>void}){
  const {ready,authenticated}=usePrivy(); const [busy,setBusy]=useState(false); const [msg,setMsg]=useState('')
  const verify=async(wallet:any)=>{setBusy(true);setMsg('Confirm the NuBagz verification message in your wallet…');try{const challenge=await api<{challenge_id:number;message:string}>('/users/wallets/challenge',{method:'POST',body:JSON.stringify({address:wallet.address})});const provider=await wallet.getEthereumProvider();const signature=await provider.request({method:'personal_sign',params:[challenge.message,wallet.address]}) as string;const chainHex=await provider.request({method:'eth_chainId'}) as string;await api('/users/wallets/verify',{method:'POST',body:JSON.stringify({challenge_id:challenge.challenge_id,address:wallet.address,signature,wallet_client_type:wallet.walletClientType||'unknown',connector_type:wallet.connectorType||'unknown',chain_id:parseInt(chainHex,16),make_primary:true})});setMsg('Wallet verified and set as your primary reward wallet.');onReady()}catch(e:any){setMsg(e.message||'Wallet verification failed')}finally{setBusy(false)}}
  const {connectWallet}=useConnectWallet({onSuccess:async({wallet})=>{await verify(wallet)},onError:(error)=>setMsg(walletErrorMessage(error,'Wallet connection cancelled'))})
  const {createWallet}=useCreateWallet({onSuccess:async({wallet})=>{await verify(wallet)},onError:(error)=>setMsg(walletErrorMessage(error,'Wallet creation failed'))})
  const createFirst=()=>{if(!authenticated){setMsg('Embedded wallet creation needs NuBagz ↔ Privy custom JWT authentication enabled. External wallet connection and payout-only addresses still work.');return}createWallet()}
  if(!ready) return <div className="wallet-provider-note">Preparing secure wallet services…</div>
  return <><div className="wallet-choice-grid"><button className="wallet-choice" disabled={busy} onClick={createFirst}><span className="choice-icon glow"><Sparkles/></span><div><b>I’m new to crypto</b><h3>Create my first wallet</h3><p>NuBagz securely provisions a user-controlled embedded EVM wallet. No seed phrase or extension needed to get started.</p><span className="choice-cta">Create NuBagz wallet <ArrowRight/></span></div></button><button className="wallet-choice" disabled={busy} onClick={()=>connectWallet({description:'Connect an existing wallet to NuBagz. You will sign a verification message; NuBagz cannot move funds.',walletList:['metamask','detected_ethereum_wallets','wallet_connect'],walletChainType:'ethereum-only'})}><span className="choice-icon"><WalletCards/></span><div><b>I already have a wallet</b><h3>Connect existing wallet</h3><p>MetaMask, Rabby and other detected browser wallets, plus Trust Wallet and 100+ wallets through WalletConnect.</p><span className="choice-cta">Choose wallet <ExternalLink/></span></div></button></div>{!authenticated&&<div className="wallet-provider-note warning"><LockKeyhole/><span>External wallet connection is available. To activate one-click embedded wallet creation for new users, finish the custom JWT setup in WALLET_SETUP.md.</span></div>}{msg&&<div className="wallet-status">{busy&&<span className="pulse-dot"/>}{msg}</div>}</>
}

export default function WalletOnboarding(){
  const nav=useNavigate(); const {refresh}=useAuth(); const [saved,setSaved]=useState(false)
  const complete=async()=>{setSaved(true);await refresh()}
  return <div className="wallet-onboarding"><header><Logo/><Link to="/app" className="skip-wallet">Do this later</Link></header><main><div className="wallet-onboarding-hero"><div className="wallet-onboarding-copy"><span className="eyebrow">YOUR FIRST ONCHAIN STEP</span><h1>How do you want to receive your <em>Bagz?</em></h1><p className="wallet-lead">New to crypto? We can create your first wallet. Already onchain? Connect the wallet you know. Security-conscious veteran? Connect nothing and give us a payout address instead.</p></div><div className="bag-z-wallet-stage"><div><span>BAG Z / WALLET MODE</span><strong>Your keys. Your choice. Your Bag.</strong></div><BagZMascot variant="wallet" className="bag-z-wallet-onboarding-art" eager/></div></div>{privyConfigured?<PrivyWalletActions onReady={complete}/>:<div className="wallet-provider-note warning"><LockKeyhole/><span>Wallet creation/connection is not configured on this deployment yet. Add a Privy App ID to enable it. The payout-only route works without Privy.</span></div>}<div className="or-divider"><span>OR — KEEP YOUR WALLET COMPLETELY DISCONNECTED</span></div><PayoutOnlySetup onSaved={complete}/>{saved&&<div className="wallet-success"><Check/><div><strong>Reward destination ready.</strong><span>You can change your primary wallet or payout address any time from My Bag.</span></div><button className="btn primary" onClick={()=>nav('/app')}>Start baggin’ <ArrowRight/></button></div>}<div className="wallet-trust-row"><div><ShieldCheck/><span>NuBagz never asks you to deposit funds to unlock rewards.</span></div><div><Wallet/><span>Connected wallets are verified with a message signature, not a transaction.</span></div><div><LockKeyhole/><span>Payout-only addresses require zero wallet permissions.</span></div></div></main></div>
}
