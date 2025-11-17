import os, json, sqlite3, datetime, csv, io, smtplib
from email.mime.text import MIMEText
from flask import Flask, render_template_string, request, redirect, url_for, session, abort, make_response

# =======================
# CONFIG
# =======================
SECRET_KEY = os.environ.get("SECRET_KEY", "cambia-esto-en-produccion")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")  # cámbialo en producción
DB_PATH = os.environ.get("DB_PATH", "data.db")

# >>> Correo de destino y credenciales (puedes moverlos a variables de entorno)
MAIL_TO = os.environ.get("MAIL_TO", "testbomberoschile@gmail.com")
MAIL_FROM = os.environ.get("MAIL_FROM", "testbomberoschile@gmail.com")
MAIL_APP_PASSWORD = os.environ.get("MAIL_APP_PASSWORD", "amgw mcvy ksbc ekgn")  # <- contraseña de aplicación Gmail
MAIL_SMTP_HOST = "smtp.gmail.com"
MAIL_SMTP_PORT_SSL = 465

app = Flask(__name__)
app.secret_key = SECRET_KEY

# =======================
# TEST
# =======================
QUESTIONS = [
    {"id": 1, "text": "Cuando enfrento presión, logro mantener la calma para decidir.", "scale": "EST", "reverse": False},
    {"id": 2, "text": "Me bloqueo fácilmente ante situaciones imprevistas.", "scale": "EST", "reverse": True},
    {"id": 3, "text": "Puedo seguir instrucciones con precisión aun con ruido y distracciones.", "scale": "EST", "reverse": False},
    {"id": 4, "text": "Los turnos largos me desregulan al punto de afectar mi desempeño.", "scale": "EST", "reverse": True},
    {"id": 5, "text": "Antes de actuar, evalúo riesgos y consecuencias.", "scale": "IMP", "reverse": False},
    {"id": 6, "text": "Me cuesta esperar indicaciones y actúo sin pensar.", "scale": "IMP", "reverse": True},
    {"id": 7, "text": "En emergencias, evito conductas temerarias innecesarias.", "scale": "IMP", "reverse": False},
    {"id": 8, "text": "Me enojo rápido y me cuesta controlarme.", "scale": "IMP", "reverse": True},
    {"id": 9,  "text": "Escucho y respeto la cadena de mando.", "scale": "TEQ", "reverse": False},
    {"id": 10, "text": "Prefiero decidir solo/a y no coordinar con otros.", "scale": "TEQ", "reverse": True},
    {"id": 11, "text": "Pido ayuda y ofrezco apoyo cuando el equipo lo necesita.", "scale": "TEQ", "reverse": False},
    {"id": 12, "text": "Me cuesta aceptar correcciones de mis superiores.", "scale": "TEQ", "reverse": True},
    {"id": 13, "text": "Identifico mis emociones y puedo expresarlas de forma adecuada.", "scale": "REM", "reverse": False},
    {"id": 14, "text": "Me quedo rumiando después de situaciones difíciles.", "scale": "REM", "reverse": True},
    {"id": 15, "text": "Tras un incidente crítico, aplico técnicas de autocuidado (respirar, pausar, hablarlo).", "scale": "REM", "reverse": False},
    {"id": 16, "text": "Eventos duros me desestabilizan por varios días.", "scale": "REM", "reverse": True},
    {"id": 17, "text": "No consumo alcohol u otras sustancias antes o durante un turno.", "scale": "SUS", "reverse": False},
    {"id": 18, "text": "Uso alcohol u otras sustancias para “bajar” después de situaciones difíciles.", "scale": "SUS", "reverse": True},
    {"id": 19, "text": "Duermo y me alimento de forma adecuada para rendir.", "scale": "SUS", "reverse": False},
    {"id": 20, "text": "Últimamente mi consumo de alcohol u otras sustancias ha aumentado.", "scale": "SUS", "reverse": True},
]
SCALES = ["EST", "IMP", "TEQ", "REM", "SUS"]
SCALE_LABELS = {
    "EST": "Tolerancia al Estrés",
    "IMP": "Impulso y Control de Riesgo",
    "TEQ": "Trabajo en Equipo",
    "REM": "Regulación Emocional",
    "SUS": "Autocuidado y Riesgo de Sustancias"
}
WEIGHTS = {"EST": 0.25, "IMP": 0.25, "TEQ": 0.20, "REM": 0.20, "SUS": 0.10}
CONSISTENCY_PAIRS = [(1,2), (5,6), (9,10), (13,14), (17,18)]

