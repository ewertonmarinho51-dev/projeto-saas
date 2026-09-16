import {Editor} from '@tiptap/core';
import StarterKit from '@tiptap/starter-kit';
import {TableKit} from '@tiptap/extension-table';
import {Markdown} from '@tiptap/markdown';
import DOMPurify from 'dompurify';

export const allowedTags=['p','br','strong','b','em','i','h1','h2','h3','h4','h5','h6','ul','ol','li','blockquote','hr','pre','code','table','thead','tbody','tr','th','td','a','s'];
export function cleanHTML(html) { return DOMPurify.sanitize(html,{ALLOWED_TAGS:allowedTags,ALLOWED_ATTR:['href','title','start'],ALLOW_DATA_ATTR:false}); }
export function extensions() {return [StarterKit.configure({underline:false,link:{openOnClick:false,autolink:false,protocols:['https','http','mailto']}}),TableKit.configure({table:{resizable:false}}),Markdown.configure({indentation:{style:'space',size:4}})];}
export function createEditor(element, html, onUpdate=()=>{}) {
  return new Editor({element,extensions:extensions(),content:cleanHTML(html),
    editorProps:{attributes:{'aria-label':'Conteúdo do documento',role:'textbox','aria-multiline':'true'},
      transformPastedHTML:cleanHTML,
      handleKeyDown(view,event){
        if(event.key==='Tab'){
          const editor=view.dom.__editor;
          if(editor?.isActive('listItem')){event.preventDefault();return event.shiftKey?editor.commands.liftListItem('listItem'):editor.commands.sinkListItem('listItem');}
        }
        return false;
      }},onUpdate});
}

function documentFingerprint(editor){
  const json=editor.getJSON();
  while(json.content?.at(-1)?.type==='paragraph' && !json.content.at(-1).content)json.content.pop();
  return JSON.stringify(json);
}

export default function renderRich(component) {
  const {data,parentElement,setStateValue}=component;
  const root=parentElement.querySelector('.gc-rich-editor');
  if(!root)return;
  // Preserve ProseMirror history and selection across data acknowledgements.
  let instance=root.__instance;
  if(instance){instance.send=setStateValue;instance.data=data;
    if(instance.version!==data.version){
      clearTimeout(instance.timer);
      if(data.markdown!==instance.lastSent || instance.dirty){
        instance.editor.commands.setContent(cleanHTML(data.html),{emitUpdate:false});
        instance.fingerprint=documentFingerprint(instance.editor);
        instance.initial=data.markdown;instance.lastSent=data.markdown;
      }
      instance.dirty=false;
      instance.version=data.version;instance.sequence=data.sequence||0;
    }
    instance.sequence=Math.max(instance.sequence,data.sequence||0);
    instance.editor.setEditable(!data.disabled);
    root.querySelectorAll('button,select').forEach(el=>el.disabled=!!data.disabled);
    return;
  }
  const toolbar=document.createElement('div');toolbar.className='gc-editor-toolbar';toolbar.setAttribute('role','toolbar');toolbar.setAttribute('aria-label','Formatação do documento');
  const page=document.createElement('div');page.className='gc-editor-page';
  const status=document.createElement('p');status.className='gc-editor-status';status.setAttribute('role','status');
  const actions=document.createElement('div');actions.className='gc-editor-actions';
  root.append(toolbar,page,status,actions);
  instance={data,send:setStateValue,version:data.version,sequence:data.sequence||0,timer:null,lastSent:data.markdown,initial:data.markdown,dirty:false};root.__instance=instance;
  function publish(action='draft'){
    if(instance.data.disabled)return;
    clearTimeout(instance.timer);
    const markdown=instance.dirty?instance.editor.getMarkdown():instance.lastSent;
    if(markdown.length>2000000){status.textContent='O documento excede o limite de edição. Reduza o conteúdo antes de continuar.';return;}
    if(action==='draft' && markdown===instance.lastSent && !instance.dirty)return;
    instance.lastSent=markdown;instance.dirty=false;
    instance.send('edit',{version:instance.version,source:instance.data.source,sequence:++instance.sequence,markdown,action});
    status.textContent='Rascunho mantido nesta sessão. Aprove quando concluir a revisão.';
  }
  instance.editor=createEditor(page,data.html,({editor})=>{
    const fingerprint=documentFingerprint(editor);
    if(fingerprint===instance.fingerprint)return;
    instance.fingerprint=fingerprint;
    instance.dirty=true;status.textContent='Edição em andamento';
    clearTimeout(instance.timer);instance.timer=setTimeout(()=>publish(),600);
  });
  instance.fingerprint=documentFingerprint(instance.editor);
  instance.editor.view.dom.__editor=instance.editor;
  instance.editor.setEditable(!data.disabled);
  // Existing GovBot captures canonical drafts through an explicit local event.
  const draftRequest=e=>{const target=e.detail;if(target && instance.editor.isFocused){target.focus=`editor_${instance.data.doc}`;}if(target)target.draft[`editor_${instance.data.doc}`]=instance.dirty?instance.editor.getMarkdown():instance.lastSent;};
  document.addEventListener('govdocs:collect-drafts',draftRequest);
  const button=(label,fn,parent=toolbar)=>{const b=document.createElement('button');b.type='button';b.textContent=label;b.setAttribute('aria-label',label);b.disabled=!!data.disabled;b.addEventListener('click',fn);parent.append(b);return b;};
  button('Negrito',()=>instance.editor.chain().focus().toggleBold().run());
  button('Itálico',()=>instance.editor.chain().focus().toggleItalic().run());
  const headings=document.createElement('select');headings.setAttribute('aria-label','Estilo de parágrafo');
  for(const [v,l] of [['0','Parágrafo'],['1','Título 1'],['2','Título 2'],['3','Título 3']]){const o=document.createElement('option');o.value=v;o.textContent=l;headings.append(o);}
  headings.addEventListener('change',()=>{const level=Number(headings.value);level?instance.editor.chain().focus().setHeading({level}).run():instance.editor.chain().focus().setParagraph().run();});toolbar.append(headings);
  button('Marcadores',()=>instance.editor.chain().focus().toggleBulletList().run());
  button('Numerar',()=>instance.editor.chain().focus().toggleOrderedList().run());
  button('Recuar',()=>instance.editor.chain().focus().liftListItem('listItem').run());
  button('Indentar',()=>instance.editor.chain().focus().sinkListItem('listItem').run());
  button('Desfazer',()=>instance.editor.chain().focus().undo().run());
  button('Refazer',()=>instance.editor.chain().focus().redo().run());
  button('Tabela',()=>instance.editor.chain().focus().insertTable({rows:3,cols:3,withHeaderRow:true}).run());
  button('Adicionar linha',()=>instance.editor.chain().focus().addRowAfter().run());
  button('Remover linha',()=>instance.editor.chain().focus().deleteRow().run());
  button('Voltar',()=>publish('back'),actions);
  button('Gerar novamente',()=>publish('regenerate'),actions);
  const approve=button('Aprovar e avançar',()=>publish('approve'),actions);approve.className='gc-editor-primary';
  status.textContent='As alterações ficam como rascunho até a aprovação.';
  const blurred=()=>{if(instance.dirty)publish();};page.addEventListener('focusout',blurred);
  // v2 calls cleanup when the component is unmounted, not on each keystroke.
  return ()=>{clearTimeout(instance.timer);document.removeEventListener('govdocs:collect-drafts',draftRequest);page.removeEventListener('focusout',blurred);instance.editor.destroy();root.__instance=null;};
}
