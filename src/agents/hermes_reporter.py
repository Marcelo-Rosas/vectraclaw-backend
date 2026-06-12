"""
HermesReporter — formata relatório em HTML fixo e envia por SMTP.

Recebe uma task com operation_type='oracle-report'.
Formato esperado em task['description']:
  RECIPIENT: email@exemplo.com[, outro@ex.com]
  SUBJECT: Assunto sugestão
  PARENT_TASK_ID: <uuid>   (opcional)

  ---

  <markdown do relatório>
"""
import html
import logging
import os
import re
import smtplib
import ssl
import json
import urllib.request
import urllib.error
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

logger = logging.getLogger("HermesReporter")

# ── Paleta / estilo fixo ──────────────────────────────────────────────────────
_CSS = """
body {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
    background-color: #f8fafc;
    color: #1e293b;
    margin: 0;
    padding: 0;
    -webkit-font-smoothing: antialiased;
}
.wrap {
    max-width: 680px;
    margin: 40px auto;
    background: #ffffff;
    border-radius: 16px;
    box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.05), 0 8px 10px -6px rgba(0, 0, 0, 0.01);
    overflow: hidden;
    border: 1px solid #e2e8f0;
}
.hdr {
    background: linear-gradient(135deg, #020617, #0f172a);
    color: #ffffff;
    padding: 40px 48px;
    border-bottom: 4px solid #3b82f6;
}
.hdr h1 {
    margin: 0;
    font-size: 26px;
    font-weight: 800;
    letter-spacing: -0.025em;
    line-height: 1.2;
}
.hdr p {
    margin: 12px 0 0;
    font-size: 14px;
    color: #94a3b8;
    font-weight: 500;
}
.body {
    padding: 48px;
}
h2 {
    color: #0f172a;
    font-size: 18px;
    font-weight: 700;
    letter-spacing: -0.01em;
    margin: 36px 0 16px;
    border-bottom: 2px solid #f1f5f9;
    padding-bottom: 10px;
}
h2:first-child {
    margin-top: 0;
}
h3 {
    color: #334155;
    font-size: 15px;
    font-weight: 600;
    margin: 24px 0 12px;
}
p {
    font-size: 15px;
    line-height: 1.6;
    margin: 0 0 16px;
    color: #475569;
}
ul {
    margin: 0 0 20px;
    padding-left: 24px;
}
li {
    font-size: 15px;
    line-height: 1.6;
    color: #475569;
    margin-bottom: 8px;
}
table {
    width: 100%;
    border-collapse: separate;
    border-spacing: 0;
    font-size: 14px;
    margin: 24px 0;
    border-radius: 12px;
    overflow: hidden;
    border: 1px solid #e2e8f0;
}
th {
    background-color: #f8fafc;
    color: #0f172a;
    padding: 14px 18px;
    text-align: left;
    font-weight: 600;
    border-bottom: 1px solid #e2e8f0;
}
td {
    padding: 14px 18px;
    border-bottom: 1px solid #f1f5f9;
    color: #475569;
}
tr:last-child td {
    border-bottom: none;
}
tr:hover td {
    background-color: #f8fafc;
}
code {
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    background-color: #f1f5f9;
    color: #0284c7;
    padding: 3px 6px;
    border-radius: 6px;
    font-size: 13.5px;
    font-weight: 500;
}
em {
    font-style: italic;
    color: #64748b;
}
.footer {
    background-color: #f8fafc;
    padding: 24px 48px;
    font-size: 13px;
    color: #94a3b8;
    text-align: center;
    border-top: 1px solid #e2e8f0;
}
"""

# ── Helpers de parse markdown → HTML ─────────────────────────────────────────

def _apply_inline_formatting(text: str) -> str:
    """Aplica formatação inline básica: negrito, itálico e código inline."""
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\w)_(.+?)(?<!\\)_(?!\w)", r"<em>\1</em>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    return text


def _md_table_to_html(lines: list[str]) -> str:
    """Converte bloco de tabela markdown em <table> HTML."""
    rows = []
    for line in lines:
        line = line.strip()
        if not line or re.match(r"^\|[-| :]+\|$", line):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        rows.append(cells)
    if not rows:
        return ""
    html = ["<table><tr>"]
    for cell in rows[0]:
        html.append(f"<th>{cell}</th>")
    html.append("</tr>")
    for row in rows[1:]:
        html.append("<tr>")
        for cell in row:
            cell = _apply_inline_formatting(cell)
            html.append(f"<td>{cell}</td>")
        html.append("</tr>")
    html.append("</table>")
    return "".join(html)


