#!/usr/bin/env python3
"""
Monitor de Compliance Pitaco — Script de atualização automática
Roda via GitHub Actions 6x/dia
"""

import os
import re
import zipfile
import requests
import anthropic
from datetime import datetime, timezone, timedelta

# ── Config ────────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
SLACK_TOKEN        = os.environ["SLACK_TOKEN"]
NETLIFY_TOKEN      = os.environ["NETLIFY_TOKEN"]
NETLIFY_SITE_ID    = os.environ.get("NETLIFY_SITE_ID", "0a81f462-de30-46e3-900a-50807c584b46")

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
    "legal-team": "C02RHL9GMHC",
    "benchmark":  "C08H223FJ4A",
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

    print("  🔍 Slack: buscando prazos concluídos...")
    done  = slack_search("prazo concluído OR entregue OR enviado OR aprovado")

    print("  🔍 Slack: buscando concorrentes...")
    comp  = slack_search("concorrente OR betano OR sportingbet OR bet365 OR blaze OR superbet")

    return f"""
=== #legal-team ===
{fmt_messages(legal)}

=== #benchmark ===
{fmt_messages(bench)}

=== Busca "prazos concluídos" ===
{fmt_search(done)}

=== Busca "concorrentes" ===
{fmt_search(comp)}
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
   Fontes P2: BNL Data, iGaming Brasil, G&M News, Mediabet.
   Fontes internacionais PM: Kalshi Blog, Polymarket Blog, Reuters, Bloomberg, CFTC.
   Cards de Concorrentes e Prediction Markets DEVEM ter fonte externa — Slack apenas como insight em card-slack.
   Aba Prediction Markets tem duas sub-abas: "Notícias & Jurídico" (id=pm-juridico) e "Concorrentes" (id=pm-concorrentes).
   Estrutura de cada card:
   <div class="card">
     <div class="card-header">
       <span class="card-title">TÍTULO</span>
       <span class="tag tag-CATEGORIA">FONTE</span>
     </div>
     <p>Resumo em 2 linhas.</p>
     <div class="card-norm"><em>⚖️ Jurídico: análise normativa relevante</em></div>
     <div class="card-link"><a href="URL_REAL" target="_blank">↗ Ver matéria completa · FONTE</a></div>
     <div class="card-slack">💬 #canal-slack — insight ou ação sugerida para a equipe</div>
   </div>

2. DEADLINE BAR — prazos confirmados como concluídos no Slack → adicione chip-status="done"
   Novos prazos mencionados no Slack → adicione nos chips corretos (urgente/atenção).

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


def deploy(html: str) -> dict:
    # Salva HTML atualizado
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

    # Cria zip
    with zipfile.ZipFile("site.zip", "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write("index.html")
        if os.path.exists("netlify.toml"):
            zf.write("netlify.toml")

    # Deploy Netlify
    with open("site.zip", "rb") as f:
        resp = requests.post(
            f"https://api.netlify.com/api/v1/sites/{NETLIFY_SITE_ID}/deploys",
            headers={
                "Authorization": f"Bearer {NETLIFY_TOKEN}",
                "Content-Type": "application/zip",
            },
            data=f.read(),
            timeout=60,
        )
    return resp.json()


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

    print("\n[5/5] Deploy no Netlify...")
    result = deploy(updated_html)
    state  = result.get("state", "unknown")
    dep_id = result.get("id", "?")
    print(f"✅ Deploy {dep_id} → {state}")
    print(f"🌐 https://lighthearted-mochi-b32abf.netlify.app")


if __name__ == "__main__":
    main()
