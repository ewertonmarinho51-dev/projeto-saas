#!/usr/bin/env python3
"""QA auxiliar de PDF (PyMuPDF). Execute: python pdf_quality_check.py arq.pdf --kind compact --max-pages 15 --require 'RELATÓRIO DE COTAÇÃO'

Auxilia testes de legibilidade estrutural, sem substituir comparação visual e de dados.
"""
import argparse, json, sys
try:
    import fitz
except ImportError as exc:
    raise SystemExit('Instale PyMuPDF: pip install pymupdf') from exc

def main():
    p=argparse.ArgumentParser()
    p.add_argument('pdf')
    p.add_argument('--kind',choices=['compact','integral'],default='compact')
    p.add_argument('--max-pages',type=int,default=None)
    p.add_argument('--require',action='append',default=[])
    p.add_argument('--out',default=None)
    a=p.parse_args()
    doc=fitz.open(a.pdf)
    if doc.is_encrypted: raise SystemExit('ERRO: PDF protegido/criptografado')
    pages=len(doc)
    empty=[];out_of_bounds=[];bad_split=[];links=0
    markers={'Méto\ndo','Situaç\não','Unitá\nrio','Méto\r\ndo'}
    all_text=[]
    for i,pag in enumerate(doc):
        txt=pag.get_text('text')
        all_text.append(txt)
        if len(txt.strip())<20:empty.append(i+1)
        for b in pag.get_text('dict').get('blocks',[]):
            if b.get('type')!=0:continue
            for line in b.get('lines',[]):
                for sp in line.get('spans',[]):
                    rect=fitz.Rect(sp.get('bbox',(0,0,0,0)))
                    if rect.is_empty:continue
                    if rect.x0 < -1 or rect.y0 < -1 or rect.x1 > pag.rect.width+1 or rect.y1>pag.rect.height+1:
                        out_of_bounds.append({'page':i+1,'text':sp.get('text','')[:45], 'bbox':[round(x,1) for x in rect]})
        for frag in markers:
            if frag in txt:bad_split.append({'page':i+1,'fragment':frag.replace('\n',' / ')})
        links+=len(pag.get_links())
    corpus='\n'.join(all_text)
    missing=[x for x in a.require if x.lower() not in corpus.lower()]
    issues=[]
    if pages==0:issues.append('sem_paginas')
    if a.max_pages is not None and pages>a.max_pages: issues.append('excede_meta_paginas')
    if empty:issues.append('paginas_sem_texto')
    if out_of_bounds:issues.append('texto_fora_da_folha')
    if bad_split:issues.append('cabecalhos_partidos')
    if missing:issues.append('texto_obrigatorio_ausente')
    data={'arquivo':a.pdf,'modo':a.kind,'paginas':pages,'links':links,'pages_vazias':empty[:30],
          'spans_fora_da_pagina':out_of_bounds[:30], 'cabecalhos_fragmentados':bad_split[:30],
          'strings_obrigatorias_ausentes':missing,'problemas':issues,'aprovado_no_qa_auxiliar':not issues}
    output=json.dumps(data,ensure_ascii=False,indent=2)
    if a.out:
        open(a.out,'w',encoding='utf-8').write(output+'\n')
    print(output)
    return 1 if issues else 0
if __name__=='__main__':sys.exit(main())
