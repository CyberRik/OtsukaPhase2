// Senpai Workspace — slash-command parsing.
//
// Skills are invoked by EXPLICIT slash commands, not by an LLM intent router.
// This keeps the trust boundary legible: the user (not the model) decides which
// deterministic engine runs. Unknown commands are rejected, never silently
// reinterpreted as free text.
//
// Phase 2 wires `/review` only; Phase 3 adds `/account` and `/research`, and a
// bare (no-slash) turn becomes general chat. Until then, a bare turn defaults to
// /review (this is the surface being dogfooded against the standalone Coach).

export const SKILLS = ["review", "account", "research"] as const;
export type SkillName = (typeof SKILLS)[number];

export interface ParsedInput {
  command: string | null; // the /word typed, lowercased, if any
  known: boolean; // whether `command` maps to a wired skill
  body: string; // the input with the command token stripped
}

const COMMAND_RE = /^\/([a-z]+)\b[ \t]*/i;

export function parseInput(raw: string): ParsedInput {
  const m = raw.match(COMMAND_RE);
  if (!m) return { command: null, known: false, body: raw.trim() };
  const command = m[1].toLowerCase();
  return {
    command,
    known: (SKILLS as readonly string[]).includes(command),
    body: raw.slice(m[0].length).trim(),
  };
}
