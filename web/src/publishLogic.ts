import {
  HORIZONTAL_PLATFORMS,
  PLATFORM_LABELS,
  accountsForPlatform,
  formatDuration,
  maxSecondsFor,
} from "./api";
import type { Clip, Job, LinkedAccount } from "./api";

export const DEFAULT_PLATFORM = "youtube_shorts";

/** Plataforma para la que se creó el job: manda sobre el destino por defecto.
 *
 * Un video generado como "YouTube (video)" (horizontal, hasta 900 s) no debe
 * ofrecerse por defecto como Short (vertical, 60 s). */
export function resolveJobPlatform(
  job: Pick<Job, "platform" | "auto_publish_platform">,
): string {
  return job.platform || job.auto_publish_platform || DEFAULT_PLATFORM;
}

/** Aviso honesto sobre lo que le pasará al clip en ese destino.
 *
 * El backend recorta al publicar (`publish_one` → `max_duration`), así que
 * publicar un clip largo en Shorts lo deja corto SIN avisar. Aquí se dice antes
 * de que el usuario pulse Publicar. */
export function describeMismatch(
  clip: Clip,
  platform: string,
  jobPlatform: string,
): string | null {
  const label = PLATFORM_LABELS[platform] ?? platform;
  const limit = maxSecondsFor(platform);
  const notes: string[] = [];

  if (clip.duration > limit + 0.5) {
    notes.push(
      `${label} admite ${formatDuration(limit)}: se publicará recortado a ${formatDuration(limit)} de los ${formatDuration(clip.duration)} del clip.`,
    );
  }

  const isVerticalTarget = !HORIZONTAL_PLATFORMS.has(platform);
  const wasVerticalExport = clip.export_platform
    ? !HORIZONTAL_PLATFORMS.has(clip.export_platform)
    : null;
  if (clip.exported && wasVerticalExport !== null && wasVerticalExport !== isVerticalTarget) {
    notes.push(
      isVerticalTarget
        ? "El clip se exportó horizontal; al publicar aquí se re-cortará a vertical con fondo borroso."
        : "El clip se exportó vertical; al publicar aquí se quedará en vertical, no se recorta a horizontal.",
    );
  } else if (clip.exported && platform !== jobPlatform) {
    notes.push(
      `El video se creó para ${PLATFORM_LABELS[jobPlatform] ?? jobPlatform}; al publicar en ${label} se recorta con el formato de ${label}.`,
    );
  }
  return notes.length > 0 ? notes.join(" ") : null;
}

/** Plataforma y cuenta con las que se prellena el formulario de un destino.
 *
 * `draftPlatform` solo se setea cuando el usuario cambia el Select a mano; si
 * no, manda la plataforma por defecto del job. */
export function resolveDefaultDraft(
  clipId: string,
  defaultTargetPlatform: string,
  accounts: LinkedAccount[],
  draftPlatform: Record<string, string>,
  draftAccount: Record<string, string>,
): { platform: string; account: string } {
  const platform = draftPlatform[clipId] ?? defaultTargetPlatform;
  const available = accountsForPlatform(accounts, platform);
  const account = available.some((a) => a.name === draftAccount[clipId])
    ? draftAccount[clipId]
    : available[0]?.name ?? "";
  return { platform, account };
}
