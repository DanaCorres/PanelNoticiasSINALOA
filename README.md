# Panel de noticias — Sinaloa

Dashboard con las noticias más relevantes de Sinaloa, organizadas en Política y
gobierno, Seguridad, Economía y campo, y Sociedad. Cada nota trae su zona
(Norte, Centro, Sur o Estatal) para ver de un vistazo qué pasa en cada región.
Se actualiza solo tres veces al día (9:00, 15:00 y 19:30, hora de Sinaloa) y
acumula las notas del día; se reinicia a medianoche.

Está construido sobre el mismo motor que el panel de Nuevo León: lee RSS cuando
el medio lo tiene, scrapea cuando no, y filtra para quedarse solo con notas de hoy.

**Enfoque editorial:** política/gobierno primero (incluido el proceso rumbo a
2027), luego seguridad con prioridad a lo institucional sobre la nota roja
aislada. El modelo tiene instrucción de cubrir norte, centro y sur, para que
Culiacán no acapare el panel. El clima se descarta salvo emergencias.

## Puesta en marcha

1. Sube los archivos respetando las carpetas. Si la carpeta .github da error de
   "file is hidden", créala a mano: "Add file" -> "Create new file" -> nombre
   .github/workflows/update.yml y pega el contenido.
2. Settings -> Pages -> Deploy from a branch -> main, / (root). El panel queda en
   https://danacorres.github.io/PanelNoticiasSINALOA/
3. Settings -> Secrets and variables -> Actions -> New repository secret:
   ANTHROPIC_API_KEY (la misma key de los otros paneles; ojo, cada panel suma
   consumo).
4. Settings -> Actions -> General -> Workflow permissions -> "Read and write".
5. Actions -> "Actualizar panel de noticias — Sinaloa" -> Run workflow.

La primera corrida es la más lenta: prueba rutas de RSS en cada fuente y guarda
lo que encuentra en data/feeds.json. En el log busca `[descubierto]` (tiene RSS,
será estable), `[sin RSS]` (scraping, más frágil), `403` (el sitio bloquea a
GitHub; no se arregla con código) y la lista final de ✓ / ✗.

## Fuentes (12 medios, 24 entradas)

**Prensa escrita, desde sus portales**
- Noroeste: secciones Culiacán, Mazatlán, Norte, El Sur y Seguridad. Parte del
  contenido es para suscriptores.
- El Sol de Sinaloa y El Sol de Mazatlán (OEM): sección Local.
- Ríodoce: semanario de investigación.
- Revista Espejo: política y ciudadanía, Culiacán.
- El Debate: ver la sección de abajo.

**Digitales, radio y TV**
- Línea Directa: secciones Norte, Centro y Sur.
- Los Noticieristas (red Vibra Radio): "Sinaloa hoy", todo el estado.
- Luz Noticias: fuerte en Los Mochis y el norte.
- Café Negro Portal: Culiacán, política y seguridad.
- TV Pacífico: noticias por plaza.
- Noticias Digitales Sinaloa: sur profundo (Escuinapa, Rosario, Concordia).
- Sinaloa en Línea: Mazatlán (en prueba).

## Sobre El Debate

Es el diario de mayor circulación del estado, pero su robots.txt restringe el
acceso automatizado. Se lee por dos caminos:

1. **Directo** a sus secciones de Culiacán, Mazatlán, Los Mochis, Guasave y
   Guamúchil. Si en el log salen con 403 o con 0 notas, el sitio está
   bloqueando a GitHub Actions: comenta esas entradas y queda solo el respaldo.
   Las rutas de Los Mochis, Guasave y Guamúchil siguen el patrón de las otras
   dos pero no se pudieron verificar; el primer log lo confirmará.
2. **Vía Google News**: titulares de debate.com.mx del último día. No toca el
   sitio de El Debate y trae fecha de publicación. Los enlaces abren primero en
   news.google.com. Google limita sus feeds RSS a uso personal y no comercial;
   para uso interno de la firma conviene tenerlo en cuenta.

## Lo que NO está y por qué

- **Facebook, Instagram y X**: requieren login. Medios que viven
  principalmente ahí (como Reacción Informativa) quedan fuera; se pueden meter
  notas a mano con notas_manuales.json.

## Limitaciones

- El scraping es frágil: si un sitio rediseña, esa fuente deja de traer notas.
- Los Noticieristas y El Sol no ponen el día en la URL; sus notas dependen del
  historial para no repetirse entre días.
- Los resúmenes los genera un modelo: úsalos como primer vistazo y verifica en
  la fuente antes de decidir algo.
