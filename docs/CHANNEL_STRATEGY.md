# Estrategia de canales — AI-videoCreator

> Documento vivo. Personalizado a tus pods reales (Piña, Frutivivientes, Tico).
> Pensado para **una persona + IA**, sin equipo. Sin jerga hueca: cada punto es accionable.

---

## 0. El problema real que resuelve esto

Tienes 3 series muy distintas y cero tiempo para llevar 6 cuentas. La pregunta no es
"¿cómo hago crecer un canal?" sino "¿dónde pongo mi poca energía para que cunda?".
Respuesta corta: **1 TikTok que lo tira todo → embudo a YouTube, donde vive el
contenido largo y el dinero**.

---

## 1. Arquitectura de canales

### TikTok (y Reels/Shorts): UN canal generalista de marca

Un solo TikTok con nombre **paraguas** (no el nombre de una serie), donde entra TODO:
teasers de episodios, recreaciones, memes, cortos, datos curiosos, "cómo se hace",
what-ifs a petición. Motivo: en TikTok **el algoritmo distribuye por vídeo, no por
canal** — no te penaliza mezclar formatos como haría YouTube. Y una sola cuenta
concentra toda tu señal en vez de repartirla en cuentas de 200 seguidores.

Nombres candidatos (comprueba disponibilidad en tiktok.com/@nombre y como .com):
- **@mundofruta** / MundoFruta — encaja con Piña + Frutivivientes (universo "frutas vivientes")
- **@pixelandia** — genérico creativo, cabe cualquier serie futura
- **@elcuartodelasideas**
- **@fabricadefrutas**
- **@tocaimaginar**

Recomendación: uno corto, pronunciable y que NO te encierre en una sola serie
(descarta "PiñaEspacial" — mañana quieres subir Frutivivientes ahí).

### YouTube: **un canal por serie** (recomendado)

Analizado honestamente para tu caso:

| | Canal por serie (✅ recomendado) | Canal paraguas único |
|---|---|---|
| Audiencias | Cada una limpia: Piña=niños, Frutivivientes=adultos | **Se pisan**: un niño y un adulto de telenovela no quieren lo mismo |
| Algoritmo YT | Suscriptores homogéneos → mejor retención → más recomendación | Señal sucia: YT no sabe a quién recomendarte |
| Monetización | Piña (niños) va aparte por **COPPA/"hecho para niños"** — obligatorio separarlo | Mezclar contenido infantil y adulto en un canal es problema legal y de ads |
| Coste para ti | Más canales que gestionar | Uno solo |

**El factor decisivo es el legal + el mismatch de audiencia**: Piña es contenido
infantil (COPPA / "made for kids") y Frutivivientes es telenovela para adultos.
Meterlos en el mismo canal de YouTube te rompe la monetización y confunde al
algoritmo. Por eso, aunque sea más trabajo, **canal por serie en YouTube**.

Arranca con **1 solo canal de YouTube** (el que tenga la serie que más te ilusione
producir — probablemente Piña, que ya tienes rodada) y abre el segundo solo cuando el
primero tenga tracción. No abras 3 canales vacíos el día 1.

**Resumen de la arquitectura:**
```
                 1 TikTok generalista (marca paraguas)
                          │  (tráfico)
             ┌────────────┼────────────┐
             ▼            ▼            ▼
       YT: Piña     YT: Frutiviv.   YT: Tico
      (kids)        (adultos)       (kids)
      ↑ empieza aquí
```

---

## 2. Cadencia realista (1 persona + IA)

No prometas lo que no sostienes 3 meses. Sostenible desde el día 1:

- **TikTok: 1 short/día** (7/semana). Es el mínimo que el algoritmo respeta. Si un día
  no puedes, mejor 5 buenos que 7 a medias.
- **YouTube: 1 episodio/semana** en el canal activo. El largo es caro de producir; la
  constancia semanal importa más que la cantidad.
- **Banco de reserva**: produce en tandas. Un domingo generas 7 shorts y los programas
  con el Calendario de la app. Así un día ocupado no rompe la racha.

**Horas punta (España + LATAM):**
- Entre semana: **14:00–15:00** (comida ES) y **20:00–22:00** (ES prime + tarde LATAM).
- Fin de semana: **11:00–13:00**.
- Programa los shorts a esas horas con el Calendario (campo `scheduled_at`).

---

## 3. Mix semanal (plantilla)

Rota formatos para no quemar a la audiencia con lo mismo. Ejemplo para el TikTok único:

