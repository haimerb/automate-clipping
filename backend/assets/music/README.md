# Pistas de música de fondo

Las pistas de este directorio se ofrecen en el generador con IA (pantalla INGRESAR →
"Generar con IA" → selector **Música**). Se mezclan por debajo de la voz
(`EDGETAPE_MUSIC_VOLUME`, por defecto `0.22`) y el generador las loopea hasta la
duración del video, así que cualquier pista corta sirve.

Formatos aceptados: `.mp3`, `.m4a`, `.wav`, `.aac`, `.ogg`, `.opus`, `.flac`.

## Pistas incluidas

`ambient-pad.mp3` y `pulse-soft.mp3` están **sintetizadas con ffmpeg** para este
proyecto (sin problemas de licencias): no pertenecen a ningún catálogo comercial.
Sustituirlas o añadir otras es simplemente dejar el archivo en la carpeta.

## Carpeta propia

```bash
EDGETAPE_MUSIC_DIR=/ruta/a/mis/pistas
```

Si la variable no está definida se usa `backend/assets/music`.

## Recomendaciones

- Sin voz ni letra: la narración del TTS va encima.
- Formato instrumental/loopeable; si dura 30 s se repite hasta el final.
- Prefiere 90-120 BPM y poca percusión para shorts narrados.
