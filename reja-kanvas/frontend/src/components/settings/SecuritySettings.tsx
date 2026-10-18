"use client";

import { useCallback, useEffect, useState } from "react";
import { api, setToken } from "@/lib/api";
import { online, setUser, toast, useStore, useT } from "@/lib/store";
import { fmtDateTime } from "@/lib/time";
import type { ApiKey, Session, Webhook } from "@/lib/types";
import { Copy, X } from "../Icons";
import { Section } from "./Section";

const EVENTS = ["plan.created", "plan.submitted", "plan.completed", "plan.returned", "plan.deleted", "comment.created"];

function copy(text: string, done: string) {
  navigator.clipboard.writeText(text).then(() => toast(done, { tone: "success" }), () => window.prompt("", text));
}

export function TwoFactor() {
  const t = useT();
  const user = useStore((s) => s.user)!;
  const [setup, setSetup] = useState<{ secret: string; uri: string } | null>(null);
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const [disable, setDisable] = useState({ password: "", code: "" });

  async function start() {
    const r = await online(() => api.post<{ secret: string; uri: string }>("/api/me/2fa/setup"));
    if (r) setSetup(r);
  }
  async function enable(e: React.FormEvent) {
    e.preventDefault();
    const r = await online(() => api.post<{ recovery_codes: string[] }>("/api/me/2fa/enable", { code }));
    if (r) {
      setCodes(r.recovery_codes);
      setSetup(null);
      setUser({ ...user, totp_enabled: true });
    }
  }
  async function turnOff(e: React.FormEvent) {
    e.preventDefault();
    const ok = await online(async () => {
      await api.post("/api/me/2fa/disable", disable);
      return true;
    });
    if (ok) {
      setUser({ ...user, totp_enabled: false });
      setDisable({ password: "", code: "" });
    }
  }

  return (
    <Section title={t("settings.twofa")} lead={t("settings.twofaLead")}>
      {codes && (
        <div className="flex flex-col gap-2 rounded-xl bg-warn-soft p-4 text-warn-ink">
          <p className="text-sm font-semibold">{t("settings.twofaCodes")}</p>
          <pre className="grid grid-cols-2 gap-1 font-mono text-sm">{codes.map((c) => <span key={c}>{c}</span>)}</pre>
          <button type="button" className="btn self-start" onClick={() => copy(codes.join("\n"), t("share.copied"))}><Copy size={16} />{t("share.copy")}</button>
        </div>
      )}
      {user.totp_enabled ? (
        <form onSubmit={turnOff} className="flex flex-wrap items-end gap-2">
          <span className="w-full font-semibold text-ok">{t("settings.twofaOn")}</span>
          <label className="flex flex-col gap-1">
            <span className="label">{t("auth.password")}</span>
            <input type="password" className="field" value={disable.password} onChange={(e) => setDisable({ ...disable, password: e.target.value })} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="label">{t("auth.code")}</span>
            <input className="field w-36 font-mono" autoComplete="one-time-code" value={disable.code} onChange={(e) => setDisable({ ...disable, code: e.target.value })} />
          </label>
          <button className="btn-danger" disabled={!disable.password || disable.code.length < 6}>{t("settings.twofaDisable")}</button>
        </form>
      ) : setup ? (
        <form onSubmit={enable} className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <span className="label">{t("settings.twofaSecret")}</span>
            <code className="select-all break-all rounded-lg bg-paper-2 p-2 font-mono text-sm">{setup.secret.replace(/(.{4})/g, "$1 ").trim()}</code>
          </div>
          <a href={setup.uri} className="self-start text-sm font-semibold text-accent-ink underline">{t("settings.twofaUri")}</a>
          <label className="flex flex-col gap-1">
            <span className="label">{t("auth.code")}</span>
            <input className="field w-40 font-mono tracking-widest" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(e) => setCode(e.target.value)} />
          </label>
          <button className="btn-primary self-start" disabled={code.length !== 6}>{t("settings.twofaEnable")}</button>
        </form>
      ) : (
        <button type="button" className="btn self-start" onClick={() => void start()}>{t("settings.twofaSetup")}</button>
      )}
    </Section>
  );
}

