import { useState, useEffect } from "react";
import { Check, Copy, Sparkles } from "lucide-react";
import { motion, AnimatePresence } from "motion/react";
import { PrismAsyncLight as SyntaxHighlighter } from "react-syntax-highlighter";
import bash from "react-syntax-highlighter/dist/esm/languages/prism/bash";
import javascript from "react-syntax-highlighter/dist/esm/languages/prism/javascript";
import json from "react-syntax-highlighter/dist/esm/languages/prism/json";
import python from "react-syntax-highlighter/dist/esm/languages/prism/python";
import typescript from "react-syntax-highlighter/dist/esm/languages/prism/typescript";
import { vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism";
import { vs } from "react-syntax-highlighter/dist/esm/styles/prism";
import { toast } from "sonner";

import { runScript } from "../lib/qgis";

SyntaxHighlighter.registerLanguage("bash", bash);
SyntaxHighlighter.registerLanguage("javascript", javascript);
SyntaxHighlighter.registerLanguage("json", json);
SyntaxHighlighter.registerLanguage("python", python);
SyntaxHighlighter.registerLanguage("typescript", typescript);

interface CodeBlockProps {
  language: string;
  value: string;
}

/** Couleur du badge selon le langage */
const LANGUAGE_BADGE_COLORS: Record<string, string> = {
  python:     "bg-emerald-500/15 text-emerald-400 border-emerald-500/25",
  javascript: "bg-yellow-500/15 text-yellow-400 border-yellow-500/25",
  typescript: "bg-blue-400/15 text-blue-400 border-blue-400/25",
  sql:        "bg-sky-500/15 text-sky-400 border-sky-500/25",
  bash:       "bg-gray-500/15 text-gray-400 border-gray-500/25",
  shell:      "bg-gray-500/15 text-gray-400 border-gray-500/25",
  json:       "bg-orange-500/15 text-orange-400 border-orange-500/25",
};

const DEFAULT_BADGE_COLOR = "bg-[#333537]/60 text-[#8e918f] border-[#444]/40";

function resolveBadgeColor(lang: string): string {
  return LANGUAGE_BADGE_COLORS[lang.toLowerCase()] ?? DEFAULT_BADGE_COLOR;
}

export default function CodeBlock({ language, value }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);
  const [isDark, setIsDark] = useState(() => document.documentElement.classList.contains("dark"));

  useEffect(() => {
    const observer = new MutationObserver(() => {
      setIsDark(document.documentElement.classList.contains("dark"));
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, []);

  const copyToClipboard = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      toast.success("Code copié dans le presse-papier");
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Impossible de copier le code (permission refusée)");
    }
  };

  const runInQgis = async () => {
    // Exécution toujours confirmée par l'utilisateur (dialogue QGIS).
    const status = await runScript(value);

    if (status) {
      toast.success(status);
    } else {
      toast.error("QGIS n'est pas connecté. Utilisez cette extension dans QGIS.");
    }
  };

  const resolvedLang = language || "python";
  const badgeColor = resolveBadgeColor(resolvedLang);

  return (
    <div className="group relative my-4 overflow-hidden rounded-2xl border border-gray-200 dark:border-[#333537] shadow-lg dark:shadow-2xl transition-all duration-500 hover:border-blue-500/30">
      <div className="relative flex items-center justify-between border-b border-gray-200 dark:border-[#333537] bg-gray-50 dark:bg-[#1a1a1b] px-4 py-2">
        <div className="flex items-center gap-2">
          {/* Dots macOS décoratifs */}
          <div className="flex gap-1.5">
            <div className="h-2.5 w-2.5 rounded-full bg-[#ff5f56]" />
            <div className="h-2.5 w-2.5 rounded-full bg-[#ffbd2e]" />
            <div className="h-2.5 w-2.5 rounded-full bg-[#27c93f]" />
          </div>
          {/* Badge langage coloré */}
          <span
            className={`ml-2 inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-mono font-semibold uppercase tracking-widest ${badgeColor}`}
          >
            {resolvedLang}
          </span>
        </div>

        <div className="flex items-center gap-2">
          {/* Bouton copier avec AnimatePresence Clipboard → Check */}
          <motion.button
            onClick={() => void copyToClipboard()}
            whileHover={{ scale: 1.1 }}
            whileTap={{ scale: 0.9 }}
            className="relative flex h-7 w-7 items-center justify-center rounded-md text-gray-500 dark:text-[#c4c7c5] transition-colors hover:bg-gray-200 dark:hover:bg-[#333537] hover:text-gray-700 dark:hover:text-white"
            title="Copier le code"
          >
            <AnimatePresence mode="wait" initial={false}>
              {copied ? (
                <motion.span
                  key="check"
                  initial={{ scale: 0, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  exit={{ scale: 0, opacity: 0 }}
                  transition={{ type: "spring", stiffness: 400, damping: 20 }}
                  className="absolute text-emerald-400"
                >
                  <Check size={14} />
                </motion.span>
              ) : (
                <motion.span
                  key="copy"
                  initial={{ scale: 0, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  exit={{ scale: 0, opacity: 0 }}
                  transition={{ type: "spring", stiffness: 400, damping: 20 }}
                  className="absolute"
                >
                  <Copy size={14} />
                </motion.span>
              )}
            </AnimatePresence>
          </motion.button>

          {(language === "python" || !language) && (
            <motion.button
              onClick={() => void runInQgis()}
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.95 }}
              className="flex items-center gap-1.5 rounded-md border border-blue-500/20 bg-blue-600/20 px-2.5 py-1 text-xs font-semibold text-blue-400 transition-all hover:bg-blue-600/30"
              title="Exécuter dans QGIS"
            >
              <Sparkles size={12} />
              <span>EXÉCUTER</span>
            </motion.button>
          )}
        </div>
      </div>

      <SyntaxHighlighter
        language={resolvedLang}
        style={isDark ? vscDarkPlus : vs}
        showLineNumbers
        lineNumberStyle={{
          color: isDark ? "#555" : "#bbb",
          fontSize: "0.75rem",
          userSelect: "none",
          paddingRight: "1rem",
          minWidth: "2.5rem",
        }}
        customStyle={{
          margin: 0,
          padding: "1.2rem",
          fontSize: "0.85rem",
          backgroundColor: isDark ? "#0d0d0d" : "#f8f8f8",
          lineHeight: "1.6",
        }}
      >
        {value}
      </SyntaxHighlighter>
    </div>
  );
}
