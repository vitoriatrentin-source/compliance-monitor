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
    # ── Compliance Central ──────────────────────────────────────────
    "compliance":                    "C03N4C6LBN3",
    "i-compliance":                  "C097EDPJYGZ",
    "compliance-alerts":             "C066KQD4P0E",
    "regulatory-updates":            "C03J0RWK72M",
    "regulatory-tech-alerts":        "C095WRCJBU0",
    # ── Legal ───────────────────────────────────────────────────────
    "legal-team":                    "C02RHL9GMHC",
    "legal-finance":                 "C061CELPX5L",
    "legal-cx":                      "C05HEMXEJRL",
    "legal-monitoramento-entries":   "C0A2LFG4X1S",
    "mkt-legal":                     "C08AM6S7R47",
    "aprovacoes-criativos-legal":    "C071YJPMB52",
    "p-legal-limites-boqueio-sigap": "C09U4MHR5TK",
    "solicitacoes-kpmg-legal":       "C09TVKGD02X",
    "questionamentos-kpmg":          "C0ADKVB2U20",
    # ── AML / PLD ───────────────────────────────────────────────────
    "aml-rg-vip-hub":                "C091VGU5LPN",   # hub central AML + JR + VIP
    "aml-alerts":                    "C07U18M098Q",
    "aml-lupa-entries":              "C09B7VCUHE3",
    # ── SIGAP ───────────────────────────────────────────────────────
    "sigap-alerts":                  "C0854U81WAY",
    "p-sigap-impedimentos":          "C09K17GR4Q1",
    # ── Jogo Responsável ────────────────────────────────────────────
    "temp-jogo-responsavel":         "C0944K2R5FB",
    "alertas-jogo-responsavel":      "C0A36KSLZNC",
    "vips-jr":                       "C0A8RKTL6H0",
    "p-alerta-jogo-cassino":         "C0AJCLPK0A0",
    # ── KYC / Usuários ──────────────────────────────────────────────
    "p-integracao-idwall":           "C08VCGS2W7K",
    "vip-solicitacao-comprovantes":  "C09SQNW10JJ",
    "limited-users":                 "C07N181P0K0",
    "checkpoint-alerts":             "C07U7RVK4RH",
    "temp-anti-fraude-cx":           "C07JJ30FQV9",
    "p-salve-aceite-no-cadastro":    "C0AKF29VA8G",
    "p-geolocalizacao":              "C0ABBC5BF9A",
    # ── Integridade Esportiva ────────────────────────────────────────
    "integrity":                     "C08M57LG8HL",
    "ops-trading":                   "C0AM19UCH5H",
    "ops-sportsbook":                "C0AM18Z5AJF",
    # ── Risco / Fraude ───────────────────────────────────────────────
    "risk-alerts":                   "C07J41Z494K",
    "betting-risk-notifications":    "C07TH8RD1D2",
    "withdrawal-alerts":             "C08EKM9ERFD",
    "vip-withdraws-alerts":          "C09419GL52P",
    "annomaly-alerts":               "C09C7S86LH1",
    "security-alerts":               "C04UAALC069",
    "security-news":                 "C0A2ZFKRK1U",
    # ── Benchmark & PM ──────────────────────────────────────────────
    "benchmark":                     "C08H223FJ4A",
    "i-prediction-markets":          "C09HD5YDM38",
    "prediction-alerts":             "C0AATMVHF8R",
    # ── Operações com impacto regulatório ───────────────────────────
    "duvidas-igaming":               "C09K9T9BTD5",
    "igaming-ops":                   "C083HNNFU94",
    "ops-apr":                       "C0AN1UY40Q0",
    "mercado-abertura-fechamento":   "C02E0DJQWKF",
    # ── Parceiro KYC externo ─────────────────────────────────────────
    "caf-reidopitaco":               "C089TPHLBS5",   # CAF — provedor KYC
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

    # ── Canais de leitura direta (ordenados por prioridade) ────────
    reads = [
        # Compliance central
        ("compliance",                    40),
        ("i-compliance",                  40),
        ("compliance-alerts",             40),
        ("regulatory-updates",            30),
        ("regulatory-tech-alerts",        30),
        # AML / PLD
        ("aml-rg-vip-hub",               40),
        ("aml-alerts",                    40),
        ("aml-lupa-entries",              30),
        # SIGAP
        ("sigap-alerts",                  40),
        ("p-sigap-impedimentos",          20),
        # Legal
        ("legal-team",                    40),
        ("legal-finance",                 30),
        ("legal-cx",                      20),
        ("legal-monitoramento-entries",   30),
        ("mkt-legal",                     20),
        ("aprovacoes-criativos-legal",    20),
        ("p-legal-limites-boqueio-sigap", 20),
        ("solicitacoes-kpmg-legal",       20),
        ("questionamentos-kpmg",          20),
        # Jogo Responsável
        ("temp-jogo-responsavel",         30),
        ("alertas-jogo-responsavel",      30),
        ("vips-jr",                       20),
        ("p-alerta-jogo-cassino",         20),
        # KYC / Usuários
        ("p-integracao-idwall",           20),
        ("vip-solicitacao-comprovantes",  20),
        ("limited-users",                 20),
        ("checkpoint-alerts",             20),
        ("temp-anti-fraude-cx",           20),
        # Integridade Esportiva
        ("integrity",                     30),
        ("ops-trading",                   20),
        ("ops-sportsbook",                20),
        # Risco / Fraude
        ("risk-alerts",                   20),
        ("betting-risk-notifications",    20),
        ("withdrawal-alerts",             20),
        ("annomaly-alerts",               20),
        ("security-alerts",               20),
        # Benchmark & PM
        ("benchmark",                     30),
        ("i-prediction-markets",          30),
        ("prediction-alerts",             20),
        # Operações
        ("duvidas-igaming",               20),
        ("mercado-abertura-fechamento",   20),
        # KYC externo
        ("caf-reidopitaco",               20),
    ]
    for name, limit in reads:
        print(f"  📱 Slack: lendo #{name}...")
        msgs = slack_channel(ch[name], limit=limit)
        parts.append(f"=== #{name} ===\n{fmt_messages(msgs)}")

    # ── Buscas temáticas ───────────────────────────────────────────
    searches = [
        ("prazos concluídos",     "prazo concluído OR entregue OR enviado OR aprovado"),
        ("prazos novos",          "prazo OR deadline OR vencimento OR entrega"),
        ("COAF SIGAP PLD",        "COAF OR SIGAP OR PLD OR AML OR lavagem"),
        ("concorrentes",          "betano OR sportingbet OR bet365 OR blaze OR superbet OR novibet"),
        ("prediction markets",    "prediction markets OR kalshi OR polymarket OR previsões"),
        ("auditoria KPMG",        "KPMG OR auditoria OR questionamento"),
        ("licença SPA portaria",  "SPA/MF OR licença OR portaria OR resolução OR SPA"),
        ("publicidade aprovação", "publicidade OR criativo OR aprovação legal"),
        ("jogo responsável JR",   "jogo responsável OR autoexclusão OR autolimite OR JR"),
        ("integridade esportiva", "integridade OR IBIA OR manipulação OR aposta suspeita"),
        ("fraude KYC",            "fraude OR KYC OR idwall OR identidade OR documento"),
        ("LGPD privacidade",      "LGPD OR ANPD OR dados pessoais OR privacidade"),
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
   Compliance: #compliance, #i-compliance, #compliance-alerts, #regulatory-updates, #regulatory-tech-alerts
   AML/PLD: #aml-rg-vip-hub (hub central), #aml-alerts, #aml-lupa-entries → aba AML/CFT
   SIGAP: #sigap-alerts, #p-sigap-impedimentos, #p-legal-limites-boqueio-sigap → Sports Integrity / AML
   Legal: #legal-team, #legal-finance, #legal-cx, #legal-monitoramento-entries → prazos e decisões
   Publicidade: #mkt-legal, #aprovacoes-criativos-legal → prazos de aprovação de criativos
   KPMG: #solicitacoes-kpmg-legal, #questionamentos-kpmg → AML/CFT
   Jogo Responsável: #temp-jogo-responsavel, #alertas-jogo-responsavel, #vips-jr, #p-alerta-jogo-cassino → aba RG
   KYC/Fraude: #p-integracao-idwall, #vip-solicitacao-comprovantes, #limited-users, #checkpoint-alerts, #temp-anti-fraude-cx → Privacy/AML
   Integridade: #integrity, #ops-trading, #ops-sportsbook → Sports Integrity
   Risco: #risk-alerts, #betting-risk-notifications, #withdrawal-alerts, #annomaly-alerts, #security-alerts → AML/Sports
   Benchmark: #benchmark → Concorrentes
   PM: #i-prediction-markets, #prediction-alerts → Prediction Markets
   KYC externo: #caf-reidopitaco → Privacy / AML

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