# =======================
# DB
# =======================
def utcnow_iso():
    # Fecha "aware" en UTC (sin warnings)
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS responses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        ip TEXT,
        user_agent TEXT,
        name TEXT,
        rut TEXT,
        email TEXT,
        phone TEXT,
        address TEXT,
        answers_json TEXT NOT NULL,
        scales_json TEXT NOT NULL,
        total REAL NOT NULL,
        verdict TEXT NOT NULL,
        ci REAL NOT NULL
    );
    """)
    con.commit()
    # Intentar migrar si faltan columnas
    def ensure_column(col, type_):
        cur.execute("PRAGMA table_info('responses')")
        cols = [c[1] for c in cur.fetchall()]
        if col not in cols:
            cur.execute(f"ALTER TABLE responses ADD COLUMN {col} {type_};")
            con.commit()
    for col, type_ in [
        ("name","TEXT"),("rut","TEXT"),("email","TEXT"),("phone","TEXT"),("address","TEXT")
    ]:
        ensure_column(col, type_)
    con.close()

def save_response(ip, ua, name, rut, email, phone, address, answers_json, scales_json, total, verdict, ci):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        """INSERT INTO responses
        (created_at, ip, user_agent, name, rut, email, phone, address, answers_json, scales_json, total, verdict, ci)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (utcnow_iso(), ip, ua, name, rut, email, phone, address, answers_json, scales_json, total, verdict, ci)
    )
    con.commit()
    con.close()

def fetch_all():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""SELECT id, created_at, ip, user_agent, name, rut, email, phone, address,
                          answers_json, scales_json, total, verdict, ci
                   FROM responses ORDER BY id DESC""")
    rows = cur.fetchall()
    con.close()
    return rows

def fetch_one(rid):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""SELECT id, created_at, ip, user_agent, name, rut, email, phone, address,
                          answers_json, scales_json, total, verdict, ci
                   FROM responses WHERE id=?""", (rid,))
    row = cur.fetchone()
    con.close()
    return row

# =======================
# SCORING
# =======================
def likert_to_score(raw, reverse=False):
    val = 6 - raw if reverse else raw
    return (val - 1) / 4 * 100.0

def scale_scores(answers):
    by_scale = {k: [] for k in SCALES}
    for q in QUESTIONS:
        r = answers.get(str(q["id"]))
        if r is None: continue
        by_scale[q["scale"]].append(likert_to_score(int(r), q["reverse"]))
    out = {}
    for sc, vals in by_scale.items():
        out[sc] = sum(vals)/len(vals) if vals else 0.0
    return out

def overall_score(scale_dict):
    return sum(scale_dict[s]*WEIGHTS[s] for s in SCALES)

def consistency_index(answers):
    penalties = 0
    for a,b in CONSISTENCY_PAIRS:
        ra = int(answers.get(str(a), 3))
        rb = int(answers.get(str(b), 3))
        sa = likert_to_score(ra, reverse=False)
        sb = likert_to_score(rb, reverse=True)
        diff = abs(sa - sb)
        if diff > 60: penalties += 20
        elif diff > 40: penalties += 10
        elif diff > 25: penalties += 5
    return max(0, 100 - penalties)

def decision_tree(scale_dict, total, ci):
    flags = []
    if scale_dict["SUS"] < 60: flags.append("Riesgo en autocuidado/sustancias")
    if scale_dict["IMP"] < 65: flags.append("Impulso y control de riesgo por debajo de lo esperado")
    if scale_dict["EST"] < 65: flags.append("Tolerancia al estrés mejorable")
    if scale_dict["TEQ"] < 65: flags.append("Trabajo en equipo/cadena de mando bajo")
    if scale_dict["REM"] < 65: flags.append("Regulación emocional por debajo de lo esperado")
    if ci < 60: flags.append("Baja consistencia de respuestas (revisar validez)")

    if ci < 50:
        verdict = "No válido (reaplicar)"
    elif scale_dict["SUS"] < 50 or scale_dict["IMP"] < 55:
        verdict = "No recomendado por ahora"
    elif total >= 75 and all(scale_dict[s] >= 65 for s in SCALES) and ci >= 70:
        verdict = "Listo para continuar con el proceso"
    elif total >= 60:
        verdict = "En desarrollo"
    else:
        verdict = "No recomendado por ahora"

    return verdict, flags

