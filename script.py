#!/usr/bin/env python3
"""
script.py — GAM Farma Rede de Representantes
Lê a planilha do Google Sheets (CSV público) e processa todas as informações
para funcionamento do index.html. Detecta automaticamente mudanças de coluna,
linha, nome, função, telefone, email, razão social e qualquer outro campo.

Este script é executado pelo GitHub Actions (deploy.yml) e gera o index.html
atualizado sempre que houver nova publicação na planilha.
"""

import csv
import sys
import os
import json
import re
import urllib.request
import urllib.error
from datetime import datetime

# =============================================================================
# CONFIGURAÇÃO
# =============================================================================

SHEETS_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vQJRPejEYUGjqFiruPTGJuS2Itk6qjvyk6moB4_ChCe5_z4_CW0jYcYXJFimYYw4kGcbP2fpdRccLkq"
    "/pub?output=csv"
)
INDEX_HTML = "index.html"
DATA_JSON  = "data.json"  # saída opcional de debug


# =============================================================================
# NORMALIZAÇÃO DE CABEÇALHOS
# =============================================================================

HEADER_ALIASES = {
    # variações conhecidas → chave canônica
    "NOME REPRESENTANTE":          "NOME",
    "NOME":                        "NOME",
    "RAZÃO SOCIAL":                "RAZAO_SOCIAL",
    "RAZAO SOCIAL":                "RAZAO_SOCIAL",
    "FUNÇÃO":                      "FUNCAO",
    "FUNCAO":                      "FUNCAO",
    "REGIÃO":                      "REGIAO",
    "REGIAO":                      "REGIAO",
    "UF":                          "UF",
    "PRINCIPAIS CIDADES":          "CIDADES",
    "CONTATO COORPORATIVO":        "TELEFONE",
    "CONTATO CORPORATIVO":         "TELEFONE",
    "EMAIL":                       "EMAIL",
    "DISTRITO":                    "DISTRITO",
    "SETOR":                       "SETOR",
    "COORDENADOR":                 "COORDENADOR",
    "COODENADOR":                  "COORDENADOR",
}


