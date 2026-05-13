import { useState, useRef, useEffect, useCallback } from 'react';
import { MessageCircle, X, Send, Loader2, Trash2 } from 'lucide-react';
import { api } from '@/lib/api';
import Markdown from 'react-markdown';

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

const STORAGE_KEY = 'portfolio-chat-history';
const FAB_POSITION_KEY = 'portfolio-chat-fab-position';

function loadHistory(): ChatMessage[] {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored ? JSON.parse(stored) : [];
  } catch {
    return [];
  }
}

function saveHistory(messages: ChatMessage[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(messages));
  } catch { /* quota exceeded — ignore */ }
}

function loadFabPosition(): { x: number; y: number } | null {
  try {
    const stored = localStorage.getItem(FAB_POSITION_KEY);
    return stored ? JSON.parse(stored) : null;
  } catch {
    return null;
  }
}

function saveFabPosition(pos: { x: number; y: number }) {
  try {
    localStorage.setItem(FAB_POSITION_KEY, JSON.stringify(pos));
  } catch { /* ignore */ }
}

export function ChatPanel() {
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>(loadHistory);
  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Draggable FAB state
  const [fabPosition, setFabPosition] = useState<{ x: number; y: number } | null>(loadFabPosition);
  const fabRef = useRef<HTMLButtonElement>(null);
  const isDragging = useRef(false);
  const dragStart = useRef({ x: 0, y: 0, fabX: 0, fabY: 0 });
  const hasMoved = useRef(false);

  // Persist messages to localStorage
  useEffect(() => {
    if (!isStreaming) {
      saveHistory(messages);
    }
  }, [messages, isStreaming]);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  useEffect(() => {
    if (isOpen && inputRef.current) {
      inputRef.current.focus();
    }
  }, [isOpen]);

  // Drag handlers for FAB
  const handlePointerDown = useCallback((e: React.PointerEvent) => {
    isDragging.current = true;
    hasMoved.current = false;
    const rect = fabRef.current?.getBoundingClientRect();
    dragStart.current = {
      x: e.clientX,
      y: e.clientY,
      fabX: rect ? rect.left + rect.width / 2 : window.innerWidth - 34,
      fabY: rect ? rect.top + rect.height / 2 : window.innerHeight - 34,
    };
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  }, []);

  const handlePointerMove = useCallback((e: React.PointerEvent) => {
    if (!isDragging.current) return;
    const dx = e.clientX - dragStart.current.x;
    const dy = e.clientY - dragStart.current.y;
    if (Math.abs(dx) > 5 || Math.abs(dy) > 5) {
      hasMoved.current = true;
    }
    const newX = Math.max(28, Math.min(window.innerWidth - 28, dragStart.current.fabX + dx));
    const newY = Math.max(28, Math.min(window.innerHeight - 28, dragStart.current.fabY + dy));
    setFabPosition({ x: newX, y: newY });
  }, []);

  const handlePointerUp = useCallback((e: React.PointerEvent) => {
    isDragging.current = false;
    (e.target as HTMLElement).releasePointerCapture(e.pointerId);
    if (hasMoved.current && fabPosition) {
      saveFabPosition(fabPosition);
    } else {
      setIsOpen(true);
    }
  }, [fabPosition]);

  const handleSend = async () => {
    const trimmed = input.trim();
    if (!trimmed || isStreaming) return;

    const userMsg: ChatMessage = { role: 'user', content: trimmed };
    setMessages((prev) => [...prev, userMsg]);
    setInput('');
    setIsStreaming(true);

    // Build history for API (exclude current message)
    const history = messages.map((m) => ({
      role: m.role,
      content: m.content,
    }));

    // Add empty assistant message to stream into
    setMessages((prev) => [...prev, { role: 'assistant', content: '' }]);

    try {
      let fullText = '';
      for await (const chunk of api.chatStream(trimmed, history)) {
        fullText += chunk;
        const captured = fullText;
        setMessages((prev) => {
          const updated = [...prev];
          updated[updated.length - 1] = {
            role: 'assistant',
            content: captured,
          };
          return updated;
        });
      }
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Something went wrong';
      setMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          role: 'assistant',
          content: `⚠️ ${errorMsg}`,
        };
        return updated;
      });
    } finally {
      setIsStreaming(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const clearHistory = () => {
    setMessages([]);
  };

  if (!isOpen) {
    const style: React.CSSProperties = fabPosition
      ? { position: 'fixed', left: fabPosition.x - 28, top: fabPosition.y - 28 }
      : { position: 'fixed', bottom: '5rem', right: '1.5rem' };

    return (
      <button
        ref={fabRef}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        style={style}
        className="z-50 flex h-14 w-14 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-lg hover:bg-primary/90 transition-all hover:scale-105 touch-none select-none"
        title="AI Assistant"
      >
        <MessageCircle className="h-6 w-6" />
      </button>
    );
  }

  return (
    <div className="fixed bottom-6 right-6 z-50 flex h-[600px] w-[440px] flex-col rounded-xl border border-border bg-card shadow-2xl">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <MessageCircle className="h-5 w-5 text-primary" />
          <span className="font-semibold text-card-foreground">Portfolio AI</span>
          <span className="text-xs text-muted-foreground">Sonnet 4.6</span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={clearHistory}
            className="rounded-md p-1.5 text-muted-foreground hover:bg-secondary hover:text-foreground transition-colors"
            title="Clear chat"
          >
            <Trash2 className="h-4 w-4" />
          </button>
          <button
            onClick={() => setIsOpen(false)}
            className="rounded-md p-1.5 text-muted-foreground hover:bg-secondary hover:text-foreground transition-colors"
            title="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
        {messages.length === 0 && (
          <div className="flex h-full items-center justify-center">
            <div className="text-center text-muted-foreground">
              <MessageCircle className="mx-auto mb-3 h-10 w-10 opacity-30" />
              <p className="text-sm font-medium">Ask me about your portfolio</p>
              <p className="mt-1 text-xs opacity-70">
                Holdings, performance, strategy, taxes, rebalancing...
              </p>
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${
                msg.role === 'user'
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-secondary text-secondary-foreground'
              }`}
            >
              {msg.role === 'assistant' ? (
                <div className="chat-markdown prose prose-sm prose-invert max-w-none">
                  <Markdown>{msg.content || '...'}</Markdown>
                </div>
              ) : (
                <p className="whitespace-pre-wrap">{msg.content}</p>
              )}
            </div>
          </div>
        ))}

        {isStreaming && messages[messages.length - 1]?.content === '' && (
          <div className="flex justify-start">
            <div className="flex items-center gap-2 rounded-lg bg-secondary px-3 py-2 text-sm text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Thinking...
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="border-t border-border p-3">
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about your portfolio..."
            rows={1}
            className="flex-1 resize-none rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
            style={{ maxHeight: '120px' }}
            onInput={(e) => {
              const target = e.target as HTMLTextAreaElement;
              target.style.height = 'auto';
              target.style.height = `${Math.min(target.scrollHeight, 120)}px`;
            }}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || isStreaming}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground disabled:opacity-40 hover:bg-primary/90 transition-colors"
          >
            {isStreaming ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
