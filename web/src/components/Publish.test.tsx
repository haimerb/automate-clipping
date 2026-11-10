import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import Publish from "./Publish";
import type { Clip, Job } from "../api";

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return {
    ...actual,
    getAccounts: vi.fn().mockResolvedValue([]),
    getPosts: vi.fn().mockResolvedValue([]),
    patchJobSettings: vi.fn().mockResolvedValue(undefined),
    publishClip: vi.fn().mockResolvedValue(undefined),
    request: vi.fn().mockResolvedValue({ pending: 0, tasks: [], account_quotas: {} }),
    setClipPublish: vi.fn().mockResolvedValue(undefined),
    updateClip: vi.fn().mockResolvedValue(undefined),
  };
});

function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    id: "job1",
    filename: "video.mp4",
    owner_id: "user1",
    source: "upload",
    source_url: null,
    status: "done",
    progress: 100,
    error: null,
    warning: null,
    duration: 400,
    transcriber: "mock",
    scorer: "heuristic",
    clip_count: 1,
    post_count: 0,
    auto_publish: false,
    auto_publish_platform: "youtube_shorts",
    auto_publish_account: null,
    platform: "youtube_shorts",
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

function makeClip(overrides: Partial<Clip> = {}): Clip {
  return {
    id: "clip1",
    index: 1,
    start: 0,
    end: 400,
    duration: 400,
    title: "Clip de prueba",
    line: "una línea",
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
    destinations: [{ platform: "youtube_shorts", account: "" }],
    ...overrides,
  };
}

function renderPublish(job: Job, clip: Clip) {
  return render(
    <Publish
      job={job}
      clips={[clip]}
      onUpdateClip={() => {}}
      onBack={() => {}}
      onJobChange={() => {}}
    />,
  );
}

describe("Publish", () => {
  it("avisa del recorte cuando un clip largo va a un destino corto", async () => {
    renderPublish(makeJob(), makeClip({ duration: 400 }));

    expect(await screen.findByText(/se publicará recortado a 1:00/i)).toBeInTheDocument();
  });

  it("no avisa del recorte cuando el destino admite la duración", async () => {
    renderPublish(
      makeJob({ platform: "youtube", auto_publish_platform: "youtube" }),
      makeClip({
        duration: 400,
        destinations: [{ platform: "youtube", account: "" }],
      }),
    );

    expect(await screen.findByText("Clip de prueba")).toBeInTheDocument();
    expect(screen.queryByText(/se publicará recortado/i)).not.toBeInTheDocument();
  });

  it("muestra la plataforma del job como destino por defecto", async () => {
    renderPublish(
      makeJob({ platform: "youtube", auto_publish_platform: "youtube" }),
      makeClip({ duration: 30, destinations: [] }),
    );

    expect((await screen.findAllByText("YouTube (video)")).length).toBeGreaterThan(0);
  });
});