def _parse_markdown_sections(md: str) -> list[tuple[str, list[str]]]:
    """
    Divide o markdown em seções (## Título, linhas).
    Retorna lista de (titulo, linhas).
    """
    sections: list[tuple[str, list[str]]] = []
    current_title = ""
    current_lines: list[str] = []
    for line in md.splitlines():
        if line.startswith("## "):
            if current_title or current_lines:
                sections.append((current_title, current_lines))
            current_title = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_title or current_lines:
        sections.append((current_title, current_lines))
    return sections


def _section_to_html(title: str, lines: list[str]) -> str:
    """Converte uma seção em HTML mantendo a ordem sequencial dos elementos."""
    html = f"<h2>{title}</h2>" if title else ""
    
    in_list = False
    in_table = False
    table_rows = []
    
    def flush_table():
        nonlocal in_table, table_rows
        out = ""
        if table_rows:
            out = _md_table_to_html(table_rows)
            table_rows = []
        in_table = False
        return out
        
    def flush_list():
        nonlocal in_list
        out = ""
        if in_list:
            out = "</ul>"
            in_list = False
        return out

    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            if in_table:
                html += flush_table()
            if in_list:
                html += flush_list()
            continue
            
        if line_stripped.startswith("|"):
            if in_list:
                html += flush_list()
            in_table = True
            table_rows.append(line_stripped)
        elif line_stripped.startswith("- ") or line_stripped.startswith("* "):
            if in_table:
                html += flush_table()
            if not in_list:
                html += "<ul>"
                in_list = True
            item_text = line_stripped[2:]
            item_formatted = _apply_inline_formatting(item_text)
            html += f"<li>{item_formatted}</li>"
        elif line_stripped.startswith("### "):
            if in_table:
                html += flush_table()
            if in_list:
                html += flush_list()
            subhead_text = line_stripped[4:]
            subhead_formatted = _apply_inline_formatting(subhead_text)
            html += f"<h3>{subhead_formatted}</h3>"
        else:
            if in_table:
                html += flush_table()
            if in_list:
                html += flush_list()
            
            line_formatted = _apply_inline_formatting(line_stripped)
            html += f"<p>{line_formatted}</p>"
            
    if in_table:
        html += flush_table()
    if in_list:
        html += flush_list()
        
    return html


def render_html(
    markdown_report: str,
    subject: str,
    *,
    company_name: str | None = None,
    report_type: str | None = None,
    header_title: str | None = None,
    footer_text: str | None = None,
) -> str:
    """
    Converte relatório markdown em HTML com template consistente.
    Mesmo input → mesmo output sempre.

    Regra de Ouro #2: header/footer NÃO são tenant-locked. Derivam de
    `company_name` (de companies.name) + `report_type` (genérico, do payload).
    `header_title`/`footer_text` explícitos têm precedência (override).
    """
    company = (company_name or "VectraClaw").strip()
    rtype = (report_type or "").strip()
    if header_title is None:
        header_title = f"{company} — {rtype}" if rtype else company
    if footer_text is None:
        footer_text = f"Relatório gerado automaticamente • {company} • VectraClaw"
    sections = _parse_markdown_sections(markdown_report)

    body_html = ""
    for title, lines in sections:
        # Seção de destaque: Resumo vira tabela de badges
        if title == "Resumo":
            body_html += "<h2>Resumo</h2>"
            table_lines = [l for l in lines if l.strip().startswith("|")]
            body_html += _md_table_to_html(table_lines)
        else:
            body_html += _section_to_html(title, lines)

    from datetime import datetime
    ts = datetime.now().strftime("%d/%m/%Y %H:%M")
    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="utf-8"><style>{_CSS}</style></head>
<body>
<div class="wrap">
  <div class="hdr">
    <h1>{header_title}</h1>
    <p>{subject} &nbsp;|&nbsp; Gerado em {ts}</p>
  </div>
  <div class="body">
    {body_html}
  </div>
  <div class="footer">{footer_text}</div>
