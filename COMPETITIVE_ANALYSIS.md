# COMPETITIVE_ANALYSIS.md — AI-videoCreator vs. el mercado 2025–2026

> Investigación realizada en junio de 2026 mediante búsqueda web (docs públicas, reviews, benchmarks).
> Mandato: no estrategia de monetización — **qué hay que hacer para ser competitivo**.

---

## 1. Qué existe hoy: el panorama real

### 1.1 Competencia directa — cómo funcionan

#### Opus Clip (opus.pro)

El líder del segmento "long-form → shorts". Su motor **ClipAnything** escanea señales visuales, sentimiento del audio, patrones de habla y transiciones de tema para identificar los momentos más enganchantes. Pipeline completo:

1. Detecta highlights automáticamente (visual + audio + semántica).
2. Recorta y reencuadra a 9:16 vertical con **tracking del sujeto** (la IA sigue al hablante y lo mantiene centrado).
3. Genera subtítulos animados con plantillas, **énfasis de keywords** y fuentes/colores de marca.
4. (Plan Pro) Inyecta **B-roll automático** para que el clip no sea solo talking-head estático.
5. Asigna un **Virality Score (0–99)** basado en tres ejes: *Hook* (¿la intro engancha y conecta con el tema?), *Flow* (¿fluye con conclusión satisfactoria?) y *Trend* (¿alinea con tendencias actuales?).

**Datos operativos**: procesa un video en 2–5 minutos y devuelve 5–15 clips. Modelo de créditos: 1 crédito = 1 minuto de video fuente (free: 60/mes; Starter $15/mes: 150; Pro $29/mes: 3.600/año).

**Failure modes documentados** (importante para nosotros):
- El Virality Score es **considerado poco fiable por los usuarios** — clips con score bajo a menudo rinden mejor que los "virales". El score es marketing más que ciencia.
- El clipping **pierde contexto y chistes** — el sarcasmo y el humor que depende de setup largo le cuesta. Cortes irrelevantes frecuentes.
- El B-roll automático es **buggy** (a veces inserta imágenes estáticas en vez de video relevante).
- Editor torpe: usuarios exportan a Premiere/Descript para acabados.
- Procesamiento lento y proyectos fallidos reportados con frecuencia.

#### Vidyo.ai (ahora quso.ai)

Mismo segmento que Opus, rebrandeado a **quso.ai**. Diferencias operativas:

- Escanea **picos de habla, transiciones de tema y hooks de engagement** → devuelve lista rankeada de candidatos con timestamps y virality score.
- Genera **8–20 clips por video** según densidad; los creadores típicamente publican 5–8.
- **Elimina muletillas (filler words)** automáticamente — feature que nosotros no tenemos.
- Publicación y scheduling directo a TikTok/IG/YT/LinkedIn — cierran el loop completo crear→publicar.

#### Higgsfield AI

**El competidor más relevante para nuestro roadmap**, porque su modelo es generación nativa, no adaptación. Lanzado en abril de 2025, escaló a **22 millones de usuarios y 6 millones de piezas de contenido al día**.

- Es un **agregador multi-modelo**: Seedance 2.0, Kling 3.0, Veo 3.1, Wan 2.7, Sora 2 — cambias de modelo sin salir de la plataforma y comparas outputs lado a lado. *Esto valida nuestra arquitectura de providers intercambiables.*
- **Cinema Studio**: simula física óptica real — eliges cuerpo de cámara virtual, tipo de lente y focal antes de generar. Lock de personajes entre tomas, control de profundidad de campo, stacking de movimientos de cámara.
- **250+ presets** de cámara, framing y VFX (crash zooms, dolly, boltcam, bullet time, FPV drone).
- Su tesis: el valor no está en el modelo sino en la **capa de control y orquestación** encima de modelos ajenos. Exactamente nuestra posición.

#### Synthesia / HeyGen / D-ID (avatares)

- **HeyGen**: líder en realismo desde Avatar IV (ago 2025) — micro-expresiones, movimiento de cabeza natural, respuesta emocional. 175+ idiomas con traducción en tiempo real manteniendo lip-sync. Clonado con 2 min de webcam. $29/mes.
- **Synthesia**: enterprise (SOC 2 Type II, integración LMS), 140+ idiomas, $18/mes. Ligeramente mejor en movimiento de manos y entonación.
- **D-ID**: API-first para developers; único que **anima imágenes estáticas** de forma convincente. Caro: $49.99/mes por 15 min (~$3.33/min). Lip-sync inferior a los otros dos.

**Conclusión avatares**: no competimos ahí hoy, pero si añadimos talking-head, HeyGen vía API es la opción (realismo + precio), D-ID solo si necesitamos animar imágenes generadas.

#### Runway / Pika

- **Runway Gen-4.5**: lideró Artificial Analysis al lanzarse (finales 2025, 1247 Elo) pero **ya cayó fuera del top 10**. Sigue siendo el mejor para **control creativo**: referencias de imagen, consistencia de personaje brand-friendly, Gen-4 Turbo rápido, editor integrado. Sweet spot: ads y deliverables de cliente.
- **Pika 2.5**: el play de volumen — **$8/mes**, pensado para creadores que publican a diario en Reels/TikTok/Shorts. Calidad suficiente, no premium.

### 1.2 Modelos de video — estado junio 2026

| Modelo | Fortaleza | Debilidad | Coste | Para nosotros |
|---|---|---|---|---|
| **Veo 3.1** | Mejor all-around; **único con diálogo sincronizado 48kHz**; tiers Lite/Fast/Quality | Caro para volumen | API $0.03–$0.50/seg | Long-form premium (ya integrado) |
| **Seedance 2.0** (ByteDance) | #1–2 en Artificial Analysis; **multi-shot + audio nativo** | Menos conocido, ecosistema ByteDance | **$0.30/clip** | Candidato serio para shorts nativos — vigilar |
| **Kling 3.0 Omni** | **Mejor física/motion** (agua, humo, tela, acción); 4 entradas en top 10; lip-sync multilingüe desde feb 2026 | Fidelidad global por debajo de Veo | Medio | Memes y story cortos (motion > fidelidad) |
| **Runway Gen-4.5** | Control creativo, consistencia de marca | Cayó del top 10 en calidad bruta | Medio-alto | Scene recreation (V2V) cuando llegue |
| **Pika 2.5** | Volumen barato | Calidad media | $8/mes | No prioritario (LTX local cubre ese nicho gratis) |
| **Grok Imagine / Vidu 2.0** | Velocidad extrema (<15s / ~10s) | Calidad | Bajo | Solo si necesitamos preview instantáneo |
| **LTX-2 / 2.3** (local) | Ver abajo | — | **$0 marginal** | Nuestro caballo de batalla local |

**LTX-2/2.3 merece sección propia** porque es nuestra apuesta local y la investigación la valida con fuerza:

- LTX-2.3: open source **Apache 2.0** (uso comercial sin fees), 22B parámetros, **4K nativo a 50 FPS con audio sincronizado integrado**.
- Corre en **12 GB VRAM (FP8)** o 24 GB (bf16). Con NVFP4: 3× más rápido y 60% menos VRAM. En una 4090: clip en ~90 segundos; en una 3060 12GB: ~7 minutos.
- La **variante destilada completa en 8 pasos de denoising** → producción en batch de alto volumen es viable.
- ComfyUI lo trae **en el core** (no custom node), con batch queuing nativo para encolar trabajos en horas valle.

**Implicación directa**: nuestra estrategia local-first con LTX no es un compromiso — es una ventaja de coste estructural frente a toda la competencia cloud-only. Opus cobra por minuto procesado; nosotros generamos memes a coste marginal cero.

### 1.3 Qué viraliza en 2025–2026 (datos, no intuición)

**La ventana de 3 segundos** — los números concretos:

- El algoritmo de TikTok toma su primera decisión sobre el video en **~1.5 segundos**.
- **84.3%** de los TikToks virales de 2025 usan triggers psicológicos específicos en los primeros 3s.
- **65%** de quienes ven los primeros 3s ven al menos 10s; 45% llegan a 30s.
- Retención del 70–85% en los primeros 3s = **2.2× más views** totales.
- Shorts virales (1M+ views) promedian **76% de retención**; superar ~75% multiplica ×3 la probabilidad de que el algoritmo lo empuje a audiencias nuevas.
- El hook completo debe entregarse en **2–2.5 segundos** (buffer de 0.5s antes de la marca crítica). Ritmo confiado, ligeramente más rápido de lo normal.
- El error #1: el "slow build" (contexto/setup antes del gancho). Funciona en long-form; **mata** un short.

**Estructura del hook ganador** (framework repetible):
1. Abrir con movimiento (corte, gesto, cambio de escena).
2. Texto on-screen que refuerza la propuesta de valor.
3. Cliffhanger — tease de lo que viene.
4. Voz o motivo visual fuerte que fija el tono.
5. Cero fluff: sin intros, sin logos.

Los hooks más virales son **en capas**: pattern interrupt visual + pregunta verbal simultáneos — engancha córtex visual y centro de lenguaje a la vez, más difícil hacer swipe.

**Triggers psicológicos**: pattern interruption, curiosity gaps, social proof. Para educativo: list hooks, myth-busting ("Todo lo que sabes de X está mal"), "¿Sabías que...?", y el patrón *expertise + respuesta contraintuitiva* ("Pasé 6 años en [campo]. La respuesta real no es [común] — es [contraintuitiva]").

**Captions** (CapCut como referencia de mercado):
- **Word-by-word sync**: cada palabra aparece en ritmo exacto con el habla. Estándar de facto.
- **Keyword highlight**: cambiar color/bold a mitad de frase en la palabra clave (ej. "TRYING" en amarillo bold). Estilos con nombre propio: Glow, Highlight, Word, Frame.
- Auto-caption + estilizado (fuente, color, animación, reveals) es feature base de cualquier herramienta seria.

**Audio**:
- Sounds trending duran **1–3 semanas** — actuar mientras pica o no actuar.
- **TikTok Creative Center** permite filtrar música por región, industria y crecimiento de uso — descubre sonidos *antes* del pico. Es API-scrapeable.
- Para cuentas business: **solo Commercial Music Library** de TikTok o tracks con licencia — música personal en contenido de marca = video muteado o eliminado. *Esto afecta directamente a nuestro pipeline: la inyección de trending audio necesita el filtro comercial.*
- SFX: los de **transición** son los más usados (catálogo Epidemic Sound) — funcionan como señales narrativas.
- Beat-sync de cortes con detección de beats: feature estándar en CapCut, esperada por los creadores.

### 1.4 Cómo promptean los creadores a los LLM

Patrones extraídos de prompts públicos (PromptBase, Fliki, MarketingBlocks, docsbot):

- **Hooks**: 3–10 palabras máximo, conversacionales, "fáciles de decir en voz alta". Los prompts piden **lotes de 8–15 hooks** explorando **10+ ángulos psicológicos** distintos (FOMO, curiosidad, controversia, transformación, insider tip, shock, relatabilidad...) — generan variedad y el humano (o un score) elige.
- **Scripts cortos**: para 15–30s, **menos de 40 palabras**. El prompt pide: hook elegido + detalle sorprendente + micro-CTA + **sugerencias de captions on-screen** + **recomendación de tipo de sonido**. Es decir: el LLM no devuelve solo texto, devuelve *spec de producción*.
- **Frameworks nombrados**: "Pattern Interrupt" para los primeros 3s; "Story-Value-Action" para el cuerpo.
- Estructura educativa viral: **hook × body × hook × body × conclusión** en 20–30s — hooks intermedios re-enganchan, no solo el inicial.

**Lección clave**: el output del LLM competitivo es un **objeto de producción estructurado** (hook + texto + caption spec + sound spec + timing), no un guion plano. Nuestro script con `audio_text`/`duration_s`/`mood` va en esa dirección pero le faltan los campos de caption-spec y sound-spec.

---

## 2. Nuestro proyecto: BIEN vs MAL

### Lo que hacemos BIEN (validado contra el mercado)

| Capacidad nuestra | Validación de mercado |
|---|---|
| **Arquitectura multi-provider** (Veo, LTX, ElevenLabs intercambiables vía ports) | Higgsfield construyó un negocio de 22M usuarios exactamente sobre esa tesis |
| **LTX local para batch** | LTX-2.3 Apache 2.0, 12GB VRAM, destilado en 8 steps — coste marginal cero vs. modelo de créditos de Opus ($15–29/mes) |
| **LLM highlight brain** (selección de highlights por LLM, no first-N-seconds) | Equivalente conceptual al ClipAnything de Opus — y el de Opus falla en contexto/humor, o sea que no es un techo alto |
| **Captions + Ken Burns + xfade** (layer 2 reciente) | Captions animadas son table stakes; las tenemos |
| **Script estructurado por escenas** (`audio_text`, `duration_s`, `mood`) | El formato correcto — los prompts competitivos generan specs estructurados |
| **Wizard idea → blueprint → pod** | UX de "concepto a configuración" que Opus/Vidyo no tienen (ellos solo reciclan video existente) |
| **LinUCB bandit ya implementado** (`domain/services/linucb.py`) | La infraestructura para A/B de hooks **ya existe** — solo falta conectarla |
| **Google Trends infra** (`infrastructure/trends/google_trends.py`) | Base existente para trend-matching; falta extender a TikTok Creative Center |
| **Taxonomía de content types** (story, meme, scene_recreation, educational) | Nadie en la competencia segmenta por tipo de contenido con configs específicos — diferenciador potencial real |

### Lo que hacemos MAL (o no hacemos)

