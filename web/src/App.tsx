import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
  Box,
  Button,
  Divider,
  Drawer,
  IconButton,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Stack,
  Toolbar,
  Typography,
} from "@mui/material";
import MenuRoundedIcon from "@mui/icons-material/MenuRounded";
import LogoutRoundedIcon from "@mui/icons-material/LogoutRounded";
import UploadFileRoundedIcon from "@mui/icons-material/UploadFileRounded";
import MovieFilterRoundedIcon from "@mui/icons-material/MovieFilterRounded";
import SendRoundedIcon from "@mui/icons-material/SendRounded";
import AccountBoxRoundedIcon from "@mui/icons-material/AccountBoxRounded";
import PaidRoundedIcon from "@mui/icons-material/PaidRounded";
import AutoAwesomeRoundedIcon from "@mui/icons-material/AutoAwesomeRounded";
import Upload from "./components/Upload";
import Reel from "./components/Reel";
import Dashboard from "./components/Dashboard";
import Accounts from "./components/Accounts";
import Publish from "./components/Publish";
import Generate from "./components/Generate";
import Auth from "./components/Auth";
import ConfirmDialog from "./components/ConfirmDialog";
import { getClips, getJob, getMe, getToken, setToken } from "./api";
import type { Clip, Job, User } from "./api";
import { CARD, INK, MARK, MONO, SIDEBAR_WIDTH } from "./theme";

type Phase = "upload" | "reel" | "publish" | "generate" | "accounts" | "dashboard";

interface NavItem {
  label: string;
  caption: string;
  phase: Phase;
  icon: ReactNode;
  needsJob?: boolean;
  needsSelection?: boolean;
  dividerBefore?: boolean;
}

const NAV: NavItem[] = [
  {
    label: "Ingresar",
    caption: "sube o pega un video",
    phase: "upload",
    icon: <UploadFileRoundedIcon fontSize="small" />,
  },
  {
    label: "Clips",
    caption: "el carrete de momentos",
    phase: "reel",
    icon: <MovieFilterRoundedIcon fontSize="small" />,
    needsJob: true,
  },
  {
    label: "Publicar",
    caption: "destinos por clip",
    phase: "publish",
    icon: <SendRoundedIcon fontSize="small" />,
    needsJob: true,
    needsSelection: true,
  },
  {
    label: "Generar",
    caption: "crear video con IA",
    phase: "generate",
    icon: <AutoAwesomeRoundedIcon fontSize="small" />,
    dividerBefore: true,
  },
  {
    label: "Cuentas",
    caption: "canales vinculados",
    phase: "accounts",
    icon: <AccountBoxRoundedIcon fontSize="small" />,
  },
  {
    label: "Ganancias",
    caption: "rendimiento por plataforma",
    phase: "dashboard",
    icon: <PaidRoundedIcon fontSize="small" />,
  },
];

