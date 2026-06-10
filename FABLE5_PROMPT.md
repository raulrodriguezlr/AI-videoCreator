# PROMPT PARA FABLE5 — AI-videoCreator: Research + Target Analysis

## Misión

**Busca en Google** qué existe en 2025 para generar contenido viral. Luego analiza **nuestro proyecto** contra eso. No estrategia de monetización — sino **qué hay que hacer para ser competitivo**.

---

## PARTE 1: Research (Búsqueda en Internet)

### 1.1 Competencia directa

Busca y analiza **cómo funcionan** estos (sin usar su API, leyendo docs públicas + videos de demostración):

- **Opus Clip** (frame.io)
- **Vidyo.ai**
- **HiggsField** (avatar + video synthesis)
- **Synthesia** (avatar video)
- **D-ID** (video DIY)
- **Runway** (AI tools for video)
- **Pika Labs** (video generation)

Por cada una: **¿Qué generan? ¿Con qué modelos? ¿Qué prompts usan? ¿Cómo fluye el UX?**

### 1.2 Tendencias actuales (TikTok, YouTube Shorts, Instagram Reels)

- **Qué contenido "viraliza" en 2025** (por tipo: humor, educativo, narrativo, trends, challenge-format).
- **Qué duración funciona mejor** (los 3s vs 6s vs 15s vs 20s).
- **Estructura ganadora** (hook 0.5s, punchline/payoff 1s, beat pattern).
- **Audio/música**: tendencias (trending sounds, royalty-free, ducking, beat-sync).
- **Captions**: cómo se usan (color, timing, font, word highlights).
- **Pacing/cuts**: velocidad crítica (jump-cuts vs smooth, transiciones, zoom).
- **AI tools que creadores usan**: CapCut, DaVinci Resolve, Adobe Firefly, Synthesia, HeyGen para quick edits.

### 1.3 Modelos de video en 2025

- Estado actual: **Veo 3.1, Kling 3.0, Luma Dream Machine, Runway Gen 3, Pika 2.0**. ¿Cuál es mejor para qué?
- **Para short-form (TikTok/Reels)**: ¿Cuál es el sweet spot (speed vs quality)?
- **Para long-form (YouTube 10–20 min)**: ¿Cuál mantiene consistencia?
- **Avatar/talking-head**: ¿Qué modelos (HeyGen, Synthesia, D-ID, ElevenLabs Studio)?
- **Local models (Comfy, LTX, SD)**: ¿Viables para produción en batch?

### 1.4 LLM prompting para generación de contenido

- ¿Cómo escriben **prompts para hooks** (3–5 palabras clave que enganchen)?
- ¿Cómo escriben **prompts para guiones cortos** (TikTok 20s = ~50 palabras)?
- ¿Cómo escriben **prompts para scripts educativos** (claridad + ejemplo)?
- ¿Qué LLM usan creadores AI** (Gemini, GPT-4, Claude)?
- **Few-shot examples** que funcionan vs no funcionan.

---

## PARTE 2: Estado Actual del Proyecto

Nuestro stack:
- **Generación**: Veo 3.1 (cloud), LTX (local), ElevenLabs (voz + video studio — pendiente).
- **Shorts engine**: selección de highlights (LLM) + trim/crop/reframe + captions (drawtext) + Ken Burns (zoom) + transiciones (xfade).
- **Content types**: story, meme, scene_recreation, educational.
- **Wizard**: idea → blueprint → pod (config centralizado).

**Limitaciones actuales**:
- Shorts: hoy adapta vídeo largo → corto (crop 16:9→9:16). No genera **nativo TikTok/Reels** con pacing específico.
- Imágenes estáticas: si mete overlay de meme/imagen, es burdo (no vídeo, es overlay puro).
- Educational: puede ser largo o corto, pero **no tiene pipeline nativo para cortos virales** (estructura diferente).
- Provider selection: **genérico** (Veo para todo). Sin hints por tipo.
- Meme: no optimizado para ultra-cortos (<6s, super-paced, beat-sync).

---

## PARTE 3: Análisis por Content Type

Para **cada tipo**, basándote en tendencias reales de 2025:

### Story (Narrative Episodes)

**Qué hace viral en YouTube / Shorts**:
- Hook 0.5s (pregunta o giro inesperado).
- Cliffhanger cada 15–20s.
- Music bajo diálogo (no compite).
- Captions para key moments (no toda la escena).

**En nuestro proyecto AHORA**:
- Script generado con escenas etiquetadas (`audio_text`, `duration_s`, `mood`).
- Shorts engine elige highlights.
- BUT: pacing/beat-sync/hook-optimization **no existe**.

**Qué falta**:
- **Hook Optimizer**: LLM regenera primeros 3s de cada episodio como ultra-gancho.
- **Beat Analyzer**: librosa detects BPM → snaps cuts a beat.
- **Pacing suggestions**: si `avg_scene_duration < 2s` → rápido (meme-like); si `> 4s` → diálogo-pesado (corta).
- **Provider hint** (sugerencia, no obligatorio): story corto (<60s) → **LTX o Kling (rápido)**; story largo (>5 min) → **Veo (calidad)**.