| Gap | Severidad | Por qué |
|---|---|---|
| **Adaptamos largo→corto en vez de generar nativo** | 🔴 CRÍTICA | Crop 16:9→9:16 de un video largo no compite con contenido diseñado para vertical. Higgsfield genera nativo. La estructura hook-2.5s/beat-pattern no puede "recortarse" de algo que no la tiene |
| **Cero optimización del hook** | 🔴 CRÍTICA | Los primeros 1.5–3s deciden TODO (decisión algorítmica en 1.5s, 2.2× views con buena retención inicial). Hoy la escena 1 sale del LLM sin reoptimizar |
| **Sin beat-sync** | 🟠 ALTA | Cortes a beat son estándar de facto (CapCut lo regala). Nuestros xfade van a timestamps arbitrarios |
| **Sin SFX** | 🟠 ALTA | Compositor silencioso. SFX de transición son los más usados del mercado; el punchline de un meme sin impact/whoosh no funciona |
| **Sin trending audio** | 🟠 ALTA | Sounds trending = combustible algorítmico (vida 1–3 semanas). No tenemos ni discovery ni inyección. Cuidado: requiere filtro Commercial Music Library |
| **Captions sin word-by-word ni keyword highlight** | 🟡 MEDIA | Tenemos drawtext por bloque; el estándar es word-sync + color pop en keywords |
| **Provider selection genérico** | 🟡 MEDIA | Veo para todo = pagar premium por memes que LTX/Kling hacen mejor (motion) y más barato. `artlist_model_selector.py` existe pero no rutea por content type |
| **Educational sin pipeline nativo corto** | 🟡 MEDIA | EduTok pide hook×body×hook×body×conclusión en 20–30s con clips separados — adaptar un explainer largo no lo produce |
| **Sin filler-word removal** | 🟢 BAJA | Vidyo lo hace; nice-to-have para nosotros (nuestro audio es TTS, controlamos el guion) |
| **Sin publicación directa** | 🟢 BAJA | Opus/Vidyo cierran el loop con scheduling. Fuera de scope inmediato pero anotado |

### Debilidades de la competencia = nuestras oportunidades

1. **Opus falla en contexto/humor/sarcasmo** → nuestro LLM highlight brain con prompts por content type (meme entiende setup/punchline) puede superar su clipping genérico.
2. **Virality scores de Opus son humo** → no copiar el score; en su lugar, **bandit real** (LinUCB ya existe) midiendo performance real.
3. **Nadie hace generación nativa por content type** → Opus/Vidyo solo reciclan; Higgsfield genera pero sin taxonomía de formatos. Nuestro wizard + pods por tipo es una posición única si añadimos generación nativa.
4. **Todos son cloud con coste por uso** → LTX local = volumen sin coste marginal.

---

## 3. Análisis por Content Type

### 3.1 Story (episodios narrativos)

**Mercado**: hook 0.5–2.5s (pregunta o giro), cliffhanger cada 15–20s, música bajo diálogo sin competir, captions solo en key moments (no toda la escena).

**Nosotros hoy**: script por escenas etiquetadas ✅, shorts engine elige highlights ✅, pacing/beat-sync/hook-optimization ❌.

**Qué falta**:
- **Hook Rewriter** (ver §4.D): regenerar los primeros 3s de cada episodio como ultra-gancho. El dato de mercado (84.3% de virales usan triggers en 3s) lo convierte en lo más rentable por esfuerzo.
- **Beat Analyzer**: librosa `beat_track` → snap de cortes a beat en transiciones.
- **Pacing heuristics**: `avg_scene_duration < 2s` → tratamiento rápido meme-like; `> 4s` → diálogo-pesado, acortar.
- **Provider hint**: corto (<60s) → Kling 3.0 (mejor motion/física, consistencia de caras) o LTX; largo (>5 min) → Veo 3.1 (único con diálogo 48kHz nativo — para story largo con diálogos esto es decisivo).

### 3.2 Meme (<20s)

**Mercado**: setup 0.5–1s (mute o música mínima), punchline 0.5–1s con SFX (impact/whoosh) y captions color-coded, trending audio en el punchline, cortes beat-locked (2–3 por segundo en clímax).

**Nosotros hoy**: content type `meme` existe en taxonomía ✅, pero sin prompting setup/punchline ❌, sin SFX ❌, sin beat-sync ❌.

**Qué falta**:
- **MemeStructurePrompt**: LLM genera setup ≤15 palabras + punchline ≤10 palabras. NO guion largo. Coincide con el patrón de mercado (<40 palabras para todo el script).
- **SFX Selector**: LLM clasifica vibe del punchline → humor: rimshot; shock: impact + bass drop; fracaso: sad trombone. Mezcla: SFX −6dB bajo diálogo.
- **BeatLocking**: último 0.5s del punchline anclado a downbeat — el timing del punchline es EL factor del meme.
- **Trending audio**: si hay sound trending compatible (y comercialmente licenciable), inyectar en punchline.
- **Provider hint**: LTX (coste cero, suficiente) o Kling (si el meme necesita física/motion). **Nunca Veo** — pagar $0.03–0.50/seg por un meme de 6s es overkill confirmado por los benchmarks de coste.

### 3.3 Scene Recreation (V2V)

**Mercado**: giro sobre escena famosa (humor/educativo/comentario cultural), fair-use respecto al original, audio propio.

**Nosotros hoy**: content type existe ✅, motor V2V no existe ❌ (deferred — correcto).

**Qué falta** (cuando toque, semanas 13+):
- **V2V Provider**: Runway es el candidato natural (video transformation con control de referencia es su fortaleza confirmada incluso tras caer en rankings de calidad bruta); Kling para modificación con física.
- **Fair-use advisor**: LLM evalúa cercanía al original y avisa.
- **Trend-matching**: extender `google_trends.py` para detectar qué escena famosa es trend → sugerir recreaciones.

**Justificación del defer**: ninguno de los datos de mercado señala V2V como driver de viralidad masiva hoy; el coste de Runway API es alto; y el riesgo legal (fair-use) añade complejidad. Mantener al final del roadmap es correcto.

### 3.4 Educational (3–30 min O shorts nativos)

**Mercado long-form (YouTube)**: hook provocativo, analogía visual animada, repetición de la clave en 3 ángulos, summary de 20s al final.

**Mercado short-form (EduTok)**: estructura **hook × body × hook × body × conclusión** en 20–30s. Hook 1–2s (pregunta, myth-busting, "¿sabías que...?"), example 10–15s, conclusión 3s. Caption con keyword destacada por sección. Audio: lo-fi/ambient educativo. Hooks de re-enganche a mitad del video, no solo al inicio.

**Nosotros hoy**: content type existe ✅, script por escenas ✅, pipeline nativo corto ❌.

**Qué falta**:
- **Short-form Educational Pipeline**: LLM genera estructura de 4 segmentos (hook 1s + explainer 10s + example 5s + conclusión 3s) → generador produce **4 clips separados** (no uno largo cortado) → compositor une con fades suaves (no jump-cuts agresivos — el educativo pide claridad, no caos) → caption con keyword destacada por sección → narración TTS clara + fondo lo-fi.
- **Hooks intermedios**: el patrón hook×body×hook×body del mercado implica que el LLM debe insertar re-enganches a mitad — añadir al prompt de estructura.
- **Long-form**: generador de analogías visuales (`ConceptVisualizerUseCase`, §4.E) — concepto abstracto → metáfora concreta animable.
- **Provider hint**: corto → Kling/LTX (claridad + turnaround); largo → Veo (consistencia long-form confirmada como su fortaleza).

---

## 4. Nuevos motores — orden por (impacto de mercado × esfuerzo)

### A. Native TikTok/Reels Generator — `GenerateNativeTikTokUseCase` 🔴 CRÍTICO

Hoy: largo → crop → no compite. La competencia que genera (Higgsfield, 6M piezas/día) genera **nativo**.

1. **Concept → TikTok structure**: LLM elige duración + beat pattern + número de segmentos según content type.
2. **Segment prompts**: por segmento, prompt visual específico (hook = "impacto visual en 1s, movimiento desde frame 1" — el dato "abrir con movimiento" del framework de hooks; payoff = "sorpresa 0.5s").
3. **Generación paralela**: cada segmento es un clip independiente (Veo/LTX/Kling según hint). Clips cortos en paralelo = más rápido y más barato que uno largo.
4. **Compose**: beat-snap + SFX + trending audio + captions word-highlighted.
5. **Output**: 15–60s nativo vertical.

Reutiliza: ffmpeg_assembler, captions layer-2, scene_mapper. Lo nuevo es el use case de estructura LLM + orquestación paralela + composer beat-aware.

### B. Beat-Locked Editing 🟠 (PRIMERO EN ORDEN — bajo esfuerzo, visible ya)

`librosa.beat_track` sobre la pista de música → grid de beats → snap de puntos de corte al beat más cercano.

- Memes: último 0.5s al downbeat.
- Educational: secciones empiezan en beat.
- Story shorts: xfades en beat.

Dependencia nueva: librosa (pure Python + numpy, sin GPU). Riesgo bajo, payoff visual inmediato.

### C. SFX Library + Auto-Selection 🟠

- Librería local: ~20 SFX royalty-free organizados por vibe (impact, whoosh, rimshot, sad trombone, bass drop, transition swipes — los de transición son los más usados del mercado).
- LLM tag: en la generación del script, cada beat narrativo recibe `sfx_vibe`.
- Mixer: SFX −6dB bajo diálogo; boost 100–200 Hz en clímax; target de loudness LUFS (−14 LUFS para plataformas sociales).

### D. Hook Rewriter — `HookRewriteUseCase` 🔴 (SEGUNDO EN ORDEN)

Los datos lo justifican solos: decisión algorítmica en 1.5s, hook en 2–2.5s, 2.2× views.

- Toma escena 1 del script → LLM la reescribe con N variantes explorando ángulos psicológicos distintos (pregunta / giro / shock visual / contrarian / expertise+contraintuitivo, según content type).
- Regenera **solo esa escena** (`hook_only=True`, resto del episodio intacto).
- **Conectar al LinUCB existente** (`domain/services/linucb.py`): cada variante de hook es un brazo; el reward es retención real post-publicación. La infra del bandit ya está — esto convierte una feature "futura" del plan original en una de corto plazo.
- Regla de prompt extraída del mercado: hook de 3–10 palabras, decible en voz alta, completo antes de 2.5s de audio TTS (validar duración con el TTS antes de aceptar la variante).

### E. Educational Animation Suggestion — `ConceptVisualizerUseCase` 🟡

- Script: "la economía es flujo de dinero" → LLM: "río con monedas fluyendo; nubosidad = inflación".
- Generador VFX: Runway como provider (su control de referencia es la fortaleza que le queda) o fallback texto-visual.
- Fallback obligatorio: sin VFX provider → texto on-screen animado, nunca bloquear el render.

### F. Trending Audio Injection 🟡

- Discovery: **TikTok Creative Center** (filtrable por región/industria/crecimiento — detecta sounds *antes* del pico) + extender `google_trends.py`.
- **Filtro legal obligatorio**: solo Commercial Music Library o royalty-free — música personal en contenido business = video muteado/eliminado. Sin este filtro la feature es una bomba.
- Ventana de acción 1–3 semanas → el discovery debe ser un job recurrente, no manual.

### G. Caption upgrade: word-by-word + keyword highlight 🟡

Estándar de mercado que nuestro drawtext por bloque no cumple:
- Timestamps por palabra (el TTS de ElevenLabs devuelve character-level timestamps — ya tenemos la fuente de datos).
- Render word-by-word con la palabra clave en color pop (el LLM marca la keyword en el script).
- Esfuerzo medio sobre la capa de captions existente.

---

## 5. Provider Hints (sugerencias, NO automático)

Default: el pod elige 1 provider, configurado una vez. Override per-episodio con sugerencia + confirmación.

| Content Type | Prioridad 1 | Prioridad 2 | Prioridad 3 | Rationale (validado) |
|---|---|---|---|---|
| Story corto (<60s) | Kling 3.0 | LTX | Veo | Kling: mejor motion/física y consistencia; LTX: gratis |
| Story largo (>5 min) | Veo 3.1 | Kling 3.0 | LTX | Veo: único diálogo 48kHz nativo + consistencia long-form |
| Meme (<20s) | LTX | Kling 3.0 | — | Coste cero local; Veo es overkill confirmado ($0.03–0.50/seg) |
| Scene Rec (V2V) | Runway | Kling | — | Runway: referencia/control es su nicho superviviente |
| Edu corto nativo | Kling 3.0 | LTX | Veo | Claridad + turnaround |
| Edu largo | Veo 3.1 | Kling 3.0 | — | Calidad + consistencia |

