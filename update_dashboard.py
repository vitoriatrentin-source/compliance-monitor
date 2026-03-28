#!/usr/bin/env python3
"""
Monitor de Compliance Pitaco — Script de atualização automática
Roda via GitHub Actions 6x/dia
"""

import os
import re
import requests
import anthropic
from datetime import datetime, timezone, timedelta

# ── Config ────────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
SLACK_TOKEN        = os.environ["SLACK_TOKEN"]

NEWS_SOURCES = [
    ("COAF",                "https://www.gov.br/coaf/pt-br/assuntos/noticias"),
    ("ANPD",                "https://www.gov.br/anpd/pt-br/assuntos/noticias"),
    ("DOU",                 "https://www.in.gov.br/consulta/-/buscar/dou?q=apostas+bets+jogos&s=todos&exactDate=mes&sortType=0"),
    ("Gambling Commission", "https://www.gamblingcommission.gov.uk/news-action-and-statistics/news"),
    ("Mediabet",            "https://mediabet.com.br/noticias/"),
    ("BNL Data",            "https://bnldata.com.br/noticias/"),
    ("iGaming Brasil",      "https://igamingbrazil.com/pt/noticias/"),
    ("G&M News",            "https://g-mnews.com/pt/noticias/"),
    # Prediction Markets — fontes internacionais
    ("Kalshi Blog",         "https://kalshi.com/blog"),
    ("Polymarket Blog",     "https://polymarket.com/blog"),
]