# =======================
# EMAIL
# =======================
def send_result_email(payload: dict):
    """
    Envía un correo con el detalle del test.
    payload contiene: name, rut, email, phone, address, total, verdict, ci, scales(dict), answers(dict), ip, ua
    """
    try:
        # Construir el cuerpo
        lines = []
        lines.append("Nuevo test psicológico completado")
        lines.append(f"Fecha (UTC): {utcnow_iso()}")
        lines.append("")
        lines.append("DATOS DEL POSTULANTE")
        lines.append(f"Nombre: {payload.get('name','')}")
        lines.append(f"RUT: {payload.get('rut','')}")
        lines.append(f"Correo: {payload.get('email','')}")
        lines.append(f"Teléfono: {payload.get('phone','')}")
        lines.append(f"Dirección: {payload.get('address','')}")
        lines.append("")
        lines.append("RESULTADOS")
        lines.append(f"Puntaje total: {payload.get('total',0):.1f} / 100")
        lines.append(f"Dictamen: {payload.get('verdict','')}")
        lines.append(f"Consistencia (CI): {payload.get('ci',0):.0f} / 100")
        lines.append("")
        lines.append("SUBESCALAS")
        scales = payload.get("scales", {})
        for k, label in SCALE_LABELS.items():
            lines.append(f"- {label}: {float(scales.get(k,0)):.1f} / 100")
        lines.append("")
        lines.append("RESPUESTAS")
        answers = payload.get("answers", {})
        for q in QUESTIONS:
            r = answers.get(str(q["id"]), "?")
            lines.append(f"{q['id']:02d}. {q['text']}  => {r}")
        lines.append("")
        lines.append("TÉCNICO")
        lines.append(f"IP: {payload.get('ip','')}")
        lines.append(f"User-Agent: {payload.get('ua','')}")
        body = "\n".join(lines)

        # Construir mensaje
        subject = f"[Bomberos] Test: {payload.get('name','(sin nombre)')} – {payload.get('verdict','')}"
        msg = MIMEText(body, _charset="utf-8")
        msg["Subject"] = subject
        msg["From"] = MAIL_FROM
        msg["To"] = MAIL_TO

        # Enviar
        with smtplib.SMTP_SSL(MAIL_SMTP_HOST, MAIL_SMTP_PORT_SSL) as smtp:
            smtp.login(MAIL_FROM, MAIL_APP_PASSWORD)
            smtp.send_message(msg)

        return True, None
    except Exception as e:
        print("EMAIL ERROR:", repr(e))
        return False, e

# =======================
# UI BASE
# =======================
BASE = """
<!doctype html><html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }}</title>
<style>
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial;margin:0;background:#f6f7fb;}
header{background:#d62828;color:#fff;padding:16px 20px}
main{max-width:960px;margin:24px auto;background:#fff;padding:20px;border-radius:12px;box-shadow:0 4px 16px rgba(0,0,0,.06)}
h1{margin:0;font-size:20px}
.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}
@media(max-width:800px){.grid{grid-template-columns:1fr}}
.card{border:1px solid #eee;border-radius:12px;padding:12px;background:#fafafa}
.badge{display:inline-block;padding:4px 10px;border-radius:999px;background:#eef2ff;color:#3730a3;font-size:12px}
.btn{background:#1d4ed8;color:#fff;border:none;padding:12px 16px;border-radius:8px;cursor:pointer;font-size:16px}
footer{color:#6b7280;font-size:12px;margin-top:24px}
a{color:#1d4ed8;text-decoration:none}
input[type=text], input[type=email], input[type=tel]{width:100%;padding:10px;border:1px solid #e5e7eb;border-radius:8px;margin:6px 0;}
fieldset{border:1px solid #eee;border-radius:12px;padding:12px}
legend{padding:0 8px;color:#374151}
</style></head><body>
<header><h1>{{ header }}</h1></header>
<main>
{{ body|safe }}
<footer><p><strong>Uso responsable:</strong> Herramienta orientativa. No reemplaza evaluación profesional.</p></footer>
</main></body></html>
"""