**Vigilar**: **Seedance 2.0** ($0.30/clip, multi-shot, audio nativo, #1–2 en rankings) no estaba en nuestro radar original y puede desbancar a Kling como Prioridad 1 en shorts nativos. Añadir spike de evaluación.

UI del hint: *"Sugerencia: para este meme, LTX (local, $0). ¿Usar en vez de Veo?"* [SÍ/NO]. El selector existente (`artlist_model_selector.py`) es el punto de extensión natural.

---

## 6. Regresiones a evitar

| Nueva feature | Posible regresión | Mitigación |
|---|---|---|
| Native TikTok gen | Scripts legacy de episodios largos dejan de aplicar | `content_type` nuevo y aislado; pipelines legacy intactos |
| Beat-locking | Subs desincronizados si los cortes se mueven post-caption | Recalcular timestamps de captions DESPUÉS del snap; test de sync antes del render |
| SFX injection | SFX enmascara diálogo | Mix test automático; target LUFS; SFX siempre −6dB bajo voz |
| Hook rewriter | Escena 1 regenerada rompe continuidad visual con escena 2 | Flag `hook_only=True`; pasar último frame de la escena 1 como referencia si el provider lo soporta |
| Trending audio | Strike de copyright / video muteado | Filtro Commercial Music Library obligatorio, hard-fail sin licencia verificada |
| Educational animation | VFX provider caído → render bloqueado | Fallback a texto visual animado; nunca bloquear |
| Word-by-word captions | Carga de render ffmpeg (un drawtext por palabra) | Pre-render de captions a overlay PNG/ASS subtitles en vez de N drawtext |
| Provider hints | Hint equivocado quema presupuesto del usuario | Hint es sugerencia con confirmación explícita, nunca auto-switch |

---

## 7. Roadmap por capas

### MVP defensivo (semanas 1–2) — bajo esfuerzo, impacto visible
- [ ] **Beat-locking** (librosa) — cortes a beat en memes y shorts. Visible de inmediato.
- [ ] **Hook Rewriter** (LLM, variantes por ángulo psicológico, `hook_only=True`) — el dato de 1.5s/2.2× lo hace la apuesta más rentable.
- [ ] Conexión Hook Rewriter ↔ **LinUCB existente** (la infra ya está; solo cablear).

### High-impact (semanas 3–6)
- [ ] **Native TikTok pipeline** (`GenerateNativeTikTokUseCase`) — CRÍTICO. Estructura LLM + generación paralela de segmentos + composer beat-aware.
- [ ] **SFX library + auto-selection** — librería por vibe + tagging LLM + mixer LUFS.
- [ ] **Provider hints UI** — extensión de `artlist_model_selector.py` + confirmación en UI.
- [ ] **Spike: evaluar Seedance 2.0** ($0.30/clip, multi-shot) como provider de shorts.

### Medium-term (semanas 7–12)
- [ ] **Caption upgrade**: word-by-word sync (timestamps de ElevenLabs) + keyword highlight.
- [ ] **Trending audio injection** — TikTok Creative Center discovery + filtro Commercial Music Library + job recurrente.
- [ ] **Educational short-form native pipeline** — 4 clips separados, hooks intermedios, fades suaves.
- [ ] **Educational animation suggestion** — depende de spike de VFX provider (Runway).

### Future (semanas 13+)
- [ ] **V2V recreation pipeline** (Runway) + fair-use advisor + trend-matching de escenas.
- [ ] **Publicación directa / scheduling** (cerrar el loop como Opus/Vidyo).
- [ ] **Filler-word removal** (baja prioridad: nuestro audio es TTS controlado).

---

## 8. Síntesis

**Lo que hay**: un mercado partido en dos — recicladores (Opus, Vidyo: largo→corto, con fallos de contexto y modelos de créditos caros) y generadores nativos (Higgsfield: multi-modelo, 6M piezas/día, capa de control sobre modelos ajenos). Los datos de viralidad son inequívocos: todo se decide en 1.5–3 segundos, los cortes van al beat, las captions son word-by-word con keywords destacadas, y el audio trending es combustible algorítmico con ventana de 1–3 semanas.

**Lo que nosotros no hacemos**: generar nativo vertical (adaptamos), optimizar el hook (la variable #1), cortar a beat, meter SFX, usar trending audio, y rutear provider por tipo de contenido.

**Cómo hacerlo**: dos quick wins (beat-locking + hook rewriter conectado al LinUCB que ya tenemos) en 2 semanas; el pipeline nativo TikTok como apuesta central en las 4 siguientes; captions/audio/educational después; V2V al final. Nuestra ventaja estructural — LTX local a coste marginal cero + taxonomía de content types que nadie más tiene — solo cuenta si el output cumple el estándar de pacing/beat/hook que el mercado ya da por hecho.

---

# FAR BEYOND — de generador de video a estación de creación total

> Ampliación de visión. Todo lo anterior (§1–8) es ser competitivo. Esto es dejar de competir en la misma categoría.
>
> Tesis: **no tenemos motor propio y eso es la ventaja, no la carencia.** Los modelos churnean brutalmente — Runway Gen-4.5 pasó de #1 a fuera del top 10 en meses; Seedance apareció de la nada y tomó el #1. Quien apuesta su producto a UN modelo muere con ese modelo. Quien construye la **capa de orquestación** sobrevive a todos los ciclos. Higgsfield demostró el modelo de negocio (22M usuarios sin entrenar un solo modelo); nosotros lo llevamos más lejos: ellos son una galería de modelos con presets — nosotros somos una **estación de producción completa** donde modelos, voces, música, avatares y efectos son piezas intercambiables.

## 9. Arquitectura Provider Plug-and-Play (el corazón)

### 9.1 De "integraciones" a "plugins": el Provider SDK

Hoy: cada provider (Veo, LTX, ElevenLabs) es código a medida en `infrastructure/providers/`. Mañana: **un provider es un paquete declarativo** que se instala sin tocar el core.

**Manifest de provider** (la pieza clave):

```yaml
# provider.yaml — ejemplo: kling-3-omni
id: kling-3-omni
version: "1.2.0"
vendor: kuaishou
capabilities:
  - text_to_video
  - image_to_video
  - lip_sync
modalities:
  output: { container: mp4, max_duration_s: 120, max_resolution: "1080p", audio: true }
cost_model:
  type: per_second
  estimate_usd: 0.08
latency:
  p50_s: 45
  p95_s: 180
quality_tier: high        # benchmark automático lo recalibra (ver 9.3)
constraints:
  max_concurrent: 4
  rate_limit_rpm: 20
auth:
  type: api_key
  vault_key: kling_api_key   # se guarda en secret_vault existente
adapter:
  type: python            # o: openapi, comfyui_workflow, http_webhook
  entrypoint: adapters/kling.py
strengths_hint: "física, motion, agua, tela, multitudes"   # consumido por el router LLM
```

Instalar provider = soltar carpeta con manifest + adapter en `providers/` (o `pip install videocreator-provider-kling`). El registry lo descubre, valida el manifest con Pydantic, lo registra en el catálogo y **aparece en la UI sin redeploy**. `domain/ports.py` ya define los contratos — esto es formalizar lo que la arquitectura hexagonal ya insinúa.

**Cuatro tipos de adapter** cubren todo el universo — **cloud y local son ciudadanos de primera clase por igual**:
1. **Python nativo** — providers complejos (lo de hoy: Veo, ElevenLabs, Artlist).
2. **OpenAPI** — el manifest apunta a un spec OpenAPI + mapping de campos; cero código para APIs simples. Por aquí entran Kling, Seedance, Runway, Pika, HeyGen, o cualquier API que el usuario quiera enchufar mañana.
3. **ComfyUI workflow** — *un JSON de workflow de ComfyUI ES un provider*. La comunidad publica miles de workflows; cada uno se vuelve un motor instalable. Esto convierte todo el ecosistema open-source local en nuestro catálogo gratis.
4. **HTTP webhook** — para motores self-hosted del usuario (su propio ComfyUI en otra máquina, un servicio interno).

**Aclaración importante**: ComfyUI no es la vía privilegiada — es el multiplicador de catálogo *local*. El catálogo *cloud* (Veo, Kling, Artlist, Seedance, el que sea) entra por los tipos 1 y 2 con el mismo manifest, el mismo registry, el mismo router. El usuario mezcla libremente: drafts con ComfyUI local gratis, render final con Veo, música de Artlist, voz de ElevenLabs — todo en el mismo DAG.

### 9.2 Capability Registry: rutear por capacidad, no por marca

El pipeline nunca pide "Veo" — pide `text_to_video(duration=8s, audio=true, quality>=high, budget<=$2)`. El registry resuelve qué providers cumplen, el router elige.

**Taxonomía de capacidades** (extensible):

| Familia | Capacidades |
|---|---|
| Video | text_to_video, image_to_video, video_to_video, lip_sync, upscale, interpolation, background_removal, style_transfer |
| Audio | tts, voice_clone, music_gen, sfx_gen, stem_separation, audio_enhance, transcription |
| Imagen | text_to_image, image_edit, inpaint, consistent_character, thumbnail_gen |
| Avatar | talking_head, avatar_clone, photo_animate |
| Texto | script_gen, hook_gen, seo_meta, translation, caption_spec |
| Análisis | virality_eval, trend_detect, beat_track, scene_detect, content_moderation |

Un render = grafo de llamadas a capacidades. Si mañana sale "VideoModelX 5.0", se escribe su manifest y **todos los pipelines existentes pueden usarlo al instante** — porque nada referencia marcas.

### 9.3 Auto-benchmark: el quality_tier se gana, no se declara

Problema real del mercado: los rankings (Artificial Analysis) cambian mensualmente. Solución: **harness de benchmark propio**.

- Suite estándar de ~20 prompts por capacidad (motion, caras, texto en pantalla, física, consistencia).
- Provider nuevo instalado → se encola benchmark automático → genera los 20 clips → un LLM-judge multimodal (+ métricas objetivas: CLIP score, OCR de texto, detección de artefactos) puntúa.
- Resultado: scorecard por dimensión (motion: 8.2, caras: 6.1, texto: 4.0...) que alimenta el router.
- Re-benchmark periódico (los providers cambian de modelo bajo el mismo endpoint sin avisar).

Esto sustituye "Kling es bueno en física porque lo leí en un blog" por datos propios y siempre frescos. **Nadie en el mercado hace esto de cara al usuario** — Higgsfield te deja comparar a mano; nosotros comparamos solos y ruteamos solos.

### 9.4 Router cost/quality/speed-aware + resiliencia

- **Presupuesto por proyecto**: el usuario fija $X o "modo gratis (solo local)"; el router optimiza calidad dentro del presupuesto. Slider calidad ↔ coste ↔ velocidad.
- **Fallback chains**: Veo caído o rate-limited → degrada a Kling → LTX local. El render nunca muere por un provider.
- **Circuit breakers + health checks**: provider con p95 disparado se saca de rotación automáticamente.
- **Cost ledger**: cada llamada registrada (provider, capacidad, segundos, $). Dashboard de gasto por proyecto/episodio/provider. Opus cobra créditos opacos; nosotros enseñamos el ticket.
- **Proxy workflow** (clave de UX, ver §10): preview con el provider más rápido/barato (LTX destilado 8-steps, Vidu ~10s) → render final con el de calidad. Es el flujo proxy/conform de la postproducción profesional, aplicado a generación.

---

## 10. La Super Interfaz: estación de creación, no formulario

Referente confeso: **Higgsfield Cinema Studio** (250+ presets, lentes virtuales, stacking de movimientos) — imitamos el *estilo de capa de control*, no dependemos de su plataforma. Y le sumamos lo que ellos no tienen: pipeline completo de producción.

### 10.1 Canvas de nodos (el "modo director técnico")

Editor visual tipo nodos (ComfyUI-style pero humano): cada nodo = capacidad (guion → escenas → t2v por escena → captions → SFX → compose). 

- Los pipelines actuales (story, meme, educational) se muestran como **grafos prefabricados editables** — el usuario novato nunca abre el canvas; el avanzado reordena, inserta nodos (un upscale aquí, un estilo allá), guarda como receta propia.
- **Recetas = JSON declarativo** versionable, exportable, compartible. El wizard actual (idea → blueprint → pod) se convierte en el generador de recetas para no-técnicos.
- Cada nodo muestra coste estimado y provider asignado; click → override manual.

### 10.2 Galería de templates estilo Higgsfield (pero como datos)

- **Presets de cámara/movimiento como prompt-fragments parametrizados**: "crash zoom", "dolly in lento", "FPV drone", "bullet time" — cada preset es un snippet de prompt + parámetros que el adapter traduce al dialecto de cada provider (Veo entiende "slow dolly in", Kling prefiere otra fraseología; el adapter mapea).
- **Templates de formato completos**: "meme setup-punchline", "edu hook×body×hook", "story cliffhanger", "carousel 7 slides", "podcast clip con audiograma" — cada uno es una receta + estilo de captions + perfil de audio + beat pattern.
- **Galería con preview en video** (render de muestra por template, generado una vez con LTX local — coste cero).
- Comunidad: importar/exportar templates → marketplace a futuro (§13).

### 10.3 Timeline + Director's Chat (edición conversacional)

- **Timeline frame-accurate en navegador** (WebCodecs para decode, WebGPU para efectos en preview): escenas como bloques, captions como pista, audio con waveform y grid de beats visible (los cortes beat-locked se VEN).
- **Regeneración quirúrgica**: click en escena → "regenerar solo esto" (ya existe `scene_regenerator.py` — exponerlo como gesto de UI de primera clase). Cache por segmento: cambiar la escena 3 no re-renderiza las otras 11.
- **Director's Chat**: panel conversacional que opera sobre el proyecto — "haz el hook más agresivo", "la música pisa el diálogo, bájala", "cambia escena 2 a atardecer", "todo 20% más rápido". El LLM traduce a operaciones sobre la receta/timeline y muestra el diff antes de aplicar. *Esto es lo que Opus llama "editor" y los usuarios abandonan por Premiere — nosotros lo hacemos conversacional.*
- **Brand kits**: fuentes, paleta, logo, voz clonada, tono de escritura, watermark — por pod/canal. Todo render lo hereda.

### 10.4 Asset Library semántica (local-first)

- Todo lo generado (clips, audios, imágenes, guiones) indexado con embeddings → búsqueda semántica: "aquel clip del río con monedas" la encuentra.
- Modo local: FAISS + SQLite + filesystem (alineado con el principio local-first del proyecto). Modo cloud: pgvector/S3.
- Deduplicación y reuso: el compositor sugiere assets existentes antes de generar de nuevo ("ya tienes un clip de 'ciudad de noche lluvia' al 92% de similitud — ¿reusar y ahorrar $0.40?").

---

## 11. Backend a la altura

### 11.1 Todo render es un DAG

- Cada render = grafo dirigido de jobs (generar 4 segmentos en paralelo → esperar → componer → caption → mix). El orquestador ejecuta el DAG con: paralelismo real, reintentos por nodo, **resumabilidad** (caída a mitad → retoma desde el último nodo completo; `resume_handler.py` existente es el embrión).
- Cola con prioridades: preview > render final > benchmark > batch nocturno.
- Modo local: cola in-process + SQLite (existente). Modo serio: el mismo DAG sobre Redis/Postgres sin cambiar la definición del grafo — la definición es declarativa.

### 11.2 Render farm híbrida

- **Local**: scheduler de GPU consciente de VRAM (`memory_manager.py` existente) — encola LTX/ComfyUI según VRAM libre, batch nocturno en horas valle.
- **Cloud burst**: cuando lo local no da o el job pide calidad cloud, el mismo DAG despacha a APIs. El usuario ve una sola cola.
- **Multi-máquina**: el adapter HTTP webhook (§9.1) permite registrar "mi otra torre con la 4090" como worker.

### 11.3 Eventos y observabilidad

- Progreso por SSE/WebSocket a la UI (barra real por nodo del DAG, no spinner mentiroso).
- Webhooks salientes: "render terminado" → Zapier/n8n/Discord del usuario.
- Métricas por provider (latencia, error rate, coste) alimentan circuit breakers y el scorecard del benchmark.
- structlog ya adoptado (commits recientes) — extender con trace-id por render para depurar DAGs.

---

## 12. Capa de inteligencia: el loop que nadie cierra

Aquí está el moat real. Opus tiene un Virality Score **falso** (los usuarios lo dicen). Nosotros podemos tener uno **verdadero** porque cerramos el loop publicación → métricas → aprendizaje.

### 12.1 Performance feedback loop

1. Publicar (o registrar publicación manual) → ingestar métricas reales (views, retención por segundo, shares) vía APIs de plataforma.
2. Cada video lleva su "genoma": template usado, tipo de hook, provider, duración, beat pattern, hora de publicación, sonido.
3. **LinUCB existente** generaliza: de elegir hooks a elegir *cualquier* dimensión del genoma. Brazos = variantes; reward = retención real.
4. Resultado emergente: **Virality Score propio entrenado con datos propios del canal** — no un número genérico, sino "para TU audiencia, este genoma predice X". Eso Opus no puede copiarlo: no tiene el pipeline de generación para actuar sobre la predicción.

### 12.2 Trend Radar + Daily Briefing

- Fuentes: TikTok Creative Center (sonidos pre-pico), Google Trends (existente), YouTube trending, subreddits del nicho.
- Job recurrente nocturno → briefing matinal por pod: "3 sonidos subiendo en tu nicho, 2 formatos ganando tracción, 1 escena famosa trending (candidata a scene recreation)". Con botón: "crear desde esta tendencia" → wizard pre-rellenado.
- Ventana de sonidos 1–3 semanas → el radar es la diferencia entre surfear la ola y llegar tarde.

### 12.3 Autopilot por canal

El final del camino: **canal en piloto automático supervisado**.

- Perfil de canal: audiencia, nicho, tono, cadencia (ej. 1 long + 5 shorts/semana).
- El sistema propone calendario semanal desde el Trend Radar → genera borradores → cola de aprobación humana (swipe: aprobar / regenerar / editar) → programa publicación.
- El feedback loop (§12.1) ajusta el genoma de lo que propone. El humano pasa de operario a editor jefe.
- Niveles de autonomía configurables: desde "propón ideas" hasta "publica solo lo que supere score X" (siempre con kill-switch).

### 12.4 El Cerebro Viral: agente LLM + MCP + análisis multimodal de video

El Trend Radar (§12.2) lee *datos* de tendencias (sonidos, búsquedas, hashtags). Eso no basta para memes: un meme es un **formato audiovisual** — no se entiende leyendo una API, se entiende *viendo el video*. El Cerebro Viral es la pieza que ve.

#### Arquitectura: un agente con herramientas, no un cron job

El cerebro es un **agente LLM con tool-use** cuyas herramientas se enchufan igual que los providers — vía **MCP (Model Context Protocol)**, el estándar plug-and-play para fuentes de inteligencia. Misma filosofía que el manifest de §9.1: añadir una fuente nueva = conectar un MCP server, no escribir integración a medida.

**Herramientas del agente (MCP servers + capabilities internas):**

| Herramienta | Qué da | Vía |
|---|---|---|
| Web search | "qué meme está explotando esta semana", artículos, KnowYourMeme | MCP search server |
| TikTok Creative Center | sonidos/hashtags por región e industria, pre-pico | scraper/MCP propio |
| YouTube Data API | trending por categoría, métricas de Shorts | MCP |
| Reddit/X del nicho | memes emergentes antes de llegar a TikTok | MCP |
| Google Trends | ya existente (`google_trends.py`) — se expone como tool | interno |
| **Video Analyst** | ingesta video/URL → genoma viral (ver abajo) | capability `video_understand` del registry |
| Biblioteca de formatos | memoria persistente de formatos detectados | interno (FAISS local) |

#### Video Analyst: pásale un video o una URL y lo descompone

El flujo estrella — el usuario (o el propio agente desde el radar) entrega un video viral:

1. **Ingesta**: URL (TikTok/YouTube/Reels) → descarga vía yt-dlp → o archivo local directo.
2. **Análisis multimodal** — capability `video_understand` del registry, con dos rutas (plug-and-play, como todo):
   - **Ruta cloud**: Gemini multimodal ingiere el video entero nativamente (ya tenemos `gemini_llm.py` — extensión natural).
   - **Ruta local**: extracción de frames + Whisper para audio/transcripción + LLM local (Ollama existente) sobre frames descritos. Más barato, menos fino. *(El plugin claude-video-vision del entorno de desarrollo es exactamente este patrón — frames + whisper — validado.)*
3. **Output: el genoma viral del video**, estructurado:

```json
{
  "format_id": "expectation-subversion-v3",
  "hook": { "type": "visual_pattern_interrupt", "duration_s": 1.2, "text_overlay": "POV: ..." },
  "structure": [
    { "beat": "setup", "duration_s": 2.5, "audio": "trending_sound_X", "camera": "static_selfie" },
    { "beat": "punchline", "duration_s": 1.0, "sfx": "bass_drop", "cut_style": "hard_cut_zoom" }
  ],
  "captions": { "style": "word_by_word", "highlight": "yellow_bold_keyword" },
  "sound": { "id": "...", "trending": true, "commercial_safe": false },
  "why_it_works": "subversión de expectativa + sonido en pico + payoff antes del swipe",
  "remixability": 0.87,
  "decay_estimate": "1-2 semanas"
}
```

4. **De genoma a receta**: un clic — el genoma se traduce a una receta del canvas (§10.1) parametrizada con el nicho/brand kit del usuario: *"este formato de meme, pero sobre TU tema"*. El gap de Opus (no entiende humor/contexto) se convierte en nuestra fortaleza: no recortamos el chiste de otro — **entendemos el formato del chiste y lo recreamos nativo**.

#### Biblioteca viva de formatos de meme

Los memes son formatos con ciclo de vida (1–3 semanas el sonido, algo más el formato). El cerebro mantiene una **biblioteca persistente**:

- Cada video analizado deposita su genoma; genomas similares se agrupan → "formato" (embedding + clustering en FAISS local).
- Cada formato lleva: curva de adopción estimada (¿emergiendo, pico, quemado?), nichos donde funciona, recetas derivadas, performance de nuestras recreaciones (conecta con el loop §12.1).
- El Daily Briefing (§12.2) pasa de "3 sonidos subiendo" a: **"formato nuevo detectado ayer en 4 videos del nicho: [preview + genoma]. Está pre-pico. Receta lista — ¿generar?"**
- Anti-cementerio: formatos marcados "quemados" se vetan en sugerencias (llegar tarde a un meme es peor que no llegar).

#### Modos de uso

1. **Pull manual**: "analiza este video" (URL o archivo) → genoma + receta. El usuario ve algo en su feed, lo pega, lo tiene desmontado en 2 minutos.
2. **Push del radar**: el agente patrulla fuentes (job recurrente), detecta candidatos, analiza los top-N con Video Analyst, archiva genomas, briefea.
3. **Conversacional**: "¿qué memes hay esta semana sobre IA?" → el agente busca, analiza, responde con formatos + ofertas de generación. Es el Director's Chat (§10.3) con el cerebro detrás.

#### Por qué MCP y no integraciones fijas

Las fuentes de tendencias churnean igual que los modelos de video: APIs que cierran, plataformas nuevas, scrapers que mueren. MCP da al cerebro lo que el manifest da a los motores: **las fuentes son enchufables**. Mañana sale una plataforma nueva → alguien publica su MCP server → el cerebro la ve sin tocar el core. Y los MCP servers de la comunidad (búsqueda, Reddit, YouTube…) ya existen — catálogo gratis, otra vez.

### 12.5 Moderación y seguridad de contenido

Al escalar a autopilot, obligatorio: capability `content_moderation` en el registry (LLM + reglas) que revisa guion y video final antes de publicar — claims médicos/financieros, copyright (el filtro Commercial Music Library de §4.F), contenido sensible por plataforma. Sin esto el autopilot es un riesgo de cuenta baneada.

---

## 13. Multiplicación de contenido: una idea → todos los formatos

La estación no produce "un video" — produce **una campaña** desde un concepto. La matriz de multiplicación:

| Input: 1 concepto (o 1 video largo) | Outputs |
|---|---|
| Video long-form (YouTube) | el master |
| 3–8 shorts nativos (TikTok/Reels/Shorts) | pipelines §4.A |
| Carousel Instagram (7–10 slides) | text_to_image + layout engine |
| Thumbnail A/B (3 variantes) | image gen + el bandit elige por CTR real |
| Audiograma / clip de podcast | waveform + captions sobre audio |
| Thread X/LinkedIn post | script_gen reutiliza el guion |
| Newsletter / post de blog SEO | infra SEO existente (`use_cases/seo.py`) |
| Versión doblada (N idiomas) | tts + lip_sync (`manual_dubbing.py` es el embrión) |

Cada celda es una receta del canvas (§10.1) — la matriz entera es "un meta-pipeline que invoca recetas". Esto es lo que convierte la herramienta en *estación*: el creador entra con una idea y sale con la semana entera de contenido multicanal coherente (mismo brand kit, mismo mensaje, formato nativo por plataforma).

Avatares entran aquí como capability más (`talking_head` — HeyGen/D-ID como plugins): el mismo guion puede salir como video generado, como avatar presentando, o ambos para A/B.

---

## 14. Por qué esto gana (moats) y qué NO hacer

### Moats reales

1. **Anti-churn estructural**: cada ciclo de modelos (6 meses) mata productos atados a un motor. A nosotros cada ciclo nos *mejora* — más providers, mismo producto. El manifest de §9.1 es el seguro de vida.
2. **Coste**: LTX/ComfyUI local como suelo gratis + router cost-aware. Ningún competidor cloud puede igualar "$0 marginal para drafts e iteración".
3. **Datos propios del loop** (§12): el Virality Score verdadero por canal es acumulativo y no copiable.
4. **Taxonomía + recetas**: pods por content type con producción nativa por formato — Opus/Vidyo no generan, Higgsfield no produce (no tiene captions/SFX/beat/publicación), los editores (CapCut) no orquestan modelos. La intersección está vacía. Es nuestra.
5. **Ecosistema**: adapters ComfyUI (§9.1 tipo 3) = miles de motores comunitarios instalables que ningún competidor cerrado puede absorber. A futuro: marketplace de recetas/templates de la comunidad.

### Qué NO hacer (anti-goals)

- **No entrenar modelos propios.** Nunca. Es el negocio de otros y el cementerio está lleno.
- **No clonar CapCut**: el timeline (§10.3) es para *ajustar* lo generado, no para edición manual desde cero. Si el usuario quiere editar a mano 40 pistas, que exporte.
- **No perseguir cada modelo nuevo a mano**: por eso existe el manifest + auto-benchmark. La regla: integrar = escribir manifest, no escribir código.
- **No romper local-first**: cada feature de esta visión debe tener su modo SQLite/FS/FAISS sin Docker. El autopilot puede correr 100% local salvo la publicación.
- **No autopilot sin humano en el loop por defecto** (§12.5).

## 15. Roadmap extendido (continúa el de §7)

### Fase A — Fundación plugin (semanas 13–18)
- [ ] **Provider SDK v1**: spec del manifest + registry + validación Pydantic + carga dinámica. Migrar los 3 providers existentes (Veo, LTX, ElevenLabs) al formato manifest — prueba de fuego del diseño.
- [ ] **Adapter ComfyUI workflow** (tipo 3) — el multiplicador de catálogo más barato.
- [ ] **Capability router v1** con fallback chains + cost ledger.

### Fase B — Estación visible (semanas 19–28)
- [ ] **Galería de templates** (presets de cámara como prompt-fragments + templates de formato) — el "efecto Higgsfield" en UI.
- [ ] **Timeline con regeneración quirúrgica** (exponer scene_regenerator + cache por segmento).
- [ ] **Director's Chat v1** (operaciones sobre receta con diff previo).
- [ ] **Proxy workflow** (preview barato → render caro).
- [ ] **Auto-benchmark harness v1** (suite de prompts + LLM-judge).

### Fase C — Multiplicación (semanas 29–38)
- [ ] **Matriz de multiplicación**: concepto → shorts + carousel + thumbnail A/B + thread (reusar seo.py, manual_dubbing.py).
- [ ] **Asset library semántica** (FAISS local).
- [ ] **Canvas de nodos** para usuarios avanzados (las recetas ya existen desde Fase A; esto es la vista).
- [ ] **Brand kits**.

### Fase D — Inteligencia (semanas 39+)
- [ ] **Video Analyst v1** (§12.4): URL/archivo → genoma viral. Ruta cloud (Gemini multimodal sobre `gemini_llm.py`) primero; ruta local (frames + Whisper + Ollama) después. El modo pull manual ("analiza este video") es el MVP del cerebro — valor inmediato sin radar.
- [ ] **Genoma → receta**: traducción de genoma a receta del canvas parametrizada por nicho/brand kit.
- [ ] **Cerebro Viral como agente MCP**: tool-use sobre web search + TikTok Creative Center + YouTube + Reddit + google_trends existente. Fuentes enchufables como MCP servers.
- [ ] **Biblioteca viva de formatos** (clustering de genomas en FAISS local + curva de adopción + veto de formatos quemados).
- [ ] **Ingesta de métricas** + genoma de video + LinUCB generalizado.
- [ ] **Trend Radar + Daily Briefing** (radar push: patrulla fuentes → analiza top-N → briefea con receta lista).
- [ ] **Autopilot supervisado** con moderación obligatoria y niveles de autonomía.
- [ ] **Marketplace de recetas/templates** (cuando haya masa de usuarios).

### Regresiones a vigilar en la ampliación

| Cambio | Riesgo | Mitigación |
|---|---|---|
| Migración a manifests | Romper los 3 providers en producción | Migrar uno a uno; tests de contrato por capability (test_provider_router existente como base) |
| Router automático | Elegir provider caro sin querer | Presupuesto hard-cap por proyecto; hint con confirmación se mantiene (§5) |
| Canvas de nodos | Complejidad espanta a usuarios wizard | Canvas opcional; wizard sigue siendo la puerta por defecto |
| Autopilot | Publicar contenido problemático | Moderación bloqueante + aprobación humana por defecto + kill-switch |
| Asset reuse | Reusar clip que no encaja | Umbral de similitud alto + siempre preview antes de reusar |

---

# GUÍA DE IMPLEMENTACIÓN TÉCNICA — para ejecutar, no pensar

> Cada feature de §4 y §9–13 mapeada a: dependencias exactas, servicios, archivos a crear (rutas reales de esta arquitectura hexagonal), firmas de código y gotchas. El modelo que implemente esto debe poder seguirlo sin tomar decisiones de diseño.

## 16.0 Convenciones y deps base

**Arquitectura existente** (respetar siempre):
- Contratos/puertos → `backend/src/videocreator/domain/ports.py`
- Lógica de negocio pura → `backend/src/videocreator/domain/services/`
- Use cases → `backend/src/videocreator/application/use_cases/`
- Adapters/IO → `backend/src/videocreator/infrastructure/`
- Endpoints → `backend/src/videocreator/interfaces/rest/routers/` (+ schemas en `schemas.py`)
- Tests unitarios → `backend/tests/unit/`

**Reglas duras**:
1. Ningún use case importa de `infrastructure/` — solo puertos de `domain/ports.py`.
2. Todo nuevo módulo usa `structlog` (ya adoptado), nunca `print`.
3. Config por `shared/config.py` (pydantic-settings), secrets por `secret_vault` existente.
4. Modo local-first siempre: cada feature con dependencia cloud lleva fallback local o se degrada limpio.

**Deps base nuevas** (añadir a `backend/pyproject.toml`):

```toml
[project.optional-dependencies]
audio = ["librosa>=0.10", "soundfile>=0.12", "pyloudnorm>=0.1"]
captions = ["pysubs2>=1.6"]
brain = ["yt-dlp>=2026.1", "faster-whisper>=1.0", "mcp>=1.0"]
vector = ["faiss-cpu>=1.8", "sentence-transformers>=3.0"]
sched = ["apscheduler>=3.10"]
resilience = ["tenacity>=8.2"]
bench = ["open-clip-torch>=2.24", "pytesseract>=0.3"]
```

`ffmpeg` ya es dependencia del sistema (lo usa `ffmpeg_assembler.py`). Para OCR del benchmark: instalar Tesseract (`winget install UB-Mannheim.TesseractOCR` en Windows; `apt install tesseract-ocr` en Linux).

---

## 16.1 Beat-Locking (librosa)

**Deps**: `pip install librosa soundfile` (librosa arrastra numpy/scipy, sin GPU).

**Archivos**:
- Crear `domain/services/beat_grid.py` — lógica pura.
- Modificar `infrastructure/video/ffmpeg_assembler.py` — consumir grid en los puntos de corte.
- Test: `tests/unit/test_beat_grid.py`.

**Implementación** de `beat_grid.py`:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class BeatGrid:
    bpm: float
    beat_times_s: tuple[float, ...]      # tiempos de beat en segundos
    downbeat_times_s: tuple[float, ...]  # cada 4º beat (asumir 4/4)

    def snap(self, t: float, tolerance_s: float = 0.35, downbeat: bool = False) -> float:
        """Devuelve el beat más cercano a t si está dentro de tolerance_s; si no, t intacto."""
        grid = self.downbeat_times_s if downbeat else self.beat_times_s
        if not grid:
            return t
        nearest = min(grid, key=lambda b: abs(b - t))
        return nearest if abs(nearest - t) <= tolerance_s else t


def analyze_beats(audio_path: str) -> BeatGrid:
    import librosa
    y, sr = librosa.load(audio_path, sr=22050, mono=True)
    tempo, beat_times = librosa.beat.beat_track(y=y, sr=sr, units="time")
    beats = tuple(float(b) for b in beat_times)
    return BeatGrid(bpm=float(tempo), beat_times_s=beats, downbeat_times_s=beats[::4])
```

**Integración en assembler**: donde hoy se calculan los timestamps de corte/xfade, interceptar:

```python
if beat_grid is not None:
    cut_t = beat_grid.snap(cut_t)
# memes: el corte del punchline usa downbeat=True
```

**Gotchas**:
- `librosa.load` falla con algunos AAC → extraer antes con ffmpeg a WAV temp: `ffmpeg -i in.mp4 -vn -ar 22050 -ac 1 tmp.wav`.
- `beat_track` devuelve `tempo` como ndarray en versiones nuevas → castear `float(tempo)` (o `tempo.item()`).
- Tras mover cortes, **recalcular timestamps de captions** (regresión documentada en §6). Orden obligatorio: snap de cortes → THEN generar captions.
- Música sin percusión clara (ambient/lo-fi): si `len(beats) < duración/2` beats esperados, desactivar snap (la grid no es fiable).

---

## 16.2 Hook Rewriter + conexión LinUCB

**Deps**: ninguna nueva (usa `gemini_llm.py`/`ollama_llm.py` y `linucb.py` existentes).

**Archivos**:
- Crear `application/use_cases/hook_rewrite.py`.
- Crear prompt en el sistema de prompts existente (donde vivan los de script-gen).
- Endpoint: añadir a `interfaces/rest/routers/episodes.py` → `POST /episodes/{id}/rewrite-hook`.
- Test: `tests/unit/test_hook_rewrite.py` con LLM fake.

**Use case**:

```python
ANGLES = ["question", "contrarian", "visual_shock", "expertise_counterintuitive", "curiosity_gap"]

class HookRewriteUseCase:
    def __init__(self, llm: LLMPort, tts: TTSPort, scenes: SceneRepoPort, bandit: LinUCB):
        ...

    async def execute(self, episode_id: str, n_variants: int = 5) -> list[HookVariant]:
        scene1 = await self.scenes.get_first(episode_id)
        variants = []
        for angle in ANGLES[:n_variants]:
            text = await self.llm.complete(HOOK_PROMPT.format(
                original=scene1.audio_text, angle=angle, content_type=scene1.content_type))
            dur = await self.tts.estimate_duration_s(text)   # ver gotcha
            if dur <= 2.5 and len(text.split()) <= 10:        # reglas de mercado, §1.3
                variants.append(HookVariant(angle=angle, text=text, est_duration_s=dur))
        return variants
```

**Reglas del prompt** (constantes, extraídas del research): hook 3–10 palabras, decible en voz alta, sin setup, completo en ≤2.5s. Una plantilla por `angle` con 2 few-shots cada una.

**Regeneración**: flag `hook_only=True` en el job de render → solo regenera el clip de la escena 1, reusa el resto (cache por escena, `scene_regenerator.py` ya hace esto por escena — reusarlo, no duplicarlo).

**LinUCB wiring**: cada variante publicada = brazo. Contexto = features del episodio (content_type, duración, hora). Reward = retención a 3s cuando lleguen métricas (§16.14); mientras no haya ingesta de métricas, reward manual desde UI (botón "esta funcionó").

**Gotcha**: `estimate_duration_s` sin llamar al TTS de pago — heurística: español ≈ 4.5 palabras/seg a ritmo rápido → `len(words)/4.5`. Validación real solo al renderizar.

---

## 16.3 SFX Library + Auto-Selection + Mixer LUFS

**Deps**: `pip install pyloudnorm` (medición; la corrección la hace ffmpeg).

**Assets**: crear `backend/assets/sfx/` con ~20 WAV royalty-free. Fuentes de descarga: freesound.org (filtrar licencia CC0), pixabay.com/sound-effects. Nombrar por vibe: `impact_01.wav`, `whoosh_01.wav`, `rimshot_01.wav`, `sad_trombone_01.wav`, `bass_drop_01.wav`, `transition_swipe_01.wav`... Manifest `backend/assets/sfx/catalog.json`:

```json
{ "impact": ["impact_01.wav", "impact_02.wav"], "whoosh": ["whoosh_01.wav"], ... }
```

**Archivos**:
- Crear `infrastructure/media/sfx_library.py` — carga catálogo, resuelve vibe → path (random entre candidatos).
- Modificar el prompt de script-gen: añadir campo `sfx_vibe: str | null` por escena/beat (enum: impact, whoosh, rimshot, sad_trombone, bass_drop, transition, none).
- Modificar `ffmpeg_assembler.py` — etapa de mezcla.

**Mezcla ffmpeg** (filtros exactos):

```
# SFX a -6dB bajo el diálogo, en el timestamp t del beat:
[sfx]adelay={t_ms}|{t_ms},volume=-6dB[sfxd];
[dialogue][sfxd]amix=inputs=2:duration=first:normalize=0[mixed];
# Normalización final a -14 LUFS (estándar plataformas sociales):
[mixed]loudnorm=I=-14:TP=-1.5:LRA=11[out]
```

**Gotchas**:
- `amix` con `normalize=0` obligatorio — sin él baja el volumen de todo.
- `loudnorm` en una pasada es aproximado; suficiente para shorts. Two-pass solo para long-form (primera pasada con `print_format=json`, segunda con los valores medidos).
- Test automático anti-enmascaramiento: medir LUFS del diálogo solo vs. mezcla con pyloudnorm; si la mezcla baja la inteligibilidad (>3dB de caída en la banda 1–4kHz), bajar SFX a -9dB y reintentar.

---

## 16.4 Captions word-by-word + keyword highlight

**Deps**: `pip install pysubs2`.

**Fuente de timestamps**: ElevenLabs endpoint `POST /v1/text-to-speech/{voice_id}/with-timestamps` → devuelve `alignment.characters[]` + `character_start_times_seconds[]`. Agrupar caracteres en palabras (split por espacios, acumulando tiempos).

**Archivos**:
- Modificar `infrastructure/providers/elevenlabs_voices.py` (o donde se llame al TTS): usar variante with-timestamps, devolver `list[WordTiming(word, start_s, end_s)]`.
- Crear `infrastructure/video/ass_captions.py` — genera archivo `.ass`.
- Modificar `ffmpeg_assembler.py`: sustituir drawtext por blocks → burn de ASS.

**Generación ASS con pysubs2**:

```python
import pysubs2

def build_ass(words: list[WordTiming], keywords: set[str], out_path: str, style: CaptionStyle):
    subs = pysubs2.SSAFile()
    subs.styles["Default"] = pysubs2.SSAStyle(
        fontname=style.font, fontsize=style.size, bold=True,
        primarycolor=pysubs2.Color(255, 255, 255),
        outlinecolor=pysubs2.Color(0, 0, 0), outline=3,
        alignment=pysubs2.Alignment.BOTTOM_CENTER, marginv=style.margin_v)
    for w in words:
        text = w.word.upper()
        if w.word.lower().strip(".,!?") in keywords:
            text = r"{\c&H00D7FF&\fscx115\fscy115}" + text   # amarillo + 15% más grande
        subs.events.append(pysubs2.SSAEvent(
            start=int(w.start_s * 1000), end=int(w.end_s * 1000), text=text))
    subs.save(out_path)
```

**Burn**: `ffmpeg -i video.mp4 -vf "ass=subs.ass" -c:a copy out.mp4`. En Windows escapar ruta: `ass='C\:/path/subs.ass'`.

**Keywords**: el LLM ya genera el script — añadir al prompt: "marca 1–2 palabras clave por frase con **asteriscos**". Parsear asteriscos → set de keywords.

**Gotchas**:
- ASS es mucho más barato en render que N drawtext (regresión de §6 resuelta de fábrica).
- Color ASS es **BGR** no RGB: amarillo = `&H00D7FF&` (si quieres #FFD700).
- Palabras <120ms de duración: fusionar con la siguiente (parpadeo ilegible).
- Si TTS no es ElevenLabs (Ollama-local pipeline): fallback con faster-whisper sobre el audio generado, `word_timestamps=True`.

---

## 16.5 Pipeline Nativo TikTok

**Deps**: ninguna nueva (asyncio + todo lo anterior).

**Archivos**:
- Crear `application/use_cases/native_short.py` → `GenerateNativeShortUseCase`.
- Crear `domain/value_objects.py` → añadir `ShortStructure`, `ShortSegment`.
- Endpoint: `interfaces/rest/routers/shorts.py` → `POST /shorts/native`.
- Prompt nuevo: estructura por content_type.

**Modelos**:

```python
class ShortSegment(BaseModel):
    role: Literal["hook", "body", "rehook", "example", "payoff", "conclusion"]
    duration_s: float            # hook<=1.5, payoff<=1.0...validar por rol
    visual_prompt: str           # prompt t2v específico del segmento
    audio_text: str | None
    sfx_vibe: str | None
    cut_style: Literal["hard", "xfade", "zoom_punch"]

class ShortStructure(BaseModel):
    total_duration_s: float      # 15–60
    segments: list[ShortSegment]
    music_vibe: str              # para selector de música/Artlist
    caption_keywords: list[str]
```

**Flujo del use case** (orden exacto):
1. LLM → `ShortStructure` (prompt por content_type; meme: setup+punchline 2 segmentos; edu: hook+body+rehook+body+conclusion). Validar con Pydantic; 1 retry si JSON inválido.
2. Generación **paralela** de segmentos: `asyncio.gather(*[provider.generate(seg.visual_prompt, seg.duration_s) for seg in segments])`. Provider resuelto por router (§16.8) con el content_type como hint.
3. TTS por segmento con timestamps (§16.4).
4. Música: selector existente (`artlist_model_selector.py`) por `music_vibe` → `analyze_beats` (§16.1).
5. Compose: concat de segmentos con `cut_style` por junta, cortes snapped a beat, SFX (§16.3), captions ASS (§16.4), loudnorm final.
6. Persistir como episodio con `content_type=native_short` — **aislado de pipelines legacy** (regresión §6).

**Gotcha**: los providers t2v no clavan duraciones exactas — pedir `duration_s + 0.5` y recortar con `-ss 0 -t {duration_s}` en el compose. Nunca estirar (slow-mo delata).

---

## 16.6 Trending Audio (discovery + filtro legal)

**Deps**: `pip install playwright` + `playwright install chromium` (Creative Center no tiene API pública).

**Archivos**:
- Crear `infrastructure/trends/tiktok_creative_center.py`.
- Crear `application/use_cases/trending_audio.py`.
- Job recurrente: registrar en scheduler (§16.13).

**Scraping Creative Center** (URL pública: `ads.tiktok.com/business/creativecenter/inspiration/popular/music/pc/en`):

```python
async def fetch_trending_sounds(region: str = "ES", limit: int = 30) -> list[TrendingSound]:
    # Playwright headless → la página carga JSON vía XHR interno.
    # Estrategia: interceptar response de la ruta que contiene "/creative_radar_api/" 
    # (page.on("response", ...)), parsear JSON: nombre, autor, rank, uso, link.
    ...
```

**Filtro legal (HARD-FAIL, §6)**: el Creative Center marca `is_commercial` en su payload (Commercial Music Library). Regla: `if not sound.is_commercial and pod.is_business: descartar`. Sin metadato fiable → descartar por defecto. Los sounds NO se descargan de TikTok (ToS): el flujo correcto es sugerir el sound al usuario para añadirlo EN la plataforma al publicar, y en el render usar música royalty-free del catálogo Artlist existente con BPM similar (matching por `analyze_beats`).

**Gotchas**:
- Scraper = frágil por diseño. Encapsular en try/except amplio → si falla, el Daily Briefing sale sin sección de sounds, nunca rompe.
- Cachear resultados 24h en SQLite (tabla `trend_cache(source, payload_json, fetched_at)`).

---

## 16.7 Provider SDK: manifest + registry + 4 adapters

**Deps**: `pip install pyyaml` (pydantic ya está).

**Archivos** (paquete nuevo):
```
infrastructure/providers/sdk/
    __init__.py
    manifest.py        # modelos Pydantic del manifest (§9.1)
    registry.py        # descubrimiento + catálogo
    adapter_base.py    # ABC con generate()/health()/estimate_cost()
    adapter_openapi.py
    adapter_comfyui.py
    adapter_webhook.py
providers.d/           # en raíz del backend: carpetas instalables
    kling-3-omni/provider.yaml
    kling-3-omni/adapters/kling.py
```

**manifest.py**: traducir el YAML de §9.1 a Pydantic 1:1 (`ProviderManifest`, `CostModel`, `LatencyProfile`, `AuthSpec`, `AdapterSpec`). Validación estricta, `extra="forbid"`.

**registry.py**:

```python
class ProviderRegistry:
    def __init__(self, providers_dir: Path, vault: SecretVault):
        self._catalog: dict[str, LoadedProvider] = {}

    def discover(self) -> None:
        for manifest_path in self._dir.glob("*/provider.yaml"):
            m = ProviderManifest.model_validate(yaml.safe_load(manifest_path.read_text()))
            adapter = self._build_adapter(m, manifest_path.parent)
            self._catalog[m.id] = LoadedProvider(manifest=m, adapter=adapter)

    def find(self, capability: str, **constraints) -> list[LoadedProvider]:
        """Todos los providers que declaran capability y cumplen constraints."""

    def _build_adapter(self, m, base_dir):
        match m.adapter.type:
            case "python":   # importlib dinámico
                spec = importlib.util.spec_from_file_location(m.id, base_dir / m.adapter.entrypoint)
                mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
                return mod.Adapter(manifest=m, vault=self._vault)
            case "openapi":  return OpenAPIAdapter(m, self._vault)
            case "comfyui_workflow": return ComfyUIAdapter(m, base_dir)
            case "http_webhook": return WebhookAdapter(m, self._vault)
```

**Migración de prueba de fuego**: convertir `ltx_desktop.py`, `artlist_provider.py`, `elevenlabs_studio_provider.py` a formato python-adapter (mover a `providers.d/`, escribir sus manifests). Los tests existentes (`test_providers.py`, `test_provider_router.py`) deben pasar sin cambios de aserciones — solo de setup.

**adapter_comfyui.py** (API de ComfyUI, httpx):

```python
class ComfyUIAdapter(AdapterBase):
    # manifest extra: comfyui: { host: "http://127.0.0.1:8188", workflow: "workflow.json",
    #                            inputs_map: { prompt: "6.inputs.text", duration: "12.inputs.length" } }
    async def generate(self, request: GenRequest) -> GenResult:
        wf = json.loads((self.base_dir / self.cfg.workflow).read_text())
        for field, node_path in self.cfg.inputs_map.items():   # "6.inputs.text"
            node_id, *keys = node_path.split(".")
            target = wf[node_id]
            for k in keys[:-1]: target = target[k]
            target[keys[-1]] = getattr(request, field)
        r = await self._client.post(f"{self.cfg.host}/prompt", json={"prompt": wf})
        prompt_id = r.json()["prompt_id"]
        # Poll GET /history/{prompt_id} hasta status completed (backoff 2s, timeout manifest.latency.p95*2)
        # Output: GET /view?filename=...&type=output → bytes → guardar vía file_storage existente
```

**adapter_openapi.py**: manifest declara `openapi: { spec_url, operation_id, field_map, poll: {...} }`. Implementar genérico: httpx + mapping de campos request/response + polling declarativo (muchas APIs de video son submit→poll).

**Gotchas**:
- Hot-reload: endpoint `POST /system/providers/reload` que re-ejecuta `discover()` — sin redeploy (promesa de §9.1).
- API keys SIEMPRE vía `vault_key` del manifest → `secret_vault` existente. Nunca en el YAML.
- Carga dinámica de python ejecuta código de terceros — para providers de comunidad (futuro) avisar en UI; para uso propio es aceptable.

---

## 16.8 Capability Router + resiliencia + cost ledger

**Deps**: `pip install tenacity`.

**Archivos**:
- Crear `domain/services/capability_router.py` (puro, testeable).
- Crear `infrastructure/persistence/models/tables.py` → tablas `cost_ledger`, `provider_health`.
- Extender `artlist_model_selector.py` o absorberlo en el router (decisión: absorber — un solo punto de selección).

**Router** (lógica de scoring, determinista):

```python
def score(p: LoadedProvider, req: CapabilityRequest, health: HealthSnapshot) -> float:
    if req.capability not in p.manifest.capabilities: return -1
    if health.circuit_open: return -1
    if req.max_cost_usd and p.estimate_cost(req) > req.max_cost_usd: return -1
    q = p.manifest.quality_score      # del benchmark §16.9, no del YAML
    speed = 1 / max(p.manifest.latency.p50_s, 1)
    cost = 1 / max(p.estimate_cost(req), 0.001)
    w = req.weights                   # slider UI: calidad/coste/velocidad, suma 1
    return w.quality * q + w.cost * cost * 0.1 + w.speed * speed * 10

def route(req) -> list[LoadedProvider]:
    """Ordenados por score desc = fallback chain implícita."""
```

**Ejecución con fallback** (en la capa de orquestación):

```python
@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=2, max=30),
       retry=retry_if_exception_type(TransientProviderError))
