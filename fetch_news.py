"""
Recolecta titulares recientes de medios de Sinaloa: los diarios impresos
desde sus portales y los principales medios digitales, de radio y de TV del
estado, con cobertura de las tres regiones (norte, centro y sur).

Cada fuente se declara una sola vez en SOURCES. Para cada una:
- Si trae "feeds", se leen esos feeds directo (lo más estable).
- Si no, se intenta descubrir su RSS probando las rutas más comunes
  (/feed/, /rss/, ?feed=rss2, etc.). Lo que se descubre se guarda en
  data/feeds.json para no volver a probar en cada corrida.
- Si no hay RSS, se scrapea la página (más frágil: puede romperse si el
  medio cambia su HTML).

Facebook, Instagram y X/Twitter no se incluyen: requieren login, no son
accesibles vía script. Ver notas_manuales.json si quieres meter algo a mano.

Salida: raw_items.json con una lista de {source, title, url, published}

IMPORTANTE sobre el orden de la salida: curate_and_render.py se queda con
los primeros MAX_ITEMS_TO_CURATE titulares del archivo. Si aquí se
escribieran uno tras otro, fuente por fuente, las primeras llenarían el
cupo y las últimas nunca llegarían al modelo. Por eso la lista se entrega
intercalada: primero el titular más reciente de cada fuente, luego el
segundo de cada una, y así.
"""

import json
import os
import re
from urllib.parse import quote_plus
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import feedparser
import requests
from bs4 import BeautifulSoup

# Un User-Agent que se anuncia como bot lo rechazan varios de estos medios
# (Cloudflare), y GitHub Actions ya corre desde IPs de datacenter, que de por sí
# son sospechosas. Los headers de un navegador real son lo que usa cualquier
# lector de RSS; aquí solo se leen titulares públicos.
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/122.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-MX,es;q=0.9,en;q=0.8",
}

# --------------------------------------------------------------------------
# Fuentes
# --------------------------------------------------------------------------

def gnews(consulta):
    """URL del RSS de búsqueda de Google News, limitada a las últimas 24 h."""
    q = quote_plus(f"{consulta} when:1d")
    return f"https://news.google.com/rss/search?q={q}&hl=es-419&gl=MX&ceid=MX:es-419"


# "feeds": lista de URLs de RSS ya confirmadas (se usan tal cual).
# Sin "feeds": se intenta descubrir el RSS y, si no hay, se scrapea el home.
# "zona" es informativo: se le pasa al modelo para que pueda agrupar.