def render_page(title, header, body_html):
    return render_template_string(BASE, title=title, header=header, body=body_html)

# =======================
# RUTAS PÚBLICAS
# =======================
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        # 0) Datos personales
        name = request.form.get("name","").strip()
        rut = request.form.get("rut","").strip()
        email = request.form.get("email","").strip()
        phone = request.form.get("phone","").strip()
        address = request.form.get("address","").strip()

        # 1) Respuestas
        answers = {k: v for k, v in request.form.items() if k.isdigit()}

        # 2) Calcular (no mostrar al usuario)
        sc = scale_scores(answers)
        total = overall_score(sc)
        ci = consistency_index(answers)
        verdict, flags = decision_tree(sc, total, ci)

        # 3) Guardar en DB
        save_response(
            ip=request.headers.get("X-Forwarded-For", request.remote_addr),
            ua=request.headers.get("User-Agent",""),
            name=name, rut=rut, email=email, phone=phone, address=address,
            answers_json=json.dumps(answers, ensure_ascii=False),
            scales_json=json.dumps(sc, ensure_ascii=False),
            total=total, verdict=verdict, ci=ci
        )

        # 4) Enviar correo al encargado
        ok, err = send_result_email({
            "name": name, "rut": rut, "email": email, "phone": phone, "address": address,
            "answers": answers, "scales": sc, "total": total, "verdict": verdict, "ci": ci,
            "ip": request.headers.get("X-Forwarded-For", request.remote_addr),
            "ua": request.headers.get("User-Agent","")
        })
        if not ok:
            # No detenemos el flujo del usuario, pero lo registramos en consola
            print("ADVERTENCIA: no se pudo enviar el correo:", err)

        # 5) Redirigir a gracias
        return redirect(url_for("gracias"))

    # GET: Formulario
    options = [(1,"Nunca"),(2,"Rara vez"),(3,"A veces"),(4,"Frecuentemente"),(5,"Siempre")]
    scale_labels = SCALE_LABELS

    body = []
    body.append('<p class="badge">Versión demo · No diagnóstico</p>')
    body.append('<form method="post">')

    # Datos personales
    body.append('<fieldset class="card"><legend>Datos del postulante</legend>')
    body.append('<label>Nombre completo</label><input type="text" name="name" required>')
    body.append('<label>RUT</label><input type="text" name="rut" required placeholder="12.345.678-9">')
    body.append('<label>Correo</label><input type="email" name="email" required>')
    body.append('<label>Número de contacto</label><input type="tel" name="phone" required>')
    body.append('<label>Dirección</label><input type="text" name="address" required>')
    body.append('</fieldset>')

    # Preguntas
    body.append('<div class="grid">')
    for q in QUESTIONS:
        body.append('<div class="card">')
        body.append(f'<p><strong>{q["id"]}.</strong> {q["text"]}</p>')
        for i,label in options:
            body.append(f'<label><input type="radio" name="{q["id"]}" value="{i}" required> {i} — {label}</label><br>')
        body.append(f'<div style="font-size:12px;color:#6b7280;margin-top:6px">Dimensión: {scale_labels[q["scale"]]}</div>')
        body.append('</div>')
    body.append('</div>')

    # Consentimiento
    body.append('<div style="margin:16px 0;">')
    body.append('<label><input type="checkbox" required> Confirmo que respondo de forma voluntaria y honesta. '
                'Entiendo que esto no reemplaza evaluación profesional y autorizo el uso anónimo de mis respuestas con fines de admisión y mejora del proceso.</label>')
    body.append('</div>')

    body.append('<button class="btn" type="submit">Enviar</button></form>')
    return render_page("Test Psicológico Bomberos","Evaluación Psicológica Inicial – Postulación a Bomberos","".join(body))

@app.route("/gracias")
def gracias():
    body = """
    <div class="card">
      <p><strong>¡Gracias!</strong> Hemos recibido tu test correctamente.</p>
      <p>El equipo de admisión revisará la información de forma privada.</p>
    </div>
    """
    return render_page("Gracias","Gracias por completar el test", body)

