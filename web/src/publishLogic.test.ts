import { describe, expect, it } from "vitest";

import {
  DEFAULT_PLATFORM,
  describeMismatch,
  resolveDefaultDraft,
  resolveJobPlatform,
} from "./publishLogic";
import type { Clip, LinkedAccount } from "./api";

function makeClip(overrides: Partial<Clip> = {}): Clip {
  return {
    id: "clip1",
    index: 1,
    start: 0,
    end: 400,
    duration: 400,
    title: "Título",
    line: "línea",
    script: "script",
    score: 1,
    description: "",
    tags: [],
    thumbnail: null,
    thumbnails: [],
    thumbnail_index: 0,
    exported: false,
    export_name: null,
    export_platform: null,
    publish: true,
    destinations: [],
    ...overrides,
  };
}

function makeAccount(platform: string, name: string): LinkedAccount {
  return {
    id: `acc-${name}`,
    platform,
    name,
    handle: name,
    token: null,
    client_id: null,
    has_client_secret: false,
    redirect_uri: null,
    created_at: new Date().toISOString(),
  };
}

describe("resolveJobPlatform", () => {
  it("prefiere job.platform", () => {
    expect(resolveJobPlatform({ platform: "youtube", auto_publish_platform: "tiktok" })).toBe(
      "youtube",
    );
  });

  it("cae a auto_publish_platform si platform está vacío", () => {
    expect(resolveJobPlatform({ platform: "", auto_publish_platform: "tiktok" })).toBe("tiktok");
  });

  it("cae al default si ambos están vacíos", () => {
    expect(resolveJobPlatform({ platform: "", auto_publish_platform: "" })).toBe(DEFAULT_PLATFORM);
  });

  it("un video creado para YouTube no se trata como Shorts (bug del recorte)", () => {
    expect(resolveJobPlatform({ platform: "youtube", auto_publish_platform: "youtube" })).toBe(
      "youtube",
    );
    expect(DEFAULT_PLATFORM).not.toBe("youtube");
  });
});

describe("describeMismatch", () => {
  it("no avisa cuando el clip cabe y no hay export", () => {
    const clip = makeClip({ duration: 30 });
    expect(describeMismatch(clip, "youtube_shorts", "youtube_shorts")).toBeNull();
  });

  it("avisa del recorte cuando el clip supera el máximo del destino", () => {
    const clip = makeClip({ duration: 400 });
    const msg = describeMismatch(clip, "youtube_shorts", "youtube_shorts");
    expect(msg).toMatch(/YouTube Shorts admite 1:00/);
    expect(msg).toMatch(/recortado a 1:00/);
    expect(msg).toMatch(/6:40/);
  });

  it("no avisa del recorte en YouTube largo (900s)", () => {
    const clip = makeClip({ duration: 400 });
    expect(describeMismatch(clip, "youtube", "youtube")).toBeNull();
  });

  it("el límite es inclusivo con medio segundo de margen", () => {
    expect(describeMismatch(makeClip({ duration: 60.5 }), "youtube_shorts", "youtube_shorts")).toBeNull();
    expect(
      describeMismatch(makeClip({ duration: 60.6 }), "youtube_shorts", "youtube_shorts"),
    ).toMatch(/recortado/);
  });

  it("avisa si el export es horizontal y el destino vertical", () => {
    const clip = makeClip({
      exported: true,
      export_platform: "youtube",
      duration: 30,
    });
    expect(describeMismatch(clip, "tiktok", "youtube")).toMatch(/exportó horizontal/);
  });

  it("avisa si el export es vertical y el destino horizontal", () => {
    const clip = makeClip({
      exported: true,
      export_platform: "youtube_shorts",
      duration: 30,
    });
    expect(describeMismatch(clip, "youtube", "youtube_shorts")).toMatch(/exportó vertical/);
  });

  it("avisa si el destino difiere de la plataforma del job (export sin plataforma)", () => {
    const clip = makeClip({ exported: true, export_platform: null, duration: 30 });
    expect(describeMismatch(clip, "tiktok", "youtube")).toMatch(
      /se creó para YouTube \(video\); al publicar en TikTok/,
    );
  });

  it("no avisa de formato si el destino coincide con la plataforma del job", () => {
    const clip = makeClip({ exported: true, export_platform: null, duration: 30 });
    expect(describeMismatch(clip, "youtube", "youtube")).toBeNull();
  });

  it("acumula varios avisos", () => {
    const clip = makeClip({ duration: 400, exported: true, export_platform: "youtube" });
    const msg = describeMismatch(clip, "tiktok", "youtube");
    expect(msg).toMatch(/recortado/);
    expect(msg).toMatch(/exportó horizontal/);
  });
});

describe("resolveDefaultDraft", () => {
  const accounts = [makeAccount("youtube", "Canal YT"), makeAccount("tiktok", "TikTok Pro")];

  it("usa defaultTargetPlatform si no hay override", () => {
    expect(resolveDefaultDraft("c1", "tiktok", accounts, {}, {})).toEqual({
      platform: "tiktok",
      account: "TikTok Pro",
    });
  });

  it("respeta la plataforma elegida a mano", () => {
    expect(resolveDefaultDraft("c1", "tiktok", accounts, { c1: "youtube_shorts" }, {})).toEqual({
      platform: "youtube_shorts",
      account: "Canal YT",
    });
  });

  it("respeta la cuenta elegida si está disponible para esa plataforma", () => {
    const result = resolveDefaultDraft(
      "c1",
      "youtube",
      accounts,
      { c1: "youtube" },
      { c1: "Canal YT" },
    );
    expect(result.account).toBe("Canal YT");
  });

  it("descarta una cuenta que no aplica a la plataforma", () => {
    const result = resolveDefaultDraft(
      "c1",
      "youtube",
      accounts,
      { c1: "youtube" },
      { c1: "TikTok Pro" },
    );
    expect(result.account).toBe("Canal YT");
  });

  it("devuelve cuenta vacía si no hay cuentas de esa plataforma", () => {
    expect(resolveDefaultDraft("c1", "instagram_reels", accounts, {}, {}).account).toBe("");
  });
});
