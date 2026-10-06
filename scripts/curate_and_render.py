"""
Toma raw_items.json (salida de fetch_news.py), le pide a Claude que elija
las notas más relevantes por categoría y las resuma en sus propias palabras
(nunca copiar texto textual, por derechos de autor).

Este script ACUMULA las notas del día en data/today.json en vez de
sobrescribirlas en cada corrida -- así, aunque solo revises el panel una o
dos veces al día, ves todo lo relevante que pasó, no solo el último
snapshot. El acumulado se reinicia solo cuando cambia el día (hora de Sinaloa).

Requiere la variable de entorno ANTHROPIC_API_KEY (se configura como
"secret" en GitHub, ver README).
"""

import json
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import anthropic

MODEL = "claude-haiku-4-5-20251001"  # rápido y barato, suficiente para curar titulares

LOCAL_TZ = ZoneInfo("America/Mazatlan")  # UTC-7 todo el año (sin horario de verano)

# El runner de GitHub está en inglés: strftime("%B") daría "October".
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

# Con ~19 fuentes, 40 titulares dejaba fuera a la mayoría de los medios.
# 180 cubre casi todo lo recolectado y sigue siendo baratísimo con Haiku:
# son unos pocos miles de tokens de entrada por corrida.
MAX_ITEMS_TO_CURATE = 180

# Para llegar a 10-15 acumuladas por categoría hay que subir los dos topes.
# 8 nuevas por corrida x 3 corridas = hasta 24 candidatas al día por categoría,
# que el tope de acumulado recorta a 15.
MAX_NEW_PER_CATEGORY = 8
MAX_ACCUMULATED_PER_CATEGORY = 15

# 4 categorías x 8 notas x (título + resumen + zona) no cabe holgado en 4096.
MAX_OUTPUT_TOKENS = 8192

DATA_FILE = "data/today.json"

CATEGORIES = ["politica", "seguridad", "economia", "sociedad"]
CATEGORY_LABELS = {
    "politica": "Política y gobierno",
    "seguridad": "Seguridad",
    "economia": "Economía y campo",
    "sociedad": "Sociedad",
}
CATEGORY_COLORS = {
    "politica": "var(--politica)",
    "seguridad": "var(--seguridad)",
    "economia": "var(--economia)",
    "sociedad": "var(--sociedad)",
}

