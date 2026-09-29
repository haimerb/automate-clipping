import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useColorScheme } from "@mui/material/styles";
import {
  Box,
  Button,
  Divider,
  Drawer,
  IconButton,
  Stack,
  Toolbar,
  Typography,
} from "@mui/material";
import MenuRoundedIcon from "@mui/icons-material/MenuRounded";
import LogoutRoundedIcon from "@mui/icons-material/LogoutRounded";
import DarkModeRoundedIcon from "@mui/icons-material/DarkModeRounded";
import LightModeRoundedIcon from "@mui/icons-material/LightModeRounded";
import Upload from "./components/Upload";
import Reel from "./components/Reel";
import Dashboard from "./components/Dashboard";
import Publish from "./components/Publish";
import Review from "./components/Review";
import Accounts from "./components/Accounts";
import Auth from "./components/Auth";
import WizardNav from "./components/WizardNav";
import { getClips, getJob, getMe, getToken, setToken } from "./api";
import type { Clip, Job, User } from "./api";
import {
  CARD,
  EDGE,
  MARK,
  MONO,
  ON_ACCENT,
  SIDEBAR_DISABLED,
  SIDEBAR_HOVER,
  SIDEBAR_TEXT,
  SIDEBAR_TEXT_ACTIVE,
  SIDEBAR_WIDTH,
} from "./theme";

type WizardStep = "ingest" | "clips" | "review" | "publish" | "accounts" | "analytics";

const WIZARD_STEPS: WizardStep[] = ["ingest", "clips", "review", "publish", "accounts", "analytics"];

export const STEP_ROUTES: Record<WizardStep, string> = {
  ingest: "/ingresar",
  clips: "/clips",
  review: "/revisar",
  publish: "/publicar",
  accounts: "/cuentas",
  analytics: "/ganancias",
};

const ROUTE_STEPS: Record<string, WizardStep> = {
  "/ingresar": "ingest",
  "/clips": "clips",
  "/revisar": "review",
  "/publicar": "publish",
  "/cuentas": "accounts",
  "/ganancias": "analytics",
};

const STEP_LABELS: Record<WizardStep, string> = {
  ingest: "Ingresar",
  clips: "Clips",
  review: "Revisar",
  publish: "Publicar",
  accounts: "Cuentas",
  analytics: "Ganancias",
};

const STORAGE_KEY = "edgetape_wizard_state";

function Brand() {
  return (
    <Box sx={{ display: "flex", alignItems: "center", gap: 1.5 }}>
      <Box
        sx={{
          width: 32,
          height: 32,
          borderRadius: 1.5,
          background: `linear-gradient(135deg, ${EDGE} 0%, ${MARK} 100%)`,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          boxShadow: "0 2px 8px rgba(0,255,136,0.25)",
        }}
      >
        <Typography
          sx={{
            fontFamily: MONO,
            fontSize: "0.9rem",
            fontWeight: 700,
            color: ON_ACCENT,
            lineHeight: 1,
          }}
        >
          ▶
        </Typography>
      </Box>
      <Box>
        <Typography
          sx={{
            fontFamily: MONO,
            fontSize: "1rem",
            fontWeight: 600,
            color: "#fff",
            letterSpacing: "0.02em",
            lineHeight: 1.2,
          }}
        >
          edgetape
        </Typography>
        <Typography
          sx={{
            fontFamily: MONO,
            fontSize: "0.52rem",
            color: "rgba(255,255,255,0.35)",
            letterSpacing: "0.1em",
            textTransform: "uppercase",
          }}
        >
          panel de control
        </Typography>
      </Box>
    </Box>
  );
}

interface SidebarProps {
  activeStep: WizardStep;
  completedSteps: WizardStep[];
  onStepClick: (step: WizardStep) => void;
  onLogout: () => void;
  user: User;
  job: Job | null;
  clipsCount: number;
  toPublish: number;
}

