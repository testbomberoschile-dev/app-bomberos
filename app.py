import os, json, sqlite3, datetime, csv, io, smtplib
from email.mime.text import MIMEText
from flask import (
    Flask,
    render_template_string,
    request,
    redirect,
    url_for,
    session,
    abort,
    make_response,
)

# =======================
# CONFIG
# =======================
SECRET_KEY = os.environ.get("SECRET_KEY", "cambia-esto-en-produccion")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
DB_PATH = os.environ.get("DB_PATH", "data.db")

MAIL_TO = os.environ.get("MAIL_TO", "testbomberoschile@gmail.com")
MAIL_FROM = os.environ.get("MAIL_FROM", "testbomberoschile@gmail.com")
MAIL_APP_PASSWORD = os.environ.get("MAIL_APP_PASSWORD", "amgw mcvy ksbc ekgn")
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
    "SUS": "Autocuidado y Riesgo de Sustancias",
}

WEIGHTS = {"EST": 0.25, "IMP": 0.25, "TEQ": 0.20, "REM": 0.20, "SUS": 0.10}

CONSISTENCY_PAIRS = [(1, 2), (5, 6), (9, 10), (13, 14), (17, 18)]

# =======================
# DB
# =======================
def utcnow_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        """
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
        """
    )
    con.commit()

    def ensure_column(col, type_):
        cur.execute("PRAGMA table_info('responses')")
        cols = [c[1] for c in cur.fetchall()]
        if col not in cols:
            cur.execute(f"ALTER TABLE responses ADD COLUMN {col} {type_};")
            con.commit()

    for col, type_ in [
        ("name", "TEXT"),
        ("rut", "TEXT"),
        ("email", "TEXT"),
        ("phone", "TEXT"),
        ("address", "TEXT"),
    ]:
        ensure_column(col, type_)

    con.close()


# Inicializar BD al cargar el módulo (compatible Flask 3)
init_db()


def save_response(
    ip,
    ua,
    name,
    rut,
    email,
    phone,
    address,
    answers_json,
    scales_json,
    total,
    verdict,
    ci,
):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO responses
        (created_at, ip, user_agent, name, rut, email, phone, address,
         answers_json, scales_json, total, verdict, ci)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            utcnow_iso(),
            ip,
            ua,
            name,
            rut,
            email,
            phone,
            address,
            answers_json,
            scales_json,
            total,
            verdict,
            ci,
        ),
    )
    con.commit()
    con.close()


def fetch_all():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        """
        SELECT id, created_at, ip, user_agent, name, rut, email, phone, address,
               answers_json, scales_json, total, verdict, ci
        FROM responses
        ORDER BY id DESC
        """
    )
    rows = con.fetchall()
    con.close()
    return rows


def fetch_one(rid):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        """
        SELECT id, created_at, ip, user_agent, name, rut, email, phone, address,
               answers_json, scales_json, total, verdict, ci
        FROM responses
        WHERE id=?
        """,
        (rid,),
    )
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
        if r is None:
            continue
        by_scale[q["scale"]].append(likert_to_score(int(r), q["reverse"]))
    out = {}
    for sc, vals in by_scale.items():
        out[sc] = sum(vals) / len(vals) if vals else 0.0
    return out


def overall_score(scale_dict):
    return sum(scale_dict[s] * WEIGHTS[s] for s in SCALES)


def consistency_index(answers):
    penalties = 0
    for a, b in CONSISTENCY_PAIRS:
        ra = int(answers.get(str(a), 3))
        rb = int(answers.get(str(b), 3))
        sa = likert_to_score(ra, reverse=False)
        sb = likert_to_score(rb, reverse=True)
        diff = abs(sa - sb)
        if diff > 60:
            penalties += 20
        elif diff > 40:
            penalties += 10
        elif diff > 25:
            penalties += 5
    return max(0, 100 - penalties)


