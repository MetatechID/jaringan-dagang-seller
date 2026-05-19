"use client";

import React from "react";
import type {
  Message,
  MessageBlock,
  MessageBlockImage,
  MessageBlockProductCard,
  MessageBlockQR,
} from "@/lib/api";
import { formatIDR, formatDate, formatRelative } from "@/lib/format";

/**
 * Return `value` only when it parses as a URL whose protocol is http(s).
 * Used to gate `<img src>` and `<a href>` on bot-supplied block payloads so
 * that `javascript:`, `data:`, `file:`, etc. cannot reach the DOM. (Markdown
 * link parsing already restricts to `https?://` via regex; this helper closes
 * the same hole on block-renderer call sites — see C3 review fix.)
 */
function safeHttpUrl(value: string | undefined): string | undefined {
  if (!value) return undefined;
  try {
    const u = new URL(value);
    if (u.protocol === "http:" || u.protocol === "https:") return value;
    return undefined;
  } catch {
    return undefined;
  }
}

/**
 * Minimal-and-safe inline Markdown renderer.
 *
 * Supports paragraphs (blank-line separated), single-line breaks, bold (`**`),
 * italic (`*`), inline code (``` ` ```), and `[label](url)` links. Escapes all
 * other HTML; never executes script. We picked this over react-markdown to
 * avoid pulling a 50 KB dep tree for a chat bubble.
 */
export function renderSafeMarkdown(text: string): React.ReactNode {
  if (!text) return null;
  // Split paragraphs on blank lines.
  const paragraphs = text.replace(/\r\n/g, "\n").split(/\n\s*\n/);
  return paragraphs.map((p, i) => (
    <p key={i} className={i === 0 ? "" : "mt-1.5"}>
      {renderInline(p)}
    </p>
  ));
}