</div>
</body></html>"""
    return html


# ── SMTP ─────────────────────────────────────────────────────────────────────

def _smtp_from_env() -> Dict[str, Any]:
    return {
        "server": os.environ["HERMES_SMTP_SERVER"],
        "port": int(os.environ["HERMES_SMTP_PORT"]),
        "user": os.environ["HERMES_EMAIL"],
        "password": os.environ["HERMES_PASSWORD"],
    }


def send_email(
    subject: str,
    html_body: str,
    to_addrs: List[str],
    *,
    credentials: Optional[Dict[str, Any]] = None,
    specialty_type: str = "smtp"
) -> str:
    """Envia via API REST (Resend) ou SMTP fallback."""
    if specialty_type == "resend_api":
        if not credentials:
            raise ValueError("Credenciais não fornecidas para resend_api")
        api_key = credentials.get("api_key")
        from_email = credentials.get("from_email")
        if not api_key or not from_email:
            raise ValueError("api_key e from_email são obrigatórios para resend_api")
        
        url = "https://api.resend.com/emails"
        payload = {
            "from": from_email,
            "to": to_addrs,
            "subject": subject,
            "html": html_body
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result.get("id", "resend-ok")
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8")
            logger.error("Falha Resend API: %s - %s", e.code, err_body)
            raise ValueError(f"Resend API Error: {err_body}")

    # Fallback SMTP
    if credentials is None:
        creds = _smtp_from_env()
    else:
        creds = credentials
    server = creds["server"]
    port = int(creds["port"])
    user = creds["user"]
    pwd = creds["password"]
    
    # O email remetente deve vir das credenciais explícitamente se for possível,
    # caso contrário, usa o 'user' do SMTP. Nunca hardcodado.
    from_email = creds.get("from_email") or user

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = ", ".join(to_addrs)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(server, port, context=ctx, timeout=30) as s:
            s.login(user, pwd)
            s.send_message(msg)
    else:
        with smtplib.SMTP(server, port, timeout=30) as s:
            s.ehlo()
            s.starttls(context=ctx)
            s.ehlo()
            s.login(user, pwd)
            s.send_message(msg)

    return msg.get("Message-Id", "")


# ── Parser da descrição da task ───────────────────────────────────────────────

def _parse_task_description(desc: str) -> tuple:
    """Extrai (recipients: list[str], subject_hint: str, markdown: str)."""
    recipient_match = re.search(r"^RECIPIENT:\s*(.+)$", desc, re.M)
    subject_match = re.search(r"^SUBJECT:\s*(.+)$", desc, re.M)

    recipients = []
    if recipient_match:
        recipients = [r.strip() for r in recipient_match.group(1).split(",") if r.strip()]

    subject_hint = subject_match.group(1).strip() if subject_match else ""

    if "---\n\n" in desc:
        markdown = desc.split("---\n\n", 1)[-1]
    elif "---\n" in desc:
        markdown = desc.split("---\n", 1)[-1]
    else:
        markdown = desc

    return recipients, subject_hint, markdown


# ── Entrypoint ────────────────────────────────────────────────────────────────

def _render_prospect_outreach_plain(subject: str, body_plain: str) -> str:
    """HTML mínimo para abordagem comercial (texto vindo do Oracle / prospect)."""
    safe = html.escape(body_plain or "").replace("\n", "<br />\n")
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="utf-8"><title>{html.escape(subject)}</title></head>
<body style="font-family:'Segoe UI',Arial,sans-serif;line-height:1.55;max-width:720px;margin:24px auto;padding:0 16px;color:#1a1a1a">
  <p style="font-size:13px;color:#666">Vectra Cargo — mensagem de abordagem</p>
  <div style="margin-top:16px">{safe}</div>
</body></html>"""