SOURCES = [
    # ======================================================================
    # PRENSA ESCRITA (diarios y semanarios impresos, leídos desde su portal)
    # ======================================================================

    # Noroeste: diario con ediciones en Culiacán y Mazatlán y corresponsalías
    # en el norte. Se apunta a sus secciones regionales y NO a la portada,
    # que mezcla nacional e internacional. Parte de su contenido es para
    # suscriptores: el titular se ve, pero al abrir algunas notas topas con
    # el muro.
    {"name": "Noroeste (Culiacán)", "url": "https://www.noroeste.com.mx/culiacan",
     "scrape_only": True, "tipo": "Impreso", "zona": "Centro"},
    {"name": "Noroeste (Mazatlán)", "url": "https://www.noroeste.com.mx/mazatlan",
     "scrape_only": True, "tipo": "Impreso", "zona": "Sur"},
    {"name": "Noroeste (Norte)", "url": "https://www.noroeste.com.mx/norte",
     "scrape_only": True, "tipo": "Impreso", "zona": "Norte"},
    {"name": "Noroeste (El Sur)", "url": "https://www.noroeste.com.mx/elsur",
     "scrape_only": True, "tipo": "Impreso", "zona": "Sur"},
    {"name": "Noroeste (Seguridad)", "url": "https://www.noroeste.com.mx/seguridad",
     "scrape_only": True, "tipo": "Impreso", "zona": "Sinaloa"},

    # El Sol de Sinaloa y El Sol de Mazatlán (Organización Editorial Mexicana).
    # Sus sitios viven dentro de oem.com.mx; se lee la sección Local de cada uno.
    {"name": "El Sol de Sinaloa", "url": "https://oem.com.mx/elsoldesinaloa/local",
     "scrape_only": True, "tipo": "Impreso", "zona": "Centro"},
    {"name": "El Sol de Mazatlán", "url": "https://oem.com.mx/elsoldemazatlan/local",
     "scrape_only": True, "tipo": "Impreso", "zona": "Sur"},

    # Ríodoce: semanario de investigación de Culiacán, referente nacional en
    # cobertura de narcotráfico y derechos humanos. Publica menos notas que
    # un diario, pero con más peso.
    {"name": "Ríodoce", "url": "https://riodoce.mx/",
     "tipo": "Impreso", "zona": "Sinaloa"},

    # Revista Espejo: medio de Culiacán (nació como revista en 2014) con foco
    # en política, ciudadanía y transparencia.
    {"name": "Revista Espejo", "url": "https://revistaespejo.com/",
     "tipo": "Impreso", "zona": "Centro"},

    # El Debate: diario de mayor circulación del estado, con ediciones en
    # Los Mochis, Guasave, Guamúchil, Culiacán y Mazatlán. Se lee por DOS
    # caminos, porque su robots.txt restringe el acceso automatizado y es
    # probable que bloquee algunas peticiones:
    #
    # 1. Directo a sus secciones por ciudad (patrón /seccion/<ciudad>/).
    #    Si en el log salen con 403 o con 0 notas, es que bloquea a GitHub
    #    Actions y estas entradas se pueden comentar.
    {"name": "El Debate (Culiacán)", "url": "https://www.debate.com.mx/seccion/culiacan/",
     "scrape_only": True, "tipo": "Impreso", "zona": "Centro"},
    {"name": "El Debate (Mazatlán)", "url": "https://www.debate.com.mx/seccion/mazatlan/",
     "scrape_only": True, "tipo": "Impreso", "zona": "Sur"},
    {"name": "El Debate (Los Mochis)", "url": "https://www.debate.com.mx/seccion/los-mochis/",
     "scrape_only": True, "tipo": "Impreso", "zona": "Norte"},
    {"name": "El Debate (Guasave)", "url": "https://www.debate.com.mx/seccion/guasave/",
     "scrape_only": True, "tipo": "Impreso", "zona": "Norte"},
    {"name": "El Debate (Guamúchil)", "url": "https://www.debate.com.mx/seccion/guamuchil/",
     "scrape_only": True, "tipo": "Impreso", "zona": "Centro"},
    #
    # 2. Respaldo vía Google News: se piden a Google los titulares de
    #    debate.com.mx del último día. No toca el sitio de El Debate, trae
    #    fecha de publicación (así el filtro de "solo hoy" funciona bien) y
    #    sigue funcionando aunque el camino 1 esté bloqueado. Los enlaces
    #    pasan por news.google.com antes de llegar a la nota.
    {"name": "El Debate (vía Google News)", "tipo": "Impreso", "zona": "Sinaloa",
     "quitar_sufijo": " - El Debate", "max": 30,
     "feeds": [
         gnews("site:debate.com.mx Culiacán"),
         gnews("site:debate.com.mx Mazatlán"),
         gnews("site:debate.com.mx \"Los Mochis\" OR Guasave OR Guamúchil OR Ahome"),
         gnews("site:debate.com.mx Sinaloa gobierno OR Congreso OR Fiscalía"),
     ]},

    # ======================================================================
    # MEDIOS DIGITALES, RADIO Y TV LOCALES
    # ======================================================================

    # Línea Directa: sistema de radio y portal con redacciones en Culiacán,
    # Los Mochis y Mazatlán. Su sección Sinaloa está dividida por región.
    {"name": "Línea Directa (Norte)", "url": "https://lineadirectaportal.com/seccion/sinaloa/norte/",
     "tipo": "Radio/digital", "zona": "Norte"},
    {"name": "Línea Directa (Centro)", "url": "https://lineadirectaportal.com/seccion/sinaloa/centro/",
     "tipo": "Radio/digital", "zona": "Centro"},
    {"name": "Línea Directa (Sur)", "url": "https://lineadirectaportal.com/seccion/sinaloa/sur/",
     "tipo": "Radio/digital", "zona": "Sur"},

    # Los Noticieristas (red Vibra Radio): cobertura de todo el estado. Su
    # categoría "Sinaloa hoy" agrupa norte, centro y sur.
    {"name": "Los Noticieristas", "url": "https://losnoticieristas.com/categoria/sinaloa/",
     "tipo": "Radio/digital", "zona": "Sinaloa"},

    # Luz Noticias: radio y portal con base en Los Mochis; fuerte en el norte.
    {"name": "Luz Noticias", "url": "https://www.luznoticias.mx/",
     "tipo": "Radio/digital", "zona": "Norte"},

    # Café Negro Portal: digital de Culiacán, política y seguridad estatal.
    {"name": "Café Negro", "url": "https://cafenegroportal.com/category/sinaloa/",
     "tipo": "Digital", "zona": "Centro"},

    # TV Pacífico: televisión regional con noticias por plaza.
    {"name": "TV Pacífico", "url": "https://tvpacifico.mx/noticias/sinaloa",
     "scrape_only": True, "tipo": "TV", "zona": "Sinaloa"},

    # Noticias Digitales Sinaloa: cubre el sur profundo (Escuinapa, Rosario,
    # Concordia, San Ignacio, Elota), que casi nadie más cubre a diario.
    {"name": "Noticias Digitales Sinaloa", "url": "https://noticiasdigitalessinaloa.mx/",
     "tipo": "Digital", "zona": "Sur"},

    # Sinaloa en Línea: digital independiente de Mazatlán. En prueba.
    {"name": "Sinaloa en Línea", "url": "https://sinaloaenlinea.com/",
     "tipo": "Digital", "zona": "Sur"},
]

