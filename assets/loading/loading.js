export default function(component) {
  const {data} = component;
  const cleanupKey = Symbol.for('govdocs.loading.cleanup');
  if (document[cleanupKey]) document[cleanupKey]();
  if (!data.ativo) return;
  const previousFocus = document.activeElement;
  const overlay = document.createElement('div');
  overlay.className = 'gc-generation-overlay';
  overlay.setAttribute('role','dialog'); overlay.setAttribute('aria-modal','true');
  overlay.setAttribute('aria-labelledby','gc-generation-title');
  const card = document.createElement('div'); card.className='gc-generation-card';
  card.tabIndex=-1;
  const title=document.createElement('h2');title.id='gc-generation-title';title.textContent=data.titulo;
  const status=document.createElement('p');status.setAttribute('role','status');status.setAttribute('aria-live','polite');status.textContent=data.rotulo;
  const bar=document.createElement('div');bar.className='gc-generation-bar';bar.setAttribute('aria-hidden','true');
  card.append(title,bar,status);overlay.append(card);document.body.append(overlay);
  // Inert blocks keyboard as well as pointer navigation. Restore exact prior state.
  const siblings=[...document.body.children].filter(n=>n!==overlay&&n.tagName!=='SCRIPT');
  const before=siblings.map(n=>[n,n.inert]);siblings.forEach(n=>{n.inert=true;});
  card.focus();
  const keys=e=>{if(e.key==='Tab'){e.preventDefault();card.focus();}};
  const unloading=e=>{e.preventDefault();e.returnValue='';};
  document.addEventListener('keydown',keys,true);
  window.addEventListener('beforeunload',unloading);
  let cleaned=false;
  const cleanup=()=>{if(cleaned)return;cleaned=true;before.forEach(([n,v])=>{n.inert=v;});overlay.remove();document.removeEventListener('keydown',keys,true);window.removeEventListener('beforeunload',unloading);if(previousFocus?.isConnected)previousFocus.focus();delete document[cleanupKey];};
  document[cleanupKey]=cleanup;
  return cleanup;
}