def decision_tree(scale_dict, total, ci):
    flags = []
    if scale_dict["SUS"] < 60:
        flags.append("Riesgo en autocuidado/sustancias")
    if scale_dict["IMP"] < 65:
        flags.append("Impulso y control de riesgo por debajo de lo esperado")
    if scale_dict["EST"] < 65:
        flags.append("Tolerancia al estrés mejorable")
    if scale_dict["TEQ"] < 65:
        flags.append("Trabajo en equipo/cadena de mando bajo")
    if scale_dict["REM"] < 65:
        flags.append("Regulación emocional por debajo de lo esperado")
    if ci < 60:
        flags.append("Baja consistencia de respuestas (revisar validez)")

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
    Envía correo sólo si ENABLE_EMAIL=1 en variables de entorno.
    Si está desactivado, no hace nada y no rompe la app.
    """
    if os.environ.get("ENABLE_EMAIL", "0") != "1":
        # Email desactivado, salimos en silencio
        return False, "Email disabled"

    try:
        lines = []
        lines.append("Nuevo test psicológico completado")
        lines.append(f"Fecha (UTC): {utcnow_iso()}")
        lines.append("")
        lines.append("DATOS DEL POSTULANTE")
        lines.append(f"Nombre: {payload.get('name', '')}")
        lines.append(f"RUT: {payload.get('rut', '')}")
        lines.append(f"Correo: {payload.get('email', '')}")
        lines.append(f"Teléfono: {payload.get('phone', '')}")
        lines.append(f"Dirección: {payload.get('address', '')}")
        lines.append("")
        lines.append("RESULTADOS")
        lines.append(f"Puntaje total: {payload.get('total', 0):.1f} / 100")
        lines.append(f"Dictamen: {payload.get('verdict', '')}")
        lines.append(f"Consistencia (CI): {payload.get('ci', 0):.0f} / 100")
        lines.append("")
        lines.append("SUBESCALAS")
        scales = payload.get("scales", {})
        for k, label in SCALE_LABELS.items():
            lines.append(f"- {label}: {float(scales.get(k, 0)):.1f} / 100")
        lines.append("")
        lines.append("RESPUESTAS")
        answers = payload.get("answers", {})
        for q in QUESTIONS:
            r = answers.get(str(q["id"]), "?")
            lines.append(f"{q['id']:02d}. {q['text']}  => {r}")
        lines.append("")
        lines.append("TÉCNICO")
        lines.append(f"IP: {payload.get('ip', '')}")
        lines.append(f"User-Agent: {payload.get('ua', '')}")
        body = "\n".join(lines)

        subject = f"[Bomberos] Test: {payload.get('name', '(sin nombre)')} – {payload.get('verdict', '')}"
        msg = MIMEText(body, _charset="utf-8")
        msg["Subject"] = subject
        msg["From"] = MAIL_FROM
        msg["To"] = MAIL_TO

        # Timeout corto para no colgar el worker
        with smtplib.SMTP_SSL(MAIL_SMTP_HOST, MAIL_SMTP_PORT_SSL, timeout=5) as smtp:
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
<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
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
label{display:block;margin:4px 0;}
</style>
</head>
<body>
<header><h1>{{ header }}</h1></header>
<main>
{{ body|safe }}
<footer><p><strong>Uso responsable:</strong> Herramienta orientativa. No reemplaza evaluación profesional.</p></footer>
</main>
</body>
</html>
"""

