from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3, os, random, openpyxl, io
from datetime import datetime, timedelta

app = Flask(__name__)
CORS(app)
app.config["JWT_SECRET_KEY"] = "boletas-pro-secret-2024"
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(days=7)
jwt = JWTManager(app)

DB = "database.db"

# ─── INIT DB ───
def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            rol TEXT DEFAULT 'vendedor',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ci TEXT UNIQUE NOT NULL,
            nombre TEXT,
            celular TEXT,
            direccion TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS sorteos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            descripcion TEXT,
            fecha TEXT,
            activo INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS boletas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numero TEXT NOT NULL,
            ci TEXT,
            nombre TEXT,
            celular TEXT,
            direccion TEXT,
            sorteo_id INTEGER DEFAULT 1,
            vendedor_id INTEGER,
            vendedor TEXT,
            fecha TEXT DEFAULT (datetime('now')),
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    # Admin por defecto
    try:
        db.execute("INSERT INTO usuarios (username, password, rol) VALUES (?, ?, ?)",
            ("ADMIN", generate_password_hash("admin123"), "admin"))
    except: pass
    # Vendedor demo
    try:
        db.execute("INSERT INTO usuarios (username, password, rol) VALUES (?, ?, ?)",
            ("vendedor1", generate_password_hash("1234"), "vendedor"))
    except: pass
    # Sorteo por defecto
    try:
        db.execute("INSERT INTO sorteos (nombre, descripcion, fecha) VALUES (?, ?, ?)",
            ("Sorteo Principal", "Sorteo de rifas", "2024-12-31"))
    except: pass
    db.commit()
    db.close()

init_db()

def gen_numero():
    return str(random.randint(10000, 99999))

# ─── AUTH ───
@app.route("/api/login", methods=["POST"])
def login():
    data = request.json
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    db = get_db()
    user = db.execute("SELECT * FROM usuarios WHERE username=?", (username,)).fetchone()
    db.close()
    if not user or not check_password_hash(user["password"], password):
        return jsonify({"error": "Credenciales incorrectas"}), 401
    token = create_access_token(identity=str(user["id"]))
    return jsonify({
        "token": token,
        "user": {"id": user["id"], "username": user["username"], "rol": user["rol"]}
    })

# ─── GENERAR BOLETA ───
@app.route("/api/generar", methods=["POST"])
@jwt_required()
def generar():
    data = request.json
    ci = data.get("ci", "").strip()
    nombre = data.get("nombre", "").strip()
    celular = data.get("celular", "").strip()
    direccion = data.get("direccion", "").strip()
    cantidad = int(data.get("cantidad", 1))
    sorteo_id = data.get("sorteo_id", 1)
    vendedor_id = data.get("vendedor_id")
    vendedor = data.get("vendedor", "")
    if cantidad > 100: cantidad = 100

    db = get_db()
    # Guardar/actualizar cliente
    try:
        db.execute("INSERT INTO clientes (ci, nombre, celular, direccion) VALUES (?,?,?,?)",
                   (ci, nombre, celular, direccion))
    except:
        db.execute("UPDATE clientes SET nombre=?, celular=?, direccion=? WHERE ci=?",
                   (nombre, celular, direccion, ci))

    numeros = []
    for _ in range(cantidad):
        num = gen_numero()
        db.execute("""INSERT INTO boletas (numero, ci, nombre, celular, direccion, sorteo_id, vendedor_id, vendedor)
                      VALUES (?,?,?,?,?,?,?,?)""",
                   (num, ci, nombre, celular, direccion, sorteo_id, vendedor_id, vendedor))
        numeros.append(num)
    db.commit()
    db.close()
    return jsonify({"numeros": numeros, "cantidad": cantidad, "cliente": nombre})

# ─── BOLETAS POR USUARIO ───
@app.route("/api/boletas/<user_id>", methods=["GET"])
@jwt_required()
def boletas_usuario(user_id):
    db = get_db()
    rows = db.execute("SELECT * FROM boletas ORDER BY id DESC LIMIT 100").fetchall()
    db.close()
    return jsonify({"boletas": [dict(r) for r in rows]})

# ─── BUSCAR CI ───
@app.route("/api/buscar_ci/<ci>", methods=["GET"])
@jwt_required()
def buscar_ci(ci):
    db = get_db()
    cliente = db.execute("SELECT * FROM clientes WHERE ci=?", (ci,)).fetchone()
    db.close()
    if not cliente:
        return jsonify({"error": "No encontrado"}), 404
    return jsonify({"cliente": dict(cliente)})

