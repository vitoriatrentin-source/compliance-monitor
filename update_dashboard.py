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
    "legal-team":           "C02RHL9GMHC",
    "benchmark":            "C08H223FJ4A",
    "i-prediction-markets": "C09HD5YDM38",  # canal dedicado ao produto de PM
    "regulatory-updates":   "C03J0RWK72M",  # reports mensais do time de legal
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
    print("  📱 Slack: lendo #legal-team...")
    legal = slack_channel(SLACK_CHANNELS["legal-team"])

    print("  📱 Slack: lendo #benchmark...")
    bench = slack_channel(SLACK_CHANNELS["benchmark"])

    print("  📱 Slack: lendo #i-prediction-markets...")
    pm = slack_channel(SLACK_CHANNELS["i-prediction-markets"])

    print("  📱 Slack: lendo #regulatory-updates...")
    reg = slack_channel(SLACK_CHANNELS["regulatory-updates"], limit=10)

    print("  🔍 Slack: buscando prazos concluídos...")
    done  = slack_search("prazo concluído OR entregue OR enviado OR aprovado")

    print("  🔍 Slack: buscando concorrentes...")
    comp  = slack_search("concorrente OR betano OR sportingbet OR bet365 OR blaze OR superbet")

    print("  🔍 Slack: buscando prediction markets...")
    pm_search = slack_search("prediction markets OR kalshi OR polymarket OR previsões OR BTG Trends")

    return f"""
=== #legal-team ===
{fmt_messages(legal)}

=== #benchmark ===
{fmt_messages(bench)}

=== #i-prediction-markets ===
{fmt_messages(pm)}

=== #regulatory-updates (últimas atualizações do time legal) ===
{fmt_messages(reg)}

=== Busca "prazos concluídos" ===
{fmt_search(done)}

=== Busca "concorrentes" ===
{fmt_search(comp)}

=== Busca "prediction markets" ===
{fmt_search(pm_search)}
""".strip()


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
Atualize o dashboard. Regras obrigatórias:

1. NOVOS CARDS — adicione apenas cards com informação NOVA (não duplicar os existentes).
   Aba correta: AML, LGPD, RG, Sports Integrity, Cenário Internacional, Concorrentes, BETS-México ou Prediction Markets.
   Fontes P1 (prioridade máxima): gov.br/coaf, gov.br/anpd, in.gov.br (DOU — apostas/bets), SPA/MF.
   ORDENAÇÃO dentro de cada lista (REORDENE também os cards existentes a cada atualização):
   Ordem obrigatória dentro de cada news-list:
     1º) P1 (gov.br, SPA/MF, DOU) — mais recente primeiro
     2º) P2 (BNL Data, iGaming Brasil, G&M News, Mediabet) — mais recente primeiro
     3º) P3 (demais fontes) — mais recente primeiro
     Último) cards com badge "⚠ Fonte única" — sempre ao final, independente da data
   NÃO use a classe "priority-alta" no article — use apenas: "news-card".

   DIVISÃO SEMANAL vs RECENTES (obrigatório em TODOS os tabs com news-list):
   - id="TABID-semanal": notícias publicadas nos últimos 7 dias
   - id="TABID-recentes": notícias com mais de 7 dias
   Mapeamento de IDs:
     AML → aml-semanal / aml-recentes
     Sports → sports-semanal / sports-recentes
     Privacy → privacy-semanal / privacy-recentes
     RG → rg-semanal / rg-recentes
     Internacional → intl-tendencias (semanal) / intl-enforcement (recentes)
     Concorrentes → comp-produto (semanal) / comp-juridico (recentes)
     México → mexico-noticias (semanal) / mexico-produto (recentes)
     PM → pm-juridico (semanal) / pm-concorrentes (recentes)
   - Cards com mais de 7 dias devem ser movidos de -semanal para -recentes.
   - Novos cards vão sempre em -semanal (se dentro dos últimos 7 dias).
   Fontes P2: BNL Data, iGaming Brasil, G&M News, Mediabet.
   Fontes internacionais PM: Kalshi Blog, Polymarket Blog, Reuters, Bloomberg, CFTC.
   Cards de Concorrentes e Prediction Markets DEVEM ter fonte externa — Slack apenas como insight em card-slack.
   Aba Prediction Markets tem duas sub-abas: "Notícias & Jurídico" (id=pm-juridico) e "Concorrentes" (id=pm-concorrentes).
   Para a aba Prediction Markets, use o #i-prediction-markets como fonte de insights internos (card-slack).
   Use o #regulatory-updates para insights jurídicos e regulatórios dos reports mensais do time de legal.
   Estrutura de cada card (use EXATAMENTE estas classes — não use as antigas):
   <article class="news-card">
     <div class="news-card-header">
       <div class="news-badges">
         <span class="badge badge-PRIORIDADE">Alta|Média|Baixa</span>
         <span class="badge badge-br">BR</span>  <!-- ou badge-intl para internacional -->
         <!-- se fonte única: <span class="badge badge-warning">⚠ Fonte única</span> -->
       </div>
       <div class="news-meta">
         <span class="news-source">NOME DA FONTE</span>
         <span class="news-date">DD mmm YYYY</span>
       </div>
     </div>
     <!-- se fonte única, adicionar aviso: -->
     <!-- <div class="source-warning"><span class="source-warning-icon">⚠️</span><span>Confirmado em 1 veículo — verificar em X antes de usar.</span></div> -->
     <h3 class="news-title">TÍTULO DO CARD</h3>
     <p class="news-body">Resumo em 2-3 linhas.</p>
     <div class="agent-box">
       <div class="agent-header"><span class="agent-icon">📊</span><span class="agent-label">Análise do agente</span></div>
       <p class="agent-text">Análise de impacto para a Pitaco.</p>
     </div>
     <div class="legal-ref"><span class="legal-icon">⚖️</span><span class="legal-text">Norma · Portaria · Lei relevante</span></div>
     <div class="news-card-footer">
       <a href="URL_REAL" class="footer-link" target="_blank"><span class="footer-link-icon">↗</span> Ver matéria completa · FONTE</a>
       <span class="slack-thread">💬 <span class="slack-channel">#canal-slack</span> insight ou ação para a equipe</span>
     </div>
   </article>

2. TICKER BAR (id="tickerTrack") — prazos confirmados como concluídos no Slack → mude a classe do ticker-dot para "green" e o ticker-deadline para "✓ concluído".
   Novos prazos mencionados no Slack → adicione novo ticker-item com ticker-dot "red" (vencido), "orange" (urgente) ou "green" (ok).
   IMPORTANTE: mantenha os itens duplicados para o loop infinito funcionar (os itens aparecem duas vezes no HTML).

3. CONTADORES DAS ABAS — atualize (ex: "AML · 7").

4. TIMESTAMP — atualize "Atualizado às HH:MM" para {timestamp}.

5. NÃO remova nenhum card ou chip existente.

⚠️ Retorne APENAS o HTML completo atualizado, sem markdown, sem explicações, sem ```html.
"""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=16000,
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