# =======================
# ROUTES
# =======================
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        rut = (request.form.get("rut") or "").strip()
        email = (request.form.get("email") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        address = (request.form.get("address") or "").strip()

        answers = {}
        for q in QUESTIONS:
            key = f"q{q['id']}"
            val = request.form.get(key)
            if not val:
                return "Falta responder todas las preguntas.", 400
            answers[str(q["id"])] = val

        scales = scale_scores(answers)
        total = overall_score(scales)
        ci = consistency_index(answers)
        verdict, flags = decision_tree(scales, total, ci)

        answers_json = json.dumps(answers, ensure_ascii=False)
        scales_json = json.dumps(scales, ensure_ascii=False)

        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")
        ua = request.headers.get("User-Agent", "")

        save_response(
            ip,
            ua,
            name,
            rut,
            email,
            phone,
            address,
            answers_json,
            scales_json,
            total,
            verdict,
            ci,
        )

        payload = {
            "name": name,
            "rut": rut,
            "email": email,
            "phone": phone,
            "address": address,
            "answers": answers,
            "scales": scales,
            "total": total,
            "verdict": verdict,
            "ci": ci,
            "ip": ip,
            "ua": ua,
        }
        # El propio send_result_email decide si está habilitado por ENV
        send_result_email(payload)

        # ⬇️ IMPORTANTE: aquí ya NO mostramos puntajes ni dictamen, solo mensaje elegante
        body = render_template_string(
            """
            <h2>Cuestionario enviado correctamente</h2>
            <div class="card">
              <p>
                Hemos recibido sus respuestas de manera satisfactoria. A partir de este momento,
                su información será analizada con estricta confidencialidad por profesionales
                especializados en evaluación psicológica y en procesos de selección para Bomberos.
              </p>
              <p>
                El objetivo de este instrumento es aportar antecedentes para valorar de manera integral
                sus recursos personales, emocionales y relacionales en relación con las exigencias propias
                del servicio bomberil. Los resultados no se muestran directamente en esta plataforma
                para resguardar su bienestar emocional y asegurar una interpretación responsable y contextualizada.
              </p>
            </div>

            <h3>Declaración de honestidad</h3>
            <div class="card">
              <p>
                Al completar este cuestionario, se considera que usted ha respondido con el máximo nivel de honestidad
                posible, reflejando de buena fe su forma habitual de pensar, sentir y actuar frente a distintas situaciones.
                Para efectos de este proceso, las respuestas se asumen como veraces y coherentes con su experiencia personal,
                constituyendo un compromiso de honestidad que es fundamental para la calidad y validez de la evaluación.
              </p>
              <p>
                Esta declaración de honestidad es especialmente relevante en el contexto bomberil, donde la confianza,
                la transparencia y la responsabilidad ética son pilares esenciales para resguardar la seguridad propia,
                la del equipo y la de la comunidad a la que se presta servicio.
              </p>
            </div>

            <h3>Agradecimiento y próximos pasos</h3>
            <div class="card">
              <p>
                Agradecemos sinceramente el tiempo, la disposición y la seriedad con que ha respondido este instrumento.
                Sus antecedentes serán revisados por un/a profesional, quien integrará esta información con otras etapas
                del proceso de selección (entrevistas, formación, evaluación médica u otros dispositivos que la institución
                determine pertinentes).
              </p>
              <p>
                En caso de que se requiera profundizar en algún aspecto, se le podrá contactar para continuar con la evaluación
                mediante entrevistas u otras instancias complementarias. Todo este proceso tiene como finalidad resguardar
                su bienestar y la seguridad de las personas a las que, eventualmente, usted podría llegar a asistir como Bombero/a.
              </p>
              <p>
                Muchas gracias por su interés en formar parte de una institución cuyo propósito central es proteger la vida,
                los bienes y la integridad de la comunidad.
              </p>
            </div>

            <p style="margin-top:16px;">
              <a href="{{ url_for('index') }}">Volver al inicio</a>
            </p>
            """,
            name=name,
            total=total,
            verdict=verdict,
            ci=ci,
            scales=scales,
            flags=flags,
            scale_labels=SCALE_LABELS,
        )

        return render_template_string(
            BASE,
            title="Cuestionario enviado",
            header="Evaluación psicológica para postulantes a Bomberos",
            body=body,
        )

    # GET
    body = render_template_string(
        """
        <h2>Evaluación psicológica orientativa para postulantes a Bomberos</h2>
        <p>Este instrumento busca apoyar el proceso de selección, evaluando aspectos de tolerancia al estrés, control de impulsos, trabajo en equipo, regulación emocional y autocuidado.</p>

        <form method="post">
          <fieldset>
            <legend>Datos del postulante</legend>
            <label>Nombre completo
              <input type="text" name="name" required>
            </label>
            <label>RUT
              <input type="text" name="rut" required>
            </label>
            <label>Correo electrónico
              <input type="email" name="email" required>
            </label>
            <label>Teléfono
              <input type="tel" name="phone">
            </label>
            <label>Dirección
              <input type="text" name="address">
            </label>
          </fieldset>

          <fieldset>
            <legend>Responda las siguientes afirmaciones</legend>
            <p>Marque según cuánto se acerca cada frase a su forma habitual de actuar:</p>
            <ul style="font-size:14px;">
              <li>1 = Nunca</li>
              <li>2 = Rara vez</li>
              <li>3 = A veces</li>
              <li>4 = Frecuentemente</li>
              <li>5 = Siempre</li>
            </ul>

            {% for q in questions %}
              <div class="card">
                <p><strong>{{ q.id }}.</strong> {{ q.text }}</p>
                <label><input type="radio" name="q{{ q.id }}" value="1" required> 1 - Nunca</label>
                <label><input type="radio" name="q{{ q.id }}" value="2"> 2 - Rara vez</label>
                <label><input type="radio" name="q{{ q.id }}" value="3"> 3 - A veces</label>
                <label><input type="radio" name="q{{ q.id }}" value="4"> 4 - Frecuentemente</label>
                <label><input type="radio" name="q{{ q.id }}" value="5"> 5 - Siempre</label>
              </div>
            {% endfor %}
          </fieldset>

          <p style="margin-top:16px;">
            <button type="submit" class="btn">Enviar respuestas</button>
          </p>
        </form>
        """,
        questions=QUESTIONS,
    )

    return render_template_string(
        BASE,
        title="Test Psicológico Bomberos",
        header="Test Psicológico para Postulantes a Bomberos",
        body=body,
    )

# =======================
# ADMIN
# =======================
def require_admin():
    if not session.get("admin"):
        return redirect(url_for("admin_login"))


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        pwd = request.form.get("password") or ""
        if pwd == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(url_for("admin_panel"))
        else:
            error = "Contraseña incorrecta."
    else:
        error = None

    body = render_template_string(
        """
        <h2>Acceso administración</h2>
        {% if error %}
          <p style="color:red;">{{ error }}</p>
        {% endif %}
        <form method="post">
          <label>Contraseña
            <input type="password" name="password" required>
          </label>
          <p style="margin-top:12px;">
            <button type="submit" class="btn">Ingresar</button>
          </p>
        </form>
        """,
        error=error,
    )

    return render_template_string(
        BASE,
        title="Admin Test Bomberos",
        header="Panel de administración",
        body=body,
    )


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("admin_login"))


