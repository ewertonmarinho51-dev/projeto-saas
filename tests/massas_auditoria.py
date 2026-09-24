"""
§4 da auditoria pré-operacional — as massas de teste A a H.

O QUE ESTE MÓDULO É

Oito processos fictícios, tecnicamente realistas, cada um com dados de
entrada definidos, resultado esperado e critério objetivo de aprovação.
Nenhum dado pessoal real, nenhum cadastro de produção: os municípios são
inventados, os responsáveis são funções e não pessoas, e os preços são
plausíveis sem serem cotação de contratação nenhuma.

POR QUE OS PREÇOS SÃO "PLAUSÍVEIS" E NÃO "REAIS"

O §4 é explícito: não confundir dado simulado de entrada com preço ou
referência real de contratação. Um número daqui não sustenta estimativa
de valor de coisa nenhuma — ele existe para que a aritmética da planilha
tenha o que conferir.

COMO CADA CENÁRIO É JULGADO

`esperado` não é prosa: é o que uma prova pode conferir sem opinar sobre
redação. Quantidade de itens, valor global, presença ou ausência de ARP,
marcador de pendência, campo que precisa atravessar até o documento.

A qualidade REDACIONAL de um documento — se o texto convence, se a
fundamentação jurídica é adequada — não está aqui e não pode estar: esta
rodada não chama modelo nenhum. Fica para a rodada operacional, e o §8
manda registrar isso como pendente em vez de disfarçar.
"""

from __future__ import annotations

import json
import pathlib

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


def _itens(*linhas) -> list[dict]:
    """(codigo, descricao, unidade, quantidade, valor_unitario) → planilha."""
    return [{"item": str(i), "codigo": c, "descricao": d, "unidade": u,
             "quantidade": q, "valor_unitario": v}
            for i, (c, d, u, q, v) in enumerate(linhas, 1)]


# ---------------------------------------------------------------------------
# A — materiais de expediente, tabela extensa
# ---------------------------------------------------------------------------
_EXPEDIENTE = _itens(
    ("57270", "Caneta esferográfica azul, corpo transparente, ponta 1,0 mm",
     "UN", 5000, 1.87),
    ("57271", "Caneta esferográfica preta, corpo transparente, ponta 1,0 mm",
     "UN", 3000, 1.87),
    ("41233", "Papel A4 75 g/m², alcalino, resma com 500 folhas",
     "RESMA", 2400, 24.90),
    ("41240", "Papel A4 90 g/m², alcalino, resma com 500 folhas",
     "RESMA", 300, 38.50),
    ("12880", "Pasta suspensa em kraft, com grampo plástico e visor",
     "UN", 1800, 3.42),
    ("12881", "Pasta AZ ofício, lombo largo, com etiqueta",
     "UN", 600, 18.70),
    ("33019", "Grampeador de mesa, capacidade 25 folhas, corpo metálico",
     "UN", 120, 42.30),
    ("33020", "Grampo galvanizado 26/6, caixa com 5.000 unidades",
     "CX", 900, 6.15),
    ("21107", "Bloco autoadesivo 76 x 102 mm, 100 folhas",
     "BL", 1500, 7.80),
    ("21108", "Fita adesiva transparente 45 mm x 45 m",
     "RL", 800, 5.60),
    ("64412", "Tinta para carimbo, frasco de 40 ml, cor preta",
     "FR", 200, 9.35),
    ("64413", "Almofada para carimbo nº 3, cor azul", "UN", 150, 12.40),
    ("18822", "Envelope ofício branco 114 x 229 mm", "UN", 6000, 0.42),
    ("18823", "Envelope saco kraft 240 x 340 mm", "UN", 2500, 1.18),
    ("50331", "Clipe metálico nº 6, caixa com 500 g", "CX", 400, 14.90),
    ("50332", "Percevejo latonado, caixa com 100 unidades", "CX", 250, 4.25),
    ("77410", "Corretivo em fita, 5 mm x 6 m", "UN", 700, 8.90),
    ("77411", "Marcador para quadro branco, cor azul", "UN", 1200, 4.70),
    ("88015", "Cola bastão 40 g", "UN", 900, 6.30),
    ("88016", "Tesoura escolar sem ponta, 13 cm", "UN", 500, 7.15),
)

