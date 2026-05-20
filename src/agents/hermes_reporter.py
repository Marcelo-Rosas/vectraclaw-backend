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
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger("HermesReporter")

# ── Paleta / estilo fixo ──────────────────────────────────────────────────────
_CSS = """
body{font-family:'Segoe UI',Arial,sans-serif;background:#f4f6f9;margin:0;padding:0}
.wrap{max-width:860px;margin:24px auto;background:#fff;border-radius:8px;
      box-shadow:0 2px 8px rgba(0,0,0,.1);overflow:hidden}
.hdr{background:#1a3a5c;color:#fff;padding:20px 28px}
.hdr h1{margin:0;font-size:20px;font-weight:600}
.hdr p{margin:4px 0 0;font-size:13px;opacity:.8}
.body{padding:24px 28px}
h2{color:#1a3a5c;font-size:15px;margin:24px 0 8px;border-bottom:2px solid #e0e7ef;
   padding-bottom:4px}
table{width:100%;border-collapse:collapse;font-size:13px;margin-bottom:16px}
th{background:#1a3a5c;color:#fff;padding:8px 10px;text-align:left;font-weight:500}
td{padding:7px 10px;border-bottom:1px solid #eaeff5}
tr:nth-child(even) td{background:#f8fafc}
.badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:12px;
       font-weight:600;color:#fff}
.ok{background:#2e7d32} .warn{background:#e65100} .info{background:#1565c0}
.footer{background:#f4f6f9;padding:12px 28px;font-size:11px;color:#888;
        border-top:1px solid #e0e7ef}
"""

# ── Helpers de parse markdown → HTML ─────────────────────────────────────────

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
            # negrito **x** → <strong>x</strong>
            cell = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", cell)
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
    """Converte uma seção em HTML (tabela se houver | no conteúdo, senão parágrafos)."""
    table_lines = [l for l in lines if l.strip().startswith("|")]
    other_lines = [l for l in lines if not l.strip().startswith("|") and l.strip()]

    html = f"<h2>{title}</h2>" if title else ""
    if table_lines:
        html += _md_table_to_html(table_lines)
    for line in other_lines:
        line = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
        if line.startswith("- ") or line.startswith("* "):
            html += f"<ul><li>{line[2:]}</li></ul>"
        else:
            html += f"<p>{line}</p>"
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

def send_smtp(subject: str, html_body: str, to_addrs: list) -> str:
    """Envia via SMTP_SSL usando HERMES_SMTP_* env vars. Retorna Message-Id."""
    server = os.environ["HERMES_SMTP_SERVER"]
    port = int(os.environ["HERMES_SMTP_PORT"])
    user = os.environ["HERMES_EMAIL"]
    pwd = os.environ["HERMES_PASSWORD"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = ", ".join(to_addrs)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(server, port, context=ctx, timeout=30) as s:
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


def entrypoint(task: dict) -> dict:
    """Ponto de entrada chamado pelo agent_daemon para operation_type='oracle-report'."""
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
            msg_id = send_smtp(subject, html_body, recipients)
        except Exception as e:
            logger.error("HermesReporter: falha no envio SMTP — %s", e)
            return {"status": "errored", "error": f"send_smtp failed: {e}"}
        logger.info("HermesReporter: e-mail enviado (prospect). Message-Id=%s", msg_id)
        return {
            "status": "done",
            "message_id": msg_id,
            "subject": subject,
            "recipients": recipients,
            "tokens": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "source": "prospect_outreach"},
            "cost_usd": 0.0,
        }

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
        msg_id = send_smtp(subject, html_body, recipients)
    except Exception as e:
        logger.error("HermesReporter: falha no envio SMTP — %s", e)
        return {"status": "errored", "error": f"send_smtp failed: {e}"}

    logger.info("HermesReporter: e-mail enviado. Message-Id=%s", msg_id)
    return {
        "status": "done",
        "message_id": msg_id,
        "subject": subject,
        "recipients": recipients,
        "tokens": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "source": "template"},
        "cost_usd": 0.0,
    }
