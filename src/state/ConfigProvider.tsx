import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  addExcludedFolder,
  addRule,
  getConfig,
  removeExcludedFolder,
  removeRule,
  saveConfig,
  updateRule,
} from "../lib/api";
import { errorMessage } from "../lib/errors";
import { withSettings } from "../lib/config";
import type { Config, Rule, Settings } from "../lib/types";

interface ConfigApi {
  config: Config | null;
  loading: boolean;
  /** Set when the initial load failed; the view renders a retry affordance. */
  error: string | null;
  reload: () => Promise<void>;

  /** Whole-config write. Callers must have spread the previous config. */
  replaceConfig: (next: Config) => Promise<void>;
  patchSettings: (patch: Partial<Settings>) => Promise<void>;

  addFolder: (path: string) => Promise<void>;
  saveRule: (rule: Rule) => Promise<void>;
  deleteRule: (path: string) => Promise<void>;
  addGlobalExclusion: (path: string) => Promise<void>;
  removeGlobalExclusion: (path: string) => Promise<void>;
}

const ConfigContext = createContext<ConfigApi | null>(null);

export function ConfigProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<Config | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const next = await getConfig();
      setConfig(next);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  /**
   * Mutations go through the granular Rust commands so the backend stays the
   * authority on merge semantics, then we re-read. That costs a round trip per
   * edit and buys guaranteed agreement with what is on disk — the right trade
   * for a config file that carries keys this UI does not model.
   *
   * Every one of these rejects on failure; callers surface the message.
   */
  const afterMutation = useCallback(async () => {
    const next = await getConfig();
    setConfig(next);
    setError(null);
  }, []);

  const replaceConfig = useCallback(
    async (next: Config) => {
      await saveConfig(next);
      await afterMutation();
    },
    [afterMutation],
  );

  const patchSettings = useCallback(
    async (patch: Partial<Settings>) => {
      if (!config) throw new Error("Configuration has not loaded yet.");
      // Spread, never rebuild: `settings` carries keys this UI does not model.
      await saveConfig(withSettings(config, patch));
      await afterMutation();
    },
    [config, afterMutation],
  );

  const addFolder = useCallback(
    async (path: string) => {
      const added = await addRule(path);
      if (!added) throw new Error(`“${path}” is already being monitored.`);
      await afterMutation();
    },
    [afterMutation],
  );

  const saveRule = useCallback(
    async (rule: Rule) => {
      const ok = await updateRule(rule);
      if (!ok) throw new Error(`No monitored folder matches “${rule.path}”.`);
      await afterMutation();
    },
    [afterMutation],
  );

  const deleteRule = useCallback(
    async (path: string) => {
      const ok = await removeRule(path);
      if (!ok) throw new Error(`“${path}” was not in the monitored list.`);
      await afterMutation();
    },
    [afterMutation],
  );

  const addGlobalExclusion = useCallback(
    async (path: string) => {
      const ok = await addExcludedFolder(path);
      if (!ok) throw new Error(`“${path}” is already excluded.`);
      await afterMutation();
    },
    [afterMutation],
  );

  const removeGlobalExclusion = useCallback(
    async (path: string) => {
      const ok = await removeExcludedFolder(path);
      if (!ok) throw new Error(`“${path}” was not in the exclusion list.`);
      await afterMutation();
    },
    [afterMutation],
  );

  const value = useMemo<ConfigApi>(
    () => ({
      config,
      loading,
      error,
      reload,
      replaceConfig,
      patchSettings,
      addFolder,
      saveRule,
      deleteRule,
      addGlobalExclusion,
      removeGlobalExclusion,
    }),
    [
      config,
      loading,
      error,
      reload,
      replaceConfig,
      patchSettings,
      addFolder,
      saveRule,
      deleteRule,
      addGlobalExclusion,
      removeGlobalExclusion,
    ],
  );

  return <ConfigContext.Provider value={value}>{children}</ConfigContext.Provider>;
}

export function useConfig(): ConfigApi {
  const ctx = useContext(ConfigContext);
  if (!ctx) throw new Error("useConfig must be used inside <ConfigProvider>");
  return ctx;
}
