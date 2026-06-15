#!/usr/bin/env python3
"""
script.py — GAM Farma: Processador da planilha Google Sheets -> index.html
============================================================================
Lê o CSV publicado do Google Sheets, processa todas as colunas e linhas,
e injeta os dados como EMBEDDED_ROWS no index.html (fallback offline).

Executa automaticamente via GitHub Actions (deploy.yml).
Arquivo de saída: index.html (sobrescreve o existente)
"""

import csv
import json
import re
import sys
import unicodedata
import urllib.request
from datetime import datetime, timezone

# ─────────────────────────────────────────────────────────────
# CONFIGURAÇÃO
# ─────────────────────────────────────────────────────────────
CSV_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vQJRPejEYUGjqFiruPTGJuS2Itk6qjvyk6moB4_"
    "ChCe5_z4_CW0jYcYXJFimYYw4kGcbP2fpdRccLkq/pub?output=csv"
)
INDEX_FILE = "index.html"

# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def normalize_header(h: str) -> str:
    """Remove acentos, normaliza para UPPER e padroniza nomes de colunas."""
    s = unicodedata.normalize("NFD", h)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.upper().strip()
    s = s.replace("COORPORATIVO", "CORPORATIVO").replace("COODENADOR", "COORDENADOR")
    # Mapeamentos conhecidos
    aliases = {
        "NOME REPRESENTANTE": "NOME",
        "NOME COLABORADOR": "NOME",
        "FUNCAO": "FUNCAO",
        "FUNÇÃO": "FUNCAO",
        "REGIAO": "REGIAO",
        "REGIÃO": "REGIAO",
        "CONTATO CORPORATIVO": "CONTATO CORPORATIVO",
        "CONTATO COORPORATIVO": "CONTATO CORPORATIVO",
        "PRINCIPAIS CIDADES": "PRINCIPAIS CIDADES",
        "RAZAO SOCIAL": "RAZAO SOCIAL",
        "EMAIL COORDENADOR": "EMAIL COORDENADOR",  # ignorado na lógica
    }
    for original, mapped in aliases.items():
        if s == original:
            return mapped
    if "RAZAO" in s and "SOCIAL" in s:
        return "RAZAO SOCIAL"
    return s


def find_header_row(lines: list[str]) -> tuple[int, str]:
    """Localiza a linha do cabeçalho e retorna (índice, data_atualizacao)."""
    update_date = ""
    for i, line in enumerate(lines):
        upper = line.upper()
        if "DISTRITO" in upper and ("NOME" in upper or "REPRESENTANTE" in upper):
            return i, update_date
        m = re.search(r"\d{2}/\d{2}/\d{4}", line)
        if m:
            update_date = m.group(0)
    return -1, update_date


def parse_csv_text(text: str) -> tuple[list[dict], str]:
    """Parseia o CSV em lista de dicts com chaves normalizadas."""
    lines = text.splitlines()
    header_idx, update_date = find_header_row(lines)
    if header_idx == -1:
        print("AVISO: Cabeçalho não encontrado no CSV.")
        return [], update_date

    raw_headers = next(csv.reader([lines[header_idx]]))
    headers = [normalize_header(h) for h in raw_headers]

    rows = []
    reader = csv.reader(lines[header_idx + 1 :])
    for cells in reader:
        row = {headers[i]: (cells[i].strip() if i < len(cells) else "") for i in range(len(headers))}
        nome = row.get("NOME", "").strip()
        if not nome:
            continue
        # Ignorar colunas irrelevantes antes de salvar
        row.pop("COORDENADOR", None)          # coluna de coordenador ignorada conforme solicitado
        row.pop("EMAIL COORDENADOR", None)    # coluna email coordenador ignorada
        rows.append(row)

    return rows, update_date