# =======================
# PANEL PRIVADO
# =======================
def login_required(fn):
    from functools import wraps
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("auth"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        pw = request.form.get("password","")
        if pw == ADMIN_PASSWORD:
            session["auth"] = True
            return redirect(url_for("admin"))
    body = """
    <form method="post" class="card">
      <p>Ingresa la contraseña de administrador:</p>
      <input type="password" name="password" required>
      <button class="btn" type="submit">Entrar</button>
    </form>
    """
    return render_page("Login","Acceso privado", body)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/admin")
@login_required
def admin():
    rows = fetch_all()
    html = ['<div class="card" style="overflow:auto"><table border="0" cellpadding="6" cellspacing="0">']
    html.append("<tr><th>ID</th><th>Fecha (UTC)</th><th>IP</th><th>Nombre</th><th>RUT</th><th>Total</th><th>Dictamen</th><th>CI</th><th>Ver</th></tr>")
    for r in rows:
        (rid, created_at, ip, ua, name, rut, email, phone, address,
         answers_json, scales_json, total, verdict, ci) = r
        html.append(f"<tr><td>{rid}</td><td>{created_at}</td><td>{ip or ''}</td>"
                    f"<td>{name or ''}</td><td>{rut or ''}</td><td>{float(total):.1f}</td>"
                    f"<td>{verdict}</td><td>{float(ci):.0f}</td>"
                    f"<td><a href='/admin/ver/{rid}'>Detalle</a></td></tr>")
    html.append("</table></div>")
    html.append("<p><a class='btn' href='/admin/export'>Descargar CSV</a> &nbsp; <a href='/logout'>Salir</a></p>")
    return render_page("Panel","Resultados recibidos", "".join(html))

@app.route("/admin/ver/<int:rid>")
@login_required
def admin_ver(rid):
    row = fetch_one(rid)
    if not row: abort(404)
    (rid, created_at, ip, ua, name, rut, email, phone, address,
     answers_json, scales_json, total, verdict, ci) = row
    answers = json.loads(answers_json)
    scales = json.loads(scales_json)
    parts = [f"<div class='card'><p><strong>ID:</strong> {rid}</p>"
             f"<p><strong>Fecha UTC:</strong> {created_at}</p>"
             f"<p><strong>IP:</strong> {ip or ''}</p>"
             f"<p><strong>Agente:</strong> {ua or ''}</p>"
             f"<p><strong>Nombre:</strong> {name or ''}</p>"
             f"<p><strong>RUT:</strong> {rut or ''}</p>"
             f"<p><strong>Correo:</strong> {email or ''}</p>"
             f"<p><strong>Teléfono:</strong> {phone or ''}</p>"
             f"<p><strong>Dirección:</strong> {address or ''}</p>"
             f"<p><strong>Total:</strong> {float(total):.1f}</p>"
             f"<p><strong>Dictamen:</strong> {verdict}</p>"
             f"<p><strong>Consistencia:</strong> {float(ci):.0f}</p></div>"]
    parts.append("<h3>Subescalas</h3><div class='grid'>")
    for k,label in SCALE_LABELS.items():
        val = float(scales.get(k,0))
        parts.append(f"<div class='card'><strong>{label}</strong><div style='font-size:12px;color:#6b7280;margin-top:6px'>{val:.1f} / 100</div></div>")
    parts.append("</div>")
    parts.append("<h3>Respuestas</h3><div class='card'><ol>")
    for q in QUESTIONS:
        r = answers.get(str(q["id"]), "?")
        parts.append(f"<li>({q['id']}) {q['text']} — <strong>{r}</strong></li>")
    parts.append("</ol></div>")
    parts.append("<p><a href='/admin'>Volver</a></p>")
    return render_page(f"Detalle {rid}","Detalle de respuesta","".join(parts))

@app.route("/admin/export")
@login_required
def admin_export():
    rows = fetch_all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id","created_at","ip","user_agent","name","rut","email","phone","address","answers_json","scales_json","total","verdict","ci"])
    for r in rows:
        writer.writerow(r)
    mem = io.BytesIO(output.getvalue().encode("utf-8"))
    resp = make_response(mem.getvalue())
    resp.headers["Content-Type"] = "text/csv; charset=utf-8"
    resp.headers["Content-Disposition"] = "attachment; filename=responses.csv"
    return resp

# =======================
# ARRANQUE
# =======================
if __name__ == "__main__":
    init_db()
    # host 0.0.0.0 para que funcione desde otros dispositivos en tu red / servidores
    app.run(host="0.0.0.0", port=5000, debug=True)