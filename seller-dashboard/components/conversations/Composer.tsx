"use client";

import { useRef, useState } from "react";

export interface ComposerProps {
  onSend: (text: string) => Promise<void>;
  disabled?: boolean;
  /**
   * Disabled-state hint rendered above the textarea. Examples:
   *  - "Bot active — your reply will take over the conversation"
   *  - "Resolved — reopen to reply"
   */
  hint?: string;
  /** Extra action under the hint (e.g. a Reopen button on resolved threads). */
  hintAction?: React.ReactNode;
  /** Optional placeholder override. */
  placeholder?: string;
}

export default function Composer({
  onSend,
  disabled = false,
  hint,
  hintAction,
  placeholder = "Type a reply…",
}: ComposerProps) {
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const canSend = !disabled && !sending && text.trim().length > 0;

  async function handleSend() {
    if (!canSend) return;
    const trimmed = text.trim();
    setSending(true);
    setError(null);
    try {
      await onSend(trimmed);
      setText("");
      textareaRef.current?.focus();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to send");
    } finally {
      setSending(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    // Enter to send; Shift+Enter for newline. matches Chatwoot / Slack.
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleSend();
    }
  }

  return (
    <div className="border-t border-gray-200 bg-white">
      {hint && (
        <div className="flex items-center justify-between gap-2 border-b border-amber-100 bg-amber-50 px-4 py-2 text-xs text-amber-800">
          <span>{hint}</span>
          {hintAction}
        </div>
      )}
      {error && (
        <div className="border-b border-red-100 bg-red-50 px-4 py-2 text-xs text-red-700">
          {error}
        </div>
      )}
      <div className="flex items-end gap-2 p-3">
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled || sending}
          placeholder={placeholder}
          rows={2}
          className="flex-1 resize-none rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-400 shadow-sm transition-colors focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20 disabled:bg-gray-50 disabled:text-gray-400"
          aria-label="Message composer"
        />
        <button
          type="button"
          onClick={handleSend}
          disabled={!canSend}
          className="inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-brand-600 px-4 text-sm font-semibold text-white shadow-sm transition-all hover:bg-brand-700 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:ring-offset-2 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50"
        >
          {sending ? (
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
          ) : (
            <svg
              className="h-4 w-4"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth={2}
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M6 12 3.269 3.125A59.769 59.769 0 0 1 21.485 12 59.768 59.768 0 0 1 3.27 20.875L5.999 12Zm0 0h7.5"
              />
            </svg>
          )}
          Send
        </button>
      </div>
    </div>
  );
}