function escapeHtmlText(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

/**
 * Parse a single paragraph into inline React nodes. Splits on supported
 * markdown patterns; everything else is rendered as plain text (HTML-escaped
 * implicitly because we use text children, not dangerouslySetInnerHTML).
 *
 * The order matters: links first (so URL syntax inside `[...]` isn't picked
 * up as italic), then code, then bold, then italic, then line-break.
 */
function renderInline(s: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  // We process by repeatedly finding the *earliest* match across patterns and
  // emitting plain text before / styled node for it.
  type Match = { start: number; end: number; node: React.ReactNode };
  const patterns: { re: RegExp; build: (m: RegExpExecArray) => React.ReactNode }[] = [
    {
      // [label](url)
      re: /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
      build: (m) => (
        <a
          key={m.index}
          href={m[2]}
          target="_blank"
          rel="noopener noreferrer"
          className="underline hover:no-underline"
        >
          {m[1]}
        </a>
      ),
    },
    {
      // `code`
      re: /`([^`]+)`/g,
      build: (m) => (
        <code
          key={m.index}
          className="rounded bg-black/10 px-1 py-0.5 font-mono text-[0.85em]"
        >
          {m[1]}
        </code>
      ),
    },
    {
      // **bold**
      re: /\*\*([^*]+)\*\*/g,
      build: (m) => <strong key={m.index}>{m[1]}</strong>,
    },
    {
      // *italic*
      re: /\*([^*]+)\*/g,
      build: (m) => <em key={m.index}>{m[1]}</em>,
    },
  ];

  // Find all matches.
  const matches: Match[] = [];
  for (const p of patterns) {
    p.re.lastIndex = 0;
    let m: RegExpExecArray | null;
    // eslint-disable-next-line no-cond-assign
    while ((m = p.re.exec(s)) !== null) {
      matches.push({ start: m.index, end: m.index + m[0].length, node: p.build(m) });
    }
  }
  matches.sort((a, b) => a.start - b.start);

  // Drop overlapping matches (keep the earlier-starting / longer).
  const kept: Match[] = [];
  for (const m of matches) {
    const last = kept[kept.length - 1];
    if (last && m.start < last.end) continue;
    kept.push(m);
  }

  let cursor = 0;
  for (const m of kept) {
    if (m.start > cursor) {
      const chunk = s.slice(cursor, m.start);
      out.push(renderLineBreaks(chunk, cursor));
    }
    out.push(m.node);
    cursor = m.end;
  }
  if (cursor < s.length) {
    out.push(renderLineBreaks(s.slice(cursor), cursor));
  }
  return out;
}

function renderLineBreaks(s: string, keyBase: number): React.ReactNode {
  const parts = s.split("\n");
  if (parts.length === 1) return <React.Fragment key={`t-${keyBase}`}>{s}</React.Fragment>;
  return (
    <React.Fragment key={`t-${keyBase}`}>
      {parts.map((part, i) => (
        <React.Fragment key={i}>
          {part}
          {i < parts.length - 1 && <br />}
        </React.Fragment>
      ))}
    </React.Fragment>
  );
}

// ---------- Block renderers ----------

function ProductCard({ block }: { block: MessageBlockProductCard }) {
  const safeImage = safeHttpUrl(block.image_url);
  const safeLink = safeHttpUrl(block.url);
  return (
    <div className="mt-2 flex items-stretch gap-3 rounded-lg border border-black/10 bg-white p-2 text-gray-900 max-w-xs">
      {safeImage ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={safeImage}
          alt={block.title}
          width={64}
          height={64}
          className="h-16 w-16 rounded-md object-cover bg-gray-100"
          loading="lazy"
        />
      ) : (
        <div
          aria-hidden="true"
          className="h-16 w-16 rounded-md bg-gray-100"
        />
      )}
      <div className="min-w-0 flex-1">
        <p className="text-xs font-mono text-gray-400">{block.sku}</p>
        <p className="truncate text-sm font-semibold">{block.title}</p>
        <p className="text-sm font-bold text-brand-700">{formatIDR(block.price_idr)}</p>
        {safeLink ? (
          <a
            href={safeLink}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-brand-600 hover:underline"
          >
            View product →
          </a>
        ) : null}
      </div>
    </div>
  );
}

function ImageBlock({ block }: { block: MessageBlockImage }) {
  const safe = safeHttpUrl(block.url);
  if (!safe) return null;
  return (
    /* eslint-disable-next-line @next/next/no-img-element */
    <img
      src={safe}
      alt={block.alt || ""}
      width={256}
      height={192}
      className="mt-2 max-h-48 max-w-xs rounded-lg object-contain bg-black/5"
      loading="lazy"
    />
  );
}

function QRBlock({ block }: { block: MessageBlockQR }) {
  const safe = safeHttpUrl(block.url);
  return (
    <div className="mt-2 inline-flex flex-col items-center rounded-lg border border-black/10 bg-white p-2 text-gray-900">
      {safe ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={safe}
          alt={block.caption || "QR code"}
          width={160}
          height={160}
          className="h-40 w-40 object-contain"
          loading="lazy"
        />
      ) : (
        <div
          aria-hidden="true"
          className="h-40 w-40 bg-gray-100"
        />
      )}
      <p className="mt-1.5 text-center text-xs text-gray-600">
        {block.caption || "Scan to pay"}
      </p>
    </div>
  );
}

function RenderedBlock({ block }: { block: MessageBlock }) {
  // Type-narrowing via the discriminator. Unknown types are silently skipped
  // (forward-compat with future bot-emitted block types).
  if (block.type === "product_card") {
    return <ProductCard block={block as MessageBlockProductCard} />;
  }
  if (block.type === "image") {
    return <ImageBlock block={block as MessageBlockImage} />;
  }
  if (block.type === "qr") {
    return <QRBlock block={block as MessageBlockQR} />;
  }
  return null;
}

// ---------- Bubble ----------

function DeliveryIndicator({ delivery }: { delivery: Message["delivery"] }) {
  if (delivery === "pending") {
    return <span className="text-[10px] text-white/70">↻ Sending</span>;
  }
  if (delivery === "sent") {
    return <span className="text-[10px] text-white/70">✓ Sent</span>;
  }
  if (delivery === "failed") {
    return <span className="text-[10px] font-semibold text-red-200">✕ Failed</span>;
  }
  // 'na' → render nothing (contact/bot messages don't have a delivery state).
  return null;
}

export interface MessageBubbleProps {
  message: Message;
  agentName?: string | null; // resolved from sender_user_id by parent; falls back to "Agent"
}

export default function MessageBubble({ message, agentName }: MessageBubbleProps) {
  const sender = message.sender;
  const isAgent = sender === "agent";
  const align = isAgent ? "items-end" : "items-start";

  // Color scheme by sender.
  let bubbleClass = "bg-gray-100 text-gray-900";
  let label: React.ReactNode = null;
  if (sender === "bot") {
    bubbleClass = "bg-blue-50 text-blue-900 border border-blue-100";
    label = <span className="text-[10px] font-semibold text-blue-700">🤖 Bot</span>;
  } else if (isAgent) {
    bubbleClass = "bg-brand-600 text-white";
    label = (
      <span className="text-[10px] font-semibold text-white/80">
        {agentName || "Agent"}
      </span>
    );
  } else {
    label = <span className="text-[10px] font-semibold text-gray-500">Customer</span>;
  }

  const text = message.content?.text ?? "";
  const blocks = message.content?.blocks ?? [];
  const created = message.created_at;

  return (
    <div className={`flex flex-col ${align} max-w-full`}>
      <div className="mb-0.5 flex items-center gap-2 px-1">{label}</div>
      <div
        className={`max-w-[80%] rounded-2xl px-3.5 py-2 text-sm leading-snug shadow-sm ${bubbleClass}`}
      >
        {text && <div className="whitespace-pre-wrap break-words">{renderSafeMarkdown(text)}</div>}
        {blocks.map((b, i) => (
          <RenderedBlock key={i} block={b} />
        ))}
        {isAgent && (
          <div className="mt-1 flex justify-end">
            <DeliveryIndicator delivery={message.delivery} />
          </div>
        )}
      </div>
      <div
        className="mt-0.5 px-1 text-[10px] text-gray-400"
        title={created ? formatDate(created) : ""}
      >
        {formatRelative(created)}
      </div>
    </div>
  );
}

// Re-export for tests / external imports.
export { ProductCard, ImageBlock, QRBlock };
