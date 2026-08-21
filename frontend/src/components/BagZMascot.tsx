import { useLocation } from 'react-router-dom'

export type BagZVariant =
  | 'base'
  | 'hello'
  | 'detective'
  | 'wallet'
  | 'loot'
  | 'security'
  | 'warning'
  | 'confused'
  | 'sleepy'
  | 'victory'

const sources: Record<BagZVariant, string> = {
  base: '/bag-z/base.webp',
  hello: '/bag-z/hello.webp',
  detective: '/bag-z/detective.webp',
  wallet: '/bag-z/wallet.webp',
  loot: '/bag-z/loot.webp',
  security: '/bag-z/security.webp',
  warning: '/bag-z/warning.webp',
  confused: '/bag-z/confused.webp',
  sleepy: '/bag-z/sleepy.webp',
  victory: '/bag-z/victory.webp',
}

export function BagZMascot({
  variant,
  className = '',
  label = 'Bag Z',
  decorative = true,
  eager = false,
}: {
  variant: BagZVariant
  className?: string
  label?: string
  decorative?: boolean
  eager?: boolean
}) {
  return (
    <img
      className={`bag-z-mascot ${className}`.trim()}
      src={sources[variant]}
      alt={decorative ? '' : label}
      aria-hidden={decorative ? true : undefined}
      loading={eager ? 'eager' : 'lazy'}
      decoding="async"
    />
  )
}

export function BagZRouteCompanion() {
  const { pathname } = useLocation()
  let variant: BagZVariant = 'base'

  if (pathname === '/app') variant = 'hello'
  else if (/^\/app\/(for-you|trending|discover|watchbag|onchain)/.test(pathname)) variant = 'detective'
  else if (/^\/app\/(bag|swaps)/.test(pathname)) variant = 'wallet'
  else if (/^\/app\/(daily|drops|earnings|revenue-share)/.test(pathname)) variant = 'loot'
  else if (/^\/app\/(trust|account-trust|reports|reviews)/.test(pathname)) variant = 'security'
  else if (/^\/app\/(gas|admin)/.test(pathname)) variant = 'warning'
  else if (/^\/app\/activity/.test(pathname)) variant = 'confused'
  else if (/^\/app\/(leaderboard|referrals|bounties|builders)/.test(pathname)) variant = 'victory'
  else if (/^\/app\/notifications/.test(pathname)) variant = 'sleepy'
  else if (/^\/app\/(studio|project-analytics|templates)/.test(pathname)) variant = 'hello'

  return <BagZMascot variant={variant} className="bag-z-route-companion" />
}