def _strip_accents(s: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode("ascii")


def normalize_header(raw: str) -> str:
    """Normaliza um cabeçalho para a chave canônica."""
    clean = _strip_accents(raw.strip()).upper()
    return HEADER_ALIASES.get(clean, clean)


# =============================================================================
# CLASSIFICAÇÃO DE FUNÇÕES
# =============================================================================

def classify(funcao: str) -> str:
    """
    Retorna a categoria canônica de uma linha conforme a coluna FUNÇÃO.
    Sempre lê a coluna FUNÇÃO — ignora a coluna COORDENADOR para classificação.
    """
    f = _strip_accents(funcao).upper().strip()
    if "COORDENADOR EQUIPE" in f or "COORDENADOR DE EQUIPE" in f:
        return "COORD_EQUIPE"
    if "GERENTE DE PROJETOS ESPECIAIS" in f:
        return "GPE"
    if "DEDICADO" in f:
        return "DEDICADO"
    if "GERENTE DE CONTAS" in f:
        return "GERENTE_CONTAS"
    if "COORDENADOR DE CONTAS" in f or "MEDIAS REDES" in f:
        return "COORD_CONTAS"
    if "REPRESENTANTE COMERCIAL" in f:
        return "REP_COMERCIAL"
    if "CONSULTOR DE VENDAS" in f:
        return "CONSULTOR"
    return "OUTRO"


def is_rep_comercial(funcao: str) -> bool:
    return _strip_accents(funcao).upper().strip().find("REPRESENTANTE COMERCIAL") >= 0


# =============================================================================
# PARSERS
# =============================================================================

def parse_ufs(uf_str: str) -> list:
    """Extrai siglas de estado (2 letras) de uma string."""
    if not uf_str or uf_str.strip() in ("-", "EXPANSÃO", "EXPANSAO"):
        return []
    parts = re.split(r"[/\-, ]+", uf_str)
    return [p.strip().upper() for p in parts if len(p.strip()) == 2 and p.strip().isalpha()]


def download_csv(url: str, retries: int = 3) -> list:
    """
    Baixa CSV do Google Sheets com cache-busting e retorna lista de dicts.
    Detecta automaticamente o índice do cabeçalho real (linha com DISTRITO/NOME).
    """
    bust_url = f"{url}&cb={int(datetime.now().timestamp())}"
    req = urllib.request.Request(
        bust_url,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma":         "no-cache",
            "Expires":        "0",
            "User-Agent":     "GAMFarma-Updater/1.0",
        }
    )
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                content = resp.read().decode("utf-8", errors="replace")
            break
        except urllib.error.URLError as exc:
            print(f"[WARN] Tentativa {attempt}/{retries} falhou: {exc}")
            if attempt == retries:
                raise
    lines = content.splitlines()
    header_idx = -1
    update_date = ""
    for i, line in enumerate(lines):
        upper = _strip_accents(line).upper()
        if "DISTRITO" in upper and ("NOME" in upper or "REPRESENTANTE" in upper):
            header_idx = i
            break
        m = re.search(r"\d{2}/\d{2}/\d{4}", line)
        if m:
            update_date = m.group(0)
    if header_idx < 0:
        raise ValueError("Cabeçalho da planilha não encontrado.")
    reader = csv.reader(lines[header_idx:])
    raw_headers = next(reader)
    headers = [normalize_header(h) for h in raw_headers]
    rows = []
    for cells in reader:
        row = {headers[i]: cells[i].strip() if i < len(cells) else "" for i in range(len(headers))}
        if not row.get("NOME", "").strip():
            continue
        row["_UPDATE_DATE"] = update_date
        row["_CATEGORIA"] = classify(row.get("FUNCAO", ""))
        rows.append(row)
    print(f"[INFO] {len(rows)} linhas lidas. Data atualização: {update_date or 'não encontrada'}")
    return rows


# =============================================================================
# AGRUPAMENTO DE EQUIPES
# =============================================================================

