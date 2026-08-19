export function Logo({compact=false}:{compact?:boolean}){
 return <div className="brand"><div className="brand-mark"><span>N</span><i>↗</i></div>{!compact&&<div className="brand-word">Nu<span>Bagz</span></div>}</div>
}