function Brand() {
  return (
    <Box sx={{ display: "flex", alignItems: "center", gap: 1.5 }}>
      <Box
        sx={{
          width: 32,
          height: 32,
          borderRadius: 1.5,
          background: `linear-gradient(135deg, ${MARK} 0%, #F59E0B 100%)`,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          boxShadow: "0 2px 8px rgba(255,198,71,0.3)",
        }}
      >
        <Typography
          sx={{
            fontFamily: MONO,
            fontSize: "0.9rem",
            fontWeight: 700,
            color: INK,
            lineHeight: 1,
          }}
        >
          e
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
  nav: NavItem[];
  active: Phase;
  badge: Partial<Record<Phase, number>>;
  disabled: Partial<Record<Phase, boolean>>;
  onNavigate: (p: Phase) => void;
  onLogout: () => void;
  user: User;
}

function SidebarContent({ nav, active, badge, disabled, onNavigate, onLogout, user }: SidebarProps) {
  return (
    <Box sx={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <Toolbar sx={{ px: 2.5, gap: 1, minHeight: 72 }}>
        <Brand />
      </Toolbar>
      <Divider sx={{ borderColor: "rgba(255,255,255,0.08)", mx: 2 }} />
      <List sx={{ px: 1.5, py: 1, flex: 1 }}>
        {nav.map((item) => {
          const disabledHere = disabled[item.phase] === true;
          const count = badge[item.phase];
          return (
            <Box key={item.phase}>
              {item.dividerBefore && (
                <Divider sx={{ borderColor: "rgba(255,255,255,0.08)", my: 1, mx: 1 }} />
              )}
              <ListItemButton
                selected={active === item.phase}
                disabled={disabledHere}
                onClick={() => onNavigate(item.phase)}
                sx={{ mb: 0.3, py: 1, px: 1.5 }}
              >
                <ListItemIcon
                  sx={{
                    minWidth: 32,
                    color: active === item.phase ? MARK : "rgba(255,255,255,0.5)",
                  }}
                >
                  {item.icon}
                </ListItemIcon>
                <ListItemText
                  primary={item.label}
                  secondary={item.caption}
                  slotProps={{
                    primary: {
                      sx: {
                        fontWeight: active === item.phase ? 700 : 500,
                        fontSize: "0.85rem",
                        lineHeight: 1.3,
                        color: disabledHere
                          ? "rgba(255,255,255,0.2)"
                          : active === item.phase
                          ? "#fff"
                          : "rgba(255,255,255,0.75)",
                      },
                    },
                    secondary: {
                      sx: {
                        fontSize: "0.62rem",
                        color: "rgba(255,255,255,0.3)",
                        lineHeight: 1.3,
                      },
                    },
                  }}
                />
                {count !== undefined && count > 0 && (
                  <Box
                    sx={{
                      minWidth: 20,
                      height: 20,
                      px: 0.5,
                      borderRadius: 1,
                      background: active === item.phase ? MARK : "rgba(255,255,255,0.12)",
                      color: active === item.phase ? INK : "rgba(255,255,255,0.7)",
                      fontFamily: MONO,
                      fontSize: "0.6rem",
                      fontWeight: 600,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                    }}
                  >
                    {count}
                  </Box>
                )}
              </ListItemButton>
            </Box>
          );
        })}
      </List>
      <Divider sx={{ borderColor: "rgba(255,255,255,0.08)", mx: 2 }} />
      <Box sx={{ px: 2, py: 2 }}>
        <Stack direction="row" spacing={1.5} sx={{ alignItems: "center" }}>
          <Box
            sx={{
              width: 34,
              height: 34,
              borderRadius: "50%",
              background: "rgba(255,198,71,0.15)",
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

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [phase, setPhase] = useState<Phase>("upload");
  const [job, setJob] = useState<Job | null>(null);
  const [clips, setClips] = useState<Clip[]>([]);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [notReadyAlert, setNotReadyAlert] = useState(false);

  useEffect(() => {
    if (!getToken()) return;
    getMe()
      .then(setUser)
      .catch(() => setToken(null));
  }, []);

  useEffect(() => {
    const onUnauthorized = () => setUser(null);
    window.addEventListener("edgetape:unauthorized", onUnauthorized);
    return () => window.removeEventListener("edgetape:unauthorized", onUnauthorized);
  }, []);

  function handleAuth(next: User) {
    setUser(next);
    goTo("upload");
  }

  function logout() {
    setToken(null);
    setUser(null);
    setJob(null);
    setClips([]);
    goTo("upload");
  }

  async function handleReady(finished: Job) {
    const found = await getClips(finished.id);
    setClips(found);
    setJob(finished);
    setPhase("reel");
    window.scrollTo({ top: 0 });
  }

  async function openJob(jobId: string) {
    const found = await getJob(jobId);
    if (found.status !== "done") {
      setNotReadyAlert(true);
      return;
    }
    await handleReady(found);
  }

  function goTo(p: Phase) {
    setPhase(p);
    setMobileOpen(false);
    window.scrollTo({ top: 0 });
  }

  function handleReset() {
    setJob(null);
    setClips([]);
    goTo("upload");
  }

  function updateClip(updated: Clip) {
    setClips((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));
  }

  if (!user) {
    return <Auth onAuth={handleAuth} />;
  }

  const toPublish = clips.filter((c) => c.publish).length;
  const disabled: Partial<Record<Phase, boolean>> = {};
  const badge: Partial<Record<Phase, number>> = {};
  for (const item of NAV) {
    if (item.needsJob && !job) disabled[item.phase] = true;
    if (item.needsSelection && (!job || toPublish === 0)) disabled[item.phase] = true;
  }
  badge.publish = toPublish;
  badge.reel = job ? clips.length : undefined;

  const sidebarProps: SidebarProps = {
    nav: NAV,
    active: phase,
    badge,
    disabled,
    onNavigate: goTo,
    onLogout: logout,
    user,
  };

  const sectionTitle = NAV.find((n) => n.phase === phase)?.label ?? "";

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
            boxShadow: "0 1px 3px rgba(20,22,26,.04)",
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
                Edgetape — panel de trabajo
              </Typography>
              <Typography variant="h6" sx={{ lineHeight: 1.15, fontSize: "1.05rem" }}>
                {sectionTitle}
              </Typography>
            </Box>
            {job && (
              <Box
                sx={{
                  ml: "auto",
                  display: "flex",
                  alignItems: "center",
                  gap: 1,
                  minWidth: 0,
                }}
              >
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
                    backgroundColor: "rgba(30,58,138,0.06)",
                  }}
                >
                  {job.filename}
                </Typography>
              </Box>
            )}
            <Box sx={{ ml: job ? 1 : "auto", display: { xs: "none", sm: "flex" }, alignItems: "center", gap: 1.5 }}>
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
                  "&:hover": { borderColor: "error.main", color: "error.main", backgroundColor: "rgba(196,61,61,.04)" },
                }}
              >
                salir
              </Button>
            </Box>
          </Toolbar>
        </Box>

        <Box component="main" sx={{ flex: 1 }}>
          {phase === "upload" && <Upload onReady={(j) => void handleReady(j)} onOpenJob={openJob} />}
          {phase === "reel" && job && (
            <Reel
              job={job}
              clips={clips}
              onUpdateClip={updateClip}
              onGoPublish={() => goTo("publish")}
              onReset={handleReset}
              onDashboard={() => goTo("dashboard")}
            />
          )}
          {phase === "publish" && job && (
            <Publish
              job={job}
              clips={clips}
              onUpdateClip={updateClip}
              onBack={() => goTo("reel")}
              onJobChange={setJob}
            />
          )}
          {phase === "generate" && (
            <Generate
              onJobReady={(j) => void handleReady(j)}
              onOpenJob={openJob}
            />
          )}
          {phase === "accounts" && <Accounts />}
          {phase === "dashboard" && (
            <Dashboard onNewJob={() => goTo("upload")} onOpenJob={(j) => void openJob(j.id)} />
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
      <ConfirmDialog
        open={notReadyAlert}
        title="Video no listo"
        message="Este video aún no está listo para ver clips. Espera a que termine de procesarse."
        confirmLabel="Entendido"
        cancelLabel=""
        severity="info"
        onConfirm={() => setNotReadyAlert(false)}
        onCancel={() => setNotReadyAlert(false)}
      />
    </Box>
  );
}
