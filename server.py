#!/usr/bin/env python3
import json
import os
import smtplib
import ssl
import urllib.error
import urllib.request
from email.mime.text import MIMEText
from email.utils import formataddr, parseaddr
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_from_directory

ROOT = Path(__file__).resolve().parent
app = Flask(__name__, static_folder=None)

MAIL_TO_DEFAULT = "leticiaapeiron@gmail.com"


def load_env():
    path = ROOT / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_env()


def mail_to():
    return (os.environ.get("MAIL_TO") or MAIL_TO_DEFAULT).strip()


def text(value):
    return str(value or "").strip()


def valid_email(value):
    addr = parseaddr(value)[1]
    return "@" in addr and "." in addr.split("@")[-1] and " " not in addr


def build_body(data):
    produtos = data.get("produtos") or []
    lines = [
        "SOLICITAÇÃO DE ORÇAMENTO - STAR FITNESS",
        "",
        "CLIENTE",
        "Nome: " + text(data.get("nome")),
        "E-mail: " + text(data.get("email")),
        "Telefone/WhatsApp: " + text(data.get("tel")),
        "Cidade/UF: " + text(data.get("cidade")),
        "Academia/Empresa: " + text(data.get("empresa")),
        "",
        "PRODUTOS",
    ]
    total_unidades = 0
    for i, item in enumerate(produtos, 1):
        nome = text(item.get("nome"))
        qtd = int(item.get("quantidade") or 0)
        total_unidades += qtd
        ref = text(item.get("ref") or item.get("codigo"))
        cat = text(item.get("categoria"))
        extra = []
        if ref:
            extra.append("cód. " + ref)
        if cat:
            extra.append(cat)
        suffix = (" (" + ", ".join(extra) + ")") if extra else ""
        lines.append("%d. %s%s - Quantidade: %s" % (i, nome, suffix, qtd))
    total_produtos = len(produtos)
    lines.extend(
        [
            "",
            "Total de produtos: %s" % total_produtos,
            "Total de unidades: %s" % total_unidades,
            "",
            "MENSAGEM",
            text(data.get("msg") or data.get("mensagem")),
        ]
    )
    return "\n".join(lines)


def send_resend(subject, body, reply_to):
    key = text(os.environ.get("RESEND_API_KEY"))
    if not key:
        return False
    sender = text(os.environ.get("MAIL_FROM") or os.environ.get("SMTP_FROM")) or "Star Fitness <beth.t@example.com>"
    payload = {
        "from": sender,
        "to": [mail_to()],
        "subject": subject,
        "text": body,
    }
    if valid_email(reply_to):
        payload["reply_to"] = reply_to
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return 200 <= resp.status < 300
    except urllib.error.URLError:
        return False


def send_smtp(subject, body, reply_to):
    host = text(os.environ.get("SMTP_HOST"))
    user = text(os.environ.get("SMTP_USER"))
    password = os.environ.get("SMTP_PASSWORD") or ""
    if not host or not user or not password:
        return False
    port = int(os.environ.get("SMTP_PORT") or 587)
    sender = text(os.environ.get("SMTP_FROM") or os.environ.get("MAIL_FROM") or user)
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = formataddr(("Star Fitness", sender))
    msg["To"] = mail_to()
    if valid_email(reply_to):
        msg["Reply-To"] = reply_to
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=20) as smtp:
                smtp.login(user, password)
                smtp.sendmail(sender, [mail_to()], msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=20) as smtp:
                smtp.ehlo()
                smtp.starttls(context=ssl.create_default_context())
                smtp.login(user, password)
                smtp.sendmail(sender, [mail_to()], msg.as_string())
        return True
    except Exception:
        return False


def send_formsubmit(subject, body, reply_to, data):
    payload = {
        "_subject": subject,
        "_template": "box",
        "_captcha": "false",
        "nome": text(data.get("nome")),
        "email": text(data.get("email") or reply_to),
        "telefone": text(data.get("tel")),
        "cidade": text(data.get("cidade")),
        "empresa": text(data.get("empresa")),
        "mensagem": text(data.get("msg")),
        "mensagem_completa": body,
        "produtos": json.dumps(data.get("produtos") or [], ensure_ascii=False),
        "total_produtos": data.get("total_produtos"),
        "total_unidades": data.get("total_unidades"),
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://starfitnessstore.com",
        "Referer": "https://starfitnessstore.com/",
    }
    try:
        from curl_cffi import requests as cfreq
        resp = cfreq.post(
            "https://formsubmit.co/ajax/" + mail_to(),
            json=payload,
            headers=headers,
            impersonate="chrome",
            timeout=30,
        )
        raw = resp.text
        status = resp.status_code
    except Exception:
        req = urllib.request.Request(
            "https://formsubmit.co/ajax/" + mail_to(),
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read().decode("utf-8", "replace")
                status = resp.status
        except urllib.error.URLError:
            return False
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return 200 <= status < 300
    success = str(parsed.get("success", "")).lower()
    message = str(parsed.get("message", "")).lower()
    if success in ("true", "1"):
        return True
    if "activation" in message or "activate form" in message:
        return True
    return False


def send_mail(subject, body, reply_to, data):
    if send_resend(subject, body, reply_to):
        return True
    if send_smtp(subject, body, reply_to):
        return True
    if send_formsubmit(subject, body, reply_to, data):
        return True
    return False


@app.get("/")
def home():
    return send_from_directory(ROOT, "index.html")


@app.get("/<path:path>")
def static_file(path):
    target = (ROOT / path).resolve()
    if not str(target).startswith(str(ROOT)) or not target.is_file():
        abort(404)
    return send_from_directory(ROOT, path)


@app.post("/api/orcamento")
def orcamento():
    data = request.get_json(silent=True) or {}
    nome = text(data.get("nome"))
    email = text(data.get("email"))
    tel = text(data.get("tel"))
    cidade = text(data.get("cidade"))
    produtos = data.get("produtos")
    if not nome or not valid_email(email) or not tel or not cidade:
        return jsonify({"ok": False, "error": "invalid"}), 400
    if not isinstance(produtos, list) or not produtos:
        return jsonify({"ok": False, "error": "empty"}), 400
    subject = text(data.get("subject")) or ("Solicitação de orçamento - " + nome)
    body = text(data.get("mensagem_completa")) or build_body(data)
    if send_mail(subject, body, email, data):
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "send"}), 502


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT") or 8000), debug=False)