CENARIO_A = {
    "id": "A",
    "titulo": "Aquisição de materiais de expediente (tabela extensa)",
    "dados": {
        "orgao": "Prefeitura Municipal de Vila Nova do Norte — Secretaria "
                 "Municipal de Administração",
        "responsavel": "Diretor do Departamento de Compras",
        "objeto": "Aquisição de materiais de expediente para as unidades "
                  "administrativas e escolares do Município, pelo período "
                  "de 12 (doze) meses.",
        "justificativa": "O estoque atual do almoxarifado central atende ao "
                         "consumo até março, e a interrupção do fornecimento "
                         "de material de expediente paralisaria a emissão de "
                         "documentos, o atendimento ao público e o registro "
                         "escolar.",
        "alinhamento": "Item 14 do Plano de Contratações Anual de 2026.",
        "requisitos": "Materiais novos, de primeiro uso, com embalagem "
                      "íntegra e prazo de validade, quando aplicável, não "
                      "inferior a 12 meses da entrega.",
        "modelo_execucao": "Entrega parcelada",
        "prazo": "Contratação pretendida para o primeiro trimestre de 2026.",
        "riscos": "Desabastecimento por atraso na entrega; variação de preço "
                  "entre a estimativa e a proposta.",
        "itens": _EXPEDIENTE,
    },
    "esperado": {
        "documentos": ("dfd", "etp", "mapa_riscos", "tr", "edital"),
        "arp": False,
        "itens": 20,
        # 5000*1,87 + 3000*1,87 + … — conferido pela própria planilha,
        # não copiado à mão: ver `valor_global_esperado`.
    },
    "criterio": "A tabela atravessa inteira, com os 20 códigos, e o valor "
                "global bate com a soma das linhas.",
}


# ---------------------------------------------------------------------------
# B — equipamentos de informática
# ---------------------------------------------------------------------------
CENARIO_B = {
    "id": "B",
    "titulo": "Aquisição de equipamentos de informática",
    "dados": {
        "orgao": "Prefeitura Municipal de Vila Nova do Norte — Secretaria "
                 "Municipal de Fazenda",
        "responsavel": "Coordenador de Tecnologia da Informação",
        "objeto": "Aquisição de 40 (quarenta) microcomputadores do tipo "
                  "corporativo e 40 (quarenta) monitores de 24 polegadas "
                  "para substituição do parque tecnológico das unidades "
                  "administrativas.",
        "justificativa": "Os equipamentos em uso foram adquiridos em 2017, "
                         "não recebem mais atualização de segurança do "
                         "fabricante do sistema operacional e apresentam "
                         "falhas recorrentes que interrompem o atendimento "
                         "tributário ao contribuinte.",
        "alinhamento": "Item 3 do Plano de Contratações Anual de 2026 e "
                       "Plano Diretor de Tecnologia da Informação 2025-2028.",
        "requisitos": "Processador com desempenho mínimo equivalente a 12.000 "
                      "pontos em índice público de referência; 16 GB de "
                      "memória; armazenamento em estado sólido de 512 GB; "
                      "garantia on-site de 36 (trinta e seis) meses com "
                      "atendimento no local; certificação de eficiência "
                      "energética.",
        "modelo_execucao": "Entrega única (fornecimento integral)",
        "prazo": "Entrega em até 45 dias corridos da ordem de fornecimento.",
        "riscos": "Descontinuidade de modelo pelo fabricante entre a "
                  "estimativa e a contratação; recebimento de equipamento "
                  "com configuração inferior à especificada.",
        "itens": _itens(
            ("90011", "Microcomputador corporativo, 16 GB RAM, SSD 512 GB, "
                      "garantia on-site 36 meses", "UN", 40, 4870.00),
            ("90012", "Monitor LED 24 polegadas, resolução 1920x1080, "
                      "entrada HDMI e DisplayPort", "UN", 40, 912.50),
            ("90013", "Teclado e mouse USB, layout ABNT2", "KIT", 40, 118.90),
        ),
    },
    "esperado": {
        "documentos": ("dfd", "etp", "mapa_riscos", "tr", "edital"),
        "arp": False,
        "itens": 3,
    },
    "criterio": "Garantia, especificação técnica e condição de recebimento "
                "chegam ao TR sem que a quantidade mude no caminho.",
}


