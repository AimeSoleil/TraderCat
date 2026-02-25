"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { cn } from "@/lib/utils";

/**
 * Styled Markdown renderer with GFM tables, task-lists, strikethrough,
 * and code-block syntax highlighting.
 *
 * Usage: <MarkdownRenderer content={md} className="..." />
 */
export function MarkdownRenderer({
  content,
  className,
}: {
  content: string;
  className?: string;
}) {
  return (
    <article
      className={cn(
        // Base prose styling (hand-rolled for Tailwind v4 compatibility)
        "prose-tc max-w-none text-foreground",
        className,
      )}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
      >
        {content}
      </ReactMarkdown>
    </article>
  );
}
