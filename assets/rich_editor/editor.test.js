import {test} from 'node:test';
import assert from 'node:assert/strict';
import {JSDOM} from 'jsdom';

const dom = new JSDOM('<!doctype html><body></body>', {pretendToBeVisual:true});
for (const key of ['window','document','navigator','Node','HTMLElement','Element','MutationObserver','DOMParser','getComputedStyle']) {
  Object.defineProperty(globalThis,key,{value:dom.window[key],configurable:true});
}
globalThis.requestAnimationFrame=dom.window.requestAnimationFrame.bind(dom.window);
globalThis.cancelAnimationFrame=dom.window.cancelAnimationFrame.bind(dom.window);
const {createEditor, cleanHTML, default: renderRich} = await import('./editor.js');

test('voltar à etapa retoma sequência confirmada e permite aprovar no primeiro clique',()=>{
  const host=document.createElement('div');document.body.append(host);
  host.innerHTML='<section class="gc-rich-editor"></section>';
  const sent=[];
  const component={parentElement:host,data:{doc:'etp',markdown:'Minuta',html:'<p>Minuta</p>',version:'v1',source:'hash',sequence:7},setStateValue:(key,value)=>sent.push(value)};
  const cleanup=renderRich(component);
  [...host.querySelectorAll('button')].find(b=>b.textContent==='Aprovar e avançar').click();
  assert.equal(sent[0].sequence,8);
  assert.equal(sent[0].action,'approve');
  renderRich({...component,data:{...component.data,sequence:8}});
  [...host.querySelectorAll('button')].find(b=>b.textContent==='Aprovar e avançar').click();
  assert.equal(sent[1].sequence,9);
  cleanup();host.remove();
});

test('roundtrip sem perda de estrutura: acentos, ênfase, listas aninhadas, links e tabela',()=>{
  const host=document.createElement('div');document.body.append(host);
  const editor=createEditor(host,'<h2>Licitação</h2><p><strong>Ação</strong> e <em>revisão</em> &amp; <a href="https://example.org">fonte</a></p><ol start="3"><li><p>Primeiro</p><ul><li><p>Interno</p></li></ul></li><li><p>Segundo</p></li></ol><table><thead><tr><th>Id</th><th>Dano</th></tr></thead><tbody><tr><td>1</td><td>Atraso</td></tr></tbody></table>');
  const before=editor.getJSON();
  const markdown=editor.getMarkdown();
  assert.match(markdown,/\*\*Ação\*\*/);
  assert.match(markdown,/\*revisão\*/);
  assert.match(markdown,/https:\/\/example.org/);
  editor.commands.setContent(markdown,{contentType:'markdown'});
  const after=editor.getJSON();
  // ProseMirror mantém um parágrafo vazio após tabela para permitir continuar
  // a digitação. Essa posição de cursor não acrescenta conteúdo documental.
  if(after.content.at(-1)?.type==='paragraph' && !after.content.at(-1).content)after.content.pop();
  assert.deepEqual(after,before);
  editor.destroy();host.remove();
});

test('colagem remove script, estilos e handlers de HTML externo',()=>{
  const html=cleanHTML('<p style="color:red" onclick="alert(1)">Texto</p><script>alert(1)</script><a href="javascript:alert(1)">x</a>');
  assert.equal(html,'<p>Texto</p><a>x</a>');
});

test('documento longo preserva parágrafos e unicode',()=>{
  const host=document.createElement('div');
  const content=Array.from({length:400},(_,i)=>`<p>Cláusula ${i}: ação, órgão e contratação.</p>`).join('');
  const editor=createEditor(host,content);
  const markdown=editor.getMarkdown();
  editor.commands.setContent(markdown,{contentType:'markdown'});
  assert.equal(editor.getJSON().content.length,400);
  assert.match(editor.getText(),/Cláusula 399/);
  editor.destroy();
});

test('quebra de linha dentro de célula preserva separação dos conteúdos',()=>{
  const host=document.createElement('div');
  const editor=createEditor(host,'<p>Primeira<br>Segunda</p><table><tr><th>Dano</th></tr><tr><td>Antes<br>Depois</td></tr></table>');
  const markdown=editor.getMarkdown();
  assert.match(markdown,/Antes<br\s*\/?>Depois/);
  editor.commands.setContent(markdown,{contentType:'markdown'});
  const json=JSON.stringify(editor.getJSON());
  assert.equal((json.match(/"type":"hardBreak"/g)||[]).length,2);
  editor.destroy();
});