# Rutas que se prueban al buscar el RSS de una fuente nueva.
FEED_CANDIDATES = ["feed/", "rss/", "?feed=rss2", "feed/rss/", "rss.xml", "feed.xml"]

FEED_CACHE = "data/feeds.json"

MAX_PER_SOURCE = 15

# Sinaloa es UTC-7 todo el año: México eliminó el horario de verano en 2022.
LOCAL_TZ = ZoneInfo("America/Mazatlan")

# Notas metidas a mano (ej. medios que solo existen en Facebook).
MANUALES = "notas_manuales.json"

# Enlaces del home que no son notas. Al scrapear un menú se cuelan secciones,
# avisos legales y llamados a suscribirse.
BASURA = re.compile(
    r"aviso de privacidad|t[eé]rminos y condiciones|pol[ií]tica de (privacidad|cookies)|"
    r"suscr[ií]b|reg[ií]strate|inicia sesi[oó]n|contacto|qui[eé]nes somos|directorio|"
    r"publicidad|newsletter|todos los derechos|men[uú] principal|ver m[aá]s|"
    r"lee tambi[eé]n|leer m[aá]s|clasificados|hor[oó]scopo",
    re.IGNORECASE)


def parece_nota(texto: str) -> bool:
    """Filtro mínimo: descarta enlaces de navegación y avisos legales."""
    if not 25 <= len(texto) <= 200:
        return False
    if BASURA.search(texto):
        return False
    # Un titular casi siempre trae varias palabras y un verbo; las secciones
    # del menú suelen ser dos o tres palabras en mayúsculas.
    if len(texto.split()) < 5:
        return False
    if texto.isupper():
        return False
    return True


# --------------------------------------------------------------------------
# RSS: lectura y autodescubrimiento
# --------------------------------------------------------------------------

def leer_feed(url, nombre):
    """Lee un feed y devuelve sus entradas. Lista vacía si no sirve."""
    items = []
    try:
        feed = feedparser.parse(url, agent=HEADERS["User-Agent"])
        # feedparser no truena con HTML: simplemente no trae entries. Eso es
        # exactamente lo que pasaba con una página que lista feeds en vez de un feed real.
        for entry in feed.entries[:MAX_PER_SOURCE]:
            titulo = entry.get("title", "").strip()
            if not titulo:
                continue
            items.append({
                "title": titulo,
                "url": entry.get("link", ""),
                "published": entry.get("published", "") or entry.get("updated", ""),
            })
    except Exception as e:
        print(f"[aviso] RSS falló para {nombre} ({url}): {e}")
    return items


def descubrir_feed(source, cache):
    """Encuentra la URL del RSS de una fuente, usando caché si ya se sabe.

    Devuelve la URL del feed, o None si la fuente no parece tener RSS.
    El resultado (incluido el "no tiene") se guarda en caché para no volver
    a probar seis rutas por fuente en cada corrida.
    """
    nombre = source["name"]
    if nombre in cache:
        return cache[nombre]  # puede ser None: ya sabemos que no tiene

    base = source["url"]
    if not base.endswith("/"):
        base = base.rsplit("/", 1)[0] + "/"

    for ruta in FEED_CANDIDATES:
        candidato = base + ruta
        entradas = leer_feed(candidato, nombre)
        if len(entradas) >= 3:  # 1 o 2 entradas suele ser un falso positivo
            print(f"  [descubierto] {nombre}: {candidato}")
            cache[nombre] = candidato
            return candidato

    print(f"  [sin RSS] {nombre}: se usará scraping")
    cache[nombre] = None
    return None


