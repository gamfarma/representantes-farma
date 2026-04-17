#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
script.py — GAM Farma: Validação e cache de dados da planilha Google Sheets
===========================================================================
Este script:
1. Busca o CSV publicado do Google Sheets
2. Valida a estrutura de colunas (detecta mudanças)
3. Processa TODAS as variáveis: distritos, setores, regiões, UFs,
   cidades, funções, nomes, razão social, contatos, emails, coordenadores
4. Gera um data.json com cache para carregamento rápido
5. Detecta mudanças de coluna, linha, nomes, funções, telefones, emails
6. Registra um log de alterações em changes.log

Arquivos gerados:
  - data.json       → Cache processado dos dados
  - changes.log     → Registro de mudanças detectadas
  - validation.json → Relatório de validação

Nomes padrão para o GitHub Actions:
  - script.py   (este arquivo)
  - index.html  (página principal)
  - deploy.yml  (workflow do GitHub Actions)
"""

import csv
import hashlib
import io
import json
import os
import sys
from datetime import datetime, timezone

import urllib.request
import urllib.error

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

# Colunas esperadas (normalizadas para comparação)
EXPECTED_COLUMNS = [
    "DISTRITO",
    "SETOR",
    "REGIAO",
    "UF",
    "PRINCIPAIS CIDADES",
    "FUNCAO",
    "NOME REPRESENTANTE",
    "RAZAO SOCIAL",
    "CONTATO CORPORATIVO",
    "EMAIL",
    "COORDENADOR",
]

# Funções reconhecidas
KNOWN_FUNCTIONS = [
    "COORDENADOR EQUIPE",
    "Consultor de Vendas",
    "Representante Comercial",
    "Gerente de Contas",
    "Coordenador de Contas - Médias Redes",
    "GERENTE DE PROJETOS ESPECIAIS",
    "Dedicados",
]


# ============================================================
# UTILITÁRIOS
# ============================================================
def normalize_header(h: str) -> str:
    """Normaliza cabeçalhos removendo acentos e padronizando nomes."""
    import unicodedata

    s = unicodedata.normalize("NFD", h)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.upper().strip()
    s = s.replace("COORPORATIVO", "CORPORATIVO")
    s = s.replace("COODENADOR", "COORDENADOR")
    return s


def hash_row(row: dict) -> str:
    """Gera hash MD5 de uma linha para detectar mudanças."""
    content = "|".join(str(v) for v in row.values())
    return hashlib.md5(content.encode("utf-8")).hexdigest()


def log_change(message: str):
    """Registra mudança no log."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{timestamp}] {message}\n"
    with open(CHANGES_LOG, "a", encoding="utf-8") as f:
        f.write(line)
    print(f"  CHANGE: {message}")


