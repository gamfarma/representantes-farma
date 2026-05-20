#!/usr/bin/env python3
"""
script.py — GAM Farma Rede de Representantes
Lê a planilha do Google Sheets, processa os dados e injeta no index.html
como EMBEDDED_ROWS para carregamento instantâneo.

Variáveis importantes detectadas automaticamente pela planilha:
  - DISTRITO, SETOR, REGIÃO, UF, PRINCIPAIS CIDADES
  - FUNÇÃO (identifica: COORDENADOR EQUIPE, Representante Comercial,
            Consultor de Vendas, Gerente de Contas, Coordenador de Contas - Médias Redes,
            GERENTE DE PROJETOS ESPECIAIS, Dedicados)
  - NOME REPRESENTANTE, RAZÃO SOCIAL (Representantes Comerciais)
  - CONTATO COORPORATIVO (telefone), EMAIL
  - COODENADOR (coluna auxiliar — NÃO usada para definir equipes, apenas como fallback)

Correções aplicadas automaticamente:
  - Glaucia Cardoso Belo → equipe de Lucas Acyole Rodrigues
  - TLV → Televendas
  - EXPANSÃO → apenas MS e SP (sem forçar GO/DF/MT)
  - Sem abreviações de função
"""

import requests
import json
import re
import csv
import io
import unicodedata
from datetime import datetime

# ─────────────────────────────────────────────
# CONFIGURAÇÕES
# ─────────────────────────────────────────────
CSV_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vQJRPejEYUGjqFiruPTGJuS2Itk6qjvyk6moB4_ChCe5_z4_CW0jYcYXJFimYYw4kGcbP2fpdRccLkq"
    "/pub?output=csv"
)
INDEX_FILE = "index.html"

# ─────────────────────────────────────────────
# NORMALIZAÇÃO DE CABEÇALHOS
# ─────────────────────────────────────────────
def normalize_header(h: str) -> str:
    """Remove acentos, normaliza para maiúsculas e corrige typos conhecidos."""
    s = unicodedata.normalize("NFD", h or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.upper().strip()
    # Typos conhecidos na planilha
    s = s.replace("COORPORATIVO", "CORPORATIVO")
    s = s.replace("COODENADOR", "COORDENADOR")
    s = s.replace("RAZAO SOCIAL", "RAZAO SOCIAL")  # já correto sem acento
    if s == "NOME REPRESENTANTE":
        s = "NOME"
    return s


# ─────────────────────────────────────────────
# HELPERS DE CAMPO
# ─────────────────────────────────────────────
def get_func(row: dict) -> str:
    return row.get("FUNCAO") or row.get("FUNÇÃO") or ""

def get_nome(row: dict) -> str:
    return row.get("NOME") or ""

def get_uf(row: dict) -> str:
    return (row.get("UF") or "").strip()

def get_regiao(row: dict) -> str:
    return row.get("REGIAO") or row.get("REGIÃO") or ""

def get_contato(row: dict) -> str:
    return row.get("CONTATO CORPORATIVO") or row.get("CONTATO COORPORATIVO") or ""

def get_email(row: dict) -> str:
    return row.get("EMAIL") or ""

def get_cidades(row: dict) -> str:
    return row.get("PRINCIPAIS CIDADES") or ""

def get_razao(row: dict) -> str:
    return row.get("RAZAO SOCIAL") or ""

def get_distrito(row: dict) -> str:
    return str(row.get("DISTRITO") or "").strip()

def get_setor(row: dict) -> str:
    return str(row.get("SETOR") or "").strip()

def is_coord_equipe(row: dict) -> bool:
    return "COORDENADOR EQUIPE" in get_func(row).upper() or "COORDENADOR DE EQUIPE" in get_func(row).upper()

def is_gerente_proj(row: dict) -> bool:
    return "GERENTE DE PROJETOS ESPECIAIS" in get_func(row).upper()

def is_dedicado(row: dict) -> bool:
    return "DEDICADO" in get_func(row).upper()

def is_gerente_contas(row: dict) -> bool:
    return "GERENTE DE CONTAS" in get_func(row).lower()

def is_coord_contas(row: dict) -> bool:
    f = get_func(row).lower()
    return "coordenador de contas" in f or "medias redes" in f or "médias redes" in f

def is_rep_comercial(row: dict) -> bool:
    return "representante comercial" in get_func(row).lower()

def is_consultor(row: dict) -> bool:
    return "consultor de vendas" in get_func(row).lower()

def parse_ufs(uf_str: str) -> list:
    """Extrai siglas de estado (2 letras) de uma string."""
    if not uf_str or uf_str.strip() in ("-", "EXPANSÃO", "EXPANS"):
        return []
    return [
        s.strip().upper()
        for s in re.split(r"[/\-,\s]+", uf_str)
        if len(s.strip()) == 2 and re.match(r"^[A-Z]{2}$", s.strip().upper())
    ]


# ─────────────────────────────────────────────
# BUSCA E PARSE DO CSV
# ─────────────────────────────────────────────
def fetch_csv(url: str = CSV_URL) -> str:
    """Baixa o CSV do Google Sheets com cache-busting."""
    cb = datetime.now().strftime("%Y%m%d%H%M%S")
    resp = requests.get(f"{url}&cb={cb}", timeout=30)
    resp.raise_for_status()
    return resp.text


def parse_csv(text: str):
    """
    Detecta a linha de cabeçalho automaticamente (procura por DISTRITO + NOME/REPRESENTANTE),
    retorna (rows: list[dict], update_date: str).
    Funciona mesmo se novas colunas forem adicionadas à planilha.
    """
    lines = text.splitlines()
    header_idx = -1
    update_date = ""

    for i, line in enumerate(lines):
        upper = line.upper()
        if "DISTRITO" in upper and ("NOME" in upper or "REPRESENTANTE" in upper):
            header_idx = i
            break
        m = re.search(r"\d{2}/\d{2}/\d{4}", line)
        if m and not update_date:
            update_date = m.group(0)

    if header_idx == -1:
        raise ValueError("Linha de cabeçalho não encontrada no CSV (esperava DISTRITO + NOME/REPRESENTANTE).")

    reader = csv.DictReader(io.StringIO("\n".join(lines[header_idx:])))
    rows = []
    for raw in reader:
        normalized = {normalize_header(k): v.strip() for k, v in raw.items() if k is not None}
        if normalized.get("NOME"):
            rows.append(normalized)

    print(f"  Planilha: {len(rows)} linhas de dados encontradas")
    print(f"  Colunas detectadas: {list(rows[0].keys()) if rows else []}")
    return rows, update_date


# ─────────────────────────────────────────────
# CORREÇÕES ESPECIAIS DE DADOS
# ─────────────────────────────────────────────
def apply_data_corrections(rows: list) -> list:
    """
    Aplica correções de dados que não podem ser resolvidas puramente
    pela lógica de distritos/funções.
    """
    for r in rows:
        nome_up = get_nome(r).strip().upper()

        # Glaucia Cardoso Belo pertence à equipe de Lucas Acyole Rodrigues (não Marcos de Bem)
        if "GLAUCIA" in nome_up and "CARDOSO" in nome_up:
            r["COORDENADOR"] = "LUCAS ACYOLE RODRIGUES"
            print(f"  Correção aplicada: {get_nome(r)} → Lucas Acyole Rodrigues")

        # Normalizar TLV → Televendas na coluna REGIÃO
        regiao = get_regiao(r)
        if regiao.strip().upper() == "TLV":
            r["REGIAO"] = "Televendas"
            r["REGIÃO"] = "Televendas"

    return rows


# ─────────────────────────────────────────────
# INJEÇÃO NO index.html
# ─────────────────────────────────────────────
def update_index_html(rows: list, update_date: str, filename: str = INDEX_FILE):
    """
    Injeta os dados do Google Sheets em index.html como EMBEDDED_ROWS.
    O HTML carrega os dados instantaneamente na abertura e ainda faz
    auto-refresh a cada 5 min para pegar eventuais atualizações.
    """
    with open(filename, "r", encoding="utf-8") as f:
        content = f.read()

    rows_json = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    date_str = update_date or datetime.now().strftime("%d/%m/%Y")

    # Substitui EMBEDDED_ROWS (pode ter qualquer conteúdo anterior)
    content = re.sub(
        r"const EMBEDDED_ROWS = \[.*?\];",
        f"const EMBEDDED_ROWS = {rows_json};",
        content,
        flags=re.DOTALL,
    )

    # Substitui EMBEDDED_DATE
    content = re.sub(
        r"const EMBEDDED_DATE = '.*?';",
        f"const EMBEDDED_DATE = '{date_str}';",
        content,
    )

    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"  index.html atualizado: {len(rows)} registros, data {date_str}")