def cargar_cache_feeds():
    try:
        with open(FEED_CACHE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def guardar_cache_feeds(cache):
    try:
        os.makedirs(os.path.dirname(FEED_CACHE), exist_ok=True)
        with open(FEED_CACHE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=1)
    except OSError as e:
        print(f"[aviso] no pude guardar la caché de feeds: {e}")


def fetch_html(source):
    items = []
    try:
        resp = requests.get(source["url"], headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        seen = set()
        vistos_titulos = set()
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True)
            href = a["href"]
            if not parece_nota(text):
                continue
            if href in seen or text.lower() in vistos_titulos:
                continue
            if not href.startswith("http"):
                if href.startswith("/"):
                    base = re.match(r"https?://[^/]+", source["url"]).group(0)
                    href = base + href
                else:
                    continue
            seen.add(href)
            vistos_titulos.add(text.lower())
            items.append({"title": text, "url": href, "published": ""})
            if len(items) >= MAX_PER_SOURCE:
                break
    except Exception as e:
        print(f"[aviso] scraping falló para {source['name']}: {e}")
    return items


def recolectar(source, cache):
    """Trae los titulares de una fuente por el mejor camino disponible."""
    crudos = []

    if source.get("feeds"):
        for f in source["feeds"]:
            crudos.extend(leer_feed(f, source["name"]))
    elif not source.get("scrape_only"):
        feed = descubrir_feed(source, cache)
        if feed:
            crudos = leer_feed(feed, source["name"])

    if not crudos and source.get("url"):
        crudos = fetch_html(source)

    # Dedup por URL dentro de la misma fuente.
    vistos = set()
    items = []
    for it in crudos:
        clave = (it.get("url") or "").rstrip("/")
        if clave and clave in vistos:
            continue
        vistos.add(clave)
        sufijo = source.get("quitar_sufijo")
        if sufijo and it.get("title", "").endswith(sufijo):
            it["title"] = it["title"][: -len(sufijo)].strip()
        # Google News repite la misma nota entre consultas con URLs distintas.
        clave_titulo = it.get("title", "").lower()
        if clave_titulo in vistos:
            continue
        vistos.add(clave_titulo)
        it["source"] = source["name"]
        it["zona"] = source.get("zona", "")
        it["tipo"] = source.get("tipo", "")
        items.append(it)
        if len(items) >= source.get("max", MAX_PER_SOURCE):
            break
    return items


# --------------------------------------------------------------------------
# Que solo entren notas de hoy
# --------------------------------------------------------------------------
# Tres filtros, de más a menos confiable:
#   1. La fecha del RSS, cuando la fuente la manda.
#   2. La fecha metida en la URL: casi todos los medios usan /2026/08/20/ o
#      -20-08-2026 en la dirección de sus notas.
#   3. El historial: si una URL ya estaba en la portada en días anteriores,
#      no es nueva hoy aunque el medio la siga mostrando.
# Lo que no cae en ninguno de los tres se deja pasar: más vale una nota vieja
# colada que perder una buena por falta de datos.

HISTORIAL = "data/urls_vistas.json"
DIAS_QUE_RECUERDA = 4

FECHA_EN_URL = [
    re.compile(r"/(20\d{2})/(\d{1,2})/(\d{1,2})/"),          # /2026/08/20/
    re.compile(r"/(20\d{2})-(\d{1,2})-(\d{1,2})"),            # /2026-08-20
    re.compile(r"[-_](\d{1,2})[-_](\d{1,2})[-_](20\d{2})"),   # -20-08-2026
    re.compile(r"-(20\d{2})-(\d{2})-(\d{2})(?:__|/|$)"),      # -2026-10-06__ (Línea Directa)
]


def fecha_de_url(url):
    """Fecha escrita en la dirección de la nota, o None si no trae."""
    for i, patron in enumerate(FECHA_EN_URL):
        m = patron.search(url or "")
        if not m:
            continue
        try:
            a, b, c = (int(x) for x in m.groups())
            anio, mes, dia = (c, b, a) if i == 2 else (a, b, c)
            return date(anio, mes, dia)
        except ValueError:
            return None
    return None


def fecha_de_rss(publicado):
    """Fecha del campo published de un feed.

    Acepta los dos formatos que aparecen en la práctica:
    - RSS clásico / RFC 2822: "Wed, 17 Sep 2026 08:51:00 -0700"
    - Atom / ISO 8601:        "2026-09-17T08:51:00-07:00"  (YouTube usa este)
    """
    if not publicado:
        return None

    try:
        t = parsedate_to_datetime(publicado)
        return t.astimezone(LOCAL_TZ).date()
    except (TypeError, ValueError):
        pass

    try:
        t = datetime.fromisoformat(publicado.replace("Z", "+00:00"))
        if t.tzinfo is None:
            return t.date()
        return t.astimezone(LOCAL_TZ).date()
    except (TypeError, ValueError, AttributeError):
        return None


def cargar_historial():
    try:
        with open(HISTORIAL, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def guardar_historial(historial, hoy):
    """Guarda las URLs vistas y olvida las de hace más de unos días."""
    limite = (hoy - timedelta(days=DIAS_QUE_RECUERDA)).isoformat()
    vigentes = {u: d for u, d in historial.items() if d >= limite}
    try:
        os.makedirs(os.path.dirname(HISTORIAL), exist_ok=True)
        with open(HISTORIAL, "w", encoding="utf-8") as f:
            json.dump(vigentes, f, ensure_ascii=False, indent=1)
    except OSError as e:
        print(f"[aviso] no pude guardar el historial de URLs: {e}")


def filtrar_de_hoy(items, historial, hoy):
    """Deja solo lo que se puede dar por publicado hoy."""
    de_hoy, viejas, sin_fecha = [], 0, 0
    for it in items:
        fecha = fecha_de_rss(it.get("published")) or fecha_de_url(it.get("url"))

        if fecha is not None:
            if fecha == hoy:
                de_hoy.append(it)
            else:
                viejas += 1
            continue

        # Sin fecha: vale el historial. Si ya la habíamos visto otro día, fuera.
        primera_vez = historial.get(it["url"])
        if primera_vez and primera_vez < hoy.isoformat():
            viejas += 1
            continue
        sin_fecha += 1
        de_hoy.append(it)

    print(f"  filtro de fecha: {len(de_hoy)} de hoy, {viejas} descartadas por "
          f"viejas ({sin_fecha} pasaron sin fecha, por historial)")
    return de_hoy


def cargar_manuales(hoy):
    """Notas metidas a mano. Formato: lista de
    {fuente, titulo, url, fecha (YYYY-MM-DD), zona}. Solo entran las de hoy.
    """
    try:
        with open(MANUALES, encoding="utf-8") as f:
            crudas = json.load(f)
    except (OSError, ValueError):
        return []

    items = []
    for n in crudas:
        if n.get("fecha") != hoy.isoformat():
            continue
        items.append({
            "source": n.get("fuente", "manual"),
            "title": n.get("titulo", ""),
            "url": n.get("url", ""),
            "published": "",
            "zona": n.get("zona", ""),
        })
    if items:
        print(f"  {len(items)} nota(s) manual(es) de hoy")
    return items


def intercalar(por_fuente):
    """Une las listas por turnos: una nota de cada fuente, luego la siguiente.

    Así, al recortar la lista más adelante, el recorte se reparte entre todos
    los medios en vez de quedarse con los primeros dos o tres.
    """
    mezclado = []
    vueltas = max((len(v) for v in por_fuente.values()), default=0)
    for i in range(vueltas):
        for nombre in por_fuente:
            if i < len(por_fuente[nombre]):
                mezclado.append(por_fuente[nombre][i])
    return mezclado


def main():
    cache = cargar_cache_feeds()

    por_fuente = {}
    for s in SOURCES:
        por_fuente[s["name"]] = recolectar(s, cache)

    guardar_cache_feeds(cache)

    all_items = intercalar(por_fuente)

    hoy = datetime.now(LOCAL_TZ).date()
    historial = cargar_historial()
    all_items = filtrar_de_hoy(all_items, historial, hoy)
    for it in all_items:
        historial.setdefault(it["url"], hoy.isoformat())
    guardar_historial(historial, hoy)

    # Las manuales se agregan al final y no pasan por el filtro de fecha
    # (ya traen la suya) ni por el historial.
    all_items.extend(cargar_manuales(hoy))

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "items": all_items,
    }
    with open("raw_items.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print()
    for nombre, notas in por_fuente.items():
        marca = "✓" if notas else "✗"
        print(f"  {marca} {nombre}: {len(notas)} notas")

    vivas = sum(1 for v in por_fuente.values() if v)
    print(f"\nRecolectadas {len(all_items)} notas de {vivas} fuentes vivas "
          f"(de {len(por_fuente)}).")
    muertas = [n for n, v in por_fuente.items() if not v]
    if muertas:
        print(f"Fuentes sin notas hoy: {', '.join(muertas)}")


if __name__ == "__main__":
    main()
