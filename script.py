#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
script.py — GAM Farma: Validação e cache de dados da planilha Google Sheets
===========================================================================
Arquivos gerados:
  - data.json       → Cache processado dos dados
  - changes.log     → Registro de mudanças detectadas
  - validation.json → Relatório de validação

Nomes padrão para GitHub Actions:
  - script.py   (este arquivo)
  - index.html  (página principal)
  - deploy.yml  (workflow do GitHub Actions)
  - data.json   (dados processados)
"""

import csv
import hashlib
import io
import json
import math
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
import urllib.request
import urllib.error
import time

# ============================================================
# CONFIGURAÇÃO
# ============================================================
CSV_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vQJRPejEYUGjqFiruPTGJuS2Itk6qjvyk6moB4_ChCe5_z4_CW0jYcYXJFimYYw4kGcbP2fpdRccLkq"
    "/pub?output=csv"
)

DATA_FILE = "data.json"
CHANGES_LOG = "changes.log"
VALIDATION_FILE = "validation.json"

EXPECTED_COLUMNS = [
    "DISTRITO", "SETOR", "REGIAO", "UF", "PRINCIPAIS CIDADES",
    "FUNCAO", "NOME REPRESENTANTE", "RAZAO SOCIAL",
    "CONTATO CORPORATIVO", "EMAIL", "COORDENADOR",
]

KNOWN_FUNCTIONS = [
    "COORDENADOR EQUIPE", "Consultor de Vendas", "Representante Comercial",
    "Gerente de Contas", "Coordenador de Contas - Médias Redes",
    "GERENTE DE PROJETOS ESPECIAIS", "Dedicados",
]


# ============================================================
# UTILITÁRIOS
# ============================================================
def normalize_header(h: str) -> str:
    s = unicodedata.normalize("NFD", h)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.upper().strip()
    s = s.replace("COORPORATIVO", "CORPORATIVO")
    s = s.replace("COODENADOR", "COORDENADOR")
    s = s.replace("RAZAO SOCIAL", "RAZAO SOCIAL")
    return s


def hash_row(row: dict) -> str:
    content = "|".join(str(v) for v in row.values())
    return hashlib.md5(content.encode("utf-8")).hexdigest()


def log_change(message: str):
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{timestamp}] {message}\n"
    with open(CHANGES_LOG, "a", encoding="utf-8") as f:
        f.write(line)
    print(f"  CHANGE: {message}")


def extract_ufs(uf_str: str) -> list:
    if not uf_str or uf_str.strip() in ("-", "", "EXPANSÃO", "EXPANSAO"):
        return []
    parts = re.split(r"[/\-,\s]+", uf_str.strip())
    return [p.strip().upper() for p in parts if len(p.strip()) == 2 and p.strip().isalpha()]


# ============================================================
# DOWNLOAD DO CSV
# ============================================================
def fetch_csv() -> str:
    url = f"{CSV_URL}&cb={int(time.time())}"
    print(f"Buscando CSV: {url[:80]}...")
    req = urllib.request.Request(url, headers={
        "Cache-Control": "no-store, no-cache",
        "Pragma": "no-cache",
        "User-Agent": "Mozilla/5.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read().decode("utf-8-sig")
            print(f"  CSV baixado: {len(data)} bytes")
            return data
    except urllib.error.URLError as e:
        print(f"  ERRO ao baixar CSV: {e}")
        sys.exit(1)


# ============================================================
# PARSE DO CSV
# ============================================================
def parse_csv(text: str) -> tuple:
    lines = text.strip().split("\n")
    header_idx = -1
    update_date = ""

    for i, line in enumerate(lines):
        upper = line.upper()
        if "DISTRITO" in upper and ("NOME" in upper or "REPRESENTANTE" in upper):
            header_idx = i
            break
        date_match = re.search(r"\d{2}/\d{2}/\d{4}", line)
        if date_match:
            update_date = date_match.group(0)

    if header_idx == -1:
        print("ERRO: Cabeçalho não encontrado no CSV!")
        sys.exit(1)

    reader = csv.reader(io.StringIO("\n".join(lines[header_idx:])))
    raw_headers = next(reader)
    headers = [normalize_header(h) for h in raw_headers]

    col_map = {}
    for i, h in enumerate(headers):
        if "DISTRITO" in h and "SETOR" not in h:
            col_map["DISTRITO"] = i
        elif h == "SETOR":
            col_map["SETOR"] = i
        elif "REGI" in h and "COORD" not in h:
            col_map["REGIAO"] = i
        elif h == "UF":
            col_map["UF"] = i
        elif "PRINCIPAIS" in h or ("CIDADES" in h and "COORD" not in h):
            col_map["PRINCIPAIS CIDADES"] = i
        elif "FUNC" in h or "FUNCAO" in h:
            col_map["FUNCAO"] = i
        elif "NOME" in h and "RAZAO" not in h:
            col_map["NOME"] = i
        elif "RAZAO" in h or "SOCIAL" in h:
            col_map["RAZAO SOCIAL"] = i
        elif "CONTATO" in h:
            col_map["CONTATO CORPORATIVO"] = i
        elif "EMAIL" in h and "COORD" not in h:
            col_map["EMAIL"] = i
        elif "COORDENADOR" in h or "COODENADOR" in h:
            col_map["COORDENADOR"] = i

    rows = []
    for cells in reader:
        if not cells:
            continue
        row = {}
        for key, idx in col_map.items():
            row[key] = cells[idx].strip() if idx < len(cells) else ""
        if not row.get("NOME", "").strip():
            continue
        row["_hash"] = hash_row({k: v for k, v in row.items() if k != "_hash"})
        rows.append(row)

    print(f"  Parseado: {len(rows)} linhas, {len(headers)} colunas")
    print(f"  Colunas mapeadas: {list(col_map.keys())}")
    print(f"  Data de atualização: {update_date or 'não encontrada'}")
    return headers, rows, update_date


# ============================================================
# CLASSIFICAÇÃO DE FUNÇÕES
# ============================================================
def classify_function(func: str) -> str:
    f = func.upper().strip()
    if "COORDENADOR EQUIPE" in f or "COORDENADOR DE EQUIPE" in f:
        return "COORDENADOR_EQUIPE"
    if "CONSULTOR DE VENDAS" in f:
        return "CONSULTOR_VENDAS"
    if "REPRESENTANTE COMERCIAL" in f:
        return "REPRESENTANTE_COMERCIAL"
    if "GERENTE DE CONTAS" in f:
        return "GERENTE_CONTAS"
    if ("COORDENADOR DE CONTAS" in f or "MEDIAS REDES" in f
            or "MÉDIAS REDES" in f or "MEDIAS REDES" in f):
        return "COORDENADOR_CONTAS"
    if "GERENTE DE PROJETOS ESPECIAIS" in f:
        return "GERENTE_PROJETOS_ESPECIAIS"
    if "DEDICADO" in f:
        return "DEDICADO"
    return "OUTRO"


# ============================================================
# PROCESSAMENTO DE DADOS
# ============================================================
def process_data(rows: list) -> dict:
    result = {
        "coordenadores_equipe": [],
        "gerentes_contas": [],
        "coordenadores_contas": [],
        "projetos_especiais": None,
        "estados": [],
        "divisoes": {},
        "total_representantes": 0,
        "total_coordenadores": 0,
        "resumo_funcoes": {},
    }

    for r in rows:
        cat = classify_function(r.get("FUNCAO", ""))
        result["resumo_funcoes"][cat] = result["resumo_funcoes"].get(cat, 0) + 1

    # 1. Coordenadores de Equipe
    coord_equipe = {}
    for r in rows:
        if classify_function(r.get("FUNCAO", "")) == "COORDENADOR_EQUIPE":
            dist = r.get("DISTRITO", "").strip()
            coord_equipe[dist] = r

    assigned = set()
    team_map = {}

    # Passo 1: Matching por base do distrito
    for dist, leader in coord_equipe.items():
        assigned.add(id(leader))
        team_map[dist] = []
        dist_parts = [p.strip() for p in re.split(r"[/,]", dist)]
        dist_bases = []
        for part in dist_parts:
            try:
                n = int(part)
                dist_bases.append(math.floor(n / 100) * 100)
            except ValueError:
                pass

        for r in rows:
            if r is leader or id(r) in assigned:
                continue
            cat = classify_function(r.get("FUNCAO", ""))
            if cat in ("COORDENADOR_EQUIPE", "GERENTE_CONTAS", "COORDENADOR_CONTAS",
                       "GERENTE_PROJETOS_ESPECIAIS", "DEDICADO"):
                continue
            r_dist = r.get("DISTRITO", "").strip()
            if not r_dist or r_dist == "-":
                continue
            try:
                r_base = math.floor(int(r_dist) / 100) * 100
                if r_base in dist_bases:
                    team_map[dist].append(r)
                    assigned.add(id(r))
            except ValueError:
                pass

    # Passo 2: Fallback por coluna COORDENADOR
    for dist, leader in coord_equipe.items():
        leader_name_upper = leader.get("NOME", "").upper().strip()
        leader_first = leader_name_upper.split()[0] if leader_name_upper else ""
        for r in rows:
            if id(r) in assigned or r is leader:
                continue
            cat = classify_function(r.get("FUNCAO", ""))
            if cat in ("COORDENADOR_EQUIPE", "GERENTE_CONTAS", "COORDENADOR_CONTAS",
                       "GERENTE_PROJETOS_ESPECIAIS", "DEDICADO"):
                continue
            coord_col = r.get("COORDENADOR", "").upper().strip()
            if coord_col and (coord_col == leader_name_upper or coord_col == leader_first
                              or leader_first in coord_col):
                team_map[dist].append(r)
                assigned.add(id(r))

    # Construir grupos finais
    for dist, leader in coord_equipe.items():
        team = team_map.get(dist, [])

        all_ufs = set(extract_ufs(leader.get("UF", "")))
        for m in team:
            all_ufs.update(extract_ufs(m.get("UF", "")))

        # Determinar divisão especial
        division = None
        uf_val = leader.get("UF", "").upper().strip()
        region_val = leader.get("REGIAO", "").upper().strip()
        if uf_val == "-" or "TLV" in region_val:
            division = "TLV"
            # Para TLV, pegar UFs dos membros
            for m in team:
                all_ufs.update(extract_ufs(m.get("UF", "")))
        elif "EXPANS" in uf_val or "EXPANS" in region_val:
            division = "EXPANSÃO"
            for m in team:
                all_ufs.update(extract_ufs(m.get("UF", "")))

        group = {
            "distrito": dist,
            "divisao": division,
            "estados": sorted(list(all_ufs)),
            "coordenador": {
                "nome": leader.get("NOME", "").strip(),
                "funcao": leader.get("FUNCAO", "").strip(),
                "regiao": leader.get("REGIAO", "").strip(),
                "uf": leader.get("UF", "").strip(),
                "contato": leader.get("CONTATO CORPORATIVO", "").strip(),
                "email": leader.get("EMAIL", "").strip(),
                "razao_social": leader.get("RAZAO SOCIAL", "").strip(),
            },
            "equipe": [
                {
                    "nome": m.get("NOME", "").strip(),
                    "funcao": m.get("FUNCAO", "").strip(),
                    "categoria": classify_function(m.get("FUNCAO", "")),
                    "regiao": m.get("REGIAO", "").strip(),
                    "uf": m.get("UF", "").strip(),
                    "principais_cidades": m.get("PRINCIPAIS CIDADES", "").strip(),
                    "contato": m.get("CONTATO CORPORATIVO", "").strip(),
                    "email": m.get("EMAIL", "").strip(),
                    "razao_social": m.get("RAZAO SOCIAL", "").strip(),
                    "setor": m.get("SETOR", "").strip(),
                }
                for m in team
            ],
            "total_membros": len(team),
        }
        result["coordenadores_equipe"].append(group)
        result["total_coordenadores"] += 1
        result["total_representantes"] += len(team)

    # 2. Gerente de Projetos Especiais + Dedicados
    gpe = None
    dedicados = []
    for r in rows:
        cat = classify_function(r.get("FUNCAO", ""))
        if cat == "GERENTE_PROJETOS_ESPECIAIS":
            gpe = r
        elif cat == "DEDICADO":
            dedicados.append(r)

    if gpe:
        all_ufs = set(extract_ufs(gpe.get("UF", "")))
        for d in dedicados:
            all_ufs.update(extract_ufs(d.get("UF", "")))
        result["projetos_especiais"] = {
            "lider": {
                "nome": gpe.get("NOME", "").strip(),
                "funcao": gpe.get("FUNCAO", "").strip(),
                "regiao": gpe.get("REGIAO", "").strip(),
                "uf": gpe.get("UF", "").strip(),
                "contato": gpe.get("CONTATO CORPORATIVO", "").strip(),
                "email": gpe.get("EMAIL", "").strip(),
            },
            "dedicados": [
                {
                    "nome": d.get("NOME", "").strip(),
                    "funcao": d.get("FUNCAO", "").strip(),
                    "regiao": d.get("REGIAO", "").strip(),
                    "uf": d.get("UF", "").strip(),
                    "principais_cidades": d.get("PRINCIPAIS CIDADES", "").strip(),
                    "contato": d.get("CONTATO CORPORATIVO", "").strip(),
                    "email": d.get("EMAIL", "").strip(),
                    "setor": d.get("SETOR", "").strip(),
                }
                for d in dedicados
            ],
            "estados": sorted(list(all_ufs)),
            "total_dedicados": len(dedicados),
        }

    # 3. Gerentes de Contas
    for r in rows:
        if classify_function(r.get("FUNCAO", "")) == "GERENTE_CONTAS":
            ufs = extract_ufs(r.get("UF", ""))
            result["gerentes_contas"].append({
                "nome": r.get("NOME", "").strip(),
                "funcao": r.get("FUNCAO", "").strip(),
                "regiao": r.get("REGIAO", "").strip(),
                "uf": r.get("UF", "").strip(),
                "ufs": ufs,
                "contato": r.get("CONTATO CORPORATIVO", "").strip(),
                "email": r.get("EMAIL", "").strip(),
                "distrito": r.get("DISTRITO", "").strip(),
            })

    # 4. Coordenadores de Contas Médias Redes
    for r in rows:
        if classify_function(r.get("FUNCAO", "")) == "COORDENADOR_CONTAS":
            ufs = extract_ufs(r.get("UF", ""))
            result["coordenadores_contas"].append({
                "nome": r.get("NOME", "").strip(),
                "funcao": r.get("FUNCAO", "").strip(),
                "regiao": r.get("REGIAO", "").strip(),
                "uf": r.get("UF", "").strip(),
                "ufs": ufs,
                "contato": r.get("CONTATO CORPORATIVO", "").strip(),
                "email": r.get("EMAIL", "").strip(),
                "distrito": r.get("DISTRITO", "").strip(),
            })

    # 5. Mapa de estados cobertos
    all_states = set()
    for group in result["coordenadores_equipe"]:
        for uf in group["estados"]:
            all_states.add(uf)
    for gc in result["gerentes_contas"]:
        for uf in gc["ufs"]:
            all_states.add(uf)
    for cc in result["coordenadores_contas"]:
        for uf in cc["ufs"]:
            all_states.add(uf)
    if result["projetos_especiais"]:
        for uf in result["projetos_especiais"]["estados"]:
            all_states.add(uf)
    result["estados"] = sorted(all_states)

    return result


# ============================================================
# DETECÇÃO DE MUDANÇAS
# ============================================================
def detect_changes(new_rows: list) -> list:
    changes = []
    if not os.path.exists(DATA_FILE):
        changes.append("Primeira execução — nenhum dado anterior para comparar")
        return changes
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            old_data = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        changes.append("Arquivo de dados anterior corrompido ou inexistente")
        return changes

    old_rows_by_name = {}
    if "raw_rows" in old_data:
        for r in old_data["raw_rows"]:
            old_rows_by_name[r.get("NOME", "").strip()] = r

    new_rows_by_name = {r.get("NOME", "").strip(): r for r in new_rows}

    for name in new_rows_by_name:
        if name not in old_rows_by_name:
            r = new_rows_by_name[name]
            changes.append(f"NOVO: {name} (Função: {r.get('FUNCAO','')}, UF: {r.get('UF','')}, Região: {r.get('REGIAO','')})")

    for name in old_rows_by_name:
        if name not in new_rows_by_name:
            changes.append(f"REMOVIDO: {name}")

    for name in new_rows_by_name:
        if name in old_rows_by_name:
            old = old_rows_by_name[name]
            new = new_rows_by_name[name]
            fields = {
                "FUNCAO": "Função", "UF": "UF", "REGIAO": "Região",
                "CONTATO CORPORATIVO": "Contato", "EMAIL": "Email",
                "RAZAO SOCIAL": "Razão Social", "PRINCIPAIS CIDADES": "Cidades",
                "DISTRITO": "Distrito", "SETOR": "Setor", "COORDENADOR": "Coordenador",
            }
            for field, label in fields.items():
                old_val = old.get(field, "").strip()
                new_val = new.get(field, "").strip()
                if old_val != new_val:
                    changes.append(f"ALTERADO: {name} — {label}: '{old_val}' → '{new_val}'")

    old_total = len(old_rows_by_name)
    new_total = len(new_rows_by_name)
    if old_total != new_total:
        changes.append(f"TOTAL LINHAS: {old_total} → {new_total}")

    return changes


# ============================================================
# VALIDAÇÃO
# ============================================================
def validate_data(headers: list, rows: list) -> dict:
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "OK",
        "total_rows": len(rows),
        "total_columns": len(headers),
        "headers_found": headers,
        "warnings": [],
        "errors": [],
    }
    normalized_headers = [normalize_header(h) for h in headers]
    for expected in EXPECTED_COLUMNS:
        found = any(expected.replace(" ", "") in nh.replace(" ", "") for nh in normalized_headers)
        if not found:
            report["warnings"].append(f"Coluna esperada não encontrada: {expected}")
    for i, r in enumerate(rows):
        if not r.get("NOME", "").strip():
            report["errors"].append(f"Linha {i+2}: NOME vazio")
        if not r.get("FUNCAO", "").strip():
            report["warnings"].append(f"Linha {i+2} ({r.get('NOME','')}): FUNÇÃO vazia")
    if report["errors"]:
        report["status"] = "ERRORS"
    elif report["warnings"]:
        report["status"] = "WARNINGS"
    return report


# ============================================================
# MAIN
# ============================================================
def main():
    print("=" * 60)
    print("GAM Farma — Script de Processamento de Dados")
    print(f"Execução: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 60)

    csv_text = fetch_csv()
    headers, rows, update_date = parse_csv(csv_text)

    print("\nValidando dados...")
    validation = validate_data(headers, rows)
    with open(VALIDATION_FILE, "w", encoding="utf-8") as f:
        json.dump(validation, f, ensure_ascii=False, indent=2)
    print(f"  Status: {validation['status']}")
    for w in validation["warnings"]:
        print(f"  WARNING: {w}")
    for e in validation["errors"]:
        print(f"  ERROR: {e}")

    print("\nDetectando mudanças...")
    changes = detect_changes(rows)
    if changes:
        for c in changes:
            log_change(c)
        print(f"  {len(changes)} mudança(s) detectada(s)")
    else:
        print("  Nenhuma mudança detectada")

    print("\nProcessando dados...")
    processed = process_data(rows)
    print(f"  Coordenadores de Equipe: {len(processed['coordenadores_equipe'])}")
    print(f"  Gerentes de Contas: {len(processed['gerentes_contas'])}")
    print(f"  Coord. Médias Redes: {len(processed['coordenadores_contas'])}")
    print(f"  Projetos Especiais: {'Sim' if processed['projetos_especiais'] else 'Não'}")
    print(f"  Estados cobertos: {', '.join(processed['estados'])}")
    print(f"  Total representantes: {processed['total_representantes']}")

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "update_date": update_date,
        "csv_url": CSV_URL,
        "total_rows": len(rows),
        "processed": processed,
        "raw_rows": rows,
        "validation": validation,
        "changes": changes,
    }

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nDados salvos em {DATA_FILE} ({os.path.getsize(DATA_FILE)} bytes)")

    print("\n" + "=" * 60)
    print("RESUMO")
    print("=" * 60)
    print(f"  Linhas processadas: {len(rows)}")
    print(f"  Mudanças encontradas: {len(changes)}")
    print(f"  Validação: {validation['status']}")
    for func, count in sorted(processed["resumo_funcoes"].items()):
        print(f"    - {func}: {count}")
    print("=" * 60)

    if validation["errors"]:
        print("\nATENÇÃO: Existem erros nos dados!")
        sys.exit(1)

    print("\nProcessamento concluído com sucesso!")
    sys.exit(0)


if __name__ == "__main__":
    main()