async def call_with_fallback(chain, request):
    for provider in chain:
        try:
            return await provider.adapter.generate(request)
        except ProviderError:
            health.record_failure(provider.id)   # 5 fallos/5min → circuit open 10min
            continue
    raise AllProvidersFailedError(request.capability)
```

Circuit breaker: implementación propia simple (tabla `provider_health`: failures, window_start, open_until) — no meter pybreaker, es estado en memoria y queremos persistencia SQLite local-first.

**Cost ledger**: tabla `cost_ledger(id, project_id, episode_id, provider_id, capability, units, unit_type, cost_usd, created_at)`. Escribir en cada `generate()` completado (el adapter devuelve `units_consumed`). Endpoint `GET /projects/{id}/costs` con agregados.

**Presupuesto hard-cap**: antes de cada llamada, `SUM(cost_usd) + estimate > project.budget_usd` → excepción `BudgetExceededError` → la UI ofrece: subir presupuesto / cambiar a chain gratis (solo providers `cost=0`).

---

## 16.9 Auto-benchmark harness

**Deps**: `pip install open-clip-torch pytesseract` (+ Tesseract sistema, §16.0). open-clip arrastra torch — instalar variante CPU si no hay GPU: `pip install torch --index-url https://download.pytorch.org/whl/cpu`.