export function Sessions() {
  const t = useT();
  const user = useStore((s) => s.user)!;
  const lang = useStore((s) => s.lang);
  const [sessions, setSessions] = useState<Session[]>([]);
  const load = useCallback(() => {
    api.get<{ sessions: Session[] }>("/api/me/sessions").then((r) => setSessions(r.sessions)).catch(() => undefined);
  }, []);
  useEffect(load, [load]);

  async function revoke(id: string) {
    if (await online(async () => { await api.del(`/api/me/sessions/${id}`); return true; })) load();
  }
  async function others() {
    const r = await online(() => api.post<{ token: string }>("/api/me/logout-all"));
    if (r) {
      setToken(r.token);
      toast(t("settings.loggedOutAll"), { tone: "success" });
      load();
    }
  }

  const device = (ua: string) => {
    const os = /Android/i.test(ua) ? "Android" : /iPhone|iPad/i.test(ua) ? "iOS" : /Windows/i.test(ua) ? "Windows" : /Mac OS/i.test(ua) ? "macOS" : /Linux/i.test(ua) ? "Linux" : "—";
    const browser = /Edg\//.test(ua) ? "Edge" : /Chrome\//.test(ua) ? "Chrome" : /Firefox\//.test(ua) ? "Firefox" : /Safari\//.test(ua) ? "Safari" : "";
    return `${browser} · ${os}`;
  };

  return (
    <Section title={t("settings.sessions")}>
      <ul className="flex flex-col divide-y divide-line-soft">
        {sessions.map((s) => (
          <li key={s.id} className="flex items-center gap-3 py-2.5">
            <span className="min-w-0 flex-1">
              <span className="block font-semibold">{device(s.user_agent)} {s.current && <span className="chip ml-1 bg-ok-soft text-ok-ink">{t("settings.thisDevice")}</span>}</span>
              <span className="text-xs text-ink-muted">{t("settings.lastSeen", { time: fmtDateTime(s.last_seen_at, user.tz, lang) })} · {s.ip}</span>
            </span>
            {!s.current && <button type="button" className="btn h-9 px-3" onClick={() => void revoke(s.id)}>{t("settings.revoke")}</button>}
          </li>
        ))}
      </ul>
      <button type="button" className="btn self-start" onClick={() => void others()}>{t("settings.logoutAll")}</button>
    </Section>
  );
}

export function ApiKeys() {
  const t = useT();
  const user = useStore((s) => s.user)!;
  const lang = useStore((s) => s.lang);
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [fresh, setFresh] = useState<ApiKey | null>(null);
  const [name, setName] = useState("");
  const load = useCallback(() => {
    api.get<{ keys: ApiKey[] }>("/api/me/api-keys").then((r) => setKeys(r.keys)).catch(() => undefined);
  }, []);
  useEffect(load, [load]);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    const k = await online(() => api.post<ApiKey>("/api/me/api-keys", { name: name.trim() }));
    if (k) {
      setFresh(k);
      setName("");
      load();
    }
  }

  return (
    <Section title={t("settings.apiKeys")} lead={t("settings.apiLead")}>
      {fresh?.key && (
        <div className="flex flex-col gap-2 rounded-xl bg-warn-soft p-3 text-warn-ink">
          <span className="text-sm font-semibold">{t("settings.apiShown")}</span>
          <code className="select-all break-all font-mono text-xs">{fresh.key}</code>
          <button type="button" className="btn self-start" onClick={() => copy(fresh.key!, t("share.copied"))}><Copy size={16} />{t("share.copy")}</button>
        </div>
      )}
      <ul className="flex flex-col gap-2">
        {keys.map((k) => (
          <li key={k.id} className="flex items-center gap-3 rounded-xl border border-line-soft px-3 py-2">
            <span className="min-w-0 flex-1">
              <span className="block font-semibold">{k.name}</span>
              <span className="font-mono text-xs text-ink-muted">{k.prefix}… · {k.last_used_at ? fmtDateTime(k.last_used_at, user.tz, lang) : "—"}</span>
            </span>
            <button type="button" className="btn-danger h-9 px-3" onClick={async () => { if (await online(async () => { await api.del(`/api/me/api-keys/${k.id}`); return true; })) load(); }}>{t("share.revoke")}</button>
          </li>
        ))}
      </ul>
      <form onSubmit={create} className="flex gap-2">
        <label className="flex-1">
          <span className="sr-only">{t("settings.apiName")}</span>
          <input className="field" maxLength={60} placeholder={t("settings.apiName")} value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <button className="btn-dark" disabled={!name.trim()}>{t("settings.apiCreate")}</button>
      </form>
    </Section>
  );
}