# ---------------------------------------------------------------------------
# C — serviços continuados
# ---------------------------------------------------------------------------
CENARIO_C = {
    "id": "C",
    "titulo": "Serviços continuados de limpeza e conservação",
    "dados": {
        "orgao": "Prefeitura Municipal de Vila Nova do Norte — Secretaria "
                 "Municipal de Educação",
        "responsavel": "Diretor de Infraestrutura Escolar",
        "objeto": "Contratação de empresa especializada na prestação de "
                  "serviços continuados de limpeza, asseio e conservação "
                  "predial, com fornecimento de mão de obra, materiais e "
                  "equipamentos, para 12 (doze) unidades escolares.",
        "justificativa": "As unidades escolares não dispõem de quadro próprio "
                         "de servidores para a atividade, e a ausência de "
                         "limpeza diária inviabiliza o funcionamento regular "
                         "das aulas e o cumprimento das normas sanitárias.",
        "alinhamento": "Item 21 do Plano de Contratações Anual de 2026.",
        "requisitos": "Execução em dias úteis, em dois turnos; fornecimento "
                      "de uniformes e equipamentos de proteção individual; "
                      "comprovação de regularidade trabalhista e "
                      "previdenciária a cada medição.",
        "modelo_execucao": "Serviço de execução continuada",
        "prazo": "Vigência de 12 meses, prorrogável na forma da lei.",
        "riscos": "Inadimplemento de obrigações trabalhistas pela contratada; "
                  "rotatividade de pessoal com prejuízo à execução.",
        "itens": _itens(
            ("70101", "Posto de serviço de servente de limpeza, 44 horas "
                      "semanais, com material e equipamento", "POSTO/MÊS",
             288, 4315.60),
            ("70102", "Posto de serviço de encarregado de limpeza, 44 horas "
                      "semanais", "POSTO/MÊS", 12, 6120.40),
        ),
    },
    "esperado": {
        "documentos": ("dfd", "etp", "mapa_riscos", "tr", "edital"),
        "arp": False,
        "itens": 2,
    },
    "criterio": "Fiscalização, medição e critério de pagamento aparecem no "
                "TR; a unidade POSTO/MÊS não é convertida nem arredondada.",
}


# ---------------------------------------------------------------------------
# D — serviços técnicos especializados
# ---------------------------------------------------------------------------
CENARIO_D = {
    "id": "D",
    "titulo": "Serviços técnicos especializados de assessoria contábil",
    "dados": {
        "orgao": "Prefeitura Municipal de Vila Nova do Norte — Secretaria "
                 "Municipal de Fazenda",
        "responsavel": "Secretário Municipal de Fazenda",
        "objeto": "Contratação de serviços técnicos especializados de "
                  "assessoria e consultoria contábil para implantação do "
                  "novo plano de contas e apoio à prestação de contas anual.",
        "justificativa": "A implantação do novo plano de contas exige "
                         "conhecimento técnico especializado de que o quadro "
                         "próprio não dispõe, e o descumprimento do prazo de "
                         "prestação de contas sujeita o Município a sanções.",
        "alinhamento": "Item 7 do Plano de Contratações Anual de 2026.",
        "requisitos": "Equipe técnica com contador registrado no conselho "
                      "profissional e experiência comprovada em contabilidade "
                      "aplicada ao setor público.",
        "modelo_execucao": "Serviço por escopo (execução única)",
        "prazo": "Execução em até 8 (oito) meses.",
        "riscos": "Substituição de profissional-chave durante a execução; "
                  "atraso na entrega dos produtos com impacto no prazo legal "
                  "da prestação de contas.",
        "itens": _itens(
            ("80501", "Diagnóstico e plano de implantação do novo plano de "
                      "contas", "SERVIÇO", 1, 78500.00),
            ("80502", "Capacitação da equipe contábil, 40 horas-aula",
             "HORA-AULA", 40, 610.00),
        ),
    },
    "esperado": {
        "documentos": ("dfd", "etp", "mapa_riscos", "tr", "edital"),
        "arp": False,
        "itens": 2,
    },
    "criterio": "A estrutura se adapta a serviço: nada de cláusula de "
                "recebimento de material ou de garantia de produto "
                "transplantada de aquisição.",
}