def validate_rows(rows: list[dict]) -> None:
    """Valida integridade mínima das linhas e imprime sumário."""
    coord_count = sum(
        1 for r in rows
        if "COORDENADOR EQUIPE" in r.get("FUNCAO", "").upper()
        or "COORDENADOR DE EQUIPE" in r.get("FUNCAO", "").upper()
    )
    rep_count = sum(1 for r in rows if "REPRESENTANTE COMERCIAL" in r.get("FUNCAO", "").lower())
    cv_count  = sum(1 for r in rows if "CONSULTOR DE VENDAS" in r.get("FUNCAO", "").lower())
    ded_count = sum(1 for r in rows if "DEDICADO" in r.get("FUNCAO", "").upper())
    ger_count = sum(1 for r in rows if "GERENTE DE CONTAS" in r.get("FUNCAO", "").lower())
    med_count = sum(1 for r in rows if "MEDIAS REDES" in r.get("FUNCAO", "").upper() or "MÉDIAS REDES" in r.get("FUNCAO", "").upper())
    gpe_count = sum(1 for r in rows if "PROJETOS ESPECIAIS" in r.get("FUNCAO", "").upper())

    print(f"  Total de linhas lidas:        {len(rows)}")
    print(f"  Coordenadores de Equipe:      {coord_count}")
    print(f"  Representantes Comerciais:    {rep_count}")
    print(f"  Consultores de Vendas:        {cv_count}")
    print(f"  Dedicados:                    {ded_count}")
    print(f"  Gerentes de Contas:           {ger_count}")
    print(f"  Coord. Médias Redes:          {med_count}")
    print(f"  Ger. Projetos Especiais:      {gpe_count}")

    # Avisos sobre campos essenciais ausentes
    for r in rows:
        nome = r.get("NOME", "")
        if not r.get("CONTATO CORPORATIVO"):
            pass  # Pode ser esperado para alguns
        if not r.get("EMAIL"):
            pass  # Pode ser esperado para alguns


def inject_into_html(rows: list[dict], update_date: str, html_path: str) -> None:
    """Injeta EMBEDDED_ROWS e EMBEDDED_DATE no index.html como fallback."""
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()

    rows_json = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    date_json = json.dumps(update_date, ensure_ascii=False)

    # Substituir EMBEDDED_ROWS
    content = re.sub(
        r"const EMBEDDED_ROWS\s*=\s*\[.*?\];",
        f"const EMBEDDED_ROWS = {rows_json};",
        content,
        flags=re.DOTALL,
    )
    # Substituir EMBEDDED_DATE
    content = re.sub(
        r"const EMBEDDED_DATE\s*=\s*'.*?';",
        f"const EMBEDDED_DATE = {date_json};",
        content,
    )

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"  {html_path} atualizado com {len(rows)} registros embarcados.")


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def main() -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n{'='*60}")
    print(f"  GAM Farma — Processador de Planilha")
    print(f"  Execução: {now}")
    print(f"{'='*60}\n")

    # 1. Baixar CSV
    print(f"[1/4] Baixando planilha de: {CSV_URL[:80]}…")
    cache_bust = f"&cb={int(datetime.now(timezone.utc).timestamp())}"
    url = CSV_URL + cache_bust
    try:
        req = urllib.request.Request(
            url,
            headers={
                "Cache-Control": "no-cache, no-store",
                "Pragma": "no-cache",
                "User-Agent": "GAMFarma-Script/1.0",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            text = resp.read().decode("utf-8")
        print(f"  Download OK ({len(text):,} bytes)")
    except Exception as e:
        print(f"  ERRO ao baixar planilha: {e}")
        sys.exit(1)

    # 2. Parsear CSV
    print("\n[2/4] Parseando CSV…")
    rows, update_date = parse_csv_text(text)
    if not rows:
        print("  ERRO: Nenhuma linha válida encontrada.")
        sys.exit(1)
    print(f"  Data de atualização da planilha: {update_date or 'não encontrada'}")

    # 3. Validar dados
    print("\n[3/4] Validando dados…")
    validate_rows(rows)

    # 4. Injetar no HTML
    print(f"\n[4/4] Injetando dados em {INDEX_FILE}…")
    try:
        inject_into_html(rows, update_date, INDEX_FILE)
    except FileNotFoundError:
        print(f"  AVISO: {INDEX_FILE} não encontrado. Apenas validação realizada.")

    print(f"\n{'='*60}")
    print("  Concluído com sucesso!")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