### Meme (Viral Humor, <20s)

**Qué hace viral**:
- Setup: 0.5–1s (mute, no music).
- Punchline: 0.5–1s (SFX: impact, whoosh; captions word-wrapped color-coded).
- Trending audio hook (Dua Lipa, etc.).
- Beat-locked cuts (2–3 por segundo en climax).

**En nuestro proyecto AHORA**:
- Content type `meme` existe, config por pod.
- BUT: no hay **meme-specific LLM prompting** (setup/punchline structure).
- No hay **SFX library** (whoosh, impact, rimshot).
- No hay **beat-sync cutting**.

**Qué falta**:
- **MemeStructurePrompt**: LLM → setup 15 palabras + punchline 10 palabras (no guión largo).
- **SFX Selector**: por punchline vibe (humor → rimshot; shock → impact; failure → sad trombone).
- **BeatLocking**: librosa.beat_track → snaps last 0.5s a downbeat.
- **Trending Audio Injection**: si disponible, usa trending TikTok sound en punchline.
- **Provider hint**: meme → **LTX o Kling (rápido + barato)**, nunca Veo (overkill).

### Scene Recreation (V2V — Adapt Existing Video)

**Qué hace viral**:
- Giro sobre una escena famosa (humor, educational twist, cultural commentary).
- Fair-use respecto fuente original.
- Audio propio (no reuse de original).

**En nuestro proyecto AHORA**:
- Content type existe.
- V2V motor: **no existe aún** (deferred).

**Qué falta**:
- **V2V Provider**: video → extract scene → modify with AI (color grade, re-enact with different actor, change setting).
- **Fair-use advisor**: LLM warns si recreación es demasiado cercana a original.
- **Trend-matching**: detecta qué escena famous es trend ahora, suggests recreations.
- **Provider hint**: scene recreation → **depende del tipo (Runway, Kling para modificación)**, no local.

### Educational (Explainer, 3–30 min OR Reels-Native Shorts)

**Qué hace viral en YouTube**:
- Hook provocativo (question / surprising fact).
- Visual analogy (animate concept).
- Repetición de clave en 3 ángulos.
- Summary 20s al final.

**Qué hace viral en TikTok/Reels** (NUEVO — nativo corto):
- Hook 1s (question: "¿Qué es X?").
- Example (10–15s).
- Conclusion (3s).
- Caption + animation on-screen.
- Trending educational sound (lo-fi study, podcast clip).

**En nuestro proyecto AHORA**:
- Educational content type existe.
- Script generado con scenes.
- BUT: **no hay pipeline nativo para shorts educativos**. Hoy es "adapta video largo" (que no funciona bien).

**Qué falta**:
- **Short-form Educational Pipeline**:
  1. LLM genera estructura TikTok: hook (1s) + explainer (10s) + example (5s) + conclusion (3s).
  2. Video generator hace **4 clips separados** (no uno largo que cortan).
  3. Compositor une con **fade smooth** (no jump-cut agresivo).
  4. Caption: **palabra clave destacada** en cada sección.
  5. Audio: **narración clara + fondo educativo** (lo-fi, ambient).
- **Long-form Educational**: 
  1. LLM genera sections + beat pattern.
  2. Visual analogy generator: concepto abstracto → metaphor visual (algo concreto).
  3. Animation suggestion (GraphQL query concept → graph visualization).
- **Provider hint**: educational corto → **Kling o LTX (clarity)**; educational largo → **Veo**.

---

## PARTE 4: Nuevos Motores / Capacidades Críticas

### A. Native TikTok/Reels Generator (No Adaptar Video Largo)

Hoy: largo → crop → no funciona.

**Propuesta**: `GenerateNativeTikTokUseCase`
1. **Concept → TikTok structure** (LLM elige duración + beat pattern).
2. **Segment LLM prompt**: por cada segmento, genera prompt específico (hook = "visualmente impactante 1s", payoff = "sorpresa 0.5s").
3. **Generate parallel**: Veo/LTX genera cada segmento (no uno largo).
4. **Compose TikTok**: beat-snap, SFX, trending audio, captions word-highlighted.
5. **Output**: 15–60s nativo, no "short de episodio largo".

**Por qué**: competencia (Opus Clip, Vidyo, HiggsField) no adaptan — generan nativo.

### B. Beat-Locked Editing

Librosa beat detection → snap cuts a beat.

- **Memes**: última 0.5s locked a downbeat (punchline timing crítico).
- **Educational**: secciones empiezan en beat (rhythm + clarity).
- **Story shorts**: transiciones en beat (visual flow).

### C. SFX Library + Auto-Selection

No hay whoosh/impact/rimshot. Compositor es silencioso.

Proposición: **SFX por vibe + LLM selection**.
- LLM: "este punchline es sorpresa" → impact + bass drop.
- LLM: "este es fracaso" → sad trombone.
- Mixer: SFX -6dB under dialogue, boost 100–200 Hz en climax.

### D. Hook Rewriter (Primeros 3s Optimizados)