function SidebarContent({ activeStep, completedSteps, onStepClick, onLogout, user, job, clipsCount, toPublish }: SidebarProps) {
  const canGoClips = !!job;
  const canGoReview = canGoClips && clipsCount > 0;
  const canGoPublish = canGoReview && toPublish > 0;

  const navItems = [
    { step: "ingest" as WizardStep, label: "1. INGRESAR", caption: "Sube o pega un video", icon: "📥", disabled: false },
    { step: "clips" as WizardStep, label: "2. CLIPS", caption: "Detecta momentos clave", icon: "🎬", disabled: !canGoClips },
    { step: "review" as WizardStep, label: "3. REVISAR", caption: "Edita metadata y miniaturas", icon: "✏️", disabled: !canGoReview },
    { step: "publish" as WizardStep, label: "4. PUBLICAR", caption: "Configura destinos y publica", icon: "🚀", disabled: !canGoPublish },
    { step: "accounts" as WizardStep, label: "5. CUENTAS", caption: "Canales vinculados", icon: "🔗", disabled: false },
    { step: "analytics" as WizardStep, label: "6. GANANCIAS", caption: "Mide tu rendimiento", icon: "📊", disabled: false },
  ];

  return (
    <Box sx={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <Toolbar sx={{ px: 2.5, gap: 1, minHeight: 72 }}>
        <Brand />
      </Toolbar>
      <Box component="nav" aria-label="Pasos del asistente" sx={{ flex: 1, overflow: "auto", py: 2, px: 1.5 }}>
        {navItems.map((item) => {
          const isCompleted = completedSteps.includes(item.step);
          const isCurrent = item.step === activeStep;

          return (
            <Button
              key={item.step}
              component="div"
              fullWidth
              disabled={item.disabled}
              onClick={() => !item.disabled && onStepClick(item.step)}
              sx={{
                mb: 1.5,
                py: 1.5,
                px: 2,
                borderRadius: 2,
                textAlign: "left",
                justifyContent: "flex-start",
                gap: 1.5,
                background: isCurrent
                  ? "rgb(var(--mui-palette-secondary-mainChannel) / 0.12)"
                  : isCompleted
                  ? "rgb(var(--mui-palette-secondary-mainChannel) / 0.08)"
                  : "transparent",
                border: isCurrent ? `2px solid ${MARK}` : isCompleted ? `1px solid ${MARK}` : `1px solid ${SIDEBAR_HOVER}`,
                color: item.disabled
                  ? SIDEBAR_DISABLED
                  : isCurrent
                  ? "#fff"
                  : isCompleted
                  ? SIDEBAR_TEXT_ACTIVE
                  : SIDEBAR_TEXT,
                "&:hover": {
                  background: item.disabled
                    ? "transparent"
                    : isCurrent
                    ? "rgb(var(--mui-palette-secondary-mainChannel) / 0.16)"
                    : "rgba(255,255,255,0.08)",
                  borderColor: isCurrent ? MARK : SIDEBAR_HOVER,
                },
                transition: "all 0.2s ease",
              }}
            >
              <Box
                sx={{
                  width: 36,
                  height: 36,
                  borderRadius: "50%",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: "1.1rem",
                  flexShrink: 0,
                  background: isCurrent || isCompleted
                    ? "linear-gradient(135deg, #1E90FF 0%, #00FF88 100%)"
                    : item.disabled
                    ? "rgba(255,255,255,0.05)"
                    : "rgba(255,255,255,0.08)",
                  color: isCurrent || isCompleted ? ON_ACCENT : item.disabled ? SIDEBAR_DISABLED : "rgba(255,255,255,0.4)",
                  border: isCurrent ? `2px solid ${MARK}` : "none",
                  boxShadow: isCurrent
                    ? "0 0 0 4px rgb(var(--mui-palette-secondary-mainChannel) / 0.3), 0 4px 12px rgba(0,0,0,0.4)"
                    : "none",
                  transition: "all 0.3s ease",
                }}
              >
                {isCompleted ? "✓" : item.icon}
              </Box>
              <Box sx={{ flex: 1, minWidth: 0 }}>
                <Typography
                  sx={{
                    fontFamily: MONO,
                    fontSize: "0.58rem",
                    fontWeight: 700,
                    letterSpacing: "0.08em",
                    textTransform: "uppercase",
                    color: item.disabled ? SIDEBAR_DISABLED : isCurrent ? "#fff" : isCompleted ? SIDEBAR_TEXT_ACTIVE : "rgba(255,255,255,0.6)",
                    lineHeight: 1.2,
                    display: "block",
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }}
                >
                  {item.label}
                </Typography>
                <Typography
                  sx={{
                    fontSize: "0.6rem",
                    color: item.disabled ? SIDEBAR_DISABLED : isCurrent ? "rgba(255,255,255,0.5)" : "rgba(255,255,255,0.3)",
                    lineHeight: 1.2,
                    display: "block",
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }}
                >
                  {item.caption}
                </Typography>
              </Box>
              {(isCompleted || isCurrent) && (
                <Box
                  sx={{
                    width: 24,
                    height: 24,
                    borderRadius: "50%",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    background: isCompleted ? MARK : "transparent",
                    border: isCurrent ? `2px solid ${MARK}` : isCompleted ? "none" : `1px solid ${SIDEBAR_HOVER}`,
                    color: isCompleted ? ON_ACCENT : MARK,
                    fontSize: "0.7rem",
                    fontWeight: 700,
                    fontFamily: MONO,
                    flexShrink: 0,
                  }}
                >
                  {isCompleted ? "✓" : isCurrent ? "▸" : ""}
                </Box>
              )}
            </Button>
          );
        })}
      </Box>
      <Divider sx={{ borderColor: SIDEBAR_HOVER, mx: 2 }} />
      <Box sx={{ px: 2, py: 2 }}>
        <Stack direction="row" spacing={1.5} sx={{ alignItems: "center" }}>
          <Box
            sx={{
              width: 34,
              height: 34,
              borderRadius: "50%",
              background: "rgb(var(--mui-palette-secondary-mainChannel) / 0.15)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
            }}
          >
            <Typography sx={{ fontWeight: 700, fontSize: "0.8rem", color: MARK }}>
              {user.name.charAt(0).toUpperCase()}
            </Typography>
          </Box>
          <Box sx={{ minWidth: 0, flex: 1 }}>
            <Typography
              variant="body2"
              sx={{
                fontWeight: 600,
                fontSize: "0.78rem",
                color: "rgba(255,255,255,0.9)",
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}
            >
              {user.name}
            </Typography>
            <Typography
              sx={{
                fontFamily: MONO,
                fontSize: "0.56rem",
                color: "rgba(255,255,255,0.35)",
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}
            >
              {user.email}
            </Typography>
          </Box>
          <IconButton
            size="small"
            onClick={onLogout}
            aria-label="salir"
            sx={{ color: "rgba(255,255,255,0.35)", "&:hover": { color: "#fff", backgroundColor: "rgba(255,255,255,0.08)" } }}
          >
            <LogoutRoundedIcon fontSize="small" />
          </IconButton>
        </Stack>
      </Box>
    </Box>
  );
}

function ColorModeToggle() {
  const { mode, setMode } = useColorScheme();
  const dark = mode === "dark";
  return (
    <IconButton
      size="small"
      aria-label={dark ? "cambiar a modo claro" : "cambiar a modo oscuro"}
      onClick={() => setMode(dark ? "light" : "dark")}
      sx={{
        border: "1px solid",
        borderColor: "divider",
        color: "text.secondary",
        "&:hover": { color: "text.primary", borderColor: EDGE },
      }}
    >
      {dark ? <LightModeRoundedIcon fontSize="small" /> : <DarkModeRoundedIcon fontSize="small" />}
    </IconButton>
  );
}

export default function App() {
  const navigate = useNavigate();
  const location = useLocation();
  const [user, setUser] = useState<User | null>(null);
  const [completedSteps, setCompletedSteps] = useState<WizardStep[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [clips, setClips] = useState<Clip[]>([]);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [resumeJob, setResumeJob] = useState<Job | null>(null);
  const [jobError, setJobError] = useState<string | null>(null);

  const step = ROUTE_STEPS[location.pathname] ?? "ingest";

  function saveWizardState() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        step: step,
        route: location.pathname,
        completedSteps,
        jobId: job?.id,
      }));
    } catch {}
  }

  function loadWizardState(): string | null {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed.completedSteps)) {
          setCompletedSteps(parsed.completedSteps.filter((s: string) => WIZARD_STEPS.includes(s as WizardStep)));
        }
        return parsed.jobId ?? null;
      }
    } catch {}
    return null;
  }

  useEffect(() => {
    if (!getToken()) return;
    const savedJobId = loadWizardState();
    getMe()
      .then(setUser)
      .catch(() => setToken(null));
    if (!savedJobId) return;
    // Tras un F5 el job sigue en el servidor: se recupera en cualquier estado,
    // no solo cuando ya terminó (antes se perdía el progreso en curso).
    getJob(savedJobId)
      .then((j) => {
        if (j.status === "done") {
          void handleReady(j);
        } else if (j.status === "failed") {
          setJobError(j.error ?? "El job falló");
          goTo("ingest");
        } else {
          setResumeJob(j);
          goTo("ingest");
        }
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    const onUnauthorized = () => setUser(null);
    window.addEventListener("edgetape:unauthorized", onUnauthorized);
    return () => window.removeEventListener("edgetape:unauthorized", onUnauthorized);
  }, []);

  useEffect(() => {
    const onNavigate = (e: CustomEvent) => {
      if (e.detail && WIZARD_STEPS.includes(e.detail)) {
        goTo(e.detail);
      }
    };
    window.addEventListener("edgetape:navigate", onNavigate as EventListener);
    return () => window.removeEventListener("edgetape:navigate", onNavigate as EventListener);
  }, [step]);

  function handleAuth(next: User) {
    setUser(next);
    goTo("ingest");
  }

  function logout() {
    setToken(null);
    setUser(null);
    setJob(null);
    setClips([]);
    setCompletedSteps([]);
    setResumeJob(null);
    setJobError(null);
    localStorage.removeItem(STORAGE_KEY);
    goTo("ingest");
  }

  async function handleReady(finished: Job) {
    setResumeJob(null);
    setJobError(null);
    let found: Clip[] = [];
    for (let i = 0; i < 5; i++) {
      found = await getClips(finished.id);
      if (found.length > 0) break;
      await new Promise(r => setTimeout(r, 500));
    }
    setClips(found);
    setJob(finished);
    markCompleted("ingest");
    goTo("clips");
    window.scrollTo({ top: 0 });
  }

  async function openJob(jobId: string) {
    const found = await getJob(jobId);
    if (found.status === "done") {
      await handleReady(found);
      return;
    }
    if (found.status === "failed") {
      setResumeJob(null);
      setJobError(found.error ?? "Ese video falló al procesarse");
      goTo("ingest");
      return;
    }
    // sigue en cola o procesándose: se retoma el seguimiento en INGRESAR
    setJobError(null);
    setResumeJob(found);
    goTo("ingest");
  }

  // Re-render de un job generado con IA: vuelve al seguimiento en INGRESAR
  // en vez de dejar la pantalla de clips mostrando el video anterior.
  function handleRegenerated() {
    setClips([]);
    setJobError(null);
    if (job) {
      setResumeJob({ ...job, status: "queued", progress: 0 });
    }
    goTo("ingest");
    window.scrollTo({ top: 0 });
  }

  function markCompleted(stepName: WizardStep) {
    setCompletedSteps((prev) => {
      if (prev.includes(stepName)) return prev;
      const newSteps = [...prev, stepName];
      saveWizardState();
      return newSteps;
    });
  }

  function goTo(newStep: WizardStep) {
    const currentIndex = WIZARD_STEPS.indexOf(step);
    const newIndex = WIZARD_STEPS.indexOf(newStep);
    const isGlobalStep = newStep === "accounts" || newStep === "analytics";
    if (isGlobalStep || newIndex <= currentIndex || newIndex === currentIndex + 1 || completedSteps.includes(newStep)) {
      navigate(STEP_ROUTES[newStep]);
      setMobileOpen(false);
      window.scrollTo({ top: 0 });
    }
  }

  function canGoTo(newStep: WizardStep): boolean {
    const newIndex = WIZARD_STEPS.indexOf(newStep);
    const currentIndex = WIZARD_STEPS.indexOf(step);
    const isGlobalStep = newStep === "accounts" || newStep === "analytics";
    const isNextStep = newIndex === currentIndex + 1;
    return isGlobalStep || newIndex <= currentIndex || isNextStep || completedSteps.includes(newStep);
  }

  function handleReset() {
    setJob(null);
    setClips([]);
    setCompletedSteps([]);
    setResumeJob(null);
    setJobError(null);
    localStorage.removeItem(STORAGE_KEY);
    goTo("ingest");
  }

  function updateClip(updated: Clip) {
    setClips((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));
  }

  useEffect(() => {
    saveWizardState();
  }, [step, completedSteps]);

  if (!user) {
    return <Auth onAuth={handleAuth} />;
  }

  const toPublish = clips.filter((c) => c.publish).length;
  const sidebarProps = {
    activeStep: step,
    completedSteps,
    onStepClick: (s: WizardStep) => canGoTo(s) && goTo(s),
    onLogout: logout,
    user,
    job,
    clipsCount: clips.length,
    toPublish,
  };

  return (
    <Box sx={{ display: "flex", minHeight: "100vh" }}>
      <Drawer
        variant="permanent"
        open
        sx={{
          width: { md: SIDEBAR_WIDTH },
          display: { xs: "none", md: "block" },
          "& .MuiDrawer-paper": { width: SIDEBAR_WIDTH, boxSizing: "border-box" },
        }}
      >
        <SidebarContent {...sidebarProps} />
      </Drawer>

      <Drawer
        variant="temporary"
        open={mobileOpen}
        onClose={() => setMobileOpen(false)}
        sx={{
          display: { xs: "block", md: "none" },
          "& .MuiDrawer-paper": { width: SIDEBAR_WIDTH, boxSizing: "border-box" },
        }}
      >
        <SidebarContent {...sidebarProps} />
      </Drawer>

      <Box sx={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        <Box
          component="header"
          sx={{
            position: "sticky",
            top: 0,
            zIndex: 10,
            background: CARD,
            borderBottom: "1px solid",
            borderColor: "divider",
            boxShadow: "0 1px 3px rgba(0,0,0,.15)",
          }}
        >
          <Toolbar sx={{ gap: 2, px: { xs: 2, md: 3 }, minHeight: 60 }}>
            <IconButton
              edge="start"
              aria-label="abrir menú"
              onClick={() => setMobileOpen(true)}
              sx={{ display: { md: "none" } }}
            >
              <MenuRoundedIcon />
            </IconButton>
            <Box sx={{ minWidth: 0 }}>
              <Typography variant="overline" sx={{ display: "block", fontSize: "0.58rem" }}>
                Edgetape — asistente de publicación
              </Typography>
              <Typography variant="h6" sx={{ lineHeight: 1.15, fontSize: "1.05rem" }}>
                {STEP_LABELS[step]}
              </Typography>
            </Box>
            <Box
              sx={{
                ml: "auto",
                display: "flex",
                alignItems: "center",
                gap: 1,
                minWidth: 0,
              }}
            >
              {job && (
                <Typography
                  variant="caption"
                  color="text.secondary"
                  sx={{
                    fontFamily: MONO,
                    fontSize: "0.62rem",
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    maxWidth: { xs: 120, sm: 220 },
                    px: 1,
                    py: 0.5,
                    borderRadius: 1,
                    backgroundColor: "rgb(var(--mui-palette-primary-mainChannel) / 0.08)",
                  }}
                >
                  {job.filename}
                </Typography>
              )}
              <Box sx={{ display: { xs: "none", sm: "flex" }, alignItems: "center", gap: 1 }}>
                <Typography
                  variant="body2"
                  sx={{ fontFamily: MONO, fontSize: "0.7rem", color: "text.secondary" }}
                >
                  {user.name}
                </Typography>
                <Button
                  variant="outlined"
                  size="small"
                  onClick={logout}
                  sx={{
                    borderColor: "divider",
                    color: "text.secondary",
                    "&:hover": { borderColor: "error.main", color: "error.main" },
                  }}
                >
                  salir
                </Button>
              </Box>
              <ColorModeToggle />
            </Box>
          </Toolbar>
        </Box>

        <Box component="main" sx={{ flex: 1 }}>
          <WizardNav
            currentStep={step}
            completedSteps={completedSteps}
            onStepClick={(s) => canGoTo(s) && goTo(s)}
          />

          {step === "ingest" && (
            <Upload
              onReady={(j) => void handleReady(j)}
              onOpenJob={openJob}
              resumeJob={resumeJob}
              notice={jobError}
            />
          )}
          {step === "clips" && job && (
            <Reel
              job={job}
              clips={clips}
              onUpdateClip={updateClip}
              onGoReview={() => { markCompleted("clips"); goTo("review"); }}
              onReset={handleReset}
              onDashboard={() => { markCompleted("clips"); markCompleted("review"); goTo("analytics"); }}
              onRegenerated={handleRegenerated}
            />
          )}
          {step === "review" && job && (
            <Review
              job={job}
              clips={clips}
              onUpdateClip={updateClip}
              onBack={() => goTo("clips")}
              onNext={() => { markCompleted("review"); goTo("publish"); }}
            />
          )}
          {step === "publish" && job && (
            <Publish
              job={job}
              clips={clips}
              onUpdateClip={updateClip}
              onBack={() => goTo("review")}
              onJobChange={setJob}
            />
          )}
          {step === "accounts" && <Accounts />}
          {step === "analytics" && (
            <Dashboard onNewJob={() => { setCompletedSteps([]); goTo("ingest"); }} onOpenJob={(j) => void openJob(j.id)} />
          )}
        </Box>

        <Box
          component="footer"
          sx={{
            borderTop: "1px solid",
            borderColor: "divider",
            background: CARD,
            px: { xs: 2, md: 3 },
            py: 1.5,
          }}
        >
          <Stack direction="row" spacing={2} sx={{ alignItems: "center", flexWrap: "wrap" }}>
            <Typography sx={{ fontFamily: MONO, fontSize: "0.68rem" }}>
              edgetape<span style={{ color: MARK }}>.</span>
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ ml: "auto", fontSize: "0.72rem" }}>
              Grabaciones largas → los momentos que importan.
            </Typography>
          </Stack>
        </Box>
      </Box>
    </Box>
  );
}