**Archivos**:
- Crear `backend/assets/benchmark/prompts.json` — suite: 20 prompts × dimensión (`motion`, `faces`, `text_render`, `physics`, `consistency`), cada uno con `expected_text` (para OCR) o descriptor CLIP.
- Crear `application/use_cases/benchmark_provider.py`.
- Tabla `provider_scorecard(provider_id, dimension, score, benchmarked_at)`.

**Flujo**:
1. Provider nuevo registrado → encolar job benchmark (prioridad mínima, §16.10).
2. Por prompt: generar clip → extraer 5 frames equiespaciados (`ffmpeg -i clip.mp4 -vf "select=not(mod(n\,{step}))" -vsync vfr f_%02d.png`).
3. Métricas objetivas por frame:
   - **CLIP score**: similitud coseno embedding(frame) vs embedding(prompt) con `open_clip` ViT-B-32.
   - **OCR**: si el prompt pide texto en pantalla, `pytesseract.image_to_string` → ratio de match con `expected_text`.
4. **LLM-judge**: enviar los 5 frames + prompt a Gemini multimodal (`gemini_llm.py` extendido para imágenes): "puntúa 0–10: adherencia, artefactos, coherencia". JSON de salida validado.
5. Score por dimensión = media ponderada (CLIP 0.3, OCR 0.2 si aplica, judge 0.5). Persistir scorecard → el router (§16.8) lee `quality_score` de aquí.
6. Re-benchmark: job mensual por provider activo (scheduler §16.13).