| Día | Formato | Fuente en la app |
|-----|---------|------------------|
| Lun | Teaser del episodio de la semana | Shorts (pipeline teaser) del episodio nuevo |
| Mar | Dato curioso (hook fuerte) | /short-creator, tema suelto |
| Mié | Recreación / what-if | Recreaciones (Omni v2v) |
| Jue | "Cómo se hace" / detrás de cámaras | Short mostrando el proceso |
| Vie | Meme / formato ligero | Memes |
| Sáb | Corto temático | /short-creator |
| Dom | What-if a petición de un comentario | Recreaciones desde petición del viewer |

El **lunes (teaser)** es el que empuja a YouTube: corta en el cliffhanger y "el episodio
completo está en mi canal".

---

## 4. El embudo TikTok → YouTube

**Lo que funciona:**
- **Cliffhanger + CTA explícito**: el short teaser corta en tensión y dice "el final
  está en YouTube" (verbal + texto en pantalla). Ya lo hace tu pipeline teaser.
- **Series numeradas**: "Parte 1" en TikTok, "completo/Parte 2" en YouTube. La gente
  persigue la continuación.
- **Pinned comment** con el link al vídeo de YouTube (no en la descripción, que nadie lee).
- **Link in bio** actualizado al último episodio.
- **Mismo gancho visual** (Piña con casco, intro reconocible) para que el de TikTok
  reconozca tu canal de YouTube al llegar.

**Lo que NO funciona (no pierdas tiempo):**
- Watermarks agresivos de otra plataforma (TikTok esconde vídeos con marca de agua de
  Reels/Shorts, y viceversa) — exporta limpio para cada una.
- "Sígueme en YouTube" a pelo sin razón: da un motivo concreto (el final, la versión larga).
- Pedir suscripción en el segundo 1: primero engancha, el CTA va al final.

---

## 5. Métricas: qué mirar cada semana

No mires seguidores. Mira estas dos, que predicen el crecimiento:

**TikTok:**
- **Retención a 3s** (¿cuánta gente no hace scroll al instante?) — si <50%, tu hook es débil.
- **Completion rate / % que lo ve entero** — el número que más pesa en el algoritmo.
- **CTR al perfil** — mide si el embudo a YouTube tira.

**YouTube:**
- **CTR de la miniatura** (2–10% es normal; <2% mala miniatura).
- **Retención media** (¿dónde se van? corta esa parte en el próximo).

**Umbrales de acción (regla simple):**
- Un formato hace **3× tu media** en 2 semanas → **dóblalo**, haz más de eso.
- Un formato hace **<0.5× tu media** 3 veces seguidas → **jubílalo**.
- Retención 3s <40% dos semanas → el problema son tus **hooks**, no el tema.

---

## 6. Primeros 30 días

**Semana 1 (montar el escaparate, sin obsesión por vistas):**
- Día 1: crea el TikTok (nombre paraguas) + el canal de YouTube de Piña. Foto, bio con
  link, banner. Conéctalos en el Centro de canales de la app.
- Día 2: sube el primer episodio completo de Piña a YouTube.
- Días 3–7: 1 short/día a YouTube+TikTok (banco que ya tienes: supernova, agujero negro,
  Neptuno). Programa a horas punta con el Calendario.

**Semanas 2–4:**
- Mantén 1 short/día + 1 episodio/semana.
- Empieza a leer métricas el **día 14** (antes no hay señal: el algoritmo tarda ~2
  semanas en clasificarte). No toques la estrategia antes de esa fecha.
- Responde TODOS los comentarios la primera semana de cada vídeo (empuja alcance).
- Al final del mes: mira qué 2 formatos funcionaron mejor y planifica el mes 2 sobre ellos.

---

## 7. Expectativas honestas

- **0 → 1.000 seguidores es lo más lento.** Es normal tirar semanas en dos cifras. No es
  señal de que falle: es cómo empieza todo el mundo.
- El algoritmo **no te conoce hasta ~2 semanas / ~10 vídeos**. Publicar constante en esa
  ventana es lo único que importa al principio.
- Un solo vídeo puede romper la tendencia de golpe (así funciona TikTok). Por eso la
  constancia > la perfección: más tiros = más probabilidad del que revienta.
- No compares tu semana 3 con un canal de 2 años.

---

*La app te ayuda: genera los shorts (/short-creator, pipeline teaser), programa las
subidas (Calendario), y `/channel-strategist` te dice cada semana qué toca publicar
según este documento.*