export function Webhooks() {
  const t = useT();
  const [hooks, setHooks] = useState<Webhook[]>([]);
  const [url, setUrl] = useState("");
  const [events, setEvents] = useState<string[]>(["plan.completed"]);
  const [secret, setSecret] = useState<string | null>(null);
  const load = useCallback(() => {
    api.get<{ webhooks: Webhook[] }>("/api/me/webhooks").then((r) => setHooks(r.webhooks)).catch(() => undefined);
  }, []);
  useEffect(load, [load]);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    const h = await online(() => api.post<Webhook>("/api/me/webhooks", { url: url.trim(), events }));
    if (h) {
      setSecret(h.secret ?? null);
      setUrl("");
      load();
    }
  }

  return (
    <Section title={t("settings.webhooks")} lead={t("settings.webhookLead")}>
      {secret && (
        <div className="flex flex-col gap-2 rounded-xl bg-warn-soft p-3 text-warn-ink">
          <span className="text-sm font-semibold">{t("settings.webhookSecret")}</span>
          <code className="select-all break-all font-mono text-xs">{secret}</code>
        </div>
      )}
      <ul className="flex flex-col gap-2">
        {hooks.map((h) => (
          <li key={h.id} className="flex flex-wrap items-center gap-2 rounded-xl border border-line-soft px-3 py-2">
            <span className="min-w-0 flex-1 basis-56">
              <span className="block truncate font-mono text-sm">{h.url}</span>
              <span className="text-xs text-ink-muted">{h.events.join(", ")} {h.last_status ? `· ${h.last_status}` : ""}</span>
              {!h.active && <span className="block text-xs font-bold text-warn-strong">{t("settings.webhookOff")}</span>}
            </span>
            {!h.active && <button type="button" className="btn h-9 px-3" onClick={async () => { if (await online(() => api.post(`/api/me/webhooks/${h.id}/reactivate`))) load(); }}>{t("settings.webhookOn")}</button>}
            <button type="button" className="btn-icon h-9 w-9" aria-label={t("common.delete")} onClick={async () => { if (await online(async () => { await api.del(`/api/me/webhooks/${h.id}`); return true; })) load(); }}><X size={16} /></button>
          </li>
        ))}
      </ul>
      <form onSubmit={create} className="flex flex-col gap-2">
        <label>
          <span className="sr-only">{t("settings.webhookUrl")}</span>
          <input type="url" className="field font-mono text-sm" placeholder={t("settings.webhookUrl")} value={url} onChange={(e) => setUrl(e.target.value)} />
        </label>
        <div className="flex flex-wrap gap-1.5">
          {EVENTS.map((ev) => (
            <label key={ev} className={`flex h-9 cursor-pointer items-center gap-1.5 rounded-lg border px-2 font-mono text-xs ${events.includes(ev) ? "border-accent bg-accent-soft" : "border-line"}`}>
              <input type="checkbox" className="accent-accent" checked={events.includes(ev)} onChange={(e) => setEvents(e.target.checked ? [...events, ev] : events.filter((x) => x !== ev))} />
              {ev}
            </label>
          ))}
        </div>
        <button className="btn-dark self-start" disabled={!url.startsWith("https://") || !events.length}>{t("settings.webhookAdd")}</button>
      </form>
    </Section>
  );
}
