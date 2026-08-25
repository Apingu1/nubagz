function groupInteger(value:string){
 const negative=value.startsWith('-');const raw=negative?value.slice(1):value;const grouped=raw.replace(/\B(?=(\d{3})+(?!\d))/g,',');return negative?`-${grouped}`:grouped
}

export function formatTokenAmount(value:string|number|null|undefined){
 const raw=String(value??'0').trim()||'0';const numeric=Number(raw)
 if(Number.isFinite(numeric)&&numeric!==0&&Math.abs(numeric)<0.0001)return '<0.0001'
 const decimal=/^(-?\d+)(?:\.(\d+))?$/.exec(raw)
 if(decimal){const integer=groupInteger(decimal[1]);const fraction=(decimal[2]||'').replace(/0+$/,'');return fraction?`${integer}.${fraction}`:integer}
 if(Number.isFinite(numeric))return numeric.toLocaleString(undefined,{maximumFractionDigits:20})
 return raw
}

export function tokenAmountTitle(value:string|number|null|undefined){return String(value??'0')}