SYSTEM_PROMPT = f"""Eres un editor de noticias para un panel de monitoreo enfocado en el estado
de Sinaloa, México. Lo usa un equipo de estrategia y comunicación que necesita
un panorama diario de TODO lo que pasa en el estado.
Se te da una lista de titulares recientes de medios locales, cada uno con su
fuente, tipo de medio (impreso, radio/digital, digital, TV), zona y URL.

PRIORIDAD EDITORIAL: política/gobierno primero, seguridad después. Economía y
campo, y sociedad, son secundarias pero sí interesan.

COBERTURA TERRITORIAL: el panel debe reflejar todo el estado, no solo
Culiacán. Si hay notas relevantes del norte y del sur, inclúyelas aunque
Culiacán genere más volumen. Las regiones son:
- Norte: Ahome (Los Mochis, Topolobampo), El Fuerte, Choix, Guasave,
  Sinaloa de Leyva, Juan José Ríos.
- Centro: Culiacán, Navolato, Eldorado, Salvador Alvarado (Guamúchil),
  Angostura, Mocorito, Badiraguato, Cosalá.
- Sur: Mazatlán, Elota, San Ignacio, Concordia, Rosario, Escuinapa.

Tu trabajo:

1. Quédate solo con notas relevantes para Sinaloa. Descarta:
   - Notas nacionales o internacionales sin relación directa con el estado.
   - Espectáculos, virales, horóscopos, curiosidades, recetas.
   - Clima y pronósticos del tiempo, SALVO emergencias (ciclones, inundaciones,
     cortes de carreteras, suspensión de clases): esas sí van, en sociedad.

2. Clasifica cada nota elegida en una de estas categorías:
   - politica: gobierno del estado, Congreso, ayuntamientos y cabildos,
     partidos, aspirantes y movimientos rumbo al proceso electoral 2027,
     designaciones y renuncias de funcionarios, presupuesto público,
     conflictos entre poderes, tribunales electorales, transparencia.
   - seguridad: violencia, crimen organizado, operativos, Fiscalía,
     desapariciones y colectivos de búsqueda, política de seguridad.
     IMPORTANTE: prefiere lo que tenga implicación institucional o muestre un
     patrón (cifras, decisiones de autoridad, detenciones relevantes, ataques
     de gran escala, afectaciones a la población, casos con seguimiento) sobre
     el hecho aislado de nota roja. Varios de estos medios publican muchos
     incidentes sueltos; no llenes la categoría con eso. Si un hecho aislado es
     realmente grande, sí va.
   - economia: campo (siembras, precios del maíz y otros granos, agua y
     presas, sequía, protestas y bloqueos de productores), pesca, turismo
     (Mazatlán), empleo, inversión, comercio, infraestructura.
   - sociedad: servicios públicos, salud, educación, universidades (UAS),
     protestas ciudadanas, derechos humanos, cultura, emergencias. Deportes
     (Tomateros, Venados, Dorados, Cañeros y similares) a lo mucho una o dos
     notas, y solo si son relevantes más allá del resultado del partido.

3. Elige como máximo {MAX_NEW_PER_CATEGORY} notas por categoría, priorizando lo
   más importante e impactante del momento. Si hay poco material bueno en una
   categoría, elige menos: mejor pocas notas fuertes que rellenar.

4. No repitas la misma noticia dos veces aunque venga de medios distintos.
   Si varios medios cubren lo mismo, elige una sola y usa la fuente que la
   cuente con más contexto.

5. Para cada nota escribe:
   - "title": título MUY corto (máx 12 palabras)
   - "summary": resumen MUY breve (máx 25 palabras)
   - "zona": "Norte", "Centro", "Sur" o "Estatal" según el CONTENIDO de la
     nota (no necesariamente la zona que trae la fuente). "Estatal" es para
     lo que afecta a todo el estado o al gobierno estatal en general.
   Título y resumen EN TUS PROPIAS PALABRAS: nunca copies el titular original
   tal cual ni frases textuales de la fuente.

6. FORMATO: responde ÚNICAMENTE con JSON válido, sin texto adicional, sin
   bloques de markdown (nada de ```). Si un título o resumen necesita comillas
   dobles, escápalas como \\" para no romper el JSON. No uses saltos de línea
   dentro de los valores de texto. Estructura exacta:

{{"politica": [{{"title": "...", "summary": "...", "zona": "...", "source": "...", "url": "..."}}],
 "seguridad": [...], "economia": [...], "sociedad": [...]}}

Si una categoría no tiene notas relevantes, devuélvela como lista vacía.
"""


def build_user_prompt(items):
    lines = []
    for it in items[:MAX_ITEMS_TO_CURATE]:
        if not it.get("title"):
            continue
        etiqueta = " / ".join(x for x in (it.get("source", ""), it.get("tipo", ""),
                                          it.get("zona", "")) if x)
        lines.append(f"- [{etiqueta}] {it['title']} ({it['url']})")
    return "Titulares disponibles:\n" + "\n".join(lines)


def extract_json(text):
    """Intenta parsear el JSON tal cual; si falla (ej. se cortó a la mitad),
    intenta recortar hasta el último objeto completo en vez de tronar el pipeline."""
    text = text.strip()
    text = re.sub(r"^```(json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"[aviso] JSON no válido en el primer intento ({e}); "
              f"intentando reparar recortando al último objeto completo.")

    last_brace = text.rfind("}")
    if last_brace == -1:
        raise ValueError("No se pudo reparar el JSON: no hay ningún '}' en la respuesta.")

    truncated = text[:last_brace + 1]
    open_stack = []
    in_string = False
    escape = False
    for ch in truncated:
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in "{[":
            open_stack.append(ch)
        elif ch in "}]":
            if open_stack:
                open_stack.pop()

    closers = {"{": "}", "[": "]"}
    repaired = truncated + "".join(closers[c] for c in reversed(open_stack))
    return json.loads(repaired)