**Gotcha**: el benchmark gasta dinero en providers de pago — cap por defecto: solo 5 prompts (1/dimensión) en cloud, suite completa solo en locales. Configurable.

---

## 16.10 DAG Orchestrator (render como grafo)

**Deps**: ninguna nueva. **Decisión cerrada**: NO Celery/Prefect/Temporal — rompen local-first (brokers, servicios). Ejecutor propio sobre asyncio + SQLite, evolución de `inprocess.py` y `resume_handler.py` existentes.

**Archivos**:
- Crear `domain/value_objects.py` → `DagSpec`, `DagNode` (declarativos, serializables).
- Crear `infrastructure/queue/dag_executor.py`.
- Tabla `dag_runs(id, episode_id, spec_json, status)` + `dag_nodes(run_id, node_id, status, result_ref, error, started_at, finished_at)`.

**Modelo**:

```python
class DagNode(BaseModel):
    id: str
    capability: str               # "text_to_video", "tts", "compose"...
    params: dict
    depends_on: list[str] = []
    max_retries: int = 2

class DagSpec(BaseModel):
    nodes: list[DagNode]          # validar: acíclico (toposort en __init__), ids únicos
```

**Ejecutor**:

```python
class DagExecutor:
    async def run(self, run_id: str) -> None:
        spec, states = self._load(run_id)            # estados desde SQLite → RESUME gratis
        pending = {n.id for n in spec.nodes if states[n.id] != "done"}
        while pending:
            ready = [n for n in spec.nodes if n.id in pending
                     and all(states[d] == "done" for d in n.depends_on)]
            if not ready: raise DagDeadlockError(run_id)
            results = await asyncio.gather(*[self._run_node(n) for n in ready],
                                           return_exceptions=True)
            # por nodo: done → persistir result_ref; error → retry o failed (y cancelar dependientes)

    async def _run_node(self, node: DagNode):
        self._mark(node.id, "running")
        chain = self.router.route(CapabilityRequest(node.capability, **node.params))
        return await call_with_fallback(chain, node.params)     # §16.8
```