@app.route("/admin")
def admin_panel():
    guard = require_admin()
    if guard:
        return guard

    rows = fetch_all()
    body = render_template_string(
        """
        <h2>Resultados registrados</h2>
        <p><a href="{{ url_for('admin_export') }}">Descargar CSV</a> | <a href="{{ url_for('admin_logout') }}">Cerrar sesión</a></p>
        {% if not rows %}
          <p>No hay respuestas registradas aún.</p>
        {% else %}
          <table border="1" cellpadding="4" cellspacing="0">
            <tr>
              <th>ID</th>
              <th>Fecha (UTC)</th>
              <th>Nombre</th>
              <th>RUT</th>
              <th>Total</th>
              <th>Dictamen</th>
              <th>Ver</th>
            </tr>
            {% for r in rows %}
              <tr>
                <td>{{ r[0] }}</td>
                <td>{{ r[1] }}</td>
                <td>{{ r[4] }}</td>
                <td>{{ r[5] }}</td>
                <td>{{ "%.1f"|format(r[12]) }}</td>
                <td>{{ r[13] }}</td>
                <td><a href="{{ url_for('admin_view', rid=r[0]) }}">Detalle</a></td>
              </tr>
            {% endfor %}
          </table>
        {% endif %}
        """,
        rows=rows,
    )

    return render_template_string(
        BASE,
        title="Admin Test Bomberos",
        header="Panel de administración",
        body=body,
    )