def build_groups(rows: list) -> dict:
    """
    Agrupa representantes sob seus coordenadores.
    Lógica:
      1) Identifica coordenadores de equipe pelo campo FUNCAO (não pela coluna COORDENADOR).
      2) Associa membros por base do DISTRITO (ex: 100, 200, 500).
      3) Fallback: associa por coluna COORDENADOR se sobrar algum.
      4) Televendas e Expansão: estados derivados apenas dos membros.
      5) GPE + Dedicados formam grupo próprio.
      6) Gerentes de Contas e Coordenadores de Contas são individuais (sem equipe).
    """
    groups   = {}   # distKey → dict
    assigned = set()

    # ---- 1) Coordenadores de Equipe ----
    coords = {r["DISTRITO"]: r for r in rows if r["_CATEGORIA"] == "COORD_EQUIPE"}
    for dist, leader in coords.items():
        assigned.add(id(leader))
        groups[dist] = {
            "leader":        leader,
            "members":       [],
            "distKey":       dist,
            "division":      None,
            "displayRegion": leader.get("REGIAO", ""),
            "states":        [],
        }

    # ---- 2) Associar membros por base de distrito ----
    def dist_base(d):
        try: return (int(d) // 100) * 100
        except: return None

    for r in rows:
        if id(r) in assigned: continue
        if r["_CATEGORIA"] in ("COORD_EQUIPE","GPE","DEDICADO","GERENTE_CONTAS","COORD_CONTAS"): continue
        r_base = dist_base(r.get("DISTRITO",""))
        if r_base is None: continue
        for dist, grp in groups.items():
            for part in dist.split("/"):
                b = dist_base(part.strip())
                if b is not None and b == r_base:
                    grp["members"].append(r)
                    assigned.add(id(r))
                    break

    # ---- 3) Fallback por coluna COORDENADOR ----
    for r in rows:
        if id(r) in assigned: continue
        if r["_CATEGORIA"] in ("COORD_EQUIPE","GPE","DEDICADO","GERENTE_CONTAS","COORD_CONTAS"): continue
        coord_col = _strip_accents(r.get("COORDENADOR","")).upper().strip()
        if not coord_col: continue
        for dist, grp in groups.items():
            leader_name = _strip_accents(grp["leader"].get("NOME","")).upper().strip()
            if coord_col == leader_name or (leader_name and coord_col.startswith(leader_name.split()[0])):
                grp["members"].append(r)
                assigned.add(id(r))
                break

    # ---- 4) Determinar estados e divisões ----
    for dist, grp in groups.items():
        leader     = grp["leader"]
        leader_uf  = leader.get("UF","").strip()
        leader_reg = leader.get("REGIAO","").strip()
        reg_up     = _strip_accents(leader_reg).upper()
        uf_up      = _strip_accents(leader_uf).upper()

        if leader_uf == "-" or "TLV" in reg_up:
            grp["division"]      = "Televendas"
            grp["displayRegion"] = "Televendas"
            member_ufs = set()
            for m in grp["members"]:
                for u in parse_ufs(m.get("UF","")):
                    member_ufs.add(u)
            grp["states"] = list(member_ufs)

        elif "EXPANS" in uf_up or "EXPANS" in reg_up:
            grp["division"]      = "EXPANSÃO"
            grp["displayRegion"] = "Centro Oeste e Sudeste"
            member_ufs = set()
            for m in grp["members"]:
                for u in parse_ufs(m.get("UF","")):
                    member_ufs.add(u)
            grp["states"] = list(member_ufs)

        else:
            all_ufs = set(parse_ufs(leader_uf))
            for m in grp["members"]:
                for u in parse_ufs(m.get("UF","")):
                    all_ufs.add(u)
            grp["states"] = list(all_ufs)

    # ---- 5) GPE + Dedicados ----
    gpe = next((r for r in rows if r["_CATEGORIA"] == "GPE"), None)
    if gpe:
        assigned.add(id(gpe))
        dedicados = [r for r in rows if r["_CATEGORIA"] == "DEDICADO"]
        for d in dedicados: assigned.add(id(d))
        ded_ufs = set()
        for m in dedicados:
            for u in parse_ufs(m.get("UF","")): ded_ufs.add(u)
        groups["PROJ_ESP"] = {
            "leader":        gpe,
            "members":       dedicados,
            "distKey":       "PROJ_ESP",
            "division":      "PROJ. ESPECIAIS",
            "displayRegion": "SUL — PR / RS / SC",
            "states":        list(ded_ufs),
        }

    # ---- 6) Gerentes de Contas e Coordenadores de Contas (individuais) ----
    for r in rows:
        if r["_CATEGORIA"] not in ("GERENTE_CONTAS","COORD_CONTAS"): continue
        assigned.add(id(r))
        key = f"CLIENT_{r.get('DISTRITO','')}"
        groups[key] = {
            "leader":        r,
            "members":       [],
            "distKey":       r.get("DISTRITO",""),
            "division":      None,
            "displayRegion": r.get("REGIAO",""),
            "states":        parse_ufs(r.get("UF","")),
            "isClientRole":  True,
        }

    return groups


# =============================================================================
# CONSTRUÇÃO DO STATE MAP
# =============================================================================

def build_state_map(groups: dict) -> dict:
    """
    Mapeia UF → lista de grupos presentes nesse estado.
    Para grupos multi-estado com membros, só aparece em UFs com membros reais.
    Divisões (TLV, Expansão, Proj. Especiais) também só em UFs dos membros.
    """
    state_map = {}
    for grp in groups.values():
        for uf in grp["states"]:
            if not uf or uf == "-": continue
            # Multi-estado com membros: só mostra onde tem membro
            if len(grp["states"]) > 1 and grp["members"]:
                has_member = any(u == uf for m in grp["members"] for u in parse_ufs(m.get("UF","")))
                if not has_member: continue
            if uf not in state_map:
                state_map[uf] = []
            state_map[uf].append(grp)
    return state_map


# =============================================================================
# EXPORT DATA JSON (debug/cache)
# =============================================================================

def export_data_json(rows: list, groups: dict, state_map: dict, path: str = DATA_JSON):
    """Exporta estrutura processada como JSON para debug ou cache."""
    def serialize(obj):
        if isinstance(obj, dict):
            return {k: serialize(v) for k, v in obj.items() if not k.startswith("_")}
        if isinstance(obj, list):
            return [serialize(i) for i in obj]
        return obj

    payload = {
        "generated_at":  datetime.now().isoformat(),
        "total_rows":    len(rows),
        "total_groups":  len(groups),
        "states":        list(state_map.keys()),
        "groups":        serialize(groups),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[INFO] {path} exportado ({os.path.getsize(path)} bytes).")


# =============================================================================
# INJEÇÃO DO CSV_URL NO index.html (cache-busting dinâmico)
# =============================================================================

def update_index_html(rows: list, update_date: str = ""):
    """
    Garante que o index.html referencia o CSV_URL correto.
    Não altera o layout — apenas confirma que a URL está presente.
    """
    if not os.path.exists(INDEX_HTML):
        print(f"[WARN] {INDEX_HTML} não encontrado. Crie o arquivo primeiro.")
        return
    with open(INDEX_HTML, "r", encoding="utf-8") as f:
        content = f.read()
    # Substituir URL do CSV caso tenha mudado
    new_url = SHEETS_CSV_URL
    content_new = re.sub(
        r"const CSV_URL\s*=\s*['\"](https://docs\.google\.com/spreadsheets[^'\";]+)['\"];",
        f"const CSV_URL = '{new_url}';",
        content
    )
    if content_new != content:
        with open(INDEX_HTML, "w", encoding="utf-8") as f:
            f.write(content_new)
        print(f"[INFO] CSV_URL atualizada no {INDEX_HTML}.")
    else:
        print(f"[INFO] CSV_URL já está correta no {INDEX_HTML}.")


# =============================================================================
# MAIN
# =============================================================================

def main():
    print(f"[START] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} — GAM Farma Updater")
    print(f"[INFO] Baixando planilha: {SHEETS_CSV_URL}")
    try:
        rows = download_csv(SHEETS_CSV_URL)
    except Exception as exc:
        print(f"[ERROR] Falha ao baixar planilha: {exc}", file=sys.stderr)
        sys.exit(1)

    update_date = rows[0].get("_UPDATE_DATE","") if rows else ""

    # Validação básica das colunas obrigatórias
    required = {"NOME", "FUNCAO", "UF", "REGIAO", "TELEFONE", "EMAIL"}
    if rows:
        missing = required - set(rows[0].keys())
        if missing:
            print(f"[WARN] Colunas não encontradas: {missing}. "
                  "Verifique os aliases em HEADER_ALIASES.")

    print("[INFO] Agrupando equipes...")
    groups    = build_groups(rows)
    state_map = build_state_map(groups)

    print(f"[INFO] {len(groups)} grupos | {len(state_map)} estados com cobertura")
    print(f"[INFO] Estados com cobertura: {sorted(state_map.keys())}")

    # Exibir resumo por tipo
    tipos = {}
    for r in rows:
        cat = r.get("_CATEGORIA","?")
        tipos[cat] = tipos.get(cat, 0) + 1
    for cat, cnt in sorted(tipos.items()):
        print(f"  {cat}: {cnt}")

    # Exportar JSON de debug
    export_data_json(rows, groups, state_map)

    # Garantir URL correta no index.html
    update_index_html(rows, update_date)

    print(f"[DONE] Atualização concluída em {datetime.now().strftime('%H:%M:%S')}")


if __name__ == "__main__":
    main()
