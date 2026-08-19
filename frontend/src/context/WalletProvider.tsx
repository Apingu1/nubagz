import type { ReactNode } from 'react'
import { PrivyProvider, useSubscribeToJwtAuthWithFlag } from '@privy-io/react-auth'
import { useAuth } from './AuthContext'

export const privyConfigured = Boolean(import.meta.env.VITE_PRIVY_APP_ID)

function PrivyAuthSync(){
  const {user,loading}=useAuth()
  useSubscribeToJwtAuthWithFlag({
    isAuthenticated:Boolean(user),
    isLoading:loading,
    getExternalJwt:async()=>user ? (localStorage.getItem('nubagz_token') || undefined) : undefined,
  })
  return null
}

export function WalletProvider({children}:{children:ReactNode}){
  const appId=import.meta.env.VITE_PRIVY_APP_ID
  if(!appId) return <>{children}</>
  return <PrivyProvider
    appId={appId}
    clientId={import.meta.env.VITE_PRIVY_CLIENT_ID || undefined}
    config={{
      appearance:{
        theme:'dark',
        accentColor:'#8B5CF6',
        walletChainType:'ethereum-only',
        walletList:['metamask','detected_ethereum_wallets','wallet_connect'],
      },
      embeddedWallets:{ethereum:{createOnLogin:'off'}},
    }}
  ><PrivyAuthSync/>{children}</PrivyProvider>
}