# ============================================================
# DOWNLOAD DO CSV
# ============================================================
def fetch_csv() -> str:
    """Busca o CSV do Google Sheets com cache-busting."""
    import time
    url = f"{CSV_URL}&cb={int(time.time())}"
    print(f"Buscando CSV: {url[:80]}...")
    req = urllib.request.Request(url, headers={
        "Cache-Control": "no-store, no-cache",
        "Pragma": "no-cache",
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
    """
    Parseia o CSV e retorna (headers, rows, update_date).
    Detecta automaticamente a linha de cabeçalho.
    """
    lines = text.strip().split("\n")
    header_idx = -1
    update_date = ""

    for i, line in enumerate(lines):
        upper = line.upper()
        if "DISTRITO" in upper and ("NOME" in upper or "REPRESENTANTE" in upper):
            header_idx = i
            break
        # Busca data de atualização
        import re
        date_match = re.search(r"\d{2}/\d{2}/\d{4}", line)
        if date_match:
            update_date = date_match.group(0)

    if header_idx == -1:
        print("ERRO: Cabeçalho não encontrado no CSV!")
        sys.exit(1)

    # Parse usando csv.reader para lidar com aspas
    reader = csv.reader(io.StringIO("\n".join(lines[header_idx:])))
    raw_headers = next(reader)
    headers = [normalize_header(h) for h in raw_headers]

    # Mapeia colunas para nomes padronizados
    col_map = {}
    for i, h in enumerate(headers):
        if "DISTRITO" in h:
            col_map["DISTRITO"] = i
        elif h == "SETOR":
            col_map["SETOR"] = i
        elif "REGI" in h:
            col_map["REGIAO"] = i
        elif h == "UF":
            col_map["UF"] = i
        elif "PRINCIPAIS" in h or "CIDADES" in h:
            col_map["PRINCIPAIS CIDADES"] = i
        elif "FUNC" in h:
            col_map["FUNCAO"] = i
        elif "NOME" in h:
            col_map["NOME"] = i
        elif "RAZAO" in h or "SOCIAL" in h:
            col_map["RAZAO SOCIAL"] = i
        elif "CONTATO" in h:
            col_map["CONTATO CORPORATIVO"] = i
        elif "EMAIL" in h and "COORD" not in h:
            col_map["EMAIL"] = i
        elif "COORDENADOR" in h:
            col_map["COORDENADOR"] = i

    rows = []
    for cells in reader:
        if not cells:
            continue
        row = {}
        for key, idx in col_map.items():
            row[key] = cells[idx].strip() if idx < len(cells) else ""
        # Pula linhas sem nome
        if not row.get("NOME", ""):
            continue
        row["_hash"] = hash_row(row)
        rows.append(row)

    print(f"  Parseado: {len(rows)} linhas, {len(headers)} colunas")
    print(f"  Colunas mapeadas: {list(col_map.keys())}")
    print(f"  Data de atualização: {update_date or 'não encontrada'}")

    return headers, rows, update_date


# ============================================================
# CLASSIFICAÇÃO DE FUNÇÕES
# ============================================================
def classify_function(func: str) -> str:
    """Classifica a função em uma categoria padronizada."""
    f = func.upper().strip()
    if "COORDENADOR EQUIPE" in f or "COORDENADOR DE EQUIPE" in f:
        return "COORDENADOR_EQUIPE"
    if "CONSULTOR DE VENDAS" in f:
        return "CONSULTOR_VENDAS"
    if "REPRESENTANTE COMERCIAL" in f:
        return "REPRESENTANTE_COMERCIAL"
    if "GERENTE DE CONTAS" in f:
        return "GERENTE_CONTAS"
    if "COORDENADOR DE CONTAS" in f or "MEDIAS REDES" in f or "MÉDIAS REDES" in f:
        return "COORDENADOR_CONTAS"
    if "GERENTE DE PROJETOS ESPECIAIS" in f:
        return "GERENTE_PROJETOS_ESPECIAIS"
    if "DEDICADO" in f:
        return "DEDICADO"
    return "OUTRO"


def extract_ufs(uf_str: str) -> list:
    """Extrai UFs de uma string (ex: 'PR/RS/SC' -> ['PR','RS','SC'])."""
    import re
    if not uf_str or uf_str == "-" or "EXPANS" in uf_str.upper():
        return []
    parts = re.split(r"[/\-,\s]+", uf_str.strip())
    return [p.strip().upper() for p in parts if len(p.strip()) == 2 and p.strip().isalpha()]


# ============================================================
# PROCESSAMENTO DE DADOS
# ============================================================
def process_data(rows: list) -> dict:
    """
    Processa as linhas e organiza em grupos por coordenador.
    Retorna estrutura completa com:
    - coordenadores de equipe e suas equipes
    - gerentes de contas (individuais)
    - coordenadores de médias redes (individuais)
    - gerente de projetos especiais e dedicados
    """
    result = {
        "coordenadores_equipe": [],
        "gerentes_contas": [],
        "coordenadores_contas": [],
        "projetos_especiais": None,
        "estados": {},
        "divisoes": {},
        "total_representantes": 0,
        "total_coordenadores": 0,
        "resumo_funcoes": {},
    }

    # Contagem de funções
    for r in rows:
        cat = classify_function(r.get("FUNCAO", ""))
        result["resumo_funcoes"][cat] = result["resumo_funcoes"].get(cat, 0) + 1

    # 1. Identificar coordenadores de equipe
    coord_equipe = {}
    for r in rows:
        if classify_function(r.get("FUNCAO", "")) == "COORDENADOR_EQUIPE":
            dist = r.get("DISTRITO", "")
            coord_equipe[dist] = r

    # 2. Montar equipes — 2 passos: base do distrito primeiro, fallback por COORDENADOR depois
    import math
    assigned = set()
    team_map = {}

    # Passo 1: Matching por base do distrito
    for dist, leader in coord_equipe.items():
        assigned.add(id(leader))
        team_map[dist] = []
        dist_parts = [p.strip() for p in dist.split("/")]
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

    # Passo 2: Fallback por coluna COORDENADOR (somente membros não atribuídos)
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
            if coord_col and (coord_col == leader_name_upper or coord_col == leader_first):
                team_map[dist].append(r)
                assigned.add(id(r))

    # Construir grupos finais
    for dist, leader in coord_equipe.items():
        team = team_map[dist]

        leader_uf = leader.get("UF", "")
        all_ufs = set(extract_ufs(leader.get("UF", "")))
        for m in team:
            all_ufs.update(extract_ufs(m.get("UF", "")))

        # Determinar se é divisão especial
        division = None
        uf_val = leader.get("UF", "").upper()
        region_val = leader.get("REGIAO", "").upper()
        if uf_val == "-" or "TLV" in region_val:
            division = "TLV"
        elif "EXPANS" in uf_val or "EXPANS" in region_val:
            division = "EXPANSÃO"

        group = {
            "distrito": dist,
            "coordenador": {
                "nome": leader.get("NOME", ""),
                "funcao": leader.get("FUNCAO", ""),
                "regiao": leader.get("REGIAO", ""),
                "uf": leader.get("UF", ""),
                "contato": leader.get("CONTATO CORPORATIVO", ""),
                "email": leader.get("EMAIL", ""),
                "razao_social": leader.get("RAZAO SOCIAL", ""),
            },
            "equipe": [
                {
                    "nome": m.get("NOME", ""),
                    "funcao": m.get("FUNCAO", ""),
                    "regiao": m.get("REGIAO", ""),
                    "uf": m.get("UF", ""),
                    "principais_cidades": m.get("PRINCIPAIS CIDADES", ""),
                    "contato": m.get("CONTATO CORPORATIVO", ""),
                    "email": m.get("EMAIL", ""),
                    "razao_social": m.get("RAZAO SOCIAL", ""),
                    "setor": m.get("SETOR", ""),
                    "categoria": classify_function(m.get("FUNCAO", "")),
                }
                for m in team
            ],
            "estados": list(all_ufs),
            "divisao": division,
            "total_membros": len(team),
        }

        result["coordenadores_equipe"].append(group)
        result["total_coordenadores"] += 1
        result["total_representantes"] += len(team)

    # 3. Gerente de Projetos Especiais + Dedicados
    gpe = None
    dedicados = []
    for r in rows:
        if classify_function(r.get("FUNCAO", "")) == "GERENTE_PROJETOS_ESPECIAIS":
            gpe = r
        elif classify_function(r.get("FUNCAO", "")) == "DEDICADO":
            dedicados.append(r)

    if gpe:
        all_ufs = set(extract_ufs(gpe.get("UF", "")))
        for d in dedicados:
            all_ufs.update(extract_ufs(d.get("UF", "")))

        result["projetos_especiais"] = {
            "lider": {
                "nome": gpe.get("NOME", ""),
                "funcao": gpe.get("FUNCAO", ""),
                "regiao": gpe.get("REGIAO", ""),
                "uf": gpe.get("UF", ""),
                "contato": gpe.get("CONTATO CORPORATIVO", ""),
                "email": gpe.get("EMAIL", ""),
            },
            "dedicados": [
                {
                    "nome": d.get("NOME", ""),
                    "funcao": d.get("FUNCAO", ""),
                    "regiao": d.get("REGIAO", ""),
                    "uf": d.get("UF", ""),
                    "principais_cidades": d.get("PRINCIPAIS CIDADES", ""),
                    "contato": d.get("CONTATO CORPORATIVO", ""),
                    "email": d.get("EMAIL", ""),
                    "setor": d.get("SETOR", ""),
                }
                for d in dedicados
            ],
            "estados": list(all_ufs),
            "total_dedicados": len(dedicados),
        }

    # 4. Gerentes de Contas (individuais)
    for r in rows:
        if classify_function(r.get("FUNCAO", "")) == "GERENTE_CONTAS":
            result["gerentes_contas"].append({
                "nome": r.get("NOME", ""),
                "funcao": r.get("FUNCAO", ""),
                "regiao": r.get("REGIAO", ""),
                "uf": r.get("UF", ""),
                "clientes": r.get("PRINCIPAIS CIDADES", ""),
                "contato": r.get("CONTATO CORPORATIVO", ""),
                "email": r.get("EMAIL", ""),
                "distrito": r.get("DISTRITO", ""),
            })

    # 5. Coordenadores de Contas Médias Redes (individuais)
    for r in rows:
        if classify_function(r.get("FUNCAO", "")) == "COORDENADOR_CONTAS":
            result["coordenadores_contas"].append({
                "nome": r.get("NOME", ""),
                "funcao": r.get("FUNCAO", ""),
                "regiao": r.get("REGIAO", ""),
                "uf": r.get("UF", ""),
                "clientes": r.get("PRINCIPAIS CIDADES", ""),
                "contato": r.get("CONTATO CORPORATIVO", ""),
                "email": r.get("EMAIL", ""),
                "distrito": r.get("DISTRITO", ""),
            })

    # 6. Mapa de estados
    all_states = set()
    for group in result["coordenadores_equipe"]:
        for uf in group["estados"]:
            all_states.add(uf)
    for gc in result["gerentes_contas"]:
        for uf in extract_ufs(gc["uf"]):
            all_states.add(uf)
    for cc in result["coordenadores_contas"]:
        for uf in extract_ufs(cc["uf"]):
            all_states.add(uf)
    result["estados"] = sorted(all_states)

    return result


# ============================================================
# DETECÇÃO DE MUDANÇAS
# ============================================================
def detect_changes(new_rows: list) -> list:
    """Compara com data.json anterior e detecta mudanças."""
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
            old_rows_by_name[r.get("NOME", "")] = r

    new_rows_by_name = {}
    for r in new_rows:
        new_rows_by_name[r.get("NOME", "")] = r

    # Novos membros
    for name in new_rows_by_name:
        if name not in old_rows_by_name:
            r = new_rows_by_name[name]
            changes.append(f"NOVO: {name} (Função: {r.get('FUNCAO','')}, UF: {r.get('UF','')}, Região: {r.get('REGIAO','')})")

    # Membros removidos
    for name in old_rows_by_name:
        if name not in new_rows_by_name:
            changes.append(f"REMOVIDO: {name}")

    # Mudanças em membros existentes
    for name in new_rows_by_name:
        if name in old_rows_by_name:
            old = old_rows_by_name[name]
            new = new_rows_by_name[name]
            for field in ["FUNCAO", "UF", "REGIAO", "CONTATO CORPORATIVO", "EMAIL",
                          "RAZAO SOCIAL", "PRINCIPAIS CIDADES", "DISTRITO", "SETOR"]:
                old_val = old.get(field, "").strip()
                new_val = new.get(field, "").strip()
                if old_val != new_val:
                    field_name = {
                        "FUNCAO": "Função",
                        "UF": "UF",
                        "REGIAO": "Região",
                        "CONTATO CORPORATIVO": "Contato",
                        "EMAIL": "Email",
                        "RAZAO SOCIAL": "Razão Social",
                        "PRINCIPAIS CIDADES": "Cidades",
                        "DISTRITO": "Distrito",
                        "SETOR": "Setor",
                    }.get(field, field)
                    changes.append(
                        f"ALTERADO: {name} — {field_name}: '{old_val}' → '{new_val}'"
                    )

    # Mudança no total de linhas
    old_total = len(old_rows_by_name)
    new_total = len(new_rows_by_name)
    if old_total != new_total:
        changes.append(f"TOTAL LINHAS: {old_total} → {new_total}")

    return changes


# ============================================================
# VALIDAÇÃO
# ============================================================
def validate_data(headers: list, rows: list) -> dict:
    """Valida a estrutura e integridade dos dados."""
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "OK",
        "total_rows": len(rows),
        "total_columns": len(headers),
        "headers_found": headers,
        "warnings": [],
        "errors": [],
    }

    # Verifica colunas esperadas
    normalized_headers = [normalize_header(h) for h in headers]
    for expected in EXPECTED_COLUMNS:
        found = False
        for nh in normalized_headers:
            if expected.replace(" ", "") in nh.replace(" ", ""):
                found = True
                break
        if not found:
            report["warnings"].append(f"Coluna esperada não encontrada: {expected}")

    # Nova coluna detectada
    known_set = set()
    for e in EXPECTED_COLUMNS:
        known_set.add(e.replace(" ", "").upper())
    for nh in normalized_headers:
        clean = nh.replace(" ", "").upper()
        if clean and not any(k in clean for k in known_set) and clean not in ("", "NAN"):
            report["warnings"].append(f"Nova coluna detectada: {nh}")

    # Verifica dados obrigatórios
    for i, r in enumerate(rows):
        nome = r.get("NOME", "").strip()
        if not nome:
            report["errors"].append(f"Linha {i+2}: NOME vazio")
        funcao = r.get("FUNCAO", "").strip()
        if not funcao:
            report["warnings"].append(f"Linha {i+2} ({nome}): FUNÇÃO vazia")

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

    # 1. Buscar CSV
    csv_text = fetch_csv()

    # 2. Parsear
    headers, rows, update_date = parse_csv(csv_text)

    # 3. Validar
    print("\nValidando dados...")
    validation = validate_data(headers, rows)
    with open(VALIDATION_FILE, "w", encoding="utf-8") as f:
        json.dump(validation, f, ensure_ascii=False, indent=2)
    print(f"  Status: {validation['status']}")
    if validation["warnings"]:
        for w in validation["warnings"]:
            print(f"  WARNING: {w}")
    if validation["errors"]:
        for e in validation["errors"]:
            print(f"  ERROR: {e}")

    # 4. Detectar mudanças
    print("\nDetectando mudanças...")
    changes = detect_changes(rows)
    if changes:
        for c in changes:
            log_change(c)
        print(f"  {len(changes)} mudança(s) detectada(s)")
    else:
        print("  Nenhuma mudança detectada")

    # 5. Processar dados
    print("\nProcessando dados...")
    processed = process_data(rows)
    print(f"  Coordenadores de Equipe: {len(processed['coordenadores_equipe'])}")
    print(f"  Gerentes de Contas: {len(processed['gerentes_contas'])}")
    print(f"  Coord. Médias Redes: {len(processed['coordenadores_contas'])}")
    print(f"  Projetos Especiais: {'Sim' if processed['projetos_especiais'] else 'Não'}")
    print(f"  Estados cobertos: {', '.join(processed['estados'])}")
    print(f"  Total representantes: {processed['total_representantes']}")

    # 6. Salvar data.json
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "update_date": update_date,
        "csv_url": CSV_URL,
        "total_rows": len(rows),
        "processed": processed,
        "raw_rows": rows,  # Para detecção de mudanças na próxima execução
        "validation": validation,
        "changes": changes,
    }

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nDados salvos em {DATA_FILE} ({os.path.getsize(DATA_FILE)} bytes)")

    # 7. Resumo
    print("\n" + "=" * 60)
    print("RESUMO")
    print("=" * 60)
    print(f"  Linhas processadas: {len(rows)}")
    print(f"  Colunas detectadas: {len(headers)}")
    print(f"  Mudanças encontradas: {len(changes)}")
    print(f"  Validação: {validation['status']}")
    print(f"  Funções encontradas:")
    for func, count in sorted(processed["resumo_funcoes"].items()):
        print(f"    - {func}: {count}")
    print("=" * 60)

    # Exit code baseado na validação
    if validation["errors"]:
        print("\nATENÇÃO: Existem erros nos dados!")
        sys.exit(1)

    print("\nProcessamento concluído com sucesso!")
    sys.exit(0)


if __name__ == "__main__":
    main()