def _render_gymsite_welcome(nome: str, access_code: str) -> str:
    """Template fixo para o e-mail de boas-vindas do lead GymSite (GYM-13)."""
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: 'Inter', sans-serif; background-color: #f8fafc; color: #1e293b; margin: 0; padding: 40px; }}
    .box {{ background: #fff; max-width: 600px; margin: 0 auto; padding: 40px; border-radius: 12px; border: 1px solid #e2e8f0; }}
    h1 {{ font-size: 24px; font-weight: 700; color: #0f172a; margin-top: 0; }}
    .code-box {{ background: #f1f5f9; border: 1px dashed #cbd5e1; padding: 16px; text-align: center; font-size: 20px; font-family: monospace; font-weight: bold; color: #3b82f6; border-radius: 8px; margin: 24px 0; letter-spacing: 2px; }}
    .warning {{ font-size: 13px; color: #64748b; text-align: center; margin-top: -16px; margin-bottom: 24px; }}
    ul {{ padding-left: 20px; }}
    li {{ margin-bottom: 8px; line-height: 1.5; }}
    .btn {{ display: inline-block; background: #3b82f6; color: #fff; padding: 14px 28px; text-decoration: none; border-radius: 6px; font-weight: 600; text-align: center; margin-top: 24px; }}
    .footer {{ font-size: 13px; color: #94a3b8; text-align: center; margin-top: 40px; }}
  </style>
</head>
<body>
  <div class="box">
    <h1>Olá, {html.escape(nome)}!</h1>
    <p>Seu acesso exclusivo à plataforma GymSite Intelligence foi liberado.</p>
    <div class="code-box">{html.escape(access_code)}</div>
    <div class="warning">Este código dá direito a apenas 1 consulta completa. Não compartilhe.</div>
    <p>O que você vai encontrar no seu relatório:</p>
    <ul>
      <li>Análise de concorrência e raio de influência por geolocalização</li>
      <li>Projeção financeira e ponto de equilíbrio do negócio</li>
      <li>Relatório PDF completo gerado por IA em minutos</li>
    </ul>
    <div style="text-align: center;">
      <a href="https://gymsite.vectracargo.com.br/acesso?code={access_code}" class="btn">Acessar Meu Relatório</a>
    </div>
  </div>
  <div class="footer">VectraCargo — Inteligência de dados para o seu negócio</div>
</body>
</html>"""


def _build_workflow_report_markdown(parent_task_id: str) -> str:
    """Gera markdown do relatório a partir das outputs dos siblings de um workflow.

    Cumpre a promessa documentada em ``kronos_planner.py:270-282``: quando o
    Step 3 (oracle-report) é materializado num workflow tipo kronos_pipeline,
    o handler aqui passa a montar o relatório automaticamente lendo
    ``parent_task.output_json`` + siblings.

    Retorna ``""`` se não conseguir resolver (sem supabase, parent não acha,
    sem siblings). Nesse caso o entrypoint cai no flow legado que exigia
    markdown em ``task.description``.
    """
    from src.api import supabase  # lazy: evita circular import
    from datetime import datetime

    if not supabase or not parent_task_id:
        return ""

    try:
        pres = (
            supabase.table("tasks").select("*").eq("id", parent_task_id).limit(1).execute()
        )
        if not pres.data:
            return ""
        parent = pres.data[0]
        sres = (
            supabase.table("tasks")
            .select("*")
            .eq("parent_task_id", parent_task_id)
            .order("created_at")
            .execute()
        )
        siblings = [s for s in (sres.data or []) if s.get("id") != parent_task_id]
    except Exception as exc:
        logger.warning("HermesReporter: build_workflow_report falhou: %s", exc)
        return ""

    wf_slug = (parent.get("input_json") or {}).get("workflowSlug", "workflow")
    when = datetime.now().strftime("%d/%m/%Y %H:%M")

    total_cat = total_unc = total_fail = 0
    for s in siblings:
        cat = (s.get("output_json") or {}).get("categorization") or {}
        total_cat += int(cat.get("lines_categorized") or 0)
        total_unc += int(cat.get("lines_unclassified") or 0)
        total_fail += int(cat.get("lines_failed") or 0)
    total = total_cat + total_unc + total_fail
    pct = (total_cat / total * 100) if total else 0.0

    lines = [f"## Pipeline `{wf_slug}` — {when}", ""]

    if total > 0:
        lines += [
            "## Totais consolidados",
            "",
            "| Métrica | Valor |",
            "|---|---|",
            f"| Linhas processadas | {total} |",
            f"| Categorizadas | **{total_cat}** ({pct:.1f}%) |",
            f"| Sem regra (Verificar) | {total_unc} |",
            f"| Falhas técnicas | {total_fail} |",
            "",
        ]

    lines += ["## Detalhamento por etapa", ""]
    for s in siblings:
        title = s.get("title") or "?"
        status = s.get("status") or "?"
        badge = "✅" if status == "done" else ("❌" if status in ("errored", "blocked") else "⏳")
        lines.append(f"### {badge} {title}")
        lines.append(f"_Status: `{status}`_")
        lines.append("")
        out = s.get("output_json") or {}
        if out.get("file_processed"):
            lines.append(f"- **Arquivo processado:** `{out['file_processed']}`")
        cat = out.get("categorization") or {}
        if cat:
            lines.append(
                f"- **Categorização:** {cat.get('lines_categorized', 0)} ok / "
                f"{cat.get('lines_unclassified', 0)} sem regra / "
                f"{cat.get('lines_failed', 0)} falhas"
            )
        if out.get("screenshot_path"):
            lines.append(f"- Screenshot: `{out['screenshot_path']}`")
        err = (out.get("error_detail") or {}).get("message")
        if err:
            lines.append(f"- **Erro:** {err}")
        lines.append("")

    return "\n".join(lines)


def _resolve_company_name(company_id: str | None) -> str:
    """Lê companies.name (catalog-driven). Fallback genérico 'VectraClaw' —
    nunca 'Vectra Cargo' cravado (Regra #2: header do e-mail não é tenant-lock)."""
    if not company_id:
        return "VectraClaw"
    try:
        from src.api import supabase
        if supabase:
            r = (
                supabase.table("companies")
                .select("name")
                .eq("company_id", company_id)
                .limit(1)
                .execute()
            )
            name = ((r.data[0].get("name") if r.data else None) or "").strip()
            if name:
                return name
    except Exception as exc:
        logger.warning("HermesReporter: falha ao ler companies.name (%s)", exc)
    return "VectraClaw"


def entrypoint(task: dict, supabase: Any = None) -> dict:
    """Ponto de entrada chamado pelo agent_daemon para operation_type='oracle-report'."""
    from src.agent_ids import HERMES_AGENT_ID
    from src.services.adapter_field_resolve import load_mcp_imap_smtp_credentials

    company_id = str(task.get("company_id") or "").strip()
    smtp_creds = (
        load_mcp_imap_smtp_credentials(
            supabase,
            company_id,
            agent_id=HERMES_AGENT_ID,
        )
        if supabase and company_id
        else None
    )
    if not smtp_creds:
        logger.warning(
            "HermesReporter: mcp-imap incompleto (smtp_host/port/email/password) — "
            "preencha Connectors ou HERMES_SMTP_* env. task=%s",
            task.get("id"),
        )
        
    resolved_config = task.get("_resolved_config") or {}
    api_key = resolved_config.get("api_key")
    from_email = resolved_config.get("from_email")
    
    specialty_type = "smtp"
    if api_key and from_email:
        specialty_type = "resend_api"
        # Substitui credenciais SMTP pelo Resend se presentes na especialidade
        smtp_creds = {"api_key": api_key, "from_email": from_email}
        logger.info("HermesReporter: Configurada especialidade resend_api para o envio.")

    desc = task.get("description", "")
    recipients, subject_hint, markdown = _parse_task_description(desc)
    input_json = task.get("input_json") or {}

    # VEC-413 alignment: fallback ao _resolved_config (agent_specialty_configs)
    # quando task.description não traz RECIPIENT explícito. Mantém retrocompat
    # com tasks legadas que ainda passam KEY=VALUE pela description.
    if not recipients:
        resolved_cfg = task.get("_resolved_config") or {}
        cfg_recipient = str(resolved_cfg.get("recipient") or "").strip()
        if cfg_recipient:
            recipients = [r.strip() for r in cfg_recipient.split(",") if r.strip()]
            logger.info(
                "HermesReporter: recipients resolvidos via _resolved_config: %s",
                recipients,
            )

    if not recipients:
        logger.error("HermesReporter: nenhum destinatário encontrado na task %s", task.get("id"))
        return {"status": "errored", "error": "no recipients"}

    # Abordagem de prospect (texto plano em input_json; evita template de auditoria Kronos)
    if input_json.get("prospect_outreach"):
        body_plain = str(input_json.get("plain_body") or "").strip()
        if not body_plain and markdown.strip():
            body_plain = markdown.strip()
        if not body_plain:
            logger.error("HermesReporter: corpo vazio (prospect) task %s", task.get("id"))
            return {"status": "errored", "error": "empty prospect body"}
        subject = (
            str(input_json.get("plain_subject") or "").strip()
            or subject_hint
            or "Contato — Vectra Cargo"
        )
        logger.info("HermesReporter: prospect outreach → %s assunto=%s", recipients, subject)
        try:
            html_body = _render_prospect_outreach_plain(subject, body_plain)
        except Exception as e:
            logger.error("HermesReporter: render prospect falhou — %s", e)
            return {"status": "errored", "error": f"render prospect failed: {e}"}
        logger.info("HermesReporter: enviando e-mail (prospect)")
        try:
            msg_id = send_email(subject, html_body, recipients, credentials=smtp_creds, specialty_type=specialty_type)
        except Exception as e:
            logger.error("HermesReporter: falha no envio de e-mail — %s", e)
            return {"status": "errored", "error": f"send_email failed: {e}"}
        logger.info("HermesReporter: e-mail enviado (prospect). Message-Id=%s", msg_id)
        return {
            "status": "done",
            "message_id": msg_id,
            "subject": subject,
            "recipients": recipients,
            "tokens": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "source": "prospect_outreach"},
            "cost_usd": 0.0,
        }

    # Fluxo Especial para Boas Vindas do GymSite (GYM-13)
    if input_json.get("gymsite_welcome"):
        nome = str(input_json.get("nome") or "Visitante")
        access_code = str(input_json.get("access_code") or "")
        subject = f"Seu acesso ao GymSite chegou — {access_code}"
        
        try:
            html_body = _render_gymsite_welcome(nome, access_code)
            logger.info("HermesReporter: enviando e-mail de boas-vindas GymSite para %s", recipients)
            msg_id = send_email(subject, html_body, recipients, credentials=smtp_creds, specialty_type=specialty_type)
            return {
                "status": "done",
                "message_id": msg_id,
                "subject": subject,
                "recipients": recipients,
                "tokens": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "source": "gymsite_welcome"},
                "cost_usd": 0.0,
            }
        except Exception as e:
            logger.error("HermesReporter: falha no gymsite welcome e-mail — %s", e)
            return {"status": "errored", "error": f"send_email failed: {e}"}

    # VEC-413 align: se markdown vazio mas task pertence a um workflow,
    # buscar parent + siblings e gerar relatório automaticamente. Cumpre o
    # acordo documentado em kronos_planner.py:270-282.
    if not markdown.strip():
        parent_id = task.get("parent_task_id")
        if parent_id:
            markdown = _build_workflow_report_markdown(parent_id)
            if markdown:
                logger.info(
                    "HermesReporter: markdown sintetizado do workflow parent_task=%s",
                    parent_id,
                )

    if not markdown.strip():
        logger.error("HermesReporter: relatório vazio na task %s", task.get("id"))
        return {"status": "errored", "error": "empty markdown body"}

    # Catalog-driven: company de companies.name; report_type do payload
    # (input_json.report_type ou REPORT_TYPE na desc), genérico — não "Kronos".
    company_name = _resolve_company_name(task.get("company_id"))
    rt_match = re.search(r"^REPORT_TYPE:\s*(.+)$", desc, re.M)
    report_type = (
        str(input_json.get("report_type") or "").strip()
        or (rt_match.group(1).strip() if rt_match else "")
        or None
    )
    subject = subject_hint or (
        f"{report_type} — {company_name}" if report_type else f"Relatório — {company_name}"
    )
    logger.info("HermesReporter: renderizando HTML para '%s' → %s", subject, recipients)

    try:
        html_body = render_html(
            markdown, subject, company_name=company_name, report_type=report_type
        )
    except Exception as e:
        logger.error("HermesReporter: render_html falhou — %s", e)
        return {"status": "errored", "error": f"render_html failed: {e}"}

    logger.info("HermesReporter: enviando e-mail")
    try:
        msg_id = send_email(subject, html_body, recipients, credentials=smtp_creds, specialty_type=specialty_type)
    except Exception as e:
        logger.error("HermesReporter: falha no envio de e-mail — %s", e)
        return {"status": "errored", "error": f"send_email failed: {e}"}

    logger.info("HermesReporter: e-mail enviado. Message-Id=%s", msg_id)
    return {
        "status": "done",
        "message_id": msg_id,
        "subject": subject,
        "recipients": recipients,
        "tokens": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "source": "template"},
        "cost_usd": 0.0,
    }