def curate_new(items):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("Falta la variable de entorno ANTHROPIC_API_KEY")

    client = anthropic.Anthropic(api_key=api_key)
    prompt = build_user_prompt(items)
    print(f"[info] se le mandan {prompt.count(chr(10))} titulares al modelo")
    resp = client.messages.create(
        model=MODEL,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    print(f"[info] stop_reason de la API: {resp.stop_reason}")
    if resp.stop_reason == "max_tokens":
        print("[aviso] la respuesta se cortó por max_tokens; considera subir "
              "MAX_OUTPUT_TOKENS o bajar MAX_NEW_PER_CATEGORY.")
    return extract_json(resp.content[0].text)


def load_accumulated(today_str):
    if not os.path.exists(DATA_FILE):
        return {"date": today_str, "run_count": 0, "notes": {c: [] for c in CATEGORIES}}
    with open(DATA_FILE, encoding="utf-8") as f:
        data = json.load(f)
    if data.get("date") != today_str:
        # Cambió el día (hora de Sinaloa): se reinicia el acumulado.
        print(f"[info] Nuevo día detectado ({data.get('date')} -> {today_str}); "
              f"se reinicia el acumulado.")
        return {"date": today_str, "run_count": 0, "notes": {c: [] for c in CATEGORIES}}
    return data


def note_key(note):
    """Identificador para detectar duplicados entre corridas."""
    if note.get("url"):
        return note["url"].strip().rstrip("/")
    return (note.get("title", "").strip().lower(), note.get("source", "").strip().lower())


def merge_notes(accumulated, new_notes, run_timestamp):
    for cat in CATEGORIES:
        existing = accumulated["notes"].setdefault(cat, [])
        existing_keys = {note_key(n) for n in existing}
        for note in new_notes.get(cat, []):
            key = note_key(note)
            if key in existing_keys:
                continue  # ya la teníamos de una corrida anterior, no duplicar
            note["_added_at"] = run_timestamp
            existing.append(note)
            existing_keys.add(key)
        # Más reciente primero, y recorta al tope para que no crezca sin límite.
        existing.sort(key=lambda n: n.get("_added_at", ""), reverse=True)
        accumulated["notes"][cat] = existing[:MAX_ACCUMULATED_PER_CATEGORY]
    accumulated["run_count"] = accumulated.get("run_count", 0) + 1
    accumulated["last_updated"] = run_timestamp
    return accumulated


def render_cards(notes_by_cat):
    html_blocks = []
    for cat in CATEGORIES:
        notes = notes_by_cat.get(cat, [])
        html_blocks.append(f'<section>\n<div class="section-title"><span class="dot" '
                           f'style="background:{CATEGORY_COLORS[cat]}"></span>'
                           f'<h2>{CATEGORY_LABELS[cat]}</h2></div>')
        if not notes:
            html_blocks.append('<p style="font-size:13px;color:var(--muted)">'
                               'Sin notas relevantes por ahora.</p>')
        for note in notes:
            zona = note.get("zona", "")
            zona_html = f' · {zona}' if zona else ''
            html_blocks.append(f'''
<div class="card {cat}">
  <h3><a href="{note.get("url", "#")}" style="color:inherit;text-decoration:none">{note.get("title", "")}</a></h3>
  <p>{note.get("summary", "")}</p>
  <p class="src">{note.get("source", "")}{zona_html}</p>
</div>''')
        html_blocks.append("</section>")
    return "\n".join(html_blocks)


def render_stats(notes_by_cat):
    parts = []
    for cat in CATEGORIES:
        n = len(notes_by_cat.get(cat, []))
        parts.append(f'<div class="stat"><p>{CATEGORY_LABELS[cat]}</p><p>{n} notas</p></div>')
    return "\n".join(parts)


def main():
    now_local = datetime.now(LOCAL_TZ)
    today_str = now_local.strftime("%Y-%m-%d")
    run_timestamp = now_local.isoformat()

    with open("raw_items.json", encoding="utf-8") as f:
        raw = json.load(f)

    new_notes = curate_new(raw["items"])

    accumulated = load_accumulated(today_str)
    accumulated = merge_notes(accumulated, new_notes, run_timestamp)

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(accumulated, f, ensure_ascii=False, indent=2)

    with open("templates/index_template.html", encoding="utf-8") as f:
        template = f.read()

    fecha_str = (f"{now_local.day} de {MESES[now_local.month - 1]} de {now_local.year}, "
                 f"{now_local:%H:%M} (hora de Sinaloa)")

    html = template.replace("{{FECHA}}", fecha_str)
    html = html.replace("{{STATS}}", render_stats(accumulated["notes"]))
    html = html.replace("{{CARDS}}", render_cards(accumulated["notes"]))

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

    for cat in CATEGORIES:
        print(f"  {CATEGORY_LABELS[cat]}: {len(accumulated['notes'].get(cat, []))}")
    print(f"index.html regenerado. Acumulado del día: "
          f"{sum(len(v) for v in accumulated['notes'].values())} notas "
          f"en {accumulated['run_count']} corridas.")


if __name__ == "__main__":
    main()