# ---------------------------------------------------------------------------
# E — Sistema de Registro de Preços
# ---------------------------------------------------------------------------
CENARIO_E = {
    "id": "E",
    "titulo": "Fornecimento por Sistema de Registro de Preços",
    "dados": {
        "orgao": "Prefeitura Municipal de Vila Nova do Norte — Secretaria "
                 "Municipal de Saúde",
        "responsavel": "Diretor do Departamento de Assistência Farmacêutica",
        "objeto": "Registro de preços para eventual aquisição de material "
                  "médico-hospitalar de consumo para a rede de atenção "
                  "básica, pelo prazo de 12 (doze) meses.",
        "justificativa": "O consumo de material médico-hospitalar oscila com "
                         "a demanda sazonal das unidades de saúde, e a "
                         "aquisição integral antecipada geraria perda por "
                         "validade e custo de armazenagem.",
        "alinhamento": "Item 31 do Plano de Contratações Anual de 2026.",
        "requisitos": "Produtos registrados na autoridade sanitária "
                      "competente, com prazo de validade não inferior a 18 "
                      "meses na data da entrega.",
        "modelo_execucao": "Sistema de Registro de Preços (SRP)",
        "prazo": "Ata com vigência de 12 meses.",
        "riscos": "Registro de quantidade muito superior ao consumo efetivo; "
                  "adesão de órgãos não participantes acima do permitido.",
        "itens": _itens(
            ("30201", "Seringa descartável 5 ml, com agulha 25x7 mm",
             "UN", 40000, 0.68),
            ("30202", "Luva de procedimento não cirúrgico, tamanho M, "
                      "caixa com 100 unidades", "CX", 3000, 29.40),
            ("30203", "Compressa de gaze 7,5 x 7,5 cm, pacote com 500",
             "PCT", 1200, 18.75),
            ("30204", "Álcool etílico 70% solução, frasco de 1 litro",
             "FR", 2500, 9.80),
        ),
    },
    "esperado": {
        "documentos": ("dfd", "etp", "mapa_riscos", "tr", "edital"),
        "arp": True,
        "itens": 4,
    },
    "criterio": "O Edital traz a Ata de Registro de Preços; a vigência da "
                "Ata é citada com lastro (art. 84) e não inventada.",
}


# ---------------------------------------------------------------------------
# F — poucos itens
# ---------------------------------------------------------------------------
CENARIO_F = {
    "id": "F",
    "titulo": "Aquisição com poucos itens",
    "dados": {
        "orgao": "Prefeitura Municipal de Vila Nova do Norte — Gabinete do "
                 "Prefeito",
        "responsavel": "Chefe de Gabinete",
        "objeto": "Aquisição de 1 (uma) motocicleta 160 cilindradas para o "
                  "serviço de entrega de documentos entre as secretarias.",
        "justificativa": "O trâmite físico de documentos entre as sete "
                         "secretarias é feito hoje por veículo de quatro "
                         "rodas, com custo de combustível desproporcional ao "
                         "volume transportado.",
        "modelo_execucao": "Entrega única (fornecimento integral)",
        "itens": _itens(
            ("60701", "Motocicleta 160 cc, partida elétrica, freio a disco "
                      "dianteiro, cor branca", "UN", 1, 18900.00),
        ),
    },
    "esperado": {
        "documentos": ("dfd", "etp", "mapa_riscos", "tr", "edital"),
        "arp": False,
        "itens": 1,
    },
    "criterio": "Nenhuma tabela, seção ou lote inventado para 'encher' o "
                "documento: um item continua sendo um item.",
}