- **Resumabilidad**: estado por nodo en SQLite → reinicio del proceso = `run()` de nuevo, salta los `done`. `resume_handler.py` existente se retira en favor de esto (migrar su lógica, no duplicar).
- **Prioridades**: tabla cola con `priority int` (preview=0, render=1, benchmark=9, batch=5); el worker loop hace `ORDER BY priority, created_at`.
- **Progreso SSE**: el executor publica eventos a un `asyncio.Queue` por run → endpoint `GET /runs/{id}/events` con `StreamingResponse` (media_type `text/event-stream`). FastAPI ya está.
- Los pipelines actuales (story, meme...) se **traducen a DagSpec** — una función por content_type que construye el grafo. Las "recetas" de §10.1 SON DagSpecs serializados + metadata.

---

## 16.11 Asset Library semántica (FAISS local)

**Deps**: `pip install faiss-cpu sentence-transformers`.

**Archivos**:
- Crear `infrastructure/vector/embedding_index.py`.
- Tabla `assets(id, kind, path, description, embedding_id, created_at, episode_id)`.
- Endpoint `GET /assets/search?q=...`.

**Implementación**:

```python
class EmbeddingIndex:
    def __init__(self, index_path: Path, dim: int = 384):
        self.model = SentenceTransformer("all-MiniLM-L6-v2")   # 384d, CPU, multilingüe ok
        self.index = faiss.read_index(str(index_path)) if index_path.exists() \
                     else faiss.IndexIDMap(faiss.IndexFlatIP(dim))

    def add(self, asset_id: int, text: str):
        v = self.model.encode([text], normalize_embeddings=True)
        self.index.add_with_ids(v, np.array([asset_id]))
        faiss.write_index(self.index, str(self.path))          # persistir cada add (barato)

    def search(self, query: str, k: int = 10) -> list[tuple[int, float]]:
        v = self.model.encode([query], normalize_embeddings=True)
        scores, ids = self.index.search(v, k)
        return [(int(i), float(s)) for i, s in zip(ids[0], scores[0]) if i != -1]
```

**Qué se indexa**: cada asset generado con su `description` textual — para clips, la descripción ES el `visual_prompt` que lo generó (gratis, ya existe). Para video importado: descripción del Video Analyst (§16.12).

**Reuso con umbral**: antes de generar un segmento, `search(visual_prompt, k=3)`; si `score > 0.92` → ofrecer reuso en UI con preview (regresión §15: nunca auto-reusar).

**Gotcha**: faiss-cpu en Windows a veces falla por pip → fallback documentado: `conda install -c pytorch faiss-cpu` o usar `sqlite-vec` como alternativa pure-SQLite (`pip install sqlite-vec`, misma interfaz, más lento, cero fricción de instalación). Implementar `EmbeddingIndex` contra una interfaz para poder cambiar backend.

---

## 16.12 Video Analyst (URL → genoma viral)

**Deps**: `pip install yt-dlp faster-whisper google-genai`.

**Archivos**:
- Crear `infrastructure/media/video_ingest.py` (descarga).
- Crear `application/use_cases/analyze_video.py`.
- Crear `domain/value_objects.py` → `ViralGenome` (Pydantic del JSON de §12.4, literal).
- Endpoint `POST /brain/analyze` body `{url | upload}`.

**Descarga**:

```python
def download(url: str, out_dir: Path) -> Path:
    import yt_dlp
    opts = {"format": "mp4[height<=1080]/best", "outtmpl": str(out_dir / "%(id)s.%(ext)s"),
            "max_filesize": 200 * 1024 * 1024, "quiet": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return Path(ydl.prepare_filename(info))
```

**Ruta cloud (primaria)** — Gemini ingiere video nativo:

```python
from google import genai
client = genai.Client(api_key=vault.get("gemini_api_key"))
f = client.files.upload(file=str(video_path))
while f.state.name == "PROCESSING":
    await asyncio.sleep(2); f = client.files.get(name=f.name)
resp = client.models.generate_content(
    model="gemini-2.5-pro",                      # leer modelo de config, no hardcodear
    contents=[f, GENOME_PROMPT],
    config={"response_mime_type": "application/json",
            "response_schema": ViralGenome.model_json_schema()})
genome = ViralGenome.model_validate_json(resp.text)
```

`GENOME_PROMPT`: instruir extracción de cada campo del genoma (§12.4) con definiciones de cada `hook.type` y `beat` — el LLM no inventa taxonomía, elige de enums cerrados.

**Ruta local (fallback)**:
1. Frames: `ffmpeg -i video.mp4 -vf fps=1 frames/f_%03d.png` (1 fps suficiente para estructura).
2. Audio + transcripción: `faster_whisper.WhisperModel("small", compute_type="int8").transcribe(audio, word_timestamps=True)`.
3. Beats: `analyze_beats` (§16.1) sobre el audio.
4. LLM local (Ollama existente, modelo con visión tipo llava si está; si no, describir frames está fuera — degradar a genoma parcial solo-audio: estructura por transcripción + beats + cambios de plano via `ffprobe`/scene detection: `ffmpeg -vf "select='gt(scene,0.4)',showinfo"`).

**Genoma → receta**: función determinista `genome_to_recipe(genome, pod) -> DagSpec` — mapea beats del genoma a `ShortSegment`s (§16.5) sustituyendo el tema por el del pod. Los campos visuales del genoma se convierten en `visual_prompt` con plantilla: `f"{beat.visual_description}, sobre {pod.topic}, {pod.brand_style}"`.

**Gotchas**:
- yt-dlp y TikTok: rompe periódicamente → pin de versión + `pip install -U yt-dlp` como primer paso de troubleshooting documentado. Si la descarga falla, aceptar upload manual del archivo (el usuario puede grabar pantalla).
- Gemini Files API: límite 2GB, retención 48h — borrar tras análisis (`client.files.delete`).
- Copyright: analizamos para extraer FORMATO, nunca persistimos el video fuente más allá del análisis (config: borrar tras genoma).

---

## 16.13 Cerebro MCP + Scheduler (Trend Radar)

**Deps**: `pip install mcp apscheduler` (pytrends si `google_trends.py` no lo usa ya).

**Archivos**:
- Crear `infrastructure/brain/agent.py` — loop del agente.
- Crear `infrastructure/brain/tools.py` — registro de tools internas.
- Crear `infrastructure/brain/mcp_client.py` — conexión a MCP servers externos.
- Config `brain_mcp.json` — qué servers conectar (mismo formato que `.mcp.json` estándar).
- Crear `application/use_cases/daily_briefing.py`.
- Scheduler: `infrastructure/queue/scheduler.py`.

**Agente = loop de function-calling** (no framework, 60 líneas):

```python
class BrainAgent:
    def __init__(self, llm: LLMPort, tools: dict[str, Tool]):  # Tool: name, json_schema, async fn
        ...
    async def run(self, goal: str, max_steps: int = 12) -> str:
        messages = [system(BRAIN_SYSTEM_PROMPT), user(goal)]
        for _ in range(max_steps):
            resp = await self.llm.complete_with_tools(messages, self.tool_schemas)
            if resp.tool_calls:
                for call in resp.tool_calls:
                    result = await self.tools[call.name].fn(**call.args)
                    messages.append(tool_result(call.id, json.dumps(result)[:8000]))
            else:
                return resp.text
        return "max_steps alcanzado"
```

`complete_with_tools`: añadir al puerto LLM — Gemini lo soporta nativo (function declarations); Ollama via formato de tools de su API chat.

**Tools internas** (registradas en `tools.py`): `analyze_video(url)` (§16.12), `search_trends(query)` (google_trends existente), `tiktok_sounds(region)` (§16.6), `format_library_search(query)` (FAISS §16.11 con namespace de genomas), `create_recipe_from_genome(genome_id)`.

**Tools MCP externas** — cliente:

```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def load_mcp_tools(config_path: Path) -> dict[str, Tool]:
    # por cada server en brain_mcp.json: stdio_client(StdioServerParameters(command=..., args=...))
    # session.initialize() → session.list_tools() → wrapear cada una como Tool
    # cuyo fn = session.call_tool(name, args)
```

Servers recomendados en config inicial: uno de web-search (p.ej. servidor MCP de Brave/Tavily — requiere API key en vault) y filesystem. Reddit/YouTube: empezar con APIs directas como tools internas (praw, google-api-python-client) — convertirlas a MCP solo si se externalizan.

**Scheduler (APScheduler, local-first)**:

```python
scheduler = AsyncIOScheduler(jobstores={"default": SQLAlchemyJobStore(url=settings.db_url)})
scheduler.add_job(daily_briefing_job, "cron", hour=7, id="daily_briefing", replace_existing=True)
scheduler.add_job(rebenchmark_job, "cron", day=1, id="monthly_benchmark", replace_existing=True)
scheduler.start()   # en lifespan de FastAPI (app.py)
```

`daily_briefing_job`: agente con goal fijo ("revisa fuentes del nicho de cada pod activo, detecta formatos/sonidos emergentes, analiza top-3 candidatos con analyze_video, devuelve briefing JSON") → persistir → notificar a UI.

**Biblioteca de formatos**: genomas en namespace propio del índice FAISS (embedding del campo `why_it_works` + estructura serializada). Clustering: al añadir genoma, `search(k=5)`; si vecino con `score>0.88` → mismo `format_id`, incrementar contador de avistamientos (curva de adopción = avistamientos/día; "quemado" = sin avistamientos 14 días → flag veto).

---

## 16.14 Multiplicación, publicación y métricas

**Deps**: `pip install google-api-python-client google-auth-oauthlib pillow`.

**Matriz** (cada celda = builder de DagSpec, `application/use_cases/multiply.py`):
- **Shorts**: N llamadas a `GenerateNativeShortUseCase` con distintos highlights del LLM brain existente.
- **Carousel**: LLM → 7–10 slides (título + cuerpo) → render: plantilla HTML + Playwright `page.screenshot()` (1080×1350) — ya tenemos Playwright por §16.6. Alternativa pura-Pillow si se quiere evitar browser.
- **Thumbnails A/B**: capability `text_to_image` (gemini_image existente) × 3 prompts de variante.
- **Thread/newsletter**: script_gen sobre el guion master (reusar `seo.py`).
- **Doblaje**: `manual_dubbing.py` existente como base + tts multivoz.

**Publicación YouTube** (la única con API estable de upload):

```python
# OAuth2 flow una vez → refresh token al vault.
youtube = build("youtube", "v3", credentials=creds)
youtube.videos().insert(part="snippet,status",
    body={"snippet": {"title": t, "description": d, "tags": tags},
          "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False}},
    media_body=MediaFileUpload(path, resumable=True)).execute()
```

TikTok Content Posting API: requiere app aprobada — fase 2; mientras: export + recordatorio. Instagram Graph API: requiere cuenta business + app review — ídem.

**Métricas**: YouTube Analytics API (`youtubeAnalytics.reports().query` con `metrics=views,averageViewPercentage,audienceWatchRatio`) → job nocturno → tabla `video_metrics(video_id, episode_id, date, views, retention_curve_json)` → reward del LinUCB (§16.2): retención a 3s extraída de `audienceWatchRatio`. Fallback universal: import manual CSV desde la UI.

---

## 16.15 Frontend (apuntes mínimos, backend-first)

- **SSE de progreso**: `EventSource` contra `/runs/{id}/events` (§16.10) → barra por nodo del DAG.
- **Timeline**: los datos ya existen (escenas + duraciones + captions + beats). Render: bloques HTML/CSS sobre un track; preview de video con `<video>` + `currentTime` sincronizado. WebCodecs/WebGPU = optimización futura, NO MVP.
- **Director's Chat**: endpoint `POST /episodes/{id}/chat` → LLM con el estado de la receta (DagSpec JSON) en contexto → responde **JSON Patch (RFC 6902)** sobre la receta (`pip install jsonpatch` para aplicar + validar re-parseando el DagSpec). UI muestra diff (campos cambiados) → botón aplicar → re-render solo de nodos afectados (el DAG sabe qué nodos dependen de qué params → invalidación selectiva).
- **Galería de templates**: carpeta `backend/assets/templates/*.json` (DagSpecs parametrizados + metadata + ruta de preview mp4) servida por endpoint; previews renderizados una vez con LTX local.

## 16.16 Orden de construcción exacto (dependencias entre piezas)

