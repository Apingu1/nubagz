import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { AuthProvider, useAuth } from './context/AuthContext'
import { PrivyCustomJwtSync, WalletProvider, privyConfigured } from './context/WalletProvider'
import './styles.css'

function PrivyBridge(){
  const {user,authSource}=useAuth()
  if(!privyConfigured||!user||authSource!=='password') return null
  return <PrivyCustomJwtSync/>
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode><BrowserRouter><WalletProvider><AuthProvider><PrivyBridge/><App/></AuthProvider></WalletProvider></BrowserRouter></React.StrictMode>
)
