import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {JSDOM} from 'jsdom';

test('fechar e reabrir não capturam rascunho de uma etapa anterior', async()=>{
  const dom=new JSDOM('<!doctype html><body></body>',{url:'http://localhost',pretendToBeVisual:true});
  const erros=[];
  dom.window.addEventListener('error',e=>erros.push(e.error));
  for(const key of ['window','document','Element','HTMLElement','CustomEvent','sessionStorage']){
    Object.defineProperty(globalThis,key,{value:dom.window[key],configurable:true});
  }
  globalThis.matchMedia=()=>({matches:false,addEventListener(){},removeEventListener(){}});
  const html=readFileSync(new URL('../govbot/govbot.html',import.meta.url),'utf8')
    .replace('<!-- GOVBOT_MASCOT -->',readFileSync(new URL('../govbot/mascot.svg',import.meta.url),'utf8'));
  document.body.innerHTML=html;
  const source=readFileSync(new URL('../govbot/govbot.js',import.meta.url),'utf8');
  const {default:render}=await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
  let capturas=0;
  document.addEventListener('govdocs:collect-drafts',e=>{
    capturas++;e.detail.draft.editor_etp='Rascunho obsoleto';
  });
  const eventos=[];
  const cleanup=render({data:{open:true,focus:'editor_etp',allowed_fields:['editor_mapa_riscos']},
    parentElement:document,setTriggerValue:(_,evento)=>eventos.push(evento)});
  try{
    document.querySelector('#govbot-close').click();
    assert.equal(document.querySelector('.govbot-root').dataset.open,'false');
    document.querySelector('#govbot-launcher').click();
    assert.equal(document.querySelector('.govbot-root').dataset.open,'true');
    assert.deepEqual(eventos.map(e=>e.event_type),['minimizar','expandir']);
    assert.equal(capturas,0);
    assert.deepEqual(erros,[]);
    for(const evento of eventos){assert.equal(evento.focus,null);assert.deepEqual(evento.draft,{});}
  }finally{cleanup();dom.window.close();}
});