```
1. 16.1 beat_grid          (aislado, 1 día)
2. 16.3 sfx_library        (aislado, 1 día)
3. 16.4 ass_captions       (aislado, 2 días)
4. 16.2 hook_rewrite       (necesita prompts; LinUCB wiring al final, 2 días)
5. 16.7 Provider SDK       (migrar 3 providers existentes = test de fuego, 1 semana)
6. 16.8 router + ledger    (necesita 16.7, 3 días)
7. 16.10 DAG executor      (necesita 16.8; migrar pipelines a DagSpec, 1 semana)
8. 16.5 native short       (necesita 16.1-16.4 + 16.10, 1 semana)
9. 16.11 FAISS index       (aislado, 2 días)
10. 16.12 Video Analyst    (necesita 16.11 para biblioteca, 1 semana)
11. 16.13 cerebro + sched  (necesita 16.12, 1 semana)
12. 16.9 benchmark         (necesita 16.7/16.10, 4 días)
13. 16.6 trending audio    (aislado, frágil, 3 días)
14. 16.14 multiply/publish (necesita 16.10, incremental)
15. 16.15 frontend         (incremental sobre todo lo anterior)
```

Regla de PRs: una pieza = un PR con sus tests unitarios (LLM y providers siempre fakeados — patrón de `test_provider_router.py` existente). Nada se mergea sin test del happy path + 1 caso de fallo.

---

## 17. Cinco faltas clave — solución, esfuerzo, riesgo

> Profundización sobre gaps identificados en §2 y §10.2. Tres ya tienen spec (§16.1, §16.5, §10.2); aquí se completan las cinco con el mismo nivel ejecutor.

| Falta | Esfuerzo | Deps nuevas | LLM/modelo | Riesgo principal |
|---|---|---|---|---|
| Filler removal | Bajo (2–3 días) | faster-whisper (ya en §16.12), pydub | Local opcional (Ollama) | Desync audio/video |
| B-roll automático | Medio (~1 semana) | Pexels API (gratis), open-clip (ya en §16.9) | Gemini existente + CLIP | B-roll irrelevante (el fallo de Opus) |
| Presets de cámara | Bajo-medio (3–4 días) | Ninguna | Ninguno obligatorio | Provider ignora lenguaje de cámara |
| Edu short nativo | ~2 días si §16.5 existe | Cadena §16.1–16.5 | Gemini con response_schema | Regresión en edu long-form |
| Beat-sync producción | Bajo (1–2 días) | librosa, soundfile | Ninguno | Captions desincronizadas |

### 17.1 Filler word removal

**Contexto**: nuestro audio principal es TTS — no genera muletillas. Aplica solo a audio importado (Video Analyst, uploads de usuario, repurposing de podcast futuro).

**Cómo**:
1. faster-whisper con `word_timestamps=True` sobre el audio.
2. Match contra léxico de fillers (`backend/assets/filler_lexicon.json`): español ("eh", "em", "o sea", "vale", "bueno", "este", "pues nada"), inglés ("um", "uh", "like", "you know").
3. Lista de cortes → recorte ffmpeg (concat de segmentos) con **crossfade 30–50ms por junta** (sin él: clicks audibles).
4. Pase LLM opcional de desambiguación (Ollama local): "¿este 'vale' es muletilla o tiene significado?". Modo solo-léxico funciona ~90%.

**Archivos**: crear `infrastructure/media/filler_removal.py`; integrar como nodo opcional del DAG (`capability: audio_enhance`).

**Rompe**: talking-head → cortar audio sin video = desync; hay que cortar ambos con los mismos segmentos. Voiceover puro: seguro. Falsos positivos en palabras con significado → pase LLM opcional como mitigación.

### 17.2 B-roll automático

**Cómo** (cascada de resolución):
1. El LLM de script añade campo `broll_query: str | null` por escena (modificar prompt de script-gen).
2. Resolución en orden: (a) biblioteca FAISS propia (§16.11) — gratis y on-brand; (b) Pexels/Pixabay API (gratis, key en vault); (c) generar con LTX local si nada encaja.
3. **Anti-fallo-de-Opus**: puntuar candidatos con CLIP (deps ya en §16.9) contra el query — score < umbral (0.25 CLIP) → NO insertar. Mejor sin B-roll que B-roll irrelevante (el failure mode documentado de Opus, §1.1).
4. Inserción: cutaway con overlay ffmpeg, audio de diálogo continuo.

**Archivos**: crear `infrastructure/media/broll_resolver.py`; nodo DAG `capability: broll`.

**Reglas duras**: nunca en los primeros 3s (zona de hook); máximo 1 cutaway por 10s; B-roll se renderiza ANTES de la capa de captions (orden de capas, si no tapa los subtítulos).

**Rompe**: captions tapadas (orden de capas), pacing destruido (regla de densidad), stock genérico que huele a stock (preferir cascada a→c antes que b cuando el pod tenga biblioteca poblada).

### 17.3 Presets de cámara

Dos capas independientes:

**Capa generación** (el "efecto Higgsfield", §10.2):
- Catálogo `backend/assets/camera_presets/presets.json`: cada preset = `{id, label, dialects: {veo: "rapid crash zoom in, motion blur", kling: "...", ltx: "..."}, params: {intensity}}`.
- El adapter del provider hace lookup del dialecto y concatena al `visual_prompt`. Cero código más allá del lookup.
- Presets iniciales (~15): crash_zoom, dolly_in_slow, dolly_out, orbit, fpv_drone, handheld_shake, bullet_time, crane_up, whip_pan, static_locked, push_in_face, dutch_angle, top_down, low_angle_hero, snap_zoom_punch.

**Capa post** (sobre footage ya generado):
- Extender el Ken Burns existente: `zoompan` de ffmpeg con curvas ease-in/out; shake simulado vía crop animado con ruido.

**LLM**: ninguno obligatorio; opcional, el LLM de script sugiere `camera_preset` por `mood` de escena.

**Rompe**: providers ignoran lenguaje de cámara con frecuencia → añadir dimensión `camera_adherence` a la suite del benchmark (§16.9) para saber qué provider obedece qué preset. Zoom en post degrada resolución → límite 1.15× o generar a resolución mayor.

### 17.4 Educational short-form nativo

Ya especificado en §3.4 + §16.5 — es **variante de estructura** del pipeline nativo, no pipeline aparte. Con `GenerateNativeShortUseCase` construido, edu short = otro builder de `ShortStructure`:

- Roles: hook (1–2s, pregunta/myth-busting) + body + **rehook intermedio** + body + conclusion (3s).
- Composición: fades suaves (NO jump-cuts agresivos — edu pide claridad), keyword caption por sección, cama lo-fi.
- **Esfuerzo real**: ~2 días si §16.5 existe; la semana entera del pipeline si no.
- **LLM**: Gemini con `response_schema` del Pydantic (JSON garantizado) + 1 retry; fallback Ollama.
- **Rompe**: edu long-form legacy — mitigado por diseño: `content_type=edu_short` nuevo y aislado (§6). Gotcha del beat-sync: la música edu (lo-fi) suele dar grid no fiable → el auto-disable de §16.1 cubre.

### 17.5 Beat-sync en producción

Spec completa en §16.1. Los tres riesgos production-grade y sus mitigaciones (ya escritas allí, listadas aquí como checklist de aceptación):

1. Captions desincronizadas → orden obligatorio: snap de cortes → DESPUÉS generar captions. Test de integración que lo verifique.
2. `librosa.load` falla con AAC → extraer siempre a WAV temp con ffmpeg antes de analizar.
3. Música sin percusión (lo-fi/ambient) → grid no fiable → auto-desactivar snap si `len(beats) < duración_s / 2`.

**Orden de implementación de las cinco**: 17.5 → 17.1 → 17.3 → 17.2 → 17.4 (beat-sync desbloquea memes ya; filler y presets son aislados y baratos; B-roll necesita FAISS poblado; edu necesita el pipeline nativo terminado).

---

## Fuentes

### Competencia
- [OpusClip Virality Score (docs oficiales)](https://help.opus.pro/docs/article/virality-score)
- [OpusClip Review 2025: AI Auto-Clipping, Virality Score & Scheduler](https://skywork.ai/blog/opusclip-review-2025-ai-auto-clipping-virality-score-scheduler/)
- [OpusClip explained: features, pricing, limitations (eesel)](https://www.eesel.ai/blog/opusclip)
- [An honest look at OpusClip reviews 2025 (eesel)](https://www.eesel.ai/blog/opusclip-reviews)
- [OpusClip pricing 2026 (eesel)](https://www.eesel.ai/blog/opusclip-pricing)
- [Opus Clip plans and credits (docs oficiales)](https://help.opus.pro/docs/article/plans-and-credits)
- [quso.ai (ex vidyo.ai)](https://quso.ai/)
- [Vidyo AI explicado (Pexo)](https://pexo.ai/blog/vidyo-ai-review-8305)
- [Vidyo AI Tutorial 2026 (MSY Editor)](https://msyeditor.com/vidyo-ai-tutorial-2026-how-to-repurpose-long-videos-into-short-clips/)
- [Higgsfield AI Video](https://higgsfield.ai/ai-video)
- [Higgsfield × NVIDIA case study](https://www.nvidia.com/en-us/case-studies/higgsfield/)
- [Higgsfield AI Review 2026](https://appreviewlab.com/higgsfield-ai-review-2026/)
- [HeyGen vs Synthesia 2026 (WaveSpeed)](https://wavespeed.ai/blog/posts/heygen-vs-synthesia-comparison-2026/)
- [D-ID alternatives & pricing (ngram)](https://www.ngram.com/blog/top-9-ai-video-creator-alternatives-to-d-id-in-2026-reviewed-and-compared)
- [Synthesia vs HeyGen hands-on (G2)](https://learn.g2.com/synthesia-vs-heygen)

### Modelos de video
- [Best AI Video Generator 2026 (Pixflow)](https://pixflow.net/blog/best-ai-video-generator/)
- [AI Video Models Guide 2026 (ulazai)](https://ulazai.com/ai-video-models-guide-2025/)
- [Best AI Video Generators Ranked 2026 (AI Video Bootcamp)](https://aivideobootcamp.com/blog/ai-video-generators-ranked-2026/)
- [17 AI Video Models: pricing & benchmarks](https://aifreeforever.com/blog/best-ai-video-generation-models-pricing-benchmarks-api-access)
- [Veo vs Runway vs Kling (tooldirectory)](https://tooldirectory.ai/blog/best-ai-video-generator-2026-veo-runway-kling-pika-luma)
- [Run AI Video Locally: LTX-2, RTX, ComfyUI 2026 (bonega)](https://bonega.ai/en/blog/run-ai-video-locally-rtx-ltx-2-comfyui-2026)
- [ComfyUI-LTXVideo (GitHub oficial)](https://github.com/Lightricks/ComfyUI-LTXVideo)
- [LTX 2.3: Open Source 4K guide (Apatero)](https://apatero.com/blog/ltx-2-3-open-source-4k-video-generation-guide-2026)
- [LTX-2 en ComfyUI core (blog oficial Comfy)](https://blog.comfy.org/p/ltx-2-open-source-audio-video-ai)
- [NVIDIA RTX AI Garage: LTX + ComfyUI](https://blogs.nvidia.com/blog/rtx-ai-garage-flux-ltx-video-comfyui-gdc/)

### Viralidad y formato
- [TikTok First 3 Seconds Retention Statistics (TTS Vibes)](https://insights.ttsvibes.com/tiktok-first-3-seconds-hook-retention-rate/)
- [YouTube Shorts Hook Formulas (OpusClip blog)](https://www.opus.pro/blog/youtube-shorts-hook-formulas)
- [TikTok Hook Formulas (OpusClip blog)](https://www.opus.pro/blog/tiktok-hook-formulas)
- [5 TikTok Hook Types That Go Viral 2026 (OpusClip blog)](https://www.opus.pro/blog/tiktok-hooks-that-go-viral-2026)
- [Ideal Shorts Length & Format (OpusClip blog)](https://www.opus.pro/blog/ideal-youtube-shorts-length-format-retention)
- [Psychology of Viral Video Openers (Brandefy)](https://brandefy.com/psychology-of-viral-video-openers/)
- [How to Hit 70%+ Retention (virvid)](https://virvid.ai/blog/ai-shorts-increase-retention-watch-time)
- [The 3-Second Rule (Scenith)](https://scenith.in/blogs/three-second-rule)
- [Caption styles guide (CapCut)](https://www.capcut.com/resource/types-of-captions)
- [Viral captions in CapCut 2025](https://vediting.home.blog/2025/10/29/how-to-make-viral-captions-in-capcut-step-by-step-guide-2025-fonts-color-motion/)
- [Beat sync en CapCut (agilityportal)](https://agilityportal.io/blog/create-viral-shorts-with-this-ultimate-guide-to-syncing-music-trends-in-capcut-pc)

### Audio y prompting
- [Trending TikTok Audio (Dash Social)](https://www.dashsocial.com/blog/tiktok-sounds)
- [Trending songs TikTok + cómo usarlas (Buffer)](https://buffer.com/resources/trending-songs-tiktok/)
- [Trending audio semanal (HeyOrca)](https://www.heyorca.com/blog/trending-audio-for-reels-tiktok)
- [Royalty-free music for TikTok (Epidemic Sound)](https://www.epidemicsound.com/tiktok/music-for-tiktok/)
- [50+ Viral Hook Templates + AI Prompts (MarketingBlocks)](https://www.marketingblocks.ai/50-viral-hook-templates-for-ads-reels-tiktok-or-captions-2026-frameworks-examples-ai-prompts-included/)
- [Viral Hook Generator Prompt (AI SuperHub)](https://www.aisuperhub.io/prompt/viral-hook-generator)
- [ChatGPT Prompts for Video Scripts (Fliki)](https://fliki.ai/blog/chatgpt-prompts-for-video-scripts)
- [Viral TikTok Script prompt (docsbot)](https://docsbot.ai/prompts/entertainment/viral-tiktok-script-1)
- [14 TikTok Hooks +84.3% engagement (sendshort)](https://sendshort.ai/guides/tiktok-hooks/)
