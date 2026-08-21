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
  base: '/bag-z-hq/base.webp',
  hello: '/bag-z-hq/hello.webp',
  detective: '/bag-z-hq/detective.webp',
  wallet: '/bag-z-hq/wallet.webp',
  loot: '/bag-z-hq/loot.webp',
  security: '/bag-z-hq/security.webp',
  warning: '/bag-z-hq/warning.webp',
  confused: '/bag-z-hq/confused.webp',
  sleepy: '/bag-z-hq/sleepy.webp',
  victory: '/bag-z-hq/victory.webp',
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

type RouteFeature = {
  variant: BagZVariant
  kicker: string
  title: string
  copy: string
}

function featureForPath(pathname: string): RouteFeature {
  if (pathname === '/app') return {variant:'hello',kicker:'BAG Z / HOME BASE',title:'Bag Z is on the hunt.',copy:'Your next funded opportunity, reward and reputation gain starts here.'}
  if (/^\/app\/(for-you|trending|discover|watchbag|onchain)/.test(pathname)) return {variant:'detective',kicker:'BAG Z / SCOUT MODE',title:'Hunting the next Bag.',copy:'Scan funded opportunities, signals and onchain activity without chasing noise.'}
  if (/^\/app\/(bag|swaps)/.test(pathname)) return {variant:'wallet',kicker:'BAG Z / WALLET MODE',title:'Keep your Bag close.',copy:'Manage rewards and onchain actions with the destination you choose.'}
  if (/^\/app\/(daily|drops|earnings|revenue-share)/.test(pathname)) return {variant:'loot',kicker:'BAG Z / EARN MODE',title:'Bag it. Then bag some more.',copy:'Track what you have earned and where the next funded reward is coming from.'}
  if (/^\/app\/(trust|account-trust|reports|reviews)/.test(pathname)) return {variant:'security',kicker:'BAG Z / TRUST MODE',title:'Trust first. Bag second.',copy:'Use reputation, reviews and project signals before you spend your time.'}
  if (/^\/app\/(gas|admin)/.test(pathname)) return {variant:'warning',kicker:'BAG Z / ALERT MODE',title:'Stay sharp.',copy:'Important controls and cost signals deserve a closer look before you move.'}
  if (/^\/app\/activity/.test(pathname)) return {variant:'confused',kicker:'BAG Z / TRACE MODE',title:'Follow the trail.',copy:'Every real action leaves a record. Bag Z is reading the story behind yours.'}
  if (/^\/app\/(leaderboard|referrals|bounties|builders)/.test(pathname)) return {variant:'victory',kicker:'BAG Z / WIN MODE',title:'Stack the wins.',copy:'Build reputation, bring value and keep moving up the Bag economy.'}
  if (/^\/app\/notifications/.test(pathname)) return {variant:'sleepy',kicker:'BAG Z / SIGNAL MODE',title:'All signal. No panic.',copy:'Your private account events stay here until there is something worth seeing.'}
  if (/^\/app\/(studio|project-analytics|templates)/.test(pathname)) return {variant:'hello',kicker:'BAG Z / BUILDER MODE',title:'Build a Bag people want.',copy:'Turn project inventory into funded participation that earns real attention.'}
  return {variant:'base',kicker:'BAG Z / NUBAGZ',title:'Find it. Earn it. Bag it.',copy:'Bag Z keeps the character of NuBagz front and centre while you explore.'}
}

export function BagZRouteFeature() {
  const { pathname } = useLocation()
  const feature = featureForPath(pathname)

  return (
    <section className={`bag-z-route-feature bag-z-route-${feature.variant}`}>
      <div className="bag-z-route-copy">
        <span>{feature.kicker}</span>
        <h2>{feature.title}</h2>
        <p>{feature.copy}</p>
      </div>
      <div className="bag-z-route-stage" aria-hidden="true">
        <i className="bag-z-orbit one" />
        <i className="bag-z-orbit two" />
        <BagZMascot variant={feature.variant} className="bag-z-route-art" eager />
      </div>
    </section>
  )
}