# ─── HISTORIAL POR CI ───
@app.route("/api/historial/<ci>", methods=["GET"])
@jwt_required()
def historial(ci):
    db = get_db()
    cliente = db.execute("SELECT * FROM clientes WHERE ci=?", (ci,)).fetchone()
    boletas = db.execute("SELECT * FROM boletas WHERE ci=? ORDER BY id DESC", (ci,)).fetchall()
    db.close()
    return jsonify({
        "cliente": dict(cliente) if cliente else {"ci": ci},
        "boletas": [dict(b) for b in boletas]
    })

# ─── RANKING CLIENTES ───
@app.route("/api/ranking", methods=["GET"])
@jwt_required()
def ranking():
    db = get_db()
    rows = db.execute("""
        SELECT nombre, ci, COUNT(*) as boletas
        FROM boletas GROUP BY ci ORDER BY boletas DESC LIMIT 20
    """).fetchall()
    db.close()
    return jsonify({"ranking": [dict(r) for r in rows]})

# ─── RANKING VENDEDORES ───
@app.route("/api/ranking_vendedores/<sorteo_id>", methods=["GET"])
@jwt_required()
def ranking_vendedores(sorteo_id):
    db = get_db()
    rows = db.execute("""
        SELECT vendedor, COUNT(*) as ventas
        FROM boletas WHERE vendedor IS NOT NULL AND vendedor != ''
        GROUP BY vendedor ORDER BY ventas DESC LIMIT 20
    """).fetchall()
    db.close()
    return jsonify({"ranking": [dict(r) for r in rows]})

# ─── CLIENTES VIP ───
@app.route("/api/clientes_vip", methods=["GET"])
@jwt_required()
def clientes_vip():
    db = get_db()
    rows = db.execute("""
        SELECT c.nombre, c.ci, c.celular, COUNT(b.id) as total
        FROM clientes c JOIN boletas b ON c.ci = b.ci
        GROUP BY c.ci HAVING total >= 3
        ORDER BY total DESC LIMIT 50
    """).fetchall()
    db.close()
    return jsonify({"clientes": [dict(r) for r in rows]})

# ─── USUARIOS (ADMIN) ───
@app.route("/api/usuarios", methods=["GET"])
@jwt_required()
def get_usuarios():
    db = get_db()
    rows = db.execute("SELECT id, username, rol, created_at FROM usuarios").fetchall()
    db.close()
    return jsonify({"usuarios": [dict(r) for r in rows]})

@app.route("/api/crear_usuario", methods=["POST"])
@jwt_required()
def crear_usuario():
    data = request.json
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    if not username or not password:
        return jsonify({"error": "Datos incompletos"}), 400
    db = get_db()
    try:
        db.execute("INSERT INTO usuarios (username, password) VALUES (?,?)",
                   (username, generate_password_hash(password)))
        db.commit()
    except:
        db.close()
        return jsonify({"error": "Usuario ya existe"}), 409
    db.close()
    return jsonify({"ok": True, "mensaje": "Usuario creado"})

@app.route("/api/eliminar_usuario/<user_id>", methods=["DELETE"])
@jwt_required()
def eliminar_usuario(user_id):
    db = get_db()
    db.execute("DELETE FROM usuarios WHERE id=?", (user_id,))
    db.commit()
    db.close()
    return jsonify({"ok": True})

# ─── DESCARGAR EXCEL ───
@app.route("/descargar_excel", methods=["GET"])
@jwt_required()
def descargar_excel():
    db = get_db()
    boletas = db.execute("SELECT * FROM boletas ORDER BY id DESC").fetchall()
    db.close()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Boletas"
    ws.append(["#", "Número", "CI", "Nombre", "Celular", "Dirección", "Vendedor", "Fecha"])
    for i, b in enumerate(boletas, 1):
        ws.append([i, b["numero"], b["ci"], b["nombre"],
                   b["celular"], b["direccion"], b["vendedor"], b["fecha"]])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                     as_attachment=True, download_name="boletas.xlsx")

@app.route("/")
def index():
    return jsonify({"status": "BoletasPRO API corriendo ✅", "version": "1.0"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