# ─────────────────────────────────────────────
# VALIDAÇÃO BÁSICA
# ─────────────────────────────────────────────
def validate_rows(rows: list):
    """Imprime um resumo dos dados para validação no log do GitHub Actions."""
    funcs = {}
    ufs = set()
    for r in rows:
        f = get_func(r)
        funcs[f] = funcs.get(f, 0) + 1
        for uf in parse_ufs(get_uf(r)):
            ufs.add(uf)

    print("\n  Resumo por FUNÇÃO:")
    for f, count in sorted(funcs.items()):
        print(f"    {count:3d}x  {f}")

    print(f"\n  Estados cobertos: {sorted(ufs)}")

    coords = [r for r in rows if is_coord_equipe(r)]
    print(f"\n  Coordenadores de Equipe ({len(coords)}):")
    for c in coords:
        print(f"    • {get_nome(c)} — {get_regiao(c)} ({get_uf(c)})")

    gerentes = [r for r in rows if is_gerente_proj(r)]
    for g in gerentes:
        print(f"  Gerente de Projetos Especiais: {get_nome(g)} ({get_uf(g)})")

    gc = [r for r in rows if is_gerente_contas(r)]
    print(f"\n  Gerentes de Contas ({len(gc)}):")
    for g in gc:
        print(f"    • {get_nome(g)} — {get_regiao(g)} ({get_uf(g)})")

    cc = [r for r in rows if is_coord_contas(r)]
    print(f"\n  Coordenadores de Médias Redes ({len(cc)}):")
    for c in cc:
        print(f"    • {get_nome(c)} — {get_regiao(c)} ({get_uf(c)})")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    print("=" * 60)
    print("GAM Farma — Atualização do Diretório")
    print(f"Executado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print("=" * 60)

    print("\n[1/4] Buscando planilha do Google Sheets...")
    csv_text = fetch_csv()

    print("\n[2/4] Processando CSV...")
    rows, update_date = parse_csv(csv_text)

    print("\n[3/4] Aplicando correções de dados...")
    rows = apply_data_corrections(rows)
    validate_rows(rows)

    print("\n[4/4] Injetando dados em index.html...")
    update_index_html(rows, update_date)

    print("\n✅ Concluído com sucesso!")


if __name__ == "__main__":
    main()