# ---------------------------------------------------------------------------
# G — planilha extensa (estresse)
# ---------------------------------------------------------------------------
def _caso_210() -> dict:
    return json.loads((FIXTURES / "caso_210_itens.json").read_text())


def cenario_g() -> dict:
    """
    Os 210 itens do caso de referência já versionado.

    Construído por função, e não por constante, porque carregar 210
    linhas na importação faria todo teste que só precisa do cenário F
    pagar por elas.
    """
    caso = _caso_210()
    return {
        "id": "G",
        "titulo": "Processo com planilha extensa (210 itens)",
        "dados": {
            "orgao": "Prefeitura Municipal de Vila Nova do Norte — Secretaria "
                     "Municipal de Administração",
            "responsavel": "Diretor do Departamento de Compras",
            "objeto": caso["objeto"],
            "justificativa": "Reposição anual do estoque do almoxarifado "
                             "central, que abastece as sete secretarias e as "
                             "doze unidades escolares do Município.",
            "modelo_execucao": "Entrega parcelada",
            "itens": caso["itens"],
        },
        "esperado": {
            "documentos": ("dfd", "etp", "mapa_riscos", "tr", "edital"),
            "arp": False,
            "itens": len(caso["itens"]),
        },
        "criterio": "Os 210 códigos saem inteiros no DOCX e no PDF — nenhum "
                    "partido entre páginas, nenhum ausente.",
    }


# ---------------------------------------------------------------------------
# H — informações incompletas
# ---------------------------------------------------------------------------
CENARIO_H = {
    "id": "H",
    "titulo": "Processo com informações incompletas",
    "dados": {
        "orgao": "Prefeitura Municipal de Vila Nova do Norte",
        "objeto": "Aquisição de materiais diversos.",
        "justificativa": "Necessidade da administração.",
        "modelo_execucao": "Entrega única (fornecimento integral)",
        "itens": _itens(
            ("", "Material diverso", "UN", 10, 0.0),
        ),
        # sem responsavel, sem alinhamento, sem requisitos, sem prazo,
        # sem riscos, sem valor unitário: é o processo que chega pela
        # metade, e é o mais comum de todos.
    },
    "esperado": {
        "documentos": ("dfd", "etp", "mapa_riscos", "tr", "edital"),
        "arp": False,
        "itens": 1,
        "valor_global": 0.0,
    },
    "criterio": "O sistema APONTA as pendências. Um campo ausente não pode "
                "virar fato afirmado no documento, e valor zero não pode "
                "virar estimativa.",
}


TODOS = (CENARIO_A, CENARIO_B, CENARIO_C, CENARIO_D, CENARIO_E,
         CENARIO_F, CENARIO_H)


def todos_com_g() -> tuple[dict, ...]:
    """A + … + H, com o cenário de estresse. Use quando ele for necessário."""
    return TODOS[:6] + (cenario_g(), CENARIO_H)


def valor_global_esperado(cenario: dict) -> float:
    """
    A soma das linhas, calculada AQUI e não copiada do sistema.

    Se o número viesse de `planilha.calcular`, a prova compararia o
    sistema consigo mesmo e passaria com a aritmética errada.
    """
    return round(sum(i["quantidade"] * i["valor_unitario"]
                     for i in cenario["dados"]["itens"]), 2)