Primeros 3s = todo. Hoy no se reoptimiza.

`HookRewriteUseCase`:
- Toma escena 1 del script.
- LLM: "reescribe como pregunta / giro inesperado / visual shock" (según content type).
- Regenera solo esa escena.
- A/B test: original vs hook-optimized → bandit elige.

### E. Educational Animation Suggestion

Concepto abstracto → visual metaphor.

`ConceptVisualizerUseCase`:
- Script: "la economía es flujo de dinero".
- LLM: "visualiza como río con monedas fluyendo, nubosidad cuando hay inflación".
- VFX generator (Runway, After Effects API): genera animación.
- Compositor inyecta en el guión.

---

## PARTE 5: Provider Hints (NO Automático)

**Default**: pod elige 1 provider (Veo, LTX, ElevenLabs, etc.). Configurado una vez.

**Override per-episode/video/meme**: sugerencias.

### Hints (recomendaciones, no mandatorias)

| Content Type | Prioridad 1 | Prioridad 2 | Prioridad 3 | Rationale |
|---|---|---|---|---|
| Story corto (<60s) | Kling 3.0 | LTX | Veo | Rápido, consistencia caras |
| Story largo (>5 min) | Veo | Kling 3.0 | LTX | Calidad premium, diálogos claros |
| Meme (<20s) | LTX | Kling 3.0 | Veo | Ultra-rápido, barato, suficiente calidad |
| Scene Rec | Runway | Kling (modify) | – | Video transformation natives |
| Edu corto nativo | Kling 3.0 | LTX | Veo | Clarity, fast turnaround |
| Edu largo | Veo | Kling 3.0 | – | Quality, long-form consistency |

**UI**: "Suggestion: for this meme, Kling 3.0 (60s faster, $0.20 cheaper). Use instead of Veo?" [YES/NO].

---

## PARTE 6: Regresiones a Evitar

| Nueva Feature | Posible Regresión | Mitigación |
|---|---|---|
| Native TikTok gen | Scripts legacy para episodios largo ya no aplican | `content_type: TikTok` = nuevo, legacy untouched |
| Beat-locking | Timing de subs puede desincronizar si no cacheado | Test subtitle sync antes de render |
| SFX injection | Volumen enmascarar diálogo | Always mix test, loudness LUFS target |
| Hook rewriter | Escena 1 regenerada ≠ original → continuidad | `hook_only=True` flag, resto de ep untouched |
| Educational animation | VFX generator no disponible → fallback? | Fallback = no animation, texto visual |

---

## PARTE 7: Roadmap de Capas (Orden + Esfuerzo)

### MVP Defensiva (Weeks 1–2)
- [ ] Beat-locking (librosa) — bajo esfuerzo, alto impacto (visible immediato en memes).
- [ ] Hook Rewriter (LLM 1–2 tries) — bajo esfuerzo, validación crítica.

### High-Impact (Weeks 3–6)
- [ ] **Native TikTok pipeline** (nuevo endpoint + LLM structure) — **CRITICAL**. Alto esfuerzo (structure LLM, parallel gen, beat-snap composer).
- [ ] SFX library + auto-selection — medio esfuerzo.
- [ ] Provider hints UI — bajo esfuerzo.

### Medium-term (Weeks 7–12)
- [ ] Educational animation suggestion — medio esfuerzo (depende de VFX provider).
- [ ] Trending audio injection — bajo esfuerzo (Spotify/YouTube API query + injection).
- [ ] Educational short-form native pipeline — alto esfuerzo (similar a TikTok, distintas rules).

### Future (Weeks 13+)
- [ ] V2V recreation pipeline (Runway integration).
- [ ] A/B testing hook-original vs hook-optimized (bandit).

---

## PARTE 8: Datos a Buscar

Cuando analices competencia, extrae:

1. **Prompts de ejemplo** (si public): cómo piden al LLM generar scripts.
2. **Timing**: ¿cuánto tarda Opus Clip de video largo → short? ¿Kling vs Veo en meme?
3. **Cost model**: ¿cómo monetizan? ¿subscription o pay-per-video?
4. **Quality benchmarks**: subs de Opus vs nuestros; pacing de HiggsField vs Kling; audio de Synthesia.
5. **Failure modes**: ¿cuándo fall short? (ej: Opus Clip falla en sarcasmo).

---

## Entregable

**Documento: `COMPETITIVE_ANALYSIS.md`** (~5000 palabras)

Incluye:

1. **Qué existe hoy** (herramientas, modelos, prompts concretos).
2. **Qué nuestro proyecto hace BIEN vs MAL** comparado.
3. **Gaps principales** (qué falta para ser competitivo).
4. **Por cada gap**: cómo solucionarlo (qué motor nuevo, qué cambio de prompt, qué provider).
5. **Capas de implementación** (MVP → defensiva → high-impact → future).
6. **Warnings** (qué puede romperse, cómo evitarlo).

**No strategy, sino: "esto es lo que hay, esto es lo que nosotros no hacemos, así es como hacerlo".**

---

**Busca en Google. Mira videos. Lee docs públicas. No inventes.**