@app.route("/admin/view/<int:rid>")
def admin_view(rid):
    guard = require_admin()
    if guard:
        return guard

    row = fetch_one(rid)
    if not row:
        abort(404)

    (
        _id,
        created_at,
        ip,
        ua,
        name,
        rut,
        email,
        phone,
        address,
        answers_json,
        scales_json,
        total,
        verdict,
        ci,
    ) = row

    answers = json.loads(answers_json)
    scales = json.loads(scales_json)

    body = render_template_string(
        """
        <h2>Detalle respuesta #{{ rid }}</h2>
        <p><a href="{{ url_for('admin_panel') }}">Volver</a></p>

        <h3>Datos generales</h3>
        <ul>
          <li><strong>Fecha (UTC):</strong> {{ created_at }}</li>
          <li><strong>Nombre:</strong> {{ name }}</li>
          <li><strong>RUT:</strong> {{ rut }}</li>
          <li><strong>Correo:</strong> {{ email }}</li>
          <li><strong>Teléfono:</strong> {{ phone }}</li>
          <li><strong>Dirección:</strong> {{ address }}</li>
          <li><strong>IP:</strong> {{ ip }}</li>
          <li><strong>User-Agent:</strong> {{ ua }}</li>
        </ul>

        <h3>Resultados</h3>
        <ul>
          <li><strong>Puntaje total:</strong> {{ "%.1f"|format(total) }} / 100</li>
          <li><strong>Dictamen:</strong> {{ verdict }}</li>
          <li><strong>Consistencia (CI):</strong> {{ "%.0f"|format(ci) }} / 100</li>
        </ul>

        <h3>Subescalas</h3>
        <ul>
        {% for code, label in scale_labels.items() %}
          <li><strong>{{ label }} ({{ code }}):</strong> {{ "%.1f"|format(scales[code]) }} / 100</li>
        {% endfor %}
        </ul>

        <h3>Respuestas</h3>
        <ol>
        {% for q in questions %}
          <li>
            {{ q.text }}<br>
            Respuesta: {{ answers[str(q.id)] }}
          </li>
        {% endfor %}
        </ol>
        """,
        rid=rid,
        created_at=created_at,
        name=name,
        rut=rut,
        email=email,
        phone=phone,
        address=address,
        ip=ip,
        ua=ua,
        total=total,
        verdict=verdict,
        ci=ci,
        scales=scales,
        scale_labels=SCALE_LABELS,
        questions=QUESTIONS,
        answers=answers,
    )

    return render_template_string(
        BASE,
        title=f"Detalle #{rid}",
        header=f"Detalle respuesta #{rid}",
        body=body,
    )


@app.route("/admin/export")
def admin_export():
    guard = require_admin()
    if guard:
        return guard

    rows = fetch_all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "id",
            "created_at",
            "ip",
            "user_agent",
            "name",
            "rut",
            "email",
            "phone",
            "address",
            "answers_json",
            "scales_json",
            "total",
            "verdict",
            "ci",
        ]
    )
    for r in rows:
        writer.writerow(r)

    resp = make_response(output.getvalue())
    resp.headers["Content-Type"] = "text/csv; charset=utf-8"
    resp.headers["Content-Disposition"] = "attachment; filename=responses.csv"
    return resp


# =======================
# MAIN
# =======================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