SLACK_CHANNELS = {
    # ── Legal & Compliance ──────────────────────────────────────────
    "legal-team":                    "C02RHL9GMHC",
    "legal-finance":                 "C061CELPX5L",
    "legal-cx":                      "C05HEMXEJRL",
    "legal-monitoramento-entries":   "C0A2LFG4X1S",
    "mkt-legal":                     "C08AM6S7R47",
    "p-legal-limites-boqueio-sigap": "C09U4MHR5TK",  # limites, bloqueios, SIGAP
    "solicitacoes-kpmg-legal":       "C09TVKGD02X",  # auditoria KPMG
    "regulatory-updates":            "C03J0RWK72M",
    "compliance":                    "C03N4C6LBN3",
    "i-compliance":                  "C097EDPJYGZ",
    "compliance-alerts":             "C066KQD4P0E",
    # ── Integridade & Operações ─────────────────────────────────────
    "integrity":                     "C08M57LG8HL",
    "ops-trading":                   "C0AM19UCH5H",
    "ops-sportsbook":                "C0AM18Z5AJF",
    "duvidas-igaming":               "C09K9T9BTD5",
    # ── Benchmark & Produto ─────────────────────────────────────────
    "benchmark":                     "C08H223FJ4A",
    "i-prediction-markets":          "C09HD5YDM38",
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def brt_now() -> str:
    brt = timezone(timedelta(hours=-3))
    return datetime.now(brt).strftime("%H:%M")


def slack_channel(channel_id: str, limit: int = 40) -> list:
    resp = requests.get(
        "https://slack.com/api/conversations.history",
        headers={"Authorization": f"Bearer {SLACK_TOKEN}"},
        params={"channel": channel_id, "limit": limit},
        timeout=15,
    )
    data = resp.json()
    return data.get("messages", []) if data.get("ok") else []


def slack_search(query: str, count: int = 20) -> list:
    resp = requests.get(
        "https://slack.com/api/search.messages",
        headers={"Authorization": f"Bearer {SLACK_TOKEN}"},
        params={"query": query, "count": count},
        timeout=15,
    )
    data = resp.json()
    return data.get("messages", {}).get("matches", []) if data.get("ok") else []


def fetch_url(url: str, max_chars: int = 4000) -> str:
    try:
        resp = requests.get(
            url, timeout=12,
            headers={"User-Agent": "Mozilla/5.0 (compliance-monitor-bot)"},
        )
        return resp.text[:max_chars]
    except Exception as e:
        return f"[erro ao buscar {url}: {e}]"


def fmt_messages(messages: list) -> str:
    if not messages:
        return "(sem mensagens)"
    lines = []
    for m in messages[:25]:
        ts  = m.get("ts", "")
        txt = m.get("text", "").replace("\n", " ")[:300]
        lines.append(f"[{ts}] {txt}")
    return "\n".join(lines)


def fmt_search(matches: list) -> str:
    if not matches:
        return "(sem resultados)"
    lines = []
    for m in matches[:15]:
        ch  = m.get("channel", {}).get("name", "?")
        txt = m.get("text", "").replace("\n", " ")[:300]
        lines.append(f"[#{ch}] {txt}")
    return "\n".join(lines)


# ── Core ──────────────────────────────────────────────────────────────────────

def collect_slack() -> str:
    ch = SLACK_CHANNELS
    parts = []

    # ── Canais de leitura direta ───────────────────────────────────
    reads = [
        ("legal-team",                    40),
        ("compliance",                    40),
        ("i-compliance",                  40),
        ("compliance-alerts",             40),
        ("regulatory-updates",            20),
        ("legal-finance",                 30),
        ("legal-cx",                      20),
        ("legal-monitoramento-entries",   20),
        ("mkt-legal",                     20),
        ("p-legal-limites-boqueio-sigap", 20),
        ("solicitacoes-kpmg-legal",       20),
        ("integrity",                     30),
        ("ops-trading",                   20),
        ("ops-sportsbook",                20),
        ("duvidas-igaming",               20),
        ("benchmark",                     30),
        ("i-prediction-markets",          30),
    ]
    for name, limit in reads:
        print(f"  📱 Slack: lendo #{name}...")
        msgs = slack_channel(ch[name], limit=limit)
        parts.append(f"=== #{name} ===\n{fmt_messages(msgs)}")

    # ── Buscas temáticas ───────────────────────────────────────────
    searches = [
        ("prazos concluídos",    "prazo concluído OR entregue OR enviado OR aprovado"),
        ("prazos novos",         "prazo OR deadline OR vencimento OR entrega"),
        ("COAF SIGAP",           "COAF OR SIGAP OR PLD OR AML"),
        ("concorrentes",         "betano OR sportingbet OR bet365 OR blaze OR superbet OR novibet"),
        ("prediction markets",   "prediction markets OR kalshi OR polymarket OR previsões OR mercado de previsão"),
        ("auditoria KPMG",       "KPMG OR auditoria OR questionamento"),
        ("licença SPA",          "SPA/MF OR licença OR portaria OR resolução"),
        ("publicidade mkt",      "publicidade OR marketing OR criativo OR aprovação legal"),
        ("jogo responsável",     "jogo responsável OR autoexclusão OR autolimite OR JR"),
        ("integridade esportiva","integridade OR IBIA OR SIGAP OR manipulação"),
    ]
    for label, query in searches:
        print(f"  🔍 Slack: buscando '{label}'...")
        results = slack_search(query)
        parts.append(f"=== Busca '{label}' ===\n{fmt_search(results)}")

    return "\n\n".join(parts)


def collect_news() -> str:
    parts = []
    for name, url in NEWS_SOURCES:
        print(f"  🌐 {name}...")
        content = fetch_url(url)
        parts.append(f"=== {name} ({url}) ===\n{content}")
    return "\n\n".join(parts)


def update_with_claude(current_html: str, slack_data: str, news_data: str) -> str:
    client    = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    timestamp = brt_now()

    prompt = f"""Você é o bot de atualização do Monitor de Compliance da Pitaco (pitaco.bet.br).

HORÁRIO ATUAL (BRT): {timestamp}

━━━ DADOS DO SLACK ━━━
{slack_data}

━━━ NOTÍCIAS EXTERNAS ━━━
{news_data}

━━━ HTML ATUAL DO DASHBOARD ━━━
{current_html}

━━━ TAREFA ━━━
Esta atualização roda automaticamente a cada poucas horas. Trate o dashboard como um feed vivo — sempre dinâmico, sempre conectado ao Slack e aos prazos reais.

1. NOVOS CARDS — adicione apenas cards com informação NOVA (não duplicar os existentes).
   Abas: AML/CFT, Data Privacy, Responsible Gaming, Sports Integrity, Cenário Internacional, Concorrentes, BETS-México ou Prediction Markets.
   Hierarquia de fontes:
     P1 (máxima confiabilidade): gov.br/coaf, gov.br/anpd, in.gov.br (DOU), SPA/MF, bcb.gov.br
     P2: BNL Data, iGaming Brasil, G&M News, Mediabet
     P3: demais fontes verificadas
     ⚠ Fonte única: confirmado em apenas 1 veículo — adicionar badge-warning e source-warning

   ORDENAÇÃO — REORDENE os cards a cada atualização seguindo esta ordem dentro de cada news-list:
     1º) P1 — mais recente primeiro
     2º) P2 — mais recente primeiro
     3º) P3 — mais recente primeiro
     Último) ⚠ Fonte única — sempre ao final, independente da data
   NÃO use a classe "priority-alta" — use apenas: "news-card".

   DIVISÃO RECENTES vs SEMANAL:
   - id="TABID-recentes": notícias das últimas 6 horas (o que há de mais novo)
   - id="TABID-semanal": notícias de 6 horas a 7 dias atrás
   - Cards com mais de 7 dias: podem ser removidos para não acumular conteúdo obsoleto
   Mapeamento de IDs:
     AML → aml-recentes / aml-semanal
     Sports → sports-recentes / sports-semanal
     Privacy → privacy-recentes / privacy-semanal
     RG → rg-recentes / rg-semanal
     Internacional → intl-tendencias (recentes) / intl-enforcement (semanal)
     Concorrentes → comp-produto (recentes) / comp-juridico (semanal)
     México → mexico-noticias (recentes) / mexico-produto (semanal)
     PM → pm-juridico (recentes) / pm-concorrentes (semanal)
   - Mova cards de -recentes para -semanal quando tiverem mais de 6 horas.
   - Novos cards sempre entram em -recentes.

   Fontes internacionais PM: Kalshi Blog, Polymarket Blog, Reuters, Bloomberg, CFTC.
   Cards de Concorrentes e PM DEVEM ter fonte externa — Slack apenas como insight no slack-thread.
   Para PM use #i-prediction-markets; para insights jurídicos use #regulatory-updates.

   Estrutura de cada card (use EXATAMENTE estas classes):
   <article class="news-card">
     <div class="news-card-header">
       <div class="news-badges">
         <span class="badge badge-[alta|media|baixa]">Alta|Média|Baixa</span>
         <span class="badge badge-br">BR</span>  <!-- badge-intl para internacional -->
         <!-- se fonte única: <span class="badge badge-warning">⚠ Fonte única</span> -->
       </div>
       <div class="news-meta">
         <span class="news-source">NOME DA FONTE</span>
         <span class="news-date">DD mmm YYYY</span>
       </div>
     </div>
     <!-- se fonte única: <div class="source-warning"><span class="source-warning-icon">⚠️</span><span>Confirmado em 1 veículo — verificar em X antes de usar.</span></div> -->
     <h3 class="news-title">TÍTULO</h3>
     <p class="news-body">Resumo em 2-3 linhas.</p>
     <div class="agent-box">
       <div class="agent-header"><span class="agent-icon">📊</span><span class="agent-label">Análise do agente</span></div>
       <p class="agent-text">Análise de impacto para a Pitaco, conectando com contexto do Slack se relevante.</p>
     </div>
     <div class="legal-ref"><span class="legal-icon">⚖️</span><span class="legal-text">Norma · Portaria · Lei relevante</span></div>
     <div class="news-card-footer">
       <a href="URL_REAL" class="footer-link" target="_blank"><span class="footer-link-icon">↗</span> Ver matéria completa · FONTE</a>
       <span class="slack-thread">💬 <span class="slack-channel">#canal</span> ação sugerida baseada no contexto do Slack</span>
     </div>
   </article>

2. PRAZOS — atualização dinâmica obrigatória a cada rodada:
   - TICKER BAR (id="tickerTrack"): reflita o estado atual dos prazos com base no Slack.
     · Prazo concluído mencionado no Slack → ticker-dot "green", ticker-deadline "✓ concluído"
     · Novo prazo mencionado no Slack → adicione ticker-item com cor correta: red=vencido, orange=urgente, green=ok
     · IMPORTANTE: os itens aparecem duplicados no HTML para o loop infinito — mantenha a duplicação.
   - ABA PRAZOS (tab-prazos): atualize os dl-item e stats-row com base nas informações mais recentes do Slack.
     · Prazo concluído → dl-tag "concluido", dl-status-dot "ok"
     · Novo prazo → adicione dl-item na seção correta (Vencidos / Urgentes / Atenção / Concluídos)
     · Stats (Vencidos / Urgentes / Atenção / Concluídos) → recalcule os números

3. SLACK — conecte ativamente os dados de TODOS os canais ao conteúdo:
   Canais e seus usos:
   - #legal-team, #legal-finance, #legal-cx → prazos, decisões, alertas jurídicos → AML/Privacy/RG/Sports
   - #compliance, #i-compliance, #compliance-alerts → alertas de compliance → aba correta conforme tema
   - #regulatory-updates → updates regulatórios do time legal → qualquer aba relevante
   - #legal-monitoramento-entries → monitoramento de entradas suspeitas → AML/CFT
   - #p-legal-limites-boqueio-sigap → limites, bloqueios, SIGAP → Sports Integrity / AML
   - #solicitacoes-kpmg-legal → auditoria KPMG em andamento → AML/CFT
   - #mkt-legal → aprovações de publicidade → prazos de publicidade
   - #integrity → integridade esportiva → Sports Integrity
   - #ops-trading, #ops-sportsbook → operações e alertas de trading → Sports Integrity / AML
   - #duvidas-igaming → dúvidas sobre regulação de iGaming → qualquer aba relevante
   - #benchmark → concorrentes → Concorrentes
   - #i-prediction-markets → prediction markets → PM

4. CONTADORES DAS ABAS — recalcule o total de cards em cada aba (semanal + recentes).

5. TIMESTAMP — atualize o badge "Atualizado HH:MM · DD mmm YYYY" para {timestamp}.

6. NÃO remova cards existentes das listas — apenas mova entre recentes/semanal conforme a idade.

⚠️ Retorne APENAS o HTML completo atualizado, sem markdown, sem explicações, sem ```html.
"""

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=32000,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()


def save(html: str):
    # Salva HTML — o git push no workflow do Actions faz o deploy no GitHub Pages
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("🚀 Monitor de Compliance Pitaco — iniciando atualização...")

    print("\n[1/4] Coletando dados do Slack...")
    slack_data = collect_slack()

    print("\n[2/4] Coletando notícias externas...")
    news_data = collect_news()

    print("\n[3/4] Lendo HTML atual...")
    with open("index.html", "r", encoding="utf-8") as f:
        current_html = f.read()

    print("\n[4/4] Atualizando com Claude API...")
    updated_html = update_with_claude(current_html, slack_data, news_data)

    if len(updated_html) < 1000:
        print("⚠️  HTML retornado muito pequeno — abortando deploy para segurança")
        print(updated_html[:500])
        return

    print("\n[5/5] Salvando HTML (deploy via git push do Actions)...")
    save(updated_html)
    print(f"✅ index.html atualizado")
    print(f"🌐 https://vitoriatrentin-source.github.io/compliance-monitor/")


if __name__ == "__main__":
    main()
