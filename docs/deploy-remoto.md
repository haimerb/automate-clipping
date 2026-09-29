# Runbook: deploy remoto y credenciales de plataformas

Manual paso a paso para dejar **edgetape** desplegado y publicando de verdad. Cubre
lo que no se puede resolver con código: registrar las apps OAuth, tener un dominio
público y rotar las claves que quedaron expuestas.

> El documento asume que ya elegiste dónde alojar (HF Spaces, VPS, etc.) y que
> levantaste la API. Para el proveedor gratuito ver [`deploy-free.md`](deploy-free.md).
> Si el destino es HF Spaces, la URL pública tiene la forma
> `https://TU-USUARIO-TU-SPACE.hf.space` y **no** puedes cambiarla después sin
> rehacer las apps OAuth.

## Orden de las cosas

El orden importa: **primero el dominio**, porque cada `redirect_uri` que
registres en TikTok, Meta y Google depende de él.

1. [Dominio y URL pública](#1-dominio-y-url-pública) ← **arranca aquí**
2. [Rotar las claves expuestas](#2-rotar-las-claves-expuestas)
3. [TikTok](#3-tiktok-self_only-sin-app-auditada)
4. [Meta (Facebook + Instagram)](#4-meta-facebook-instagram)
5. [YouTube (Google Cloud)](#5-youtube-google-cloud)
6. [Verificación final](#6-verificación-final)
7. [Si algo falla](#7-cuando-algo-falla)

## 1. Dominio y URL pública

### Por qué hace falta

Instagram es la única plataforma que **no** puede recibir el archivo del video:
sus servidores tienen que **descargarlo desde una URL pública**. No aceptan un
`Authorization: Bearer` porque el token es del usuario y ellos no lo tienen.

Por eso edgetape sirve los clips en una URL firmada:

```
https://TU-DOMINIO/api/public/clips/{job_id}/{clip_id}/{firma_hmac}.mp4
```

La firma es un HMAC-SHA256 de `EDGETAPE_JWT_SECRET` recortado a 40 hex
(`auth.media_token`). Sin conocer el secreto es imposible adivinarla, así que
**no se abrió un endpoint anónimo**. Esa ruta no lleva `Authorization`, pero sí
el token firmado: si alguien altera o adivina la firma, la respuesta es `404`.

> Consecuencia práctica: **`EDGETAPE_PUBLIC_BASE_URL` es obligatorio para
> automatizar Reels**. Sin él el backend lo detecta y el post queda
> `status="listo"`, `method="manual"`, con el motivo en `post.error` — no falla en
> silencio.

### Configuración

```bash
# en .env del deploy
EDGETAPE_PUBLIC_BASE_URL=https://tu-dominio.com
```

Sin barra final (el backend hace `.rstrip("/")`, pero mejor no depender de eso).

### Cómo comprobarlo

El endpoint `/api/health` debe responder. Y un clip ya exportado debe servir el
mp4. Lo más simple es pedir un job y mirar el log del worker; si aparece
`public_clip_url` sin `base`, verás el aviso.

**Prueba manual de una URL firmada** (desde fuera, sin token):

```bash
# debe devolver 404 (la firma no existe)
curl -I https://tu-dominio.com/api/public/clips/NOEXISTE/NOEXISTE/malo.mp4

# el archivo real, con la firma que devuelve publish.public_clip_url, debe bajar el mp4
curl -o clip.mp4 "https://tu-dominio.com/api/public/clips/<job>/<clip>/<firma>.mp4"
```

Si el segundo devuelve `404 clip not exported`, el clip no está exportado todavía
(Instagram solo se automatiza sobre clips con export).

Verificado en la versión actual: la ruta devuelve `200` con `content-type: video/mp4`
y el archivo completo (probado con un clip vertical de 1080x1920 / 60 s, 17 MB).
Con la firma manipulada responde `404`, no `403` — no revela si el clip existe.

## 2. Rotar las claves expuestas

Las claves de **Pexels** y **Pixabay** que estaban en `.env` deben considerarse
comprometidas si el repo llegó a ser público, aunque `.env` esté en `.gitignore`
(el historial de git no se borra con un `.gitignore` de hoy para mañana).

### Rotar Pexels

1. <https://www.pexels.com/api/> → tu cuenta → **Regenerate API key** (la vieja
   deja de servir al instante).
2. Copia la nueva a `.env` (local) y a las variables del deploy.
3. Reinicia API y worker.

### Rotar Pixabay

1. <https://pixabay.com/api/docs/> → **API Keys** → regenerar.
2. Igual que arriba.

### Verificar que no quedaron filtradas

```bash
# ¿hay asignaciones con valor real (no placeholders) en el historial?
git log -p --all -S "EDGETAPE_PEXELS_API_KEY=" | grep -E "^\+EDGETAPE_[A-Z_]+=.{10,}"
```

Salida esperada: nada, o solo `.env.example` con placeholders
(`EDGETAPE_PEXELS_API_KEY=` vacío o con `TU-…`). Si aparece una línea con 10+ caracteres
reales tras el `=`, la clave está en el historial: **rotarla ya** (arriba). Reescribir el
historial con `git filter-repo` es opcional y forcea a todos a re-clonar.

Un chequeo más amplio de otros secretos:

```bash
git grep -nE "gsk_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{20,}" $(git rev-list --all) 2>/dev/null | head
```

Si algo aparece, se rotó la clave correspondiente (tabla de arriba) y listo: rotar es
siempre más barato y más seguro que limpiar el historial.

### Otros secretos que conviene rotar si alguna vez aparecieron

| Clave | Dónde se rota | Impacto si se filtra |
|---|---|---|
| `EDGETAPE_JWT_SECRET` | local (`python -c "import secrets; print(secrets.token_urlsafe(48))"`) | Firma JWT **y** las URLs públicas de clips: invalida todos los links firmados |
| `EDGETAPE_DATABASE_URL` | Neon | Acceso a la base (usuarios y cuentas) |
| `EDGETAPE_CELERY_BROKER` | Upstash | Acceso al broker de jobs |
| `EDGETAPE_GROQ_API_KEY` | <https://console.groq.com/keys> | Cuota de tu cuenta |
| `EDGETAPE_YT_CLIENT_SECRET` | Google Cloud → Credenciales | Robo de refresh tokens de YouTube |

**Nunca** subas `.env` a un Space de HF ni a un VPS: usa las *Variables and
secrets* de la plataforma. Y recordá que `client_secret` de una cuenta vinculada
nunca se devuelve por API (`LinkedAccountOut.has_client_secret` es booleano).

## 3. TikTok (SELF_ONLY sin app auditada)

### Qué pide el backend

`backend/app/tiktok_publish.py` usa la **Content Posting API** v2:

- Scopes: `video.upload,video.publish`
- Auth: `https://www.tiktok.com/v2/auth/authorize/`
- Token: `https://open.tiktokapis.com/v2/oauth/token/`
- Guarda el **`refresh_token`** (vence a los 365 días), no el access token.

### Pasos

1. <https://developers.tiktok.com/> → **My Apps** → *Create app*.
2. Nombre y descripción; la categoría que elijas condiciona para qué sirve.
3. En el producto **Content Posting API** es donde vive la subida de videos.
4. Copia **Client Key** y **Client Secret**.
5. Registra el redirect exacto que te devuelva la app:
   ```
   https://tu-dominio.com/api/tiktok/callback
   ```
   (o el de HF Spaces: `https://TU-USUARIO-TU-SPACE.hf.space/api/tiktok/callback`)

   > El backend deriva el `redirect_uri` de la request si la cuenta no tiene uno
   > guardado (`main.py` → `derived_uri`), así que si entras por el dominio real
   > el que se manda es ese. **El que registres en TikTok tiene que ser el mismo
   > carácter por carácter** — el `https`, el subdominio, la barra final.

### La restricción que muerde

Sin auditoría, TikTok **no publica público**. La app sin auditar acepta
únicamente `SELF_ONLY` (el video queda visible solo para ti). El default del
backend es ese:

```bash
EDGETAPE_TIKTOK_PRIVACY=SELF_ONLY   # default
```

Si más adelante aprobás la app, pasá a `PUBLIC_TO_EVERYONE`. **La auditoría
depende de ti, no del código**: es un proceso de TikTok que revisa la app y
exige, entre otras cosas, un sitio webTerms y una app que cumpla sus políticas.
Hasta entonces, automatizá con `SELF_ONLY` y no prometas Reels públicos.

### Dónde pegar las credenciales

Dos opciones, con esta prioridad (si la cuenta tiene credenciales propias, ganan
sobre las del entorno):

- **Por cuenta** (recomendado en multiusuario): en la app, **CUENTAS** → añadir
  cuenta TikTok → campos `Client Key`, `Client Secret`, `Redirect URI`.
- **Global**: `EDGETAPE_TIKTOK_CLIENT_KEY` / `EDGETAPE_TIKTOK_CLIENT_SECRET`.

## 4. Meta (Facebook + Instagram)

Es lo más enrevesado porque son dos cosas: **Facebook Login** da acceso a tus
**páginas**, y para publicar en Instagram necesitás que la página tenga una
**cuenta de Instagram business vinculada**.

### Qué pide el backend

`backend/app/meta_publish.py` pide estos permisos en el diálogo:

```
pages_show_list, pages_manage_posts, pages_read_engagement,
instagram_basic, instagram_content_publish
```

### Pasos

1. <https://developers.facebook.com/> → *My App* → **Business** (o "Other" si no
   tenés empresa) → tipo **Business**.
2. Productos → añadir **Facebook Login**. Configurá:
   - **Valid OAuth Redirect URIs**:
     `https://tu-dominio.com/api/meta/callback`
   - **Domain**: `tu-dominio.com` (el dominio, no la URL con path).
   - Dejá el resto por defecto.
3. Client ID y Client Secret en **Configuración → Básico**.
4. **Cuenta de Instagram business**: en la app de Facebook, *Configuración de
   página → Cuentas → Instagram*, vinculá la cuenta de Instagram. **Debe ser una
   cuenta business o profesional**, no personal. Si no la vinculaste, el login
   puede devolver `?meta=no_instagram`.
5. Configuración de la app (izquierda, abajo) → **Live** (o **En producción**):
   mientras esté en *Development* solo vos y los testers pueden autorizar. Para
   usuarios reales hace falta app en vivo, y si los permisos son sensibles
   (`instagram_content_publish`, `pages_manage_posts`) Meta te va a pedir **App
   Review** o **Business Verification**.
6. Meta **no** acepta URLs `localhost` en producción: el dominio tiene que ser de
   verdad.

### Qué guarda el backend

- El **Page Access Token** (no el token de usuario): es lo que permite publicar
  en esa página.
- La página (o el `ig_user_id` si la cuenta es Instagram) queda en `handle`.
- Se detecta sola la página y el Instagram business: `list_targets` pide
  `instagram_business_account{id,username}`.

### La parte que casi nadie tiene lista

**Reelsautomáticos = Instagram business + Page Access Token +
`EDGETAPE_PUBLIC_BASE_URL`.** Si falta cualquiera de los tres, el post cae a
`manual`. Son tres independientes y painless por separado.

## 5. YouTube (Google Cloud)

Es la plataforma más fácil de las tres porque el respaldo manual siempre funciona
(un enlace a YouTube Studio), pero la subida automática necesita credenciales.

1. <https://console.cloud.google.com/> → proyecto nuevo.
2. APIs y servicios → **Biblioteca** → activá **YouTube Data API v3**.
3. APIs y servicios → **Credenciales** → *Crear credenciales* → **ID de cliente
   OAuth** → tipo **Aplicación web**.
4. **URI de redireccionamiento autorizado**:
   ```
   https://tu-dominio.com/api/youtube/callback
   ```
5. Te da **Client ID** y **Client Secret**.

```bash
EDGETAPE_YT_CLIENT_ID=...apps.googleusercontent.com
EDGETAPE_YT_CLIENT_SECRET=...
EDGETAPE_YT_REDIRECT_URI=https://tu-dominio.com/api/youtube/callback
```

Ojo con dos cosas que ya están manejadas en el código:

- Si guardás una **API key** (`AIzaSy…`) en vez de un client secret, el backend
  detecta que no es OAuth y cae al respaldo de Studio sin intentar subir.
- Un proyecto de API **sin verificar** (creado después del 28-jul-2020) fuerza
  los videos a **privados**. Verificá el proyecto o los shorts quedan privados.

El límite diario (`uploadLimitExceeded`) es del **canal**, no del proyecto ni del
servidor: no lo arregla ningún deploy, hay que esperar 24 h. El backend pausa la
cuenta sola hasta medianoche UTC. Ver la sección dedicada en
[`deploy-free.md`](deploy-free.md#sobre-el-límite-de-youtube-uploadlimitexceeded).

## 6. Verificación final

En orden, después de desplegar:

```bash
# 1. la API responde
curl https://tu-dominio.com/api/health
# esperá: ok true, transcriber groq-whisper-*, scorer llm-*

# 2. la base y el broker están
docker compose ps        # si es compose local
```

Y en la app, en este orden:

1. **CUENTAS** → conectar **YouTube** (el más simple: si falla, el problema es de
   Google, no tuyo). Debe redirigir y volver con "YouTube conectado".
2. **CUENTAS** → conectar **TikTok**. Si vuelve con error, es el redirect o el
   Client Key/Secret.
3. **CUENTAS** → conectar **Meta**. Si vuelve con `?meta=empty` no devolvió
   páginas; con `?meta=no_instagram`, ninguna página tiene Instagram business.
4. **PUBLICAR** → generar un video con IA, marcar el clip para publicar, elegir
   plataforma y publicar.
5. Verificar en cada plataforma que el video exists. Si quedó `manual`, el
   `post.error` dice por qué — **siempre se guarda el motivo**.

**En los logs del worker** estas líneas son las buenas:

```
generating metadata with groq-metadata-openai/gpt-oss-20b
material por escena: 2 b-roll, 0 imágenes, 2 fondos (4 escenas)
música de fondo agregada: pulse-soft.mp3
escena 1: pexels video · ...
```

Y estas son las que avejan:

| Log | Qué significa | Qué hacer |
|---|---|---|
| `metadata generation FAILED ... using HEURISTIC` | Groq no respondió (429 o modelo caído) | Esperar y reintentar; ya hay rotación de modelos |
| `public_clip_url` sin base / `EDGETAPE_PUBLIC_BASE_URL` | Falta URL pública | Definirla (sección 1) |
| `uploadLimitExceeded` | Límite del canal de YouTube | Esperar 24 h, el backend ya pausó la cuenta |
| `No se generaron clips` | El guion no encontró gancho publicable | Cambiar el prompt del video generado |

## 7. Cuando algo falla

| Síntoma | Causa probable | Arreglo |
|---|---|---|
| `?tiktok=error` | Client Key/Secret mal, o el redirect no está registrado **en la app** | Verificá carácter por carácter contra el panel de TikTok |
| `?meta=empty` | El login no devolvió ninguna página administrada | El usuario no administra ninguna página, o la app no tiene esos permisos |
| `?meta=no_instagram` | Ninguna página tiene Instagram business | Vincular IG business a la página (sección 4) |
| `?youtube=error` | Refresh token rechazado, credenciales de otra app | Recrear credenciales en Google Cloud |
| El Reel queda `manual` | Sin `EDGETAPE_PUBLIC_BASE_URL`, o clip sin exportar | Sección 1 + exportar el clip |
| `404 clip not exported` al probar la URL firmada | El clip no tiene export | Exportar antes de publicar |
| El video se sube pero no aparece | Privacidad de la app | `EDGETAPE_TIKTOK_PRIVACY` según auditoría |
| Groq devuelve 400 `model_decommissioned` | Modelo retirado por Groq | Ya hay rotación automática a `GROQ_FALLBACK_MODELS`; si persiste, cambiá `EDGETAPE_GROQ_MODEL` |

**Herramienta de debug**: casi todos los callbacks son `GET` con `?code=&state=`.
Para ver qué falla, copiá la URL de redirección del navegador: si vuelve a
`?tiktok=error` el backend ya logueó la causa en su consola (con el server en
foreground, en el terminal donde corre `uvicorn`).

---

Ver también: [`deploy-free.md`](deploy-free.md) (alojamiento gratuito) ·
[`pipeline.mmd`](pipeline.mmd) (flujo) · `README.md` (funcionalidad).